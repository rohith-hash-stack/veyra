"""
Tests for VBGStore.get_outgoing_edges / get_incoming_edges -- the
graph-traversal primitives Phase 2.4 (Neighborhood Model) is built on.
"""

from __future__ import annotations

from veyra.vbg import Edge, Node, RelationshipType, VBGStore, VerificationState


def _edge(source, target, rel, version="commit1", status=VerificationState.STRUCTURALLY_IDENTIFIED):
    return Edge(source_id=source, target_id=target, relationship_type=rel, repository_version=version, status=status)


def _node(entity_id, node_type="Function", version="commit1"):
    return Node(entity_id=entity_id, type=node_type, name=entity_id, repository_version=version)


def test_get_outgoing_edges(store: VBGStore) -> None:
    store.insert_edge(_edge("A", "B", RelationshipType.CONTAINS))
    store.insert_edge(_edge("A", "C", RelationshipType.CALLS))
    store.insert_edge(_edge("X", "Y", RelationshipType.CONTAINS))  # unrelated source

    outgoing = store.get_outgoing_edges("A", "commit1")

    pairs = {(e.target_id, e.relationship_type) for e in outgoing}
    assert pairs == {("B", RelationshipType.CONTAINS), ("C", RelationshipType.CALLS)}


def test_get_incoming_edges(store: VBGStore) -> None:
    store.insert_edge(_edge("A", "Z", RelationshipType.CONTAINS))
    store.insert_edge(_edge("B", "Z", RelationshipType.CALLS))
    store.insert_edge(_edge("A", "Q", RelationshipType.CONTAINS))  # unrelated target

    incoming = store.get_incoming_edges("Z", "commit1")

    pairs = {(e.source_id, e.relationship_type) for e in incoming}
    assert pairs == {("A", RelationshipType.CONTAINS), ("B", RelationshipType.CALLS)}


def test_outgoing_edges_use_latest_on_conflicting_history(store: VBGStore) -> None:
    store.insert_edge(_edge("A", "B", RelationshipType.CALLS, status=VerificationState.STATICALLY_SUPPORTED))
    store.insert_edge(_edge("A", "B", RelationshipType.CALLS, status=VerificationState.RUNTIME_OBSERVED))

    outgoing = store.get_outgoing_edges("A", "commit1")

    assert len(outgoing) == 1  # deduped to the (target, type) pair
    assert outgoing[0].status is VerificationState.RUNTIME_OBSERVED  # most recent wins for this "current" view


def test_edges_scoped_to_repository_version(store: VBGStore) -> None:
    store.insert_edge(_edge("A", "B", RelationshipType.CONTAINS, version="commit1"))
    store.insert_edge(_edge("A", "B", RelationshipType.CONTAINS, version="commit2"))

    assert len(store.get_outgoing_edges("A", "commit1")) == 1
    assert len(store.get_outgoing_edges("A", "commit2")) == 1


def test_no_edges_returns_empty_list(store: VBGStore) -> None:
    assert store.get_outgoing_edges("nonexistent", "commit1") == []
    assert store.get_incoming_edges("nonexistent", "commit1") == []


def test_get_all_nodes(store: VBGStore) -> None:
    store.insert_node(_node("A"))
    store.insert_node(_node("B"))
    store.insert_node(_node("C", version="commit2"))  # different commit

    nodes = store.get_all_nodes("commit1")

    assert {n.entity_id for n in nodes} == {"A", "B"}


def test_get_all_nodes_dedupes_to_latest_per_entity(store: VBGStore) -> None:
    store.insert_node(Node(entity_id="A", type="Function", name="A", repository_version="commit1", occurrence_count=1))
    store.insert_node(Node(entity_id="A", type="Function", name="A", repository_version="commit1", occurrence_count=2))

    nodes = store.get_all_nodes("commit1")

    assert len(nodes) == 1
    assert nodes[0].occurrence_count == 2


def test_get_all_edges(store: VBGStore) -> None:
    store.insert_edge(_edge("A", "B", RelationshipType.CONTAINS))
    store.insert_edge(_edge("A", "C", RelationshipType.CALLS))
    store.insert_edge(_edge("X", "Y", RelationshipType.CONTAINS, version="commit2"))

    edges = store.get_all_edges("commit1")

    assert {(e.source_id, e.target_id) for e in edges} == {("A", "B"), ("A", "C")}
