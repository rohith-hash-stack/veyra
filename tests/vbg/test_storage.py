"""
Tests for PLAN.md Phase 1.2's storage layer, covering the acceptance
criteria that only make sense at the storage level: "historical records
cannot be silently overwritten" and "conflicts are representable".
"""

from __future__ import annotations

from pathlib import Path

import pytest

from veyra.acquisition import AcquisitionStatus, RepositoryInfo
from veyra.vbg import Edge, Node, RelationshipType, VBGStore, VerificationState


def _make_repository_info(
    *,
    status: AcquisitionStatus = AcquisitionStatus.SUCCESS,
    commit_sha: str | None = "a" * 40,
    error_reason: str | None = None,
) -> RepositoryInfo:
    return RepositoryInfo(
        source="https://example.invalid/repo.git",
        local_path=Path("/tmp/does-not-matter"),
        status=status,
        commit_sha=commit_sha,
        file_count=3,
        language_counts={"Python": 3},
        repository_size_bytes=1024,
        clone_start=0.0,
        clone_end=1.5,
        clone_duration_seconds=1.5,
        error_reason=error_reason,
    )


# -- Nodes ----------------------------------------------------------------


def test_insert_and_retrieve_node(store: VBGStore) -> None:
    node = Node(
        entity_id="OrderService.process_order",
        type="Method",
        name="process_order",
        repository_version="commit1",
        language="Python",
    )
    store.insert_node(node)

    latest = store.get_latest_node("OrderService.process_order", "commit1")

    assert latest is not None
    assert latest.name == "process_order"
    assert latest.language == "Python"


def test_node_history_is_scoped_to_exact_repository_version(store: VBGStore) -> None:
    store.insert_node(
        Node(entity_id="foo", type="Function", name="foo_v1", repository_version="commit1")
    )
    store.insert_node(
        Node(entity_id="foo", type="Function", name="foo_v2", repository_version="commit2")
    )

    commit1_history = store.get_node_history("foo", "commit1")
    commit2_history = store.get_node_history("foo", "commit2")

    assert [n.name for n in commit1_history] == ["foo_v1"]
    assert [n.name for n in commit2_history] == ["foo_v2"]


def test_node_history_preserves_conflicting_writes(store: VBGStore) -> None:
    # Two writes for the SAME (entity_id, repository_version) that disagree --
    # e.g. two analysis runs producing different data for the same commit.
    first = Node(
        entity_id="foo", type="Function", name="foo",
        repository_version="commit1", status=VerificationState.STRUCTURALLY_IDENTIFIED,
    )
    second = Node(
        entity_id="foo", type="Function", name="foo",
        repository_version="commit1", status=VerificationState.CONFLICTED,
    )
    store.insert_node(first)
    store.insert_node(second)

    history = store.get_node_history("foo", "commit1")

    # Nothing was overwritten: both rows are still there, in write order.
    assert len(history) == 2
    assert history[0].status is VerificationState.STRUCTURALLY_IDENTIFIED
    assert history[1].status is VerificationState.CONFLICTED
    # And the convenience "current" view surfaces the most recent one.
    assert store.get_latest_node("foo", "commit1").status is VerificationState.CONFLICTED


# -- Edges ------------------------------------------------------------------


def test_insert_and_retrieve_edge(store: VBGStore) -> None:
    edge = Edge(
        source_id="OrderService.process_order",
        target_id="PaymentService.charge",
        relationship_type=RelationshipType.CALLS,
        repository_version="commit1",
    )
    store.insert_edge(edge)

    latest = store.get_latest_edge(
        "OrderService.process_order", "PaymentService.charge",
        RelationshipType.CALLS, "commit1",
    )

    assert latest is not None
    assert latest.relationship_type is RelationshipType.CALLS


def test_edge_history_preserves_conflicting_writes(store: VBGStore) -> None:
    store.insert_edge(
        Edge(source_id="a", target_id="b", relationship_type=RelationshipType.CALLS,
             repository_version="commit1", status=VerificationState.STATICALLY_SUPPORTED)
    )
    store.insert_edge(
        Edge(source_id="a", target_id="b", relationship_type=RelationshipType.CALLS,
             repository_version="commit1", status=VerificationState.RUNTIME_OBSERVED)
    )

    history = store.get_edge_history("a", "b", RelationshipType.CALLS, "commit1")

    assert len(history) == 2
    assert [e.status for e in history] == [
        VerificationState.STATICALLY_SUPPORTED,
        VerificationState.RUNTIME_OBSERVED,
    ]


# -- Immutability by design, not just by convention -------------------------


def test_store_exposes_no_update_or_delete_methods(store: VBGStore) -> None:
    forbidden_names = ("update_node", "delete_node", "update_edge", "delete_edge")
    for name in forbidden_names:
        assert not hasattr(store, name), (
            f"VBGStore must not expose {name} -- historical records cannot be "
            "silently overwritten (PLAN.md Phase 1.2)."
        )


# -- Repository acquisition record (Phase 1.1 -> Phase 1.2 integration) -----


def test_record_repository_from_successful_acquisition(store: VBGStore) -> None:
    info = _make_repository_info()

    store.record_repository(info)
    history = store.get_repository_history(info.source, info.commit_sha)

    assert len(history) == 1
    assert history[0].file_count == 3
    assert history[0].language_counts == {"Python": 3}


def test_record_repository_rejects_failed_acquisition(store: VBGStore) -> None:
    info = _make_repository_info(
        status=AcquisitionStatus.FAILED, commit_sha=None, error_reason="clone failed"
    )

    with pytest.raises(ValueError):
        store.record_repository(info)


def test_repository_history_preserves_multiple_acquisitions(store: VBGStore) -> None:
    info = _make_repository_info()

    store.record_repository(info)
    store.record_repository(info)  # re-acquiring the same commit is a new event, not a dupe error

    history = store.get_repository_history(info.source, info.commit_sha)

    assert len(history) == 2


# -- Connection lifecycle (performance finding: one connection per instance,
# not one per call -- measured at 96,105 separate sqlite3.connect() calls
# to build one real retrieval index) --


def test_connection_is_reused_across_calls_not_recreated_per_call(store: VBGStore) -> None:
    """The actual regression-protection test: the intended lifecycle
    behavior (one lazily-created connection, reused for the life of the
    instance) rather than an arbitrary exact connection-count assertion,
    which the architecture doesn't establish any particular number for."""
    first = store._connect()
    second = store._connect()
    assert first is second  # the same live object, not a new connect() each time

    # And it's still a real, working connection after multiple operations --
    # reuse doesn't mean stale or broken.
    node = Node(
        entity_id="m.f", type="Function", name="f", repository_version="c1", language="Python",
    )
    store.insert_node(node)
    store.insert_node(node)
    assert store._connect() is first
    assert len(store.get_node_history("m.f", "c1")) == 2


def test_each_store_instance_gets_its_own_connection(tmp_path: Path) -> None:
    """Reuse is per-instance, not a shared global -- two VBGStore objects
    (even on the same db path) never end up sharing one connection."""
    path = tmp_path / "shared.sqlite3"
    store_a = VBGStore(path)
    store_b = VBGStore(path)
    try:
        assert store_a._connect() is not store_b._connect()
    finally:
        store_a.close()
        store_b.close()


def test_close_releases_the_connection_and_a_later_call_reopens_one(tmp_path: Path) -> None:
    store = VBGStore(tmp_path / "v.sqlite3")
    first = store._connect()

    store.close()

    # A later call transparently opens a fresh connection rather than
    # raising on a closed one -- close() is a clean release, not a
    # permanent shutdown of the instance.
    second = store._connect()
    assert second is not first
    node = Node(entity_id="m.f", type="Function", name="f", repository_version="c1", language="Python")
    store.insert_node(node)  # proves the reopened connection actually works
    store.close()


def test_get_incoming_edges_uses_an_index_not_a_full_table_scan(store: VBGStore) -> None:
    """Regression protection for the other real Fix 8 finding: the
    original schema's only edges index led with source_id, so
    get_incoming_edges()'s target_id-first WHERE clause (get_parents/
    get_siblings' actual query, called once per entity while building a
    retrieval index) could only ever do "SCAN edges USING COVERING INDEX
    idx_edges_key_version" -- a full index scan, confirmed directly via
    EXPLAIN QUERY PLAN before this was fixed. idx_edges_target_version
    gives that query path its own leading column. Tests the query plan
    itself (the actual mechanism), not a timing threshold."""
    conn = store._connect()
    plan_rows = conn.execute(
        """
        EXPLAIN QUERY PLAN
        SELECT e.* FROM edges e
        INNER JOIN (
            SELECT source_id, relationship_type, MAX(row_id) AS max_row_id
            FROM edges
            WHERE target_id = ? AND repository_version = ?
            GROUP BY source_id, relationship_type
        ) latest
        ON e.source_id = latest.source_id
           AND e.relationship_type = latest.relationship_type
           AND e.row_id = latest.max_row_id
        WHERE e.target_id = ? AND e.repository_version = ?
        """,
        ("x", "c1", "x", "c1"),
    ).fetchall()
    plan_text = " ".join(str(tuple(row)) for row in plan_rows)
    assert "idx_edges_target_version" in plan_text
    assert "SCAN edges USING COVERING INDEX idx_edges_key_version" not in plan_text
