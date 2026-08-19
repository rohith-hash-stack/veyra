"""
PLAN.md Milestone 3, Phase 3.3a -- discovering the repository's existing test
suite via static AST inspection (no execution, no third-party test-runner
dependency). This is the harness's "what already exists to trace" input --
Phase 3.3b's novel scenario synthesis is separate, not-yet-built work.

Only two conventions are recognized, matching pytest's own default
discovery rules (the most common convention across the Python ecosystem):
  - file name: `test_*.py` or `*_test.py`
  - module-level function: `def test_*(...)`
  - class-based: any class whose name starts with `Test`, containing
    `def test_*` methods (pytest's own default collection rule -- this also
    happens to cover unittest.TestCase subclasses without needing to
    resolve base classes here)

entity_id is built with the exact same convention Phase 2.1's extractor
uses (`compute_module_id` + `f"{parent_id}.{name}"`) so a discovered test's
entity_id always matches the Node the extractor already persisted for it --
this is what lets the harness manager look the node up directly rather than
re-deriving identity.

Deliberately NOT supported in this first slice (PLAN.md D2: 3.3a traces what
already exists with minimal synthesis risk, it is not a general
pytest-compatible collector):
  - pytest fixtures/parametrize/conftest.py -- these need pytest's own
    collection machinery, a third-party dependency; harnessing fixture-based
    tests is exactly the kind of dependency-installation problem
    install_policy.py conservatively declines to solve yet.
  - async test functions -- would need an event-loop runner in the harness
    script; not attempted here.
"""

from __future__ import annotations

import ast
from dataclasses import dataclass
from pathlib import Path

from veyra.static_analysis import compute_module_id


@dataclass(frozen=True)
class DiscoveredTest:
    entity_id: str
    module_id: str
    module_path: str  # posix path relative to the repository root
    qualified_name: str
    class_name: str | None
    function_name: str


def _is_test_file(path: Path) -> bool:
    stem = path.stem
    return stem.startswith("test_") or stem.endswith("_test")


def discover_tests(repository_root: Path) -> list[DiscoveredTest]:
    """Deterministic: files walked in sorted path order, discovered tests
    within a file sorted by entity_id."""
    tests: list[DiscoveredTest] = []
    for file_path in sorted(repository_root.rglob("*.py")):
        if ".git" in file_path.parts or not _is_test_file(file_path):
            continue
        rel_path = file_path.relative_to(repository_root).as_posix()
        module_id = compute_module_id(file_path, repository_root)
        try:
            source = file_path.read_text(encoding="utf-8", errors="replace")
            tree = ast.parse(source, filename=str(file_path))
        except SyntaxError:
            continue  # an unparsable test file yields zero discoverable tests, not a crash
        tests.extend(_collect_from_module(tree, module_id, rel_path))
    return tests


def _collect_from_module(tree: ast.Module, module_id: str, rel_path: str) -> list[DiscoveredTest]:
    found: list[DiscoveredTest] = []
    for stmt in tree.body:
        if isinstance(stmt, ast.FunctionDef) and stmt.name.startswith("test_"):
            entity_id = f"{module_id}.{stmt.name}"
            found.append(
                DiscoveredTest(
                    entity_id=entity_id,
                    module_id=module_id,
                    module_path=rel_path,
                    qualified_name=entity_id,
                    class_name=None,
                    function_name=stmt.name,
                )
            )
        elif isinstance(stmt, ast.ClassDef) and stmt.name.startswith("Test"):
            class_id = f"{module_id}.{stmt.name}"
            for member in stmt.body:
                if isinstance(member, ast.FunctionDef) and member.name.startswith("test_"):
                    entity_id = f"{class_id}.{member.name}"
                    found.append(
                        DiscoveredTest(
                            entity_id=entity_id,
                            module_id=module_id,
                            module_path=rel_path,
                            qualified_name=entity_id,
                            class_name=stmt.name,
                            function_name=member.name,
                        )
                    )
    return sorted(found, key=lambda t: t.entity_id)
