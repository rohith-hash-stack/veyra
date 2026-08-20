from __future__ import annotations

from pathlib import Path

from veyra.retrieval import build_retrieval_index, retrieve_context
from veyra.vbg import Evidence, EvidenceType, Provenance, RelationshipType, VBGStore, edge_evidence_key

COMMIT = "commit1"


def test_retrieve_context_returns_matching_entities(sample_repo: Path, store: VBGStore) -> None:
    index = build_retrieval_index(store, COMMIT)
    context = retrieve_context(store, index, COMMIT, "process_order")
    assert context.entities[0].entity_id == "orders.process_order"


def test_retrieve_context_includes_evidence(sample_repo: Path, store: VBGStore) -> None:
    index = build_retrieval_index(store, COMMIT)
    store.insert_evidence(
        Evidence(
            subject_id="orders.process_order", evidence_type=EvidenceType.STATIC, repository_version=COMMIT,
            provenance=Provenance(producer="test", method="test", recorded_at="2026-08-20T00:00:00+00:00"),
            detail="statically extracted",
        )
    )
    context = retrieve_context(store, index, COMMIT, "process_order")
    assert len(context.evidence_by_entity["orders.process_order"]) == 1


def test_retrieve_context_includes_relationships(sample_repo: Path, store: VBGStore) -> None:
    index = build_retrieval_index(store, COMMIT)
    context = retrieve_context(store, index, COMMIT, "process_order")
    targets = {e.target_id for e in context.relationships}
    assert "orders.validate_order" in targets
    assert "orders.charge_customer" in targets


def test_retrieve_context_surfaces_conflicts(sample_repo: Path, store: VBGStore) -> None:
    index = build_retrieval_index(store, COMMIT)
    store.insert_evidence(
        Evidence(
            subject_id=edge_evidence_key("orders.process_order", "orders.somewhere_else", RelationshipType.CALLS),
            evidence_type=EvidenceType.RUNTIME, repository_version=COMMIT,
            provenance=Provenance(producer="test", method="test", recorded_at="2026-08-20T00:00:00+00:00"),
            scenario_id="s1", environment_id="e1",
        )
    )
    context = retrieve_context(store, index, COMMIT, "process_order")
    assert any(c.target_id == "orders.somewhere_else" for c in context.conflicts)


def test_no_matching_entities_returns_empty_context(sample_repo: Path, store: VBGStore) -> None:
    index = build_retrieval_index(store, COMMIT)
    context = retrieve_context(store, index, COMMIT, "xylophone quantum teapot")
    assert context.entities == ()
    assert context.relationships == ()
