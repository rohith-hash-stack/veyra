"""
Tests for the PLAN.md Phase 1.4 D4 extension (symbol-level diff). Builds
realistic Node lists via the real Phase 2.1 extractor at two "commits"
(the same file path, written twice) rather than hand-crafted Node objects,
so these tests also double-check the extractor/symbol-diff integration.
"""

from __future__ import annotations

from pathlib import Path

from veyra.git_tracking import SymbolChangeType, diff_symbols
from veyra.static_analysis import extract_file

COMMIT = "commit1"


def _extract(repo_root: Path, source: str):
    file_path = repo_root / "orders.py"
    file_path.write_text(source)
    return extract_file(file_path, repo_root, COMMIT).nodes


def _change_for(changes, entity_id: str):
    return next(c for c in changes if c.entity_id == entity_id)


def test_added_symbol(tmp_path: Path) -> None:
    old_nodes = _extract(tmp_path, "def foo():\n    pass\n")
    new_nodes = _extract(tmp_path, "def foo():\n    pass\n\ndef bar():\n    pass\n")

    changes = diff_symbols(old_nodes, new_nodes)

    assert _change_for(changes, "orders.bar").change_type is SymbolChangeType.ADDED


def test_removed_symbol(tmp_path: Path) -> None:
    old_nodes = _extract(tmp_path, "def foo():\n    pass\n\ndef bar():\n    pass\n")
    new_nodes = _extract(tmp_path, "def foo():\n    pass\n")

    changes = diff_symbols(old_nodes, new_nodes)

    assert _change_for(changes, "orders.bar").change_type is SymbolChangeType.REMOVED


def test_unchanged_symbol(tmp_path: Path) -> None:
    source = "def foo():\n    return 1\n"
    old_nodes = _extract(tmp_path, source)
    new_nodes = _extract(tmp_path, source)

    changes = diff_symbols(old_nodes, new_nodes)

    assert _change_for(changes, "orders.foo").change_type is SymbolChangeType.UNCHANGED


def test_modified_signature(tmp_path: Path) -> None:
    old_nodes = _extract(tmp_path, "def foo(x):\n    return x\n")
    new_nodes = _extract(tmp_path, "def foo(x, y):\n    return x\n")

    changes = diff_symbols(old_nodes, new_nodes)

    assert _change_for(changes, "orders.foo").change_type is SymbolChangeType.MODIFIED_SIGNATURE


def test_modified_body(tmp_path: Path) -> None:
    old_nodes = _extract(tmp_path, "def foo(x):\n    return x + 1\n")
    new_nodes = _extract(tmp_path, "def foo(x):\n    return x + 2\n")

    changes = diff_symbols(old_nodes, new_nodes)

    assert _change_for(changes, "orders.foo").change_type is SymbolChangeType.MODIFIED_BODY


def test_variable_change_is_always_modified_body(tmp_path: Path) -> None:
    old_nodes = _extract(tmp_path, "DEFAULT_TIMEOUT = 30\n")
    new_nodes = _extract(tmp_path, "DEFAULT_TIMEOUT = 60\n")

    changes = diff_symbols(old_nodes, new_nodes)

    assert _change_for(changes, "orders.DEFAULT_TIMEOUT").change_type is SymbolChangeType.MODIFIED_BODY


def test_class_changes_are_covered_too(tmp_path: Path) -> None:
    old_nodes = _extract(tmp_path, "class OrderService:\n    pass\n")
    new_nodes = _extract(tmp_path, "class OrderService(BaseService):\n    pass\n")

    changes = diff_symbols(old_nodes, new_nodes)

    assert _change_for(changes, "orders.OrderService").change_type is SymbolChangeType.MODIFIED_SIGNATURE
