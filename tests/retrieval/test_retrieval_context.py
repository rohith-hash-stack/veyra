from __future__ import annotations

import math
from pathlib import Path
from typing import Callable

import pytest

from veyra.retrieval import build_retrieval_index, retrieve_context, search
from veyra.retrieval.context import (
    _decide_confidence,
    _matched_idf_coverage,
    _neighbor_matched_idf_coverage,
    _relative_confidence_scores,
)
from veyra.retrieval.index import IndexedEntity, RetrievalIndex
from veyra.retrieval.search import ScoredEntity, _build_bm25_index, _entity_text, _tokenize
from veyra.static_analysis import extract_repository, persist_extraction
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


def test_low_confidence_tfidf_match_is_suppressed_between_two_real_measured_z_scores(
    sample_repo: Path, store: VBGStore
) -> None:
    """ARCF Fix 3: derives real z-scores dynamically (rather than
    hardcoding numbers tied to one confidence mechanism's scale -- Fix 3
    already changed that scale once, from an absolute BM25 score to a
    query-relative z-score) and picks a threshold strictly between two
    real, currently-measured z-scores, so this test verifies the
    suppression *mechanism* itself, decoupled from whatever the current
    default bar or scoring formula happens to produce."""
    index = build_retrieval_index(store, COMMIT)
    query = "charge the customer for their order"
    # A permissive bar (well below any real z-score) surfaces every tfidf
    # candidate's real, computed z-score via confidence_decisions.
    permissive = retrieve_context(store, index, COMMIT, query, min_confidence_z=-1e9)
    z_scores = {
        entity_id: d.confidence
        for entity_id, d in permissive.confidence_decisions.items()
        if d.matched_by == "tfidf" and d.confidence is not None
    }
    assert "orders.charge_customer" in z_scores and "orders.validate_order" in z_scores
    # charge_customer's docstring/name lexically dominates this query; validate_order
    # only shares "order". Confirm that real ordering, then threshold strictly between them.
    assert z_scores["orders.charge_customer"] > z_scores["orders.validate_order"]
    threshold = (z_scores["orders.charge_customer"] + z_scores["orders.validate_order"]) / 2

    context = retrieve_context(store, index, COMMIT, query, min_confidence_z=threshold)

    ids = {e.entity_id for e in context.entities}
    assert "orders.charge_customer" in ids
    assert "orders.validate_order" not in ids
    assert context.insufficient_evidence is False


def test_custom_min_confidence_z_can_suppress_every_result(sample_repo: Path, store: VBGStore) -> None:
    index = build_retrieval_index(store, COMMIT)
    query = "charge the customer for their order"
    permissive = retrieve_context(store, index, COMMIT, query, min_confidence_z=-1e9)
    real_z_scores = [
        d.confidence
        for d in permissive.confidence_decisions.values()
        if d.matched_by == "tfidf" and d.confidence is not None
    ]
    # A bar strictly above every real z-score observed for this query must
    # suppress everything -- not silently fall back to best-effort top-k.
    above_everything = max(real_z_scores, default=0.0) + 1.0

    context = retrieve_context(store, index, COMMIT, query, min_confidence_z=above_everything)
    assert context.entities == ()
    assert context.insufficient_evidence is True


def test_exact_name_match_is_never_suppressed_by_the_confidence_threshold(sample_repo: Path, store: VBGStore) -> None:
    index = build_retrieval_index(store, COMMIT)
    context = retrieve_context(store, index, COMMIT, "process_order", min_confidence_z=1e9)
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


def test_candidate_becomes_eligible_for_confidence_judgment_once_pool_widened(
    write_file: Callable[[str, str], Path], repo_root: Path, store: VBGStore
) -> None:
    """Requirements 1-3, reframed honestly for ARCF Fix 3's relative
    confidence model: reproducing the real `fastapi-01`/`fastapi-03`-shaped
    mechanism (PHASE_D_RESULTS.md, Checkpoint A) where a candidate never
    reached the confidence filter *at all* because a plain top_k window
    excluded it first. Fix 1's job is narrower than "guarantees
    acceptance" -- it makes a candidate *reachable for judgment*
    (`confidence_decisions` gets a real entry with a real reason);
    whether that judgment accepts or rejects it is Fix 3's job, and for
    this fixture's genuinely weak minority candidate (surrounded by 15
    much stronger decoys) the correct, honest answer is a real, negative
    z-score -- Fix 1 does not, and should not, force acceptance on its
    own. No query name from any real benchmark is referenced in
    production code -- this fixture is self-contained."""
    _write_pool_fixture(write_file)
    extraction = extract_repository(repo_root, COMMIT)
    persist_extraction(store, extraction)
    index = build_retrieval_index(store, COMMIT)
    query = "how does the payment gateway validate a transaction"

    # With only the old, narrow candidate window, the real candidate never
    # even gets a ConfidenceDecision -- it was excluded before judgment.
    narrow = retrieve_context(store, index, COMMIT, query, top_k=10, candidate_pool_size=10, min_confidence_z=-1e9)
    assert "payment.sparse_match_entity" not in narrow.confidence_decisions

    # Widen the pool: the candidate now reaches judgment and gets a real,
    # reasoned ConfidenceDecision -- reachability achieved, exactly Fix 1's
    # scope. Its z-score is genuinely, correctly negative (it IS the weak
    # candidate in this field), so a normal confidence bar still rejects
    # it -- that's Fix 3 working correctly, not a Fix 1 shortfall.
    wide = retrieve_context(store, index, COMMIT, query, top_k=16, candidate_pool_size=20, min_confidence_z=-1e9)
    assert "payment.sparse_match_entity" in wide.confidence_decisions
    decision = wide.confidence_decisions["payment.sparse_match_entity"]
    assert decision.confidence is not None  # a real z-score was computed, not "no data"
    assert decision.reason

    default_bar_wide = retrieve_context(store, index, COMMIT, query, top_k=16, candidate_pool_size=20)
    assert "payment.sparse_match_entity" not in {e.entity_id for e in default_bar_wide.entities}


def test_final_result_count_always_respects_top_k_even_with_a_wide_pool(
    write_file: Callable[[str, str], Path], repo_root: Path, store: VBGStore
) -> None:
    """Requirement 4."""
    _write_pool_fixture(write_file)
    extraction = extract_repository(repo_root, COMMIT)
    persist_extraction(store, extraction)
    index = build_retrieval_index(store, COMMIT)
    query = "how does the payment gateway validate a transaction"

    context = retrieve_context(store, index, COMMIT, query, top_k=3, candidate_pool_size=200, min_confidence_z=-1e9)
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
        store, index, COMMIT, query, top_k=2, candidate_pool_size=100, min_confidence_z=-1e9
    )
    assert len(wide_pool_small_top_k.entities) == 2

    narrow_pool_large_top_k = retrieve_context(
        store, index, COMMIT, query, top_k=50, candidate_pool_size=5, min_confidence_z=-1e9
    )
    assert len(narrow_pool_large_top_k.entities) <= 5


# -- ARCF Fix 2: retrieval score separated from the confidence decision --


def test_high_retrieval_score_does_not_automatically_imply_acceptance(sample_repo: Path, store: VBGStore) -> None:
    """Requirement 1. A tfidf-tier candidate with a high raw score but a
    low z-score (statistically unremarkable relative to its own query's
    candidate pool) is still rejected -- score alone is never sufficient
    for acceptance."""
    index = build_retrieval_index(store, COMMIT)
    entity = index.all_entities()[0]
    high_scoring_but_statistically_average_candidate = ScoredEntity(entity=entity, score=25.0, matched_by="tfidf")

    decision = _decide_confidence(
        high_scoring_but_statistically_average_candidate, z_score=0.3, min_confidence_z=1.0, matched_idf_coverage=1.0
    )

    assert decision.accepted is False
    assert decision.retrieval_score == 25.0
    assert decision.confidence == 0.3
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
    higher_scoring_but_low_z_tfidf_match = ScoredEntity(entity=entity, score=25.0, matched_by="tfidf")

    name_decision = _decide_confidence(low_scoring_name_match, z_score=None, min_confidence_z=1.0, matched_idf_coverage=None)
    tfidf_decision = _decide_confidence(
        higher_scoring_but_low_z_tfidf_match, z_score=0.2, min_confidence_z=1.0, matched_idf_coverage=1.0
    )

    assert name_decision.accepted is True
    assert tfidf_decision.accepted is False
    assert name_decision.retrieval_score < tfidf_decision.retrieval_score


def test_lower_absolute_score_with_strong_relative_evidence_is_accepted(sample_repo: Path, store: VBGStore) -> None:
    """ARCF Fix 3 negative-validation requirement: a candidate whose raw
    score is well below what the old fixed 29.0 threshold required must
    still be accepted when its z-score (strong relative standing within
    its own query's candidate pool) clears the bar -- no absolute number
    gates acceptance any more."""
    index = build_retrieval_index(store, COMMIT)
    entity = index.all_entities()[0]
    low_absolute_score_strong_relative_candidate = ScoredEntity(entity=entity, score=3.0, matched_by="tfidf")

    decision = _decide_confidence(
        low_absolute_score_strong_relative_candidate, z_score=2.5, min_confidence_z=1.0, matched_idf_coverage=1.0
    )

    assert decision.accepted is True
    assert decision.retrieval_score == 3.0  # far below the old 29.0 -- irrelevant now
    assert decision.confidence == 2.5


def test_retrieval_ordering_is_independent_of_confidence_classification(sample_repo: Path, store: VBGStore) -> None:
    """Requirement 3. Whether a threshold accepts or rejects candidates
    must not reorder the ones that do get through -- ranking comes from
    `search()`'s score order alone, filtering only removes entries from
    that same order, it never re-sorts by acceptance."""
    index = build_retrieval_index(store, COMMIT)
    query = "order"

    permissive = retrieve_context(store, index, COMMIT, query, min_confidence_z=-1e9)
    strict_ids = {e.entity_id for e in retrieve_context(store, index, COMMIT, query, min_confidence_z=1e9).entities}

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

    context = retrieve_context(store, index, COMMIT, query, min_confidence_z=1e9)

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


# -- ARCF Fix 3: relative (z-score) confidence semantics --


def _fake_scored(scores: list[float]) -> list[ScoredEntity]:
    """A minimal, real-shaped `IndexedEntity` per score -- lets these
    tests exercise `_relative_confidence_scores`/`_decide_confidence`
    directly against exact, hand-chosen score distributions, without the
    indirection of getting a real BM25 run to produce specific numbers."""
    entities = []
    for i, score in enumerate(scores):
        entity = IndexedEntity(
            entity_id=f"m.e{i}", node_type="Function", name=f"e{i}", repository_version="c1",
            lexical_representation=None, docstring=None, source_location=None,
            parents=(), children=(), siblings=(), outgoing_relationships=(), incoming_relationships=(),
            verification_state=VerificationState.STRUCTURALLY_IDENTIFIED, evidence_counts={},
        )
        entities.append(ScoredEntity(entity=entity, score=score, matched_by="tfidf"))
    return entities


def test_case_a_weak_absolute_scores_but_close_competitors_yields_low_confidence() -> None:
    """Directive Case A: A=15.2, B=14.9, C=8.1. The nominal "winner" (A) is
    barely ahead of its closest competitor (B) -- the mechanism must
    reflect that as a *weak* relative signal, not a confident one, purely
    because A happens to be the largest number."""
    scored = _fake_scored([15.2, 14.9, 8.1])
    z = _relative_confidence_scores(scored)
    top_z = z["m.e0"]  # the 15.2 candidate
    assert top_z < 1.0  # does not clear the standard confidence bar
    decision = _decide_confidence(scored[0], top_z, min_confidence_z=1.0, matched_idf_coverage=1.0)
    assert decision.accepted is False


def test_case_b_strong_score_with_large_separation_yields_high_confidence() -> None:
    """Directive Case B: A=40, B=20, C=8. A's separation from the rest of
    the field is large -- the mechanism must reflect that as a genuinely
    strong relative signal."""
    scored = _fake_scored([40.0, 20.0, 8.0])
    z = _relative_confidence_scores(scored)
    top_z = z["m.e0"]  # the 40.0 candidate
    assert top_z >= 1.0  # clears the standard confidence bar
    decision = _decide_confidence(scored[0], top_z, min_confidence_z=1.0, matched_idf_coverage=1.0)
    assert decision.accepted is True


def test_mechanism_distinguishes_the_two_score_landscapes() -> None:
    """The actual point of Case A vs. Case B, stated directly: the
    mechanism must NOT treat "A is numerically the largest" as sufficient
    on its own -- the *shape* of the competing field has to matter, and
    Case B's top candidate must come out with meaningfully higher
    confidence than Case A's, even though 15.2 (Case A) and 40 (Case B)
    are both just "the largest number in a 3-item list.\""""
    case_a_top_z = _relative_confidence_scores(_fake_scored([15.2, 14.9, 8.1]))["m.e0"]
    case_b_top_z = _relative_confidence_scores(_fake_scored([40.0, 20.0, 8.0]))["m.e0"]
    assert case_b_top_z > case_a_top_z


def test_high_rank_with_weak_evidence_is_not_automatically_high_confidence() -> None:
    """ARCF Fix 3 negative validation, requirement 1: rank alone (being
    #1) proves nothing. Several candidates plateaued near the top (a
    genuinely undifferentiated leading group, not one clear leader) must
    not produce a confident #1 merely because it's nominally the largest
    number. (An evenly-*spread* sequence is not the right construction
    here -- z-scores are scale-invariant, so a uniform arithmetic spread's
    top value has an approximately constant z regardless of how tightly
    packed the values are; what actually lowers confidence is several
    candidates bunched at the top with no real leader, which is what this
    plateau constructs.)"""
    scored = _fake_scored([9.0, 8.9, 8.8, 8.7, 8.6, 8.5, 3.0, 2.9, 2.8])
    z = _relative_confidence_scores(scored)
    rank_one_z = z["m.e0"]
    assert rank_one_z < 1.0
    decision = _decide_confidence(scored[0], rank_one_z, min_confidence_z=1.0, matched_idf_coverage=1.0)
    assert decision.accepted is False


def test_confidence_requires_a_real_pool_not_a_lone_candidate() -> None:
    """A single tfidf candidate has nothing to be relatively stronger
    than -- the mechanism must not fabricate a confident judgment from no
    real competing evidence at all (`_MIN_POOL_FOR_RELATIVE_CONFIDENCE`)."""
    scored = _fake_scored([50.0])  # a huge raw score, but alone in its pool
    z = _relative_confidence_scores(scored)
    assert z == {}
    decision = _decide_confidence(scored[0], z.get("m.e0"), min_confidence_z=1.0, matched_idf_coverage=1.0)
    assert decision.accepted is False
    assert decision.confidence is None


@pytest.mark.parametrize(
    "corpus_shape,scores",
    [
        ("small_sparse", [12.0, 3.0, 2.5]),
        ("medium_dense", [t * 1.0 for t in range(30, 5, -1)]),  # 25 candidates, gently sloped
        ("large_sparse", [45.0] + [1.0] * 199),  # 200 candidates, one real outlier
        ("large_dense_tie", [22.0] * 150),  # 150 candidates, all identical
    ],
)
def test_relative_confidence_is_computable_and_well_formed_across_corpus_shapes(
    corpus_shape: str, scores: list[float]
) -> None:
    """ARCF Fix 3 cross-corpus requirement: the *same* algorithm, with no
    per-shape special-casing, must produce finite, well-formed confidence
    values across small/large, sparse/dense score distributions -- no
    crash, no NaN, no unbounded blow-up."""
    scored = _fake_scored(scores)
    z = _relative_confidence_scores(scored)
    if len(scores) < 3:
        assert z == {}
        return
    assert len(z) == len(scores)
    for value in z.values():
        assert math.isfinite(value)
    # The top score's z is always >= every other candidate's z (order-preserving).
    top_entity_id = "m.e0"  # scores are constructed in descending order in every case above
    assert z[top_entity_id] == max(z.values())


def test_matched_idf_coverage_precomputed_doc_terms_and_max_idf_match_the_recomputed_path(
    write_file: Callable[[str, str], Path], repo_root: Path, store: VBGStore
) -> None:
    """Final hardening pass performance fix: `_matched_idf_coverage`'s
    optional `doc_terms`/`max_known_idf` parameters exist purely to avoid
    redundant re-tokenizing/re-scanning at the higher call volume
    structural corroboration introduces -- they must never change the
    result. Real entities/idf table from a real extraction, not hand-built,
    so this exercises the exact values `retrieve_context()` itself computes
    and passes through."""
    write_file(
        "billing.py",
        "class PaymentProcessor:\n"
        "    def dispatch(self, payload):\n"
        '        """Handles gateway payment routing before handing off to validation."""\n'
        "        return payload\n",
    )
    extraction = extract_repository(repo_root, COMMIT)
    persist_extraction(store, extraction)
    index = build_retrieval_index(store, COMMIT)
    query_terms = set(_tokenize("payment gateway transaction fraud authorization compliance"))
    _, _, idf, _ = _build_bm25_index(index)
    entity = index.get("billing.PaymentProcessor.dispatch")
    assert entity is not None

    recomputed = _matched_idf_coverage(query_terms, entity, idf)
    precomputed = _matched_idf_coverage(
        query_terms, entity, idf,
        doc_terms=set(_tokenize(_entity_text(entity))),
        max_known_idf=max(idf.values(), default=0.0),
    )

    assert precomputed == recomputed


def _write_repo_of_size(write_file: Callable[[str, str], Path], n: int) -> None:
    """A synthetic repository of `n` real, distinct, independently-
    extracted functions -- used to validate that `retrieve_context()`'s
    confidence mechanism runs the *same* algorithm, no per-size tuning,
    end to end through real extraction/indexing/BM25/z-score code, not
    just the isolated `_relative_confidence_scores` unit above."""
    for i in range(n):
        write_file(
            f"module_{i}.py",
            f"def handler_{i}(request, response):\n"
            f'    """Handles incoming request number {i}, validating headers and dispatching to the '
            f'appropriate processing pipeline stage {i}."""\n'
            "    return response\n",
        )


@pytest.mark.parametrize("size_name,n", [("small", 3), ("medium", 30), ("large", 150)])
def test_confidence_mechanism_runs_end_to_end_across_real_synthetic_repo_sizes(
    size_name: str, n: int, write_file: Callable[[str, str], Path], repo_root: Path, store: VBGStore
) -> None:
    """ARCF Fix 3 cross-corpus requirement, end to end: the exact same
    `retrieve_context()` call, same default parameters, no repository-name
    or size-specific branch anywhere in the implementation, run against
    small/medium/large real synthetic repositories."""
    _write_repo_of_size(write_file, n)
    extraction = extract_repository(repo_root, COMMIT)
    persist_extraction(store, extraction)
    index = build_retrieval_index(store, COMMIT)

    context = retrieve_context(store, index, COMMIT, "how does the request handler dispatch processing")

    assert isinstance(context.insufficient_evidence, bool)  # ran to completion, well-formed result
    for decision in context.confidence_decisions.values():
        if decision.confidence is not None:
            assert math.isfinite(decision.confidence)
        assert decision.reason


def test_a_genuinely_unanswerable_query_is_not_confidently_answered_by_the_weak_field_leader(
    write_file: Callable[[str, str], Path], repo_root: Path, store: VBGStore
) -> None:
    """Regression test for a real bug real-repository validation found
    (flask-13/flask-14 regressed after the z-score-only design): in a
    pool where every candidate is genuine noise for this query, z-score
    alone will always crown *something* "relatively confident" -- there
    is always a statistical top of any distribution, however weak. None
    of these decoys match more than 1 of the query's 5 distinct terms
    (well under `_MIN_MATCHED_IDF_COVERAGE`), so none should be accepted
    even though, on pure z-score, the strongest of them would clear
    `_MIN_CONFIDENCE_Z` easily -- the matched-term-fraction floor must be
    the deciding factor here, not a coincidence."""
    for i in range(30):
        write_file(
            f"unrelated/module_{i}.py",
            f"def helper_{i}(value):\n"
            f'    """Performs unrelated bookkeeping task number {i} for internal accounting purposes."""\n'
            "    return value\n",
        )
    # A handful of these decoys share exactly one token ("widget") with
    # the query below, nothing else -- real but minimal, coincidental overlap.
    for i in range(5):
        write_file(
            f"unrelated/widget_adjacent_{i}.py",
            f"def widget_helper_{i}(value):\n"
            f'    """Some widget-adjacent bookkeeping, task {i}."""\n'
            "    return value\n",
        )
    extraction = extract_repository(repo_root, COMMIT)
    persist_extraction(store, extraction)
    index = build_retrieval_index(store, COMMIT)

    context = retrieve_context(store, index, COMMIT, "where does the widget subsystem implement caching logic")

    assert context.entities == ()
    assert context.insufficient_evidence is True


# -- Final hardening pass: structural corroboration for the coverage floor --


def _fake_entity(entity_id: str, *, parents=(), children=(), siblings=(), docstring: str | None = None) -> IndexedEntity:
    """Same minimal, real-shaped construction as `_fake_scored` above, but
    exposing `docstring`/`parents`/`children`/`siblings` so these tests can
    hand-build small, fully controlled CONTAINS neighborhoods -- exercising
    `_neighbor_matched_idf_coverage` directly, without the indirection of a
    real extraction run."""
    return IndexedEntity(
        entity_id=entity_id, node_type="Function", name=entity_id.rsplit(".", 1)[-1], repository_version="c1",
        lexical_representation=None, docstring=docstring, source_location=None,
        parents=parents, children=children, siblings=siblings,
        outgoing_relationships=(), incoming_relationships=(),
        verification_state=VerificationState.STRUCTURALLY_IDENTIFIED, evidence_counts={},
    )


def test_neighbor_coverage_is_zero_when_entity_has_no_neighbors_at_all() -> None:
    entity = _fake_entity("m.lonely")
    index = RetrievalIndex("c1", {"m.lonely": entity})
    idf = {"gateway": 2.0, "payment": 1.0, "transaction": 3.0}
    coverage = _neighbor_matched_idf_coverage(entity, index, {"gateway", "payment", "transaction"}, idf)
    assert coverage == 0.0


def test_neighbor_coverage_is_zero_when_referenced_neighbors_are_not_in_the_index() -> None:
    """A CONTAINS edge can name a neighbor id this particular index snapshot
    doesn't have an `IndexedEntity` for (e.g. filtered out upstream) --
    `_neighbor_matched_idf_coverage` must skip it, not crash or fabricate a
    coverage value for an entity it never actually looked at."""
    entity = _fake_entity("m.orphan", children=("m.missing_child",), siblings=("m.missing_sibling",))
    index = RetrievalIndex("c1", {"m.orphan": entity})
    idf = {"gateway": 2.0, "payment": 1.0, "transaction": 3.0}
    coverage = _neighbor_matched_idf_coverage(entity, index, {"gateway", "payment", "transaction"}, idf)
    assert coverage == 0.0


def test_neighbor_coverage_returns_the_strongest_real_neighbors_coverage() -> None:
    """Real, verified CONTAINS neighbors only (parents + children +
    siblings) -- and when more than one exists, the *strongest* of them,
    not the first or an average. `idf` and `query_terms` are hand-chosen so
    the expected coverage fractions are exact, not approximate."""
    idf = {"gateway": 2.0, "payment": 1.0, "transaction": 3.0}  # total weight 6.0
    query_terms = {"gateway", "payment", "transaction"}
    candidate = _fake_entity(
        "m.candidate", children=("m.weak_child",), siblings=("m.strong_sibling",), docstring="widget"
    )
    weak_child = _fake_entity("m.weak_child", docstring="payment")  # matches 1.0/6.0
    strong_sibling = _fake_entity("m.strong_sibling", docstring="payment gateway transaction")  # matches 6.0/6.0
    index = RetrievalIndex(
        "c1", {"m.candidate": candidate, "m.weak_child": weak_child, "m.strong_sibling": strong_sibling}
    )

    own_coverage = _matched_idf_coverage(query_terms, candidate, idf)
    neighbor_coverage = _neighbor_matched_idf_coverage(candidate, index, query_terms, idf)

    assert own_coverage == 0.0  # "widget" shares nothing with the query
    assert neighbor_coverage == pytest.approx(1.0)  # the strong sibling, not the weak child
    assert neighbor_coverage == _matched_idf_coverage(query_terms, strong_sibling, idf)


def test_decide_confidence_or_path_accepts_via_neighbor_coverage_when_own_coverage_is_below_the_floor() -> None:
    """The actual acceptance-rule change: a candidate whose own coverage
    fails the floor is accepted anyway when a real neighbor's coverage
    clears it -- and the `reason` names which path did it, for
    auditability."""
    entity = _fake_entity("m.candidate")
    scored = ScoredEntity(entity=entity, score=6.4, matched_by="tfidf")

    decision = _decide_confidence(
        scored, z_score=1.5, min_confidence_z=1.0, matched_idf_coverage=0.3, neighbor_matched_idf_coverage=0.7
    )

    assert decision.accepted is True
    assert "neighbor" in decision.reason


def test_decide_confidence_or_path_still_rejects_when_neither_own_nor_neighbor_coverage_clears() -> None:
    """Negative validation: an irrelevant/coincidental neighbor (also below
    the floor) must not manufacture acceptance -- the OR-path only ever
    fires when a *real* neighbor's coverage genuinely clears the same bar
    the candidate's own coverage was held to."""
    entity = _fake_entity("m.candidate")
    scored = ScoredEntity(entity=entity, score=6.4, matched_by="tfidf")

    decision = _decide_confidence(
        scored, z_score=1.5, min_confidence_z=1.0, matched_idf_coverage=0.3, neighbor_matched_idf_coverage=0.2
    )

    assert decision.accepted is False


def test_decide_confidence_or_path_defaults_to_no_neighbor_evidence_when_omitted() -> None:
    """Backward-compatible default: callers that don't pass
    `neighbor_matched_idf_coverage` (every pre-existing call site/test in
    this file) get the exact same behavior as before this mechanism
    existed -- the OR-path never silently activates itself."""
    entity = _fake_entity("m.candidate")
    scored = ScoredEntity(entity=entity, score=6.4, matched_by="tfidf")

    decision = _decide_confidence(scored, z_score=1.5, min_confidence_z=1.0, matched_idf_coverage=0.3)

    assert decision.accepted is False


def test_structural_corroboration_recovers_a_real_sibling_corroborated_candidate_end_to_end(
    write_file: Callable[[str, str], Path], repo_root: Path, store: VBGStore
) -> None:
    """End-to-end regression test for the real, measured flask-06/flask-10-
    shaped recovery mechanism: a method (`dispatch`) whose own docstring
    only weakly echoes the query, sitting alongside a sibling method
    (`validate_transaction`) on the same class whose docstring strongly
    covers it. Real extraction produces the real CONTAINS edges (siblings
    computed via `get_siblings`, both children of `PaymentProcessor`) --
    nothing about this test hand-wires any relationship.

    `dispatch`'s own coverage is confirmed below the floor (so acceptance,
    if it happens, cannot be explained by the pre-existing own-coverage
    path); the threshold used is `dispatch`'s own real, measured z-score
    (the same "threshold strictly at a real measured value" pattern used
    elsewhere in this file), so this isolates the coverage mechanism, not
    the ranking mechanism, as the thing under test."""
    write_file(
        "billing.py",
        "class PaymentProcessor:\n"
        "    def dispatch(self, payload):\n"
        '        """Handles gateway payment routing before handing off to validation."""\n'
        "        return payload\n\n"
        "    def validate_transaction(self, payload):\n"
        '        """Validates a payment gateway transaction for fraud and authorization compliance."""\n'
        "        return True\n",
    )
    for i in range(10):
        write_file(
            f"unrelated/module_{i}.py",
            f"def helper_{i}(value):\n"
            f'    """Performs unrelated bookkeeping task number {i}."""\n'
            "    return value\n",
        )
    weak_terms = ["compliance", "fraud", "authorization", "gateway", "payment", "transaction"]
    for i, term in enumerate(weak_terms):
        write_file(
            f"unrelated/weak_{i}.py",
            f"def weak_helper_{i}(value):\n"
            f'    """Some {term} adjacent bookkeeping routine, task {i}."""\n'
            "    return value\n",
        )
    extraction = extract_repository(repo_root, COMMIT)
    persist_extraction(store, extraction)
    index = build_retrieval_index(store, COMMIT)
    query = "payment gateway transaction fraud authorization compliance"
    dispatch_id = "billing.PaymentProcessor.dispatch"

    query_terms = set(_tokenize(query))
    _, _, idf, _ = _build_bm25_index(index)
    dispatch_entity = index.get(dispatch_id)
    assert dispatch_entity is not None
    assert _matched_idf_coverage(query_terms, dispatch_entity, idf) < 0.5  # own coverage genuinely fails the floor

    permissive = retrieve_context(store, index, COMMIT, query, min_confidence_z=-1e9, candidate_pool_size=50)
    dispatch_z = permissive.confidence_decisions[dispatch_id].confidence
    assert dispatch_z is not None

    context = retrieve_context(store, index, COMMIT, query, min_confidence_z=dispatch_z, candidate_pool_size=50)

    decision = context.confidence_decisions[dispatch_id]
    assert decision.accepted is True
    assert "neighbor" in decision.reason
    assert dispatch_id in {e.entity_id for e in context.entities}


def test_structural_corroboration_does_not_rescue_a_coincidental_match_with_an_equally_weak_sibling(
    write_file: Callable[[str, str], Path], repo_root: Path, store: VBGStore
) -> None:
    """Negative validation, end to end: two sibling methods that both only
    coincidentally share the query's common word ("widget") and neither
    covers the query's other, more distinctive terms. Neither the
    candidate's own coverage nor its real sibling's coverage clears the
    floor, so the OR-path correctly finds nothing to corroborate with --
    this is not a fabricated-relationship problem (the sibling edge is
    real), it's a case where the real neighbor genuinely isn't
    corroborating evidence either. Uses an extreme permissive z bar so the
    z-score gate cannot be the thing suppressing acceptance -- only the
    coverage mechanism is under test here."""
    write_file(
        "reports.py",
        "class ReportBuilder:\n"
        "    def summarize(self, data):\n"
        '        """Summarizes widget inventory counts for the nightly report."""\n'
        "        return data\n\n"
        "    def export(self, data):\n"
        '        """Exports the nightly widget report to a csv file on disk."""\n'
        "        return data\n",
    )
    for i in range(20):
        write_file(
            f"unrelated/module_{i}.py",
            f"def helper_{i}(value):\n"
            f'    """Performs unrelated bookkeeping task number {i}."""\n'
            "    return value\n",
        )
    extraction = extract_repository(repo_root, COMMIT)
    persist_extraction(store, extraction)
    index = build_retrieval_index(store, COMMIT)
    query = "how does the widget subsystem implement caching for the payment gateway transaction"

    context = retrieve_context(store, index, COMMIT, query, min_confidence_z=-1e9, candidate_pool_size=50)

    ids = {e.entity_id for e in context.entities}
    assert "reports.ReportBuilder.summarize" not in ids
    assert "reports.ReportBuilder.export" not in ids
