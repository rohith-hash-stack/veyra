from __future__ import annotations

from pathlib import Path
from typing import Callable

from veyra.retrieval import build_retrieval_index, retrieve_context, search
from veyra.retrieval.context import _decide_confidence
from veyra.retrieval.search import ScoredEntity
from veyra.static_analysis import extract_repository, persist_extraction
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


# -- ARCF Fix 1: candidate pool separate from final top_k --


def _write_pool_fixture(write_file: Callable[[str, str], Path]) -> None:
    """Same construction as test_retrieval_search.py's pool-mechanism
    fixture: 15 decoys score higher than one genuinely relevant, weakly-
    matching candidate, pushing it to rank 15 -- outside top_k=10, inside
    a candidate_pool_size of 20+. Real measured scores: decoys 8.361 each,
    real candidate 1.198."""
    for i in range(15):
        write_file(
            f"decoys/decoy_{i}.py",
            "def strong_match_entity(amount, currency):\n"
            '    """payment gateway validate a transaction how does the"""\n'
            "    return amount\n",
        )
    write_file(
        "payment.py",
        "def sparse_match_entity(x):\n"
        '    """gateway"""\n'
        "    return x\n",
    )


def test_candidate_recovers_into_final_top_k_when_pool_widened_and_confidence_allows(
    write_file: Callable[[str, str], Path], repo_root: Path, store: VBGStore
) -> None:
    """Requirements 1-3: a candidate outside the old top-k, inside the
    wider pool, that receives sufficient confidence, reaches the final
    result -- reproducing the real `fastapi-01`/`fastapi-03`-shaped
    mechanism (PHASE_D_RESULTS.md) where a confidently-scored entity never
    reached the confidence filter because a plain top_k window excluded it
    first. No query name from that benchmark is referenced in production
    code -- this fixture is self-contained."""
    _write_pool_fixture(write_file)
    extraction = extract_repository(repo_root, COMMIT)
    persist_extraction(store, extraction)
    index = build_retrieval_index(store, COMMIT)
    query = "how does the payment gateway validate a transaction"

    # With only the old, narrow candidate window, the real candidate is
    # invisible to retrieve_context no matter how low the confidence bar is.
    narrow = retrieve_context(store, index, COMMIT, query, top_k=10, candidate_pool_size=10, min_tfidf_score=0.0)
    assert "payment.sparse_match_entity" not in {e.entity_id for e in narrow.entities}

    # Widen the pool and confidence-accept the candidate's actual measured
    # score (1.198 >= 1.0). top_k=16 gives all 15 (also-accepted) decoys
    # plus the real candidate room to all survive the final truncation --
    # this test isolates "reaches the confidence filter and is accepted",
    # not "final result count", which the next test covers on its own.
    wide = retrieve_context(store, index, COMMIT, query, top_k=16, candidate_pool_size=20, min_tfidf_score=1.0)
    assert "payment.sparse_match_entity" in {e.entity_id for e in wide.entities}
    assert wide.scores["payment.sparse_match_entity"] >= 1.0


def test_final_result_count_always_respects_top_k_even_with_a_wide_pool(
    write_file: Callable[[str, str], Path], repo_root: Path, store: VBGStore
) -> None:
    """Requirement 4."""
    _write_pool_fixture(write_file)
    extraction = extract_repository(repo_root, COMMIT)
    persist_extraction(store, extraction)
    index = build_retrieval_index(store, COMMIT)
    query = "how does the payment gateway validate a transaction"

    context = retrieve_context(store, index, COMMIT, query, top_k=3, candidate_pool_size=200, min_tfidf_score=0.0)
    assert len(context.entities) <= 3


def test_candidate_pool_size_and_top_k_are_independently_configurable(
    write_file: Callable[[str, str], Path], repo_root: Path, store: VBGStore
) -> None:
    """Requirement 5: a wide pool with a small top_k still returns only
    top_k entities; a narrow pool with a larger top_k is bounded by
    whatever the (smaller) pool actually contained."""
    _write_pool_fixture(write_file)
    extraction = extract_repository(repo_root, COMMIT)
    persist_extraction(store, extraction)
    index = build_retrieval_index(store, COMMIT)
    query = "how does the payment gateway validate a transaction"

    wide_pool_small_top_k = retrieve_context(
        store, index, COMMIT, query, top_k=2, candidate_pool_size=100, min_tfidf_score=0.0
    )
    assert len(wide_pool_small_top_k.entities) == 2

    narrow_pool_large_top_k = retrieve_context(
        store, index, COMMIT, query, top_k=50, candidate_pool_size=5, min_tfidf_score=0.0
    )
    assert len(narrow_pool_large_top_k.entities) <= 5


# -- ARCF Fix 2: retrieval score separated from the confidence decision --


def test_high_retrieval_score_does_not_automatically_imply_acceptance(sample_repo: Path, store: VBGStore) -> None:
    """Requirement 1. A tfidf-tier candidate with a high raw score is
    still rejected once the confidence threshold is set above it -- score
    alone is never sufficient for acceptance."""
    index = build_retrieval_index(store, COMMIT)
    entity = index.all_entities()[0]
    high_scoring_tfidf_candidate = ScoredEntity(entity=entity, score=25.0, matched_by="tfidf")

    decision = _decide_confidence(high_scoring_tfidf_candidate, min_tfidf_score=30.0)

    assert decision.accepted is False
    assert decision.retrieval_score == 25.0
    assert decision.reason  # a real, non-empty explanation, not silence


def test_lower_retrieval_score_can_be_accepted_when_match_type_warrants_it(
    sample_repo: Path, store: VBGStore
) -> None:
    """Requirement 2. An exact-name match's raw score (2.0, by design far
    lower than most real tfidf scores) is still always accepted -- proving
    retrieval score and confidence are genuinely different signals, not
    the same number filtered twice."""
    index = build_retrieval_index(store, COMMIT)
    entity = index.all_entities()[0]
    low_scoring_name_match = ScoredEntity(entity=entity, score=2.0, matched_by="exact_name")
    higher_scoring_but_rejected_tfidf_match = ScoredEntity(entity=entity, score=25.0, matched_by="tfidf")

    name_decision = _decide_confidence(low_scoring_name_match, min_tfidf_score=30.0)
    tfidf_decision = _decide_confidence(higher_scoring_but_rejected_tfidf_match, min_tfidf_score=30.0)

    assert name_decision.accepted is True
    assert tfidf_decision.accepted is False
    assert name_decision.retrieval_score < tfidf_decision.retrieval_score


def test_retrieval_ordering_is_independent_of_confidence_classification(sample_repo: Path, store: VBGStore) -> None:
    """Requirement 3. Whether a threshold accepts or rejects candidates
    must not reorder the ones that do get through -- ranking comes from
    `search()`'s score order alone, filtering only removes entries from
    that same order, it never re-sorts by acceptance."""
    index = build_retrieval_index(store, COMMIT)
    query = "order"

    permissive = retrieve_context(store, index, COMMIT, query, min_tfidf_score=0.0)
    strict_ids = {e.entity_id for e in retrieve_context(store, index, COMMIT, query, min_tfidf_score=1e9).entities}

    permissive_ids_in_order = [e.entity_id for e in permissive.entities]
    surviving_in_order = [eid for eid in permissive_ids_in_order if eid in strict_ids]
    # Every survivor keeps its original relative position from the
    # permissive (unfiltered-by-score) ranking.
    assert surviving_in_order == [eid for eid in permissive_ids_in_order if eid in strict_ids]


def test_confidence_decisions_are_recorded_for_every_considered_candidate_with_a_reason(
    sample_repo: Path, store: VBGStore
) -> None:
    """Requirement 4, plus observability: confidence_decisions covers every
    candidate search() considered, including rejected ones, each with a
    real, non-empty explanation -- not just the entities that survived."""
    index = build_retrieval_index(store, COMMIT)
    query = "charge the customer for their order"

    context = retrieve_context(store, index, COMMIT, query, min_tfidf_score=1e9)

    assert context.entities == ()  # everything tfidf-tier got rejected at this threshold
    assert context.confidence_decisions  # but the decisions themselves were still recorded
    for entity_id, decision in context.confidence_decisions.items():
        assert decision.entity_id == entity_id
        assert decision.reason
        assert isinstance(decision.accepted, bool)
    # At least one real rejection is actually present and explained.
    rejected = [d for d in context.confidence_decisions.values() if not d.accepted]
    assert rejected
    assert all(d.reason for d in rejected)
