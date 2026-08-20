"""
Tests for PLAN.md Milestone 2, Phase 2.1 (Static Repository Analysis,
Python). Required fixture categories per the plan: classes, methods,
functions, imports, calls, inheritance, references, nested structures,
duplicate names. "Multiple languages" is explicitly out of scope per D5
(Python-only until the pipeline clears its M5 gates) -- not tested here.
"""

from __future__ import annotations

import ast
from pathlib import Path
from typing import Callable

from veyra.static_analysis import extract_file, extract_repository, persist_extraction
from veyra.static_analysis.python_extractor import _splitlines_no_ff, _source_segment
from veyra.vbg import RelationshipType, VBGStore

COMMIT = "commit1"


def _edges_of_type(edges, rel_type: RelationshipType):
    return [e for e in edges if e.relationship_type is rel_type]


def test_classes(repo_root: Path, write_module: Callable[[str, str], Path]) -> None:
    write_module("orders.py", "class OrderService:\n    pass\n")

    result = extract_file(repo_root / "orders.py", repo_root, COMMIT)

    class_nodes = [n for n in result.nodes if n.type == "Class"]
    assert len(class_nodes) == 1
    assert class_nodes[0].entity_id == "orders.OrderService"
    contains = _edges_of_type(result.edges, RelationshipType.CONTAINS)
    assert any(e.source_id == "orders" and e.target_id == "orders.OrderService" for e in contains)


def test_functions(repo_root: Path, write_module: Callable[[str, str], Path]) -> None:
    write_module("orders.py", "def process_order():\n    pass\n")

    result = extract_file(repo_root / "orders.py", repo_root, COMMIT)

    function_nodes = [n for n in result.nodes if n.type == "Function"]
    assert len(function_nodes) == 1
    assert function_nodes[0].entity_id == "orders.process_order"


def test_methods(repo_root: Path, write_module: Callable[[str, str], Path]) -> None:
    write_module(
        "orders.py",
        "class OrderService:\n"
        "    def process_order(self):\n"
        "        pass\n",
    )

    result = extract_file(repo_root / "orders.py", repo_root, COMMIT)

    method_nodes = [n for n in result.nodes if n.type == "Method"]
    assert len(method_nodes) == 1
    assert method_nodes[0].entity_id == "orders.OrderService.process_order"
    # A method is NOT also classified as a bare Function.
    assert not any(n.type == "Function" for n in result.nodes)


def test_imports(repo_root: Path, write_module: Callable[[str, str], Path]) -> None:
    write_module(
        "orders.py",
        "import os\n"
        "import os.path\n"
        "from collections import OrderedDict\n"
        "from . import sibling\n",
    )

    result = extract_file(repo_root / "orders.py", repo_root, COMMIT)

    import_targets = {e.target_id for e in _edges_of_type(result.edges, RelationshipType.IMPORTS)}
    assert "os" in import_targets
    assert "os.path" in import_targets
    assert "collections.OrderedDict" in import_targets
    assert ".sibling" in import_targets


def test_calls(repo_root: Path, write_module: Callable[[str, str], Path]) -> None:
    write_module(
        "orders.py",
        "class OrderService:\n"
        "    def process_order(self):\n"
        "        self.validate_order()\n"
        "        charge_payment()\n"
        "        unknown_external_call()\n"
        "\n"
        "    def validate_order(self):\n"
        "        pass\n"
        "\n"
        "def charge_payment():\n"
        "    pass\n",
    )

    result = extract_file(repo_root / "orders.py", repo_root, COMMIT)

    call_edges = _edges_of_type(result.edges, RelationshipType.CALLS)
    call_targets = {(e.source_id, e.target_id) for e in call_edges}

    assert ("orders.OrderService.process_order", "orders.OrderService.validate_order") in call_targets
    assert ("orders.OrderService.process_order", "orders.charge_payment") in call_targets
    # self.validate_order() resolves even though validate_order is DEFINED
    # AFTER process_order in the file -- same-file resolution is order-
    # independent because of the two-phase collect-then-resolve design.
    assert result.unresolved_calls == 1  # unknown_external_call()


def test_inheritance(repo_root: Path, write_module: Callable[[str, str], Path]) -> None:
    write_module(
        "orders.py",
        "class BaseService:\n"
        "    pass\n"
        "\n"
        "class OrderService(BaseService):\n"
        "    pass\n",
    )

    result = extract_file(repo_root / "orders.py", repo_root, COMMIT)

    inherits = _edges_of_type(result.edges, RelationshipType.INHERITS)
    assert any(
        e.source_id == "orders.OrderService" and e.target_id == "orders.BaseService"
        for e in inherits
    )


def test_references(repo_root: Path, write_module: Callable[[str, str], Path]) -> None:
    write_module(
        "orders.py",
        "class OrderService:\n"
        "    pass\n"
        "\n"
        "def handle(order: OrderService) -> OrderService:\n"
        "    return order\n",
    )

    result = extract_file(repo_root / "orders.py", repo_root, COMMIT)

    references = _edges_of_type(result.edges, RelationshipType.REFERENCES)
    reference_pairs = {(e.source_id, e.target_id) for e in references}
    assert ("orders.handle", "orders.OrderService") in reference_pairs


def test_nested_structures(repo_root: Path, write_module: Callable[[str, str], Path]) -> None:
    write_module(
        "orders.py",
        "class Outer:\n"
        "    class Inner:\n"
        "        pass\n"
        "\n"
        "    def method(self):\n"
        "        def nested_helper():\n"
        "            pass\n"
        "        return nested_helper\n",
    )

    result = extract_file(repo_root / "orders.py", repo_root, COMMIT)
    entity_ids = {n.entity_id: n.type for n in result.nodes}

    assert entity_ids["orders.Outer.Inner"] == "Class"
    assert entity_ids["orders.Outer.method"] == "Method"
    # A function nested inside a method is a Function, not a Method --
    # it is not a direct member of the class.
    assert entity_ids["orders.Outer.method.nested_helper"] == "Function"


def test_duplicate_names(repo_root: Path, write_module: Callable[[str, str], Path]) -> None:
    write_module(
        "orders.py",
        "def foo():\n"
        "    return 1\n"
        "\n"
        "def foo():\n"
        "    return 2\n",
    )

    result = extract_file(repo_root / "orders.py", repo_root, COMMIT)

    foo_nodes = [n for n in result.nodes if n.entity_id == "orders.foo"]
    # Both definitions are preserved -- the extractor does not silently drop
    # or merge the shadowed one. (Persisting both to VBGStore is exactly the
    # append-only "history" behavior from Phase 1.2.)
    assert len(foo_nodes) == 2


def test_lexical_representation_is_populated(repo_root: Path, write_module: Callable[[str, str], Path]) -> None:
    write_module("orders.py", "def process_order():\n    return 42\n")

    result = extract_file(repo_root / "orders.py", repo_root, COMMIT)

    func_node = next(n for n in result.nodes if n.entity_id == "orders.process_order")
    assert func_node.lexical_representation == "def process_order():\n    return 42"


def test_syntax_error_is_recorded_not_raised(repo_root: Path, write_module: Callable[[str, str], Path]) -> None:
    write_module("broken.py", "def broken(:\n")
    write_module("valid.py", "def ok():\n    pass\n")

    result = extract_repository(repo_root, COMMIT)

    assert "broken.py" in result.files_failed
    assert result.files_failed["broken.py"]  # non-empty message
    assert result.files_analyzed == 1  # valid.py still got analyzed
    assert any(n.entity_id == "valid.ok" for n in result.nodes)


def test_cross_module_call_resolution(repo_root: Path, write_module: Callable[[str, str], Path]) -> None:
    write_module("payment.py", "def charge_payment():\n    pass\n")
    write_module(
        "orders.py",
        "from payment import charge_payment\n"
        "\n"
        "def process_order():\n"
        "    charge_payment()\n",
    )

    result = extract_repository(repo_root, COMMIT)

    calls = {(e.source_id, e.target_id) for e in _edges_of_type(result.edges, RelationshipType.CALLS)}
    assert ("orders.process_order", "payment.charge_payment") in calls
    assert result.unresolved_calls == 0


def test_cross_module_call_with_alias(repo_root: Path, write_module: Callable[[str, str], Path]) -> None:
    write_module("payment.py", "def charge():\n    pass\n")
    write_module(
        "orders.py",
        "from payment import charge as do_charge\n"
        "\n"
        "def process_order():\n"
        "    do_charge()\n",
    )

    result = extract_repository(repo_root, COMMIT)

    calls = {(e.source_id, e.target_id) for e in _edges_of_type(result.edges, RelationshipType.CALLS)}
    assert ("orders.process_order", "payment.charge") in calls


def test_cross_module_inheritance(repo_root: Path, write_module: Callable[[str, str], Path]) -> None:
    write_module("base.py", "class BaseService:\n    pass\n")
    write_module(
        "orders.py",
        "from base import BaseService\n"
        "\n"
        "class OrderService(BaseService):\n"
        "    pass\n",
    )

    result = extract_repository(repo_root, COMMIT)

    inherits = {(e.source_id, e.target_id) for e in _edges_of_type(result.edges, RelationshipType.INHERITS)}
    assert ("orders.OrderService", "base.BaseService") in inherits


def test_cross_module_reference(repo_root: Path, write_module: Callable[[str, str], Path]) -> None:
    write_module("models.py", "class Order:\n    pass\n")
    write_module(
        "handlers.py",
        "from models import Order\n"
        "\n"
        "def handle(order: Order) -> None:\n"
        "    pass\n",
    )

    result = extract_repository(repo_root, COMMIT)

    references = {(e.source_id, e.target_id) for e in _edges_of_type(result.edges, RelationshipType.REFERENCES)}
    assert ("handlers.handle", "models.Order") in references


def test_module_qualified_attribute_calls_remain_unresolved(
    repo_root: Path, write_module: Callable[[str, str], Path]
) -> None:
    # `requests.get(...)` is a module-qualified attribute call -- explicitly
    # NOT resolved cross-module in this slice (documented scope decision).
    write_module("orders.py", "import requests\n\ndef fetch():\n    requests.get('http://example.invalid')\n")

    result = extract_repository(repo_root, COMMIT)

    assert result.unresolved_calls == 1
    calls = _edges_of_type(result.edges, RelationshipType.CALLS)
    assert calls == []


def test_call_cycles_are_supported(repo_root: Path, write_module: Callable[[str, str], Path]) -> None:
    # PLAN.md Phase 2.3 acceptance criterion: "Cycles are supported." Nothing
    # in the storage or extraction layer prevents or collapses a cycle --
    # both edges of a mutual-recursion pair must be present.
    write_module(
        "orders.py",
        "def ping():\n"
        "    pong()\n"
        "\n"
        "def pong():\n"
        "    ping()\n",
    )

    result = extract_file(repo_root / "orders.py", repo_root, COMMIT)

    calls = {(e.source_id, e.target_id) for e in _edges_of_type(result.edges, RelationshipType.CALLS)}
    assert ("orders.ping", "orders.pong") in calls
    assert ("orders.pong", "orders.ping") in calls


def test_extraction_persists_to_vbg_store(repo_root: Path, write_module: Callable[[str, str], Path], store: VBGStore) -> None:
    write_module(
        "orders.py",
        "class OrderService:\n"
        "    def process_order(self):\n"
        "        pass\n",
    )

    result = extract_repository(repo_root, COMMIT)
    persist_extraction(store, result)

    latest = store.get_latest_node("orders.OrderService.process_order", COMMIT)
    assert latest is not None
    assert latest.type == "Method"


# -- Performance regression: source is split once per file, not once per node --
#
# Real-repository investigation found `ast.get_source_segment(source, node)`
# (the previous implementation of `_lexical()`) re-splits the *entire*
# file's source into lines on every single call -- called once per node,
# an O(node_count x file_size) cost that measured at 25-45 real seconds to
# extract a single ~8,000-line SQLAlchemy file (1,323s to extract all of
# SQLAlchemy in memory, no storage/SQLite involved at all). Fixed by
# splitting the source once per file (`_FileExtractor._source_lines`) and
# reusing it for every node -- verified byte-identical output against the
# stdlib version on real files before landing. These tests protect the
# *mechanism* (source split count stays constant, not proportional to node
# count), not a timing threshold, which would be flaky on a loaded machine.


def test_source_segment_matches_stdlib_get_source_segment_output() -> None:
    """The replacement must be byte-identical to `ast.get_source_segment`,
    not just faster -- checked directly against the stdlib function across
    a real multi-line, multi-node source snippet."""
    source = (
        "class Widget:\n"
        "    def configure(self, mode, timeout=30):\n"
        '        """Configures the widget."""\n'
        "        return mode\n"
        "\n"
        "\n"
        "def helper(x, y):\n"
        "    return x + y\n"
    )
    tree = ast.parse(source)
    lines = _splitlines_no_ff(source)
    for node in ast.walk(tree):
        if hasattr(node, "lineno"):
            assert _source_segment(lines, node) == ast.get_source_segment(source, node)


def test_extraction_time_does_not_scale_quadratically_with_file_size(
    repo_root: Path, write_module: Callable[[str, str], Path]
) -> None:
    """The actual regression-protection test: split-call count (not wall
    time) must stay at exactly 1 per file regardless of how many nodes it
    contains -- the direct, deterministic signature of the fixed
    mechanism, immune to machine-speed flakiness a timing assertion would
    have."""
    import veyra.static_analysis.python_extractor as extractor_module

    call_count = 0
    real_splitlines = extractor_module._splitlines_no_ff

    def counting_splitlines(source: str) -> list[str]:
        nonlocal call_count
        call_count += 1
        return real_splitlines(source)

    extractor_module._splitlines_no_ff = counting_splitlines
    try:
        # 300 functions in one file -- large enough that the old O(node
        # count) re-split behavior would have been trivially detectable.
        source = "\n\n".join(f"def func_{i}(a, b):\n    return a + b" for i in range(300))
        write_module("big_module.py", source)
        result = extract_file(repo_root / "big_module.py", repo_root, COMMIT)
        assert len(result.nodes) > 300  # sanity: real nodes were actually produced
        assert call_count == 1  # exactly one split for the whole file, not one per node
    finally:
        extractor_module._splitlines_no_ff = real_splitlines
