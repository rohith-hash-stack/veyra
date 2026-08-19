"""
Tests for PLAN.md Phase 2.4 (Neighborhood Model). Builds a small, explicit
CONTAINS tree so parent/child/sibling/grandchild relationships are easy to
reason about:

    Module (M)
    |-- ClassA (A)
    |   |-- method1 (A.m1)
    |   `-- method2 (A.m2)
    `-- ClassB (B)
        `-- method3 (B.m3)
"""

from __future__ import annotations

from veyra.vbg import (
    Edge,
    RelationshipType,
    VBGStore,
    get_children,
    get_descendants,
    get_grandchildren,
    get_neighborhood,
    get_parents,
    get_siblings,
)

COMMIT = "commit1"


def _contains(source: str, target: str) -> Edge:
    return Edge(source_id=source, target_id=target, relationship_type=RelationshipType.CONTAINS, repository_version=COMMIT)


def _build_tree(store: VBGStore) -> None:
    store.insert_edge(_contains("M", "A"))
    store.insert_edge(_contains("M", "B"))
    store.insert_edge(_contains("A", "A.m1"))
    store.insert_edge(_contains("A", "A.m2"))
    store.insert_edge(_contains("B", "B.m3"))


def test_get_parents(store: VBGStore) -> None:
    _build_tree(store)
    assert get_parents(store, "A", COMMIT) == ["M"]
    assert get_parents(store, "A.m1", COMMIT) == ["A"]


def test_get_parents_of_root_is_empty_not_an_error(store: VBGStore) -> None:
    _build_tree(store)
    # "Unobserved relationships remain identifiable as unobserved": a
    # top-level node legitimately has no parent -- an empty list, not None,
    # not an exception.
    assert get_parents(store, "M", COMMIT) == []


def test_get_children(store: VBGStore) -> None:
    _build_tree(store)
    assert get_children(store, "M", COMMIT) == ["A", "B"]
    assert get_children(store, "A", COMMIT) == ["A.m1", "A.m2"]
    assert get_children(store, "A.m1", COMMIT) == []  # leaf node


def test_get_siblings(store: VBGStore) -> None:
    _build_tree(store)
    assert get_siblings(store, "A", COMMIT) == ["B"]
    assert get_siblings(store, "A.m1", COMMIT) == ["A.m2"]


def test_get_siblings_of_root_is_empty(store: VBGStore) -> None:
    _build_tree(store)
    assert get_siblings(store, "M", COMMIT) == []


def test_get_grandchildren(store: VBGStore) -> None:
    _build_tree(store)
    assert get_grandchildren(store, "M", COMMIT) == ["A.m1", "A.m2", "B.m3"]
    assert get_grandchildren(store, "A", COMMIT) == []  # A's children (methods) have no children


def test_get_descendants_configurable_depth(store: VBGStore) -> None:
    _build_tree(store)

    depth1 = get_descendants(store, "M", COMMIT, max_depth=1)
    assert depth1 == {1: ["A", "B"]}

    depth2 = get_descendants(store, "M", COMMIT, max_depth=2)
    assert depth2 == {1: ["A", "B"], 2: ["A.m1", "A.m2", "B.m3"]}

    # Asking for more depth than the tree has stops early once a level is
    # empty, rather than padding with nonsense.
    depth5 = get_descendants(store, "M", COMMIT, max_depth=5)
    assert depth5[1] == ["A", "B"]
    assert depth5[2] == ["A.m1", "A.m2", "B.m3"]
    assert depth5[3] == []
    assert 4 not in depth5


def test_neighborhood_only_uses_contains_for_tree_relationships(store: VBGStore) -> None:
    _build_tree(store)
    # A CALLS edge should show up in incoming/outgoing but must not be
    # mistaken for a structural parent/child relationship.
    store.insert_edge(
        Edge(source_id="A.m1", target_id="A.m2", relationship_type=RelationshipType.CALLS, repository_version=COMMIT)
    )

    neighborhood = get_neighborhood(store, "A.m1", COMMIT)

    assert neighborhood.parents == ["A"]
    assert neighborhood.children == []
    assert neighborhood.siblings == ["A.m2"]
    call_targets = {e.target_id for e in neighborhood.outgoing if e.relationship_type is RelationshipType.CALLS}
    assert call_targets == {"A.m2"}


def test_neighborhood_full_result(store: VBGStore) -> None:
    _build_tree(store)

    neighborhood = get_neighborhood(store, "M", COMMIT)

    assert neighborhood.entity_id == "M"
    assert neighborhood.repository_version == COMMIT
    assert neighborhood.parents == []
    assert neighborhood.children == ["A", "B"]
    assert neighborhood.siblings == []
    assert neighborhood.grandchildren == ["A.m1", "A.m2", "B.m3"]
    assert {e.target_id for e in neighborhood.outgoing} == {"A", "B"}
