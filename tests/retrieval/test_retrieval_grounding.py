from __future__ import annotations

from pathlib import Path

from veyra.retrieval import build_grounding_context, build_retrieval_index, retrieve_context
from veyra.vbg import (
    Evidence,
    EvidenceType,
    Provenance,
    RelationshipType,
    VBGStore,
    VerificationState,
    edge_evidence_key,
)

COMMIT = "commit1"


def test_every_fact_carries_a_verification_note(sample_repo: Path, store: VBGStore) -> None:
    index = build_retrieval_index(store, COMMIT)
    retrieved = retrieve_context(store, index, COMMIT, "process_order")

    grounding = build_grounding_context(retrieved)

    assert len(grounding.facts) > 0
    assert all(fact.verification_note for fact in grounding.facts)


def test_unverified_state_gets_a_hedging_note(store: VBGStore) -> None:
    from veyra.retrieval.grounding import _VERIFICATION_NOTES

    note = _VERIFICATION_NOTES[VerificationState.STATICALLY_SUPPORTED]
    assert "NOTE" in note
    assert "never actually been executed" in note


def test_runtime_verified_state_is_stated_without_hedge_language(store: VBGStore) -> None:
    from veyra.retrieval.grounding import _VERIFICATION_NOTES

    note = _VERIFICATION_NOTES[VerificationState.RUNTIME_VERIFIED]
    assert "NOTE" not in note  # a genuinely confirmed fact isn't hedged


def test_disclaimer_is_always_present(sample_repo: Path, store: VBGStore) -> None:
    index = build_retrieval_index(store, COMMIT)
    retrieved = retrieve_context(store, index, COMMIT, "process_order")
    grounding = build_grounding_context(retrieved)
    assert "hedge" in grounding.disclaimer.lower()


def test_conflicts_are_rendered_as_readable_text(sample_repo: Path, store: VBGStore) -> None:
    index = build_retrieval_index(store, COMMIT)
    store.insert_evidence(
        Evidence(
            subject_id=edge_evidence_key("orders.process_order", "orders.somewhere_else", RelationshipType.CALLS),
            evidence_type=EvidenceType.RUNTIME, repository_version=COMMIT,
            provenance=Provenance(producer="test", method="test", recorded_at="2026-08-20T00:00:00+00:00"),
            scenario_id="s1", environment_id="e1",
        )
    )
    retrieved = retrieve_context(store, index, COMMIT, "process_order")

    grounding = build_grounding_context(retrieved)

    assert len(grounding.conflicts) == 1
    assert "disagree" in grounding.conflicts[0]


def test_unknowns_lists_referenced_but_unretrieved_entities(sample_repo: Path, store: VBGStore) -> None:
    index = build_retrieval_index(store, COMMIT)
    # Search narrowly enough that process_order's own callees aren't
    # independently retrieved -- they should show up as "unknowns" instead.
    retrieved = retrieve_context(store, index, COMMIT, "process_order", top_k=1)

    grounding = build_grounding_context(retrieved)

    assert "orders.validate_order" in grounding.unknowns
    assert "orders.charge_customer" in grounding.unknowns


def test_repository_version_is_explicit(sample_repo: Path, store: VBGStore) -> None:
    index = build_retrieval_index(store, COMMIT)
    retrieved = retrieve_context(store, index, COMMIT, "process_order")
    grounding = build_grounding_context(retrieved)
    assert grounding.repository_version == COMMIT


def test_evidence_excerpts_come_from_real_evidence_details(sample_repo: Path, store: VBGStore) -> None:
    index = build_retrieval_index(store, COMMIT)
    store.insert_evidence(
        Evidence(
            subject_id="orders.process_order", evidence_type=EvidenceType.STATIC, repository_version=COMMIT,
            provenance=Provenance(producer="test", method="test", recorded_at="2026-08-20T00:00:00+00:00"),
            detail="a real, specific static observation",
        )
    )
    retrieved = retrieve_context(store, index, COMMIT, "process_order")

    grounding = build_grounding_context(retrieved)

    fact = next(f for f in grounding.facts if f.entity_id == "orders.process_order")
    assert "a real, specific static observation" in fact.evidence_excerpts
