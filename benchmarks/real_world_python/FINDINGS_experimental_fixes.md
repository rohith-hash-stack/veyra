# Experimental Fixes Log

Per the benchmark's own rules: every entry here documents a real, observed failure BEFORE any fix is
applied, on the `experiment/real-world-python-benchmark` branch only. Baseline and experimental/fixed
results are reported separately; nothing here is merged into the working development branch.

---

## Fix #1: `build_retrieval_index()` crashes on any real-world repository containing a top-level or class-level variable assignment

**BEFORE (baseline result):**
`veyra.retrieval.index.build_retrieval_index()` raised an unhandled `TypeError` on the very first call made
against real-world code (Flask, the smallest of the four benchmark repositories), before a single benchmark
query could be issued:

```
TypeError: 'Assign' can't have docstrings
  File "src/veyra/retrieval/index.py", line 171, in _build_entity
    docstring=_extract_docstring(node.lexical_representation),
  File "src/veyra/retrieval/index.py", line 76, in _extract_docstring
    return ast.get_docstring(body[0])
```

Baseline outcome: **0 of 56 benchmark queries could be executed against any repository.** Veyra's entire
Phase 4.1-4.7 retrieval pipeline is non-functional on real-world Python code as of this commit.

**PROBLEM:**
`_extract_docstring()` (`src/veyra/retrieval/index.py`) parses a node's `lexical_representation` and
unconditionally calls `ast.get_docstring(tree.body[0])`, assuming `body[0]` is always a `Module`, `ClassDef`,
`FunctionDef`, or `AsyncFunctionDef` -- the only node types `ast.get_docstring()` accepts. That assumption
holds for `Class`/`Function`/`Method`-typed VBG nodes, but the Phase 2.1 extractor also populates
`lexical_representation` for `Variable`-typed nodes (module-level and class-level assignments), and a bare
assignment statement like `author = "Pallets"` parses to `Module(body=[Assign(...)])` -- `body[0]` is an
`Assign` node, which `ast.get_docstring()` was never designed to accept, and raises `TypeError` rather than
returning `None`.

**ROOT CAUSE, with evidence:**
Queried Flask's real, persisted VBG (via `store.get_all_nodes()`) directly and checked every node's
`lexical_representation` against the same parse-and-inspect logic `_extract_docstring()` uses:

```
total nodes: 2607
nodes whose lexical_representation's first parsed statement is NOT a
Module/ClassDef/FunctionDef/AsyncFunctionDef: 954  (36.6%)
```

All 954 are `Variable`-typed nodes -- ordinary module-level constants and config values, e.g.
`docs.conf.author` (`docs/conf.py:9`, `author = "Pallets"`), `docs.conf.extensions` (a list literal), and
hundreds like them. This is not an edge case -- roughly a third of all nodes in a real, ordinary Python
codebase are exactly this shape.

**WHY THIS IS A VEYRA LIMITATION, NOT A BENCHMARK/QUERY PROBLEM:**
The crash happens entirely inside `build_retrieval_index()`, which every benchmark query needs before any
query can run -- it has nothing to do with query phrasing, ground truth, or this benchmark's design. It
reproduces deterministically against Flask's real, unmodified, pinned-commit source with zero
benchmark-specific involvement, and would reproduce on virtually any real-world Python repository containing
an ordinary top-level assignment (i.e. nearly all of them). Veyra's own existing Phase 4.1 test suite
(`tests/retrieval/`, 38 tests, all passing pre- and post-fix) never happened to combine a `Variable`-typed
node with this exact code path -- a real, previously invisible test-coverage gap that only real-world code
surfaced, exactly the kind of thing this benchmark exists to find.

**CHANGE (experiment branch only, `src/veyra/retrieval/index.py`, `_extract_docstring()`):**
Added a type check on `body[0]` before calling `ast.get_docstring()`, returning `None` for any non-eligible
statement type -- semantically correct (a bare assignment has no docstring to extract), not a suppressed
error:

```python
def _extract_docstring(lexical_representation: str | None) -> str | None:
    if not lexical_representation:
        return None
    try:
        tree = ast.parse(lexical_representation)
    except SyntaxError:
        return None
    body = tree.body
    if not body:
        return None
    if not isinstance(body[0], (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
        return None
    return ast.get_docstring(body[0])
```

This is a pure, additive type guard -- it does not change behavior for any node whose `lexical_representation`
already parsed to a docstring-eligible statement (Class/Function/Method nodes, the only ones the existing
test suite exercised).

**AFTER (experimental/fixed result):**
See Section 6 of `REPORT.md` and `results/*_raw_results.json` -- `build_retrieval_index()` now completes
successfully on all four repositories, and all 56 benchmark queries execute.

**REGRESSION CHECK:**
Re-ran Veyra's own full project test suite immediately after applying the change:

```
$ python -m pytest -q
421 passed, 26 skipped, 2 warnings in 22.73s
```

Identical to the pre-fix result (421 passed, 26 skipped, 0 failures) -- confirmed, not assumed, zero
regressions. No test in `tests/retrieval/` (or elsewhere) constructs a `Variable`-typed node with a
bare-statement `lexical_representation` and asserts on its `docstring` field, so this change was not
expected to alter any existing test's outcome, and the full-suite re-run bears that out.
