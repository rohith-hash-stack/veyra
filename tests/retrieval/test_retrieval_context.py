from __future__ import annotations

from pathlib import Path

from veyra.retrieval import build_retrieval_index, retrieve_context, search
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
    assert context.insufficient_evidence is True


# -- Phase B: confidence propagation (benchmarks/real_world_python/REPORT.md) --


def test_scores_and_matched_by_are_carried_for_every_retrieved_entity(sample_repo: Path, store: VBGStore) -> None:
    index = build_retrieval_index(store, COMMIT)
    context = retrieve_context(store, index, COMMIT, "process_order")
    for entity in context.entities:
        assert entity.entity_id in context.scores
        assert entity.entity_id in context.matched_by
    assert context.matched_by["orders.process_order"] == "exact_name"
    assert context.scores["orders.process_order"] == 2.0


def test_low_confidence_tfidf_match_is_suppressed_between_two_real_measured_scores(
    sample_repo: Path, store: VBGStore
) -> None:
    """Derives real scores dynamically (rather than hardcoding numbers tied
    to one scoring algorithm's scale -- Phase D already changed that scale
    once, from bounded cosine similarity to unbounded BM25 sums) and picks a
    threshold strictly between two real, currently-measured scores, so this
    test verifies the suppression *mechanism* itself, decoupled from
    whatever the current default threshold or scoring formula happens to
    produce."""
    index = build_retrieval_index(store, COMMIT)
    query = "charge the customer for their order"
    raw = search(index, query, top_k=10)
    tfidf_scores = {r.entity.entity_id: r.score for r in raw if r.matched_by == "tfidf"}
    assert "orders.charge_customer" in tfidf_scores and "orders.validate_order" in tfidf_scores
    # charge_customer's docstring/name lexically dominates this query; validate_order
    # only shares "order". Confirm that real ordering, then threshold strictly between them.
    assert tfidf_scores["orders.charge_customer"] > tfidf_scores["orders.validate_order"]
    threshold = (tfidf_scores["orders.charge_customer"] + tfidf_scores["orders.validate_order"]) / 2

    context = retrieve_context(store, index, COMMIT, query, min_tfidf_score=threshold)

    ids = {e.entity_id for e in context.entities}
    assert "orders.charge_customer" in ids
    assert "orders.validate_order" not in ids
    assert context.insufficient_evidence is False


def test_custom_min_tfidf_score_can_suppress_every_result(sample_repo: Path, store: VBGStore) -> None:
    index = build_retrieval_index(store, COMMIT)
    query = "charge the customer for their order"
    raw = search(index, query, top_k=10)
    # A threshold strictly above every real score observed for this query
    # must suppress everything -- not silently fall back to best-effort top-k.
    above_everything = max((r.score for r in raw), default=0.0) + 1.0

    context = retrieve_context(store, index, COMMIT, query, min_tfidf_score=above_everything)
    assert context.entities == ()
    assert context.insufficient_evidence is True


def test_exact_name_match_is_never_suppressed_by_the_confidence_threshold(sample_repo: Path, store: VBGStore) -> None:
    index = build_retrieval_index(store, COMMIT)
    context = retrieve_context(store, index, COMMIT, "process_order", min_tfidf_score=0.99)
    assert context.entities[0].entity_id == "orders.process_order"
    assert context.insufficient_evidence is False
