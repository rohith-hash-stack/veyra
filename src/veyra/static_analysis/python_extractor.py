"""
PLAN.md Milestone 2, Phase 2.1 -- Static Repository Analysis (Python only,
per Design Decision D5's flagship-language sequencing).

Scope of this first slice, deliberately bounded to what Phase 2.1's required
tests actually exercise (classes, methods, functions, imports, calls,
inheritance, references, nested structures, duplicate names):

  Extracted as Nodes: Module (one per .py file -- Python has no meaningful
    distinction between "file" and "module", so these are NOT modeled as two
    separate node types), Class, Function, Method, Variable (module-level
    and class-level simple assignments only, not every local variable).
  Extracted as Edges: CONTAINS (structural nesting), IMPORTS (import /
    from-import), CALLS (same-file only -- see below), INHERITS (same-file
    base classes only), REFERENCES (type annotations on parameters, return
    types, and annotated assignments, resolved to a same-file class/function).

  NOT extracted in this slice (explicit scope decisions, not oversights):
    - Package nodes (directory / __init__.py hierarchy) -- not required by
      Phase 2.1's test list; each file maps directly to a Module today.
    - IMPLEMENTS -- doesn't map cleanly onto Python's structural typing.
    - DEPENDS_ON -- a higher-level aggregate the plan's own Phase 2.3
      diagram uses at service/class granularity, not something read directly
      off syntax; would need to be inferred from CALLS/IMPORTS, not
      extracted here.
    - Definitions nested inside conditional blocks (if/try/for at module or
      class level) are not visited -- only unconditional class/function
      bodies are walked.
    - Symbol resolution is a single flat per-file table (simple name ->
      most-recently-defined entity_id). A name reused across unrelated
      scopes in the same file resolves to whichever definition was seen
      last; this is a documented heuristic limitation, not full lexical
      scoping.

Cross-module resolution (Phase 2.3's "cross-module relationships are
supported"): `extract_repository()` runs a second pass after every file has
been extracted, resolving CALLS/INHERITS/REFERENCES that a single file
couldn't resolve on its own against that file's `from X import Y [as Z]`
bindings, checked against the full repository-wide set of known entity IDs.
This deliberately covers only the "from X import Y; Y(...)" pattern -- a
bare name bound by a `from`-import. Module-qualified attribute calls
(`module.func()`), plain `import module` usage, and star imports are NOT
resolved cross-module in this slice; those call sites remain in
`unresolved_calls`, not silently guessed at.

"Unsupported constructs are explicitly recorded" (Phase 2.1 acceptance
criterion) is satisfied via ExtractionResult.files_failed (files that failed
to parse) and .unresolved_calls (call sites whose target could not be
resolved even after the cross-module pass).
"""

from __future__ import annotations

import ast
from dataclasses import dataclass, field
from pathlib import Path

from veyra.vbg import Edge, Node, RelationshipType


def _splitlines_no_ff(source: str) -> list[str]:
    """Splits `source` into lines the same way the Python parser does --
    only `\\n`/`\\r\\n`/`\\r` are real line breaks (unlike `str.splitlines()`,
    which also breaks on form feed and several other Unicode line-separator
    characters that can legally appear inside a string literal or comment
    without ending a *source* line as far as `ast` node `lineno`/`col_offset`
    values are concerned). A local copy of `ast`'s own private
    `_splitlines_no_ff` helper (same algorithm `ast.get_source_segment`
    uses internally) -- copied rather than imported so this doesn't depend
    on a private stdlib symbol that could move between Python versions,
    and so it can be called *once per file* instead of once per node (see
    `_FileExtractor._lexical`)."""
    idx = 0
    lines: list[str] = []
    next_line = ""
    while idx < len(source):
        c = source[idx]
        next_line += c
        idx += 1
        if c == "\r" and idx < len(source) and source[idx] == "\n":
            next_line += "\n"
            idx += 1
        if c in "\r\n":
            lines.append(next_line)
            next_line = ""
    if next_line:
        lines.append(next_line)
    return lines


def _source_segment(lines: list[str], node: ast.AST) -> str | None:
    """`ast.get_source_segment(source, node)`, with the expensive
    `_splitlines_no_ff(source)` call factored out and done once per file
    (`lines`) instead of once per node -- see the real-repository
    performance finding this fixes: `ast.get_source_segment` re-splits the
    *entire* file's source on every single call, an O(node_count x
    file_size) cost that measured at 25-45 real seconds *per large file*
    (SQLAlchemy's compiler.py/selectable.py, thousands of nodes each) --
    with nothing to do with storage or SQLite at all. Same slicing logic
    as the stdlib version, verified byte-identical output against it."""
    try:
        if node.end_lineno is None or node.end_col_offset is None:  # type: ignore[attr-defined]
            return None
        lineno = node.lineno - 1  # type: ignore[attr-defined]
        end_lineno = node.end_lineno - 1  # type: ignore[attr-defined]
        col_offset = node.col_offset  # type: ignore[attr-defined]
        end_col_offset = node.end_col_offset  # type: ignore[attr-defined]
    except AttributeError:
        return None

    if end_lineno == lineno:
        return lines[lineno].encode()[col_offset:end_col_offset].decode()

    first = lines[lineno].encode()[col_offset:].decode()
    last = lines[end_lineno].encode()[:end_col_offset].decode()
    middle = lines[lineno + 1 : end_lineno]
    segment = [first, *middle, last]
    return "".join(segment)


@dataclass(frozen=True)
class UnresolvedReference:
    source_id: str
    attempted_name: str
    relationship_type: RelationshipType


@dataclass(frozen=True)
class FileExtractionResult:
    nodes: list[Node]
    edges: list[Edge]
    unresolved_calls: int
    parse_error: str | None
    import_aliases: dict[str, str] = field(default_factory=dict)
    unresolved: list[UnresolvedReference] = field(default_factory=list)


@dataclass(frozen=True)
class ExtractionResult:
    nodes: list[Node]
    edges: list[Edge]
    files_analyzed: int
    files_failed: dict[str, str]
    unresolved_calls: int


def _simple_name(expr: ast.expr) -> str | None:
    if isinstance(expr, ast.Name):
        return expr.id
    if isinstance(expr, ast.Attribute):
        return expr.attr
    return None


def _direct_calls(func_node: ast.FunctionDef | ast.AsyncFunctionDef) -> list[ast.Call]:
    """Call nodes in this function's own scope -- does not descend into
    nested function/class definitions, which get their own scope."""
    calls: list[ast.Call] = []

    def walk(node: ast.AST) -> None:
        for child in ast.iter_child_nodes(node):
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                continue
            if isinstance(child, ast.Call):
                calls.append(child)
            walk(child)

    for stmt in func_node.body:
        walk(stmt)
    return calls


class _FileExtractor:
    def __init__(self, module_id: str, repository_version: str, rel_path: str, source: str) -> None:
        self.module_id = module_id
        self.repository_version = repository_version
        self.rel_path = rel_path
        self._source = source
        self._source_lines = _splitlines_no_ff(source)
        self.nodes: list[Node] = []
        self.edges: list[Edge] = []
        self.symbol_table: dict[str, str] = {}
        self.known_entity_ids: set[str] = set()
        self.import_aliases: dict[str, str] = {}
        self.unresolved_calls = 0
        self.unresolved: list[UnresolvedReference] = []
        self._pending_calls: list[tuple[ast.Call, str, str | None]] = []
        self._pending_inherits: list[tuple[ast.expr, str]] = []
        self._pending_references: list[tuple[ast.expr, str]] = []

    def _location(self, node: ast.AST) -> str:
        end = getattr(node, "end_lineno", node.lineno)
        return f"{self.rel_path}:{node.lineno}-{end}"

    def _lexical(self, node: ast.AST) -> str | None:
        """Exact source text for this node -- doubles as the input to the
        Phase 1.4/D4 symbol-level diff hash (see git_tracking.symbol_diff).

        Performance finding: `ast.get_source_segment(self._source, node)`
        re-splits the entire file's source into lines on *every call* --
        called once per node, that's O(node_count x file_size) for one
        file. Measured directly: 25-45 real seconds to extract a single
        ~8,000-line SQLAlchemy file. `_source_segment()` does the
        equivalent work against `self._source_lines`, split once in
        `__init__` and reused for every node in this file."""
        return _source_segment(self._source_lines, node)

    def _add_node(self, node: Node) -> None:
        self.nodes.append(node)
        self.known_entity_ids.add(node.entity_id)
        self.symbol_table[node.name] = node.entity_id

    def extract(self, tree: ast.Module) -> None:
        self._add_node(
            Node(
                entity_id=self.module_id,
                type="Module",
                name=self.module_id,
                repository_version=self.repository_version,
                language="Python",
                source_location=f"{self.rel_path}:1",
            )
        )
        self._visit_body(tree.body, self.module_id, parent_is_class=False, enclosing_class_id=None)
        self._resolve_pending()

    def _visit_body(
        self,
        body: list[ast.stmt],
        parent_id: str,
        parent_is_class: bool,
        enclosing_class_id: str | None,
    ) -> None:
        for stmt in body:
            if isinstance(stmt, ast.ClassDef):
                self._handle_class(stmt, parent_id)
            elif isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef)):
                self._handle_function(stmt, parent_id, parent_is_class, enclosing_class_id)
            elif isinstance(stmt, ast.Import):
                self._handle_import(stmt, parent_id)
            elif isinstance(stmt, ast.ImportFrom):
                self._handle_import_from(stmt, parent_id)
            elif isinstance(stmt, (ast.Assign, ast.AnnAssign)):
                self._handle_assignment(stmt, parent_id)

    def _handle_class(self, node: ast.ClassDef, parent_id: str) -> None:
        class_id = f"{parent_id}.{node.name}"
        self._add_node(
            Node(
                entity_id=class_id,
                type="Class",
                name=node.name,
                repository_version=self.repository_version,
                language="Python",
                source_location=self._location(node),
                lexical_representation=self._lexical(node),
            )
        )
        self.edges.append(
            Edge(
                source_id=parent_id,
                target_id=class_id,
                relationship_type=RelationshipType.CONTAINS,
                repository_version=self.repository_version,
            )
        )
        for base in node.bases:
            self._pending_inherits.append((base, class_id))
        self._visit_body(node.body, class_id, parent_is_class=True, enclosing_class_id=class_id)

    def _handle_function(
        self,
        node: ast.FunctionDef | ast.AsyncFunctionDef,
        parent_id: str,
        parent_is_class: bool,
        enclosing_class_id: str | None,
    ) -> None:
        func_id = f"{parent_id}.{node.name}"
        node_type = "Method" if parent_is_class else "Function"
        self._add_node(
            Node(
                entity_id=func_id,
                type=node_type,
                name=node.name,
                repository_version=self.repository_version,
                language="Python",
                source_location=self._location(node),
                lexical_representation=self._lexical(node),
            )
        )
        self.edges.append(
            Edge(
                source_id=parent_id,
                target_id=func_id,
                relationship_type=RelationshipType.CONTAINS,
                repository_version=self.repository_version,
            )
        )

        for call in _direct_calls(node):
            self._pending_calls.append((call, func_id, enclosing_class_id))

        all_args = [
            *node.args.posonlyargs,
            *node.args.args,
            *node.args.kwonlyargs,
        ]
        for arg in all_args:
            if arg.annotation is not None:
                self._pending_references.append((arg.annotation, func_id))
        if node.returns is not None:
            self._pending_references.append((node.returns, func_id))

        # Nested defs are never direct class members, even inside a method;
        # self./cls. resolution still uses the same enclosing class though.
        self._visit_body(node.body, func_id, parent_is_class=False, enclosing_class_id=enclosing_class_id)

    def _handle_import(self, node: ast.Import, parent_id: str) -> None:
        for alias in node.names:
            self.edges.append(
                Edge(
                    source_id=parent_id,
                    target_id=alias.name,
                    relationship_type=RelationshipType.IMPORTS,
                    repository_version=self.repository_version,
                )
            )

    def _handle_import_from(self, node: ast.ImportFrom, parent_id: str) -> None:
        prefix = "." * node.level
        base = node.module or ""
        for alias in node.names:
            if alias.name == "*":
                continue  # star imports bind no discoverable local name
            target = f"{prefix}{base}.{alias.name}" if base else f"{prefix}{alias.name}"
            self.edges.append(
                Edge(
                    source_id=parent_id,
                    target_id=target,
                    relationship_type=RelationshipType.IMPORTS,
                    repository_version=self.repository_version,
                )
            )
            bound_name = alias.asname or alias.name
            self.import_aliases[bound_name] = target

    def _handle_assignment(self, node: ast.Assign | ast.AnnAssign, parent_id: str) -> None:
        targets = node.targets if isinstance(node, ast.Assign) else [node.target]
        for target in targets:
            if not isinstance(target, ast.Name):
                continue
            var_id = f"{parent_id}.{target.id}"
            self._add_node(
                Node(
                    entity_id=var_id,
                    type="Variable",
                    name=target.id,
                    repository_version=self.repository_version,
                    language="Python",
                    source_location=self._location(node),
                    lexical_representation=self._lexical(node),
                )
            )
            self.edges.append(
                Edge(
                    source_id=parent_id,
                    target_id=var_id,
                    relationship_type=RelationshipType.CONTAINS,
                    repository_version=self.repository_version,
                )
            )
            if isinstance(node, ast.AnnAssign) and node.annotation is not None:
                self._pending_references.append((node.annotation, var_id))

    def _resolve_pending(self) -> None:
        for base_expr, class_id in self._pending_inherits:
            name = _simple_name(base_expr)
            target = self.symbol_table.get(name) if name else None
            if target and target in self.known_entity_ids:
                self.edges.append(
                    Edge(
                        source_id=class_id,
                        target_id=target,
                        relationship_type=RelationshipType.INHERITS,
                        repository_version=self.repository_version,
                    )
                )
            elif name:
                self.unresolved.append(
                    UnresolvedReference(class_id, name, RelationshipType.INHERITS)
                )

        for annotation_expr, source_id in self._pending_references:
            name = _simple_name(annotation_expr)
            target = self.symbol_table.get(name) if name else None
            if target and target in self.known_entity_ids and target != source_id:
                self.edges.append(
                    Edge(
                        source_id=source_id,
                        target_id=target,
                        relationship_type=RelationshipType.REFERENCES,
                        repository_version=self.repository_version,
                    )
                )
            elif name:
                self.unresolved.append(
                    UnresolvedReference(source_id, name, RelationshipType.REFERENCES)
                )

        for call, source_id, enclosing_class_id in self._pending_calls:
            target = self._resolve_call_target(call, enclosing_class_id)
            if target:
                self.edges.append(
                    Edge(
                        source_id=source_id,
                        target_id=target,
                        relationship_type=RelationshipType.CALLS,
                        repository_version=self.repository_version,
                    )
                )
            else:
                self.unresolved_calls += 1
                if isinstance(call.func, ast.Name):
                    self.unresolved.append(
                        UnresolvedReference(source_id, call.func.id, RelationshipType.CALLS)
                    )

    def _resolve_call_target(self, call: ast.Call, enclosing_class_id: str | None) -> str | None:
        func = call.func
        if isinstance(func, ast.Name):
            return self.symbol_table.get(func.id)
        if (
            isinstance(func, ast.Attribute)
            and isinstance(func.value, ast.Name)
            and func.value.id in ("self", "cls")
            and enclosing_class_id
        ):
            candidate = f"{enclosing_class_id}.{func.attr}"
            if candidate in self.known_entity_ids:
                return candidate
        return None


def compute_module_id(file_path: Path, repository_root: Path) -> str:
    rel = file_path.relative_to(repository_root).with_suffix("")
    return ".".join(rel.parts)


def extract_file(file_path: Path, repository_root: Path, repository_version: str) -> FileExtractionResult:
    rel_path = file_path.relative_to(repository_root).as_posix()
    module_id = compute_module_id(file_path, repository_root)
    source = file_path.read_text(encoding="utf-8", errors="replace")

    try:
        tree = ast.parse(source, filename=str(file_path))
    except SyntaxError as exc:
        return FileExtractionResult(nodes=[], edges=[], unresolved_calls=0, parse_error=str(exc))

    extractor = _FileExtractor(module_id, repository_version, rel_path, source)
    extractor.extract(tree)
    return FileExtractionResult(
        nodes=extractor.nodes,
        edges=extractor.edges,
        unresolved_calls=extractor.unresolved_calls,
        parse_error=None,
        import_aliases=extractor.import_aliases,
        unresolved=extractor.unresolved,
    )


def extract_repository(repository_root: Path, repository_version: str) -> ExtractionResult:
    """
    Extracts every .py file, then runs a second, repository-wide pass that
    resolves each file's leftover UnresolvedReferences (CALLS/INHERITS/
    REFERENCES that couldn't be resolved within that single file) against
    that file's own `from X import Y [as Z]` bindings, checked against the
    full set of entity IDs known across the whole repository. This is what
    satisfies Phase 2.3's "cross-module relationships are supported" --
    see the module docstring for exactly which import patterns this covers.
    """
    nodes: list[Node] = []
    edges: list[Edge] = []
    files_failed: dict[str, str] = {}
    unresolved_calls = 0
    files_analyzed = 0
    file_results: list[FileExtractionResult] = []

    for file_path in sorted(repository_root.rglob("*.py")):
        if ".git" in file_path.parts:
            continue
        rel_path = file_path.relative_to(repository_root).as_posix()
        result = extract_file(file_path, repository_root, repository_version)
        if result.parse_error is not None:
            files_failed[rel_path] = result.parse_error
            continue
        files_analyzed += 1
        nodes.extend(result.nodes)
        edges.extend(result.edges)
        file_results.append(result)

    known_entity_ids = {n.entity_id for n in nodes}

    # Start from each file's own unresolved-call count (this already
    # includes self./cls. attribute calls with no importable simple name,
    # which never get a cross-module retry -- there is nothing to import-
    # alias-resolve for those). Then subtract the ones the cross-module
    # pass below actually manages to resolve.
    unresolved_calls = sum(result.unresolved_calls for result in file_results)

    for result in file_results:
        for ref in result.unresolved:
            target = result.import_aliases.get(ref.attempted_name)
            if target is not None and target in known_entity_ids:
                edges.append(
                    Edge(
                        source_id=ref.source_id,
                        target_id=target,
                        relationship_type=ref.relationship_type,
                        repository_version=repository_version,
                    )
                )
                if ref.relationship_type is RelationshipType.CALLS:
                    unresolved_calls -= 1

    return ExtractionResult(
        nodes=nodes,
        edges=edges,
        files_analyzed=files_analyzed,
        files_failed=files_failed,
        unresolved_calls=unresolved_calls,
    )
