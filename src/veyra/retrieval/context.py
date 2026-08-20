"""
PLAN.md Milestone 4, Phase 4.3 -- Query-Time Evidence Retrieval.

"Query -> relevant nodes -> relevant relationships -> relevant evidence ->
verification states -> context. The LLM explains that evidence; it does
not discover it." This module is that pipeline, built directly on Phase
4.1's index, Phase 4.2's search, and Phase 3.7's reconciliation --
primarily *retrieving* existing verified knowledge, not generating new
Q&A datasets (see PLAN.md's own three-milestone "questions" distinction:
M2 structural, M3 behavioral, M4 evidence retrieval).

**Retrieval-quality remediation, Phase B -- confidence propagation.**
The real-world benchmark (benchmarks/real_world_python/REPORT.md) found
that `ScoredEntity.score` was computed by `search()` and then silently
discarded here -- every caller got the top-k results with no way to tell
a solid match from a desperate one, which is exactly why all 8 of the
benchmark's negative/boundary queries were mishandled (retrieval always
returned *something*). `scores`/`matched_by` now survive into
`RetrievedContext`, and `min_tfidf_score` lets the caller (or this
function's own default) suppress TF-IDF-tier results too weak to trust.

Exact and substring name matches (`matched_by in ("exact_name",
"substring_name")`) are never filtered by this threshold -- a query that
literally names a real symbol should always surface it; the ambiguity
this benchmark exposed is specific to the TF-IDF tier.

**Threshold recalibrated after Phase D, still explicitly provisional.**
Phase B's original calibration (against raw cosine-similarity TF-IDF
scores, bounded 0-1) found relevant and irrelevant scores overlapped
almost completely -- no threshold could separate them, because the score
itself was biased (`search.py`'s Phase D docstring has the full mechanism
and the real numbers that proved it). Phase D replaced that scoring
function with BM25 plus per-entity-type length normalization, which
produces unbounded, much larger raw scores on a different scale entirely
-- so this threshold had to be recalibrated from scratch, not just
reused. Re-running `calibrate_confidence_threshold.py` against the *new*
scores (still real Flask+FastAPI ground-truth data) showed genuine
separation improvement: relevant/irrelevant medians moved from
nearly-identical (0.297 vs 0.267) to clearly distinct (35.1 vs 29.9).
`_PROVISIONAL_MIN_TFIDF_SCORE` (29.0) is chosen for a specific, describable
relevance-separation property, not to hit any target pass rate (the
remediation plan explicitly prohibits threshold-tuning-to-benchmark-score):
it's the point, just above the highest score any negative-query calibration
case reached (28.59), where none of that calibration set's known false
positives survive, while 67% of true-positive recall is retained --
compared to only 45% recall at the equivalent zero-leak point under the
pre-Phase-D score. Still marked provisional: further ranking refinements
(source-category weighting, Phase E; stopword filtering, Phase C) will
change the score distribution again and should trigger another
recalibration, the same way Phase D did.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from veyra.reconciliation import EdgeReconciliation, reconcile_calls
from veyra.vbg import Edge, Evidence, VBGStore

from .index import IndexedEntity, RetrievalIndex
from .search import ScoredEntity, search

_PROVISIONAL_MIN_TFIDF_SCORE = 29.0

# ARCF Fix 1 -- candidate pool separate from final top_k. `search_semantic()`
# already fully scores and sorts every entity in the index before any
# truncation (an O(N) pass regardless of `top_k`), so widening how many of
# those already-computed candidates this function *considers* for confidence
# filtering costs nothing extra in scoring -- only in the downstream
# evidence/edge lookups this function does per *accepted* entity, which stays
# bounded by the confidence filter itself, not by the pool size. 20x the
# default top_k (200) is chosen as a generous, fixed multiple with no
# query-specific tuning: wide enough that an entity BM25's flatter score
# distribution pushed several ranks past a plain top_k=10 window can still
# reach the confidence filter (see PHASE_D_RESULTS.md's `fastapi-01`/
# `fastapi-03`/`flask-08` mechanism), while still bounded well below any real
# corpus size (Flask ~2,600 entities, FastAPI ~13,900) so this function's
# per-entity evidence/edge queries don't scale toward "the whole repository."
_DEFAULT_CANDIDATE_POOL_SIZE = 200


@dataclass(frozen=True)
class ConfidenceDecision:
    """ARCF Fix 2 -- retrieval score and the accept/reject decision made
    explicit as two separate things, not one number doing both jobs.
    `retrieval_score`/`matched_by` are exactly what ranked this candidate
    (unchanged by this decision); `accepted`/`reason` are a *separate*,
    deterministic judgment about whether that ranking earns enough trust
    to surface -- always true for a name match regardless of its (lower)
    raw score, score-threshold-driven for a lexical match. `reason` is
    always a real, human-readable sentence -- never fabricated, never
    empty -- so any acceptance or rejection is auditable after the fact,
    for every candidate this function considered, not just the ones it
    returned."""

    entity_id: str
    retrieval_score: float
    matched_by: str
    accepted: bool
    reason: str


@dataclass(frozen=True)
class RetrievedContext:
    query: str
    repository_version: str
    entities: tuple[IndexedEntity, ...]
    evidence_by_entity: dict[str, tuple[Evidence, ...]]
    relationships: tuple[Edge, ...]
    conflicts: tuple[EdgeReconciliation, ...]
    scores: dict[str, float] = field(default_factory=dict)
    matched_by: dict[str, str] = field(default_factory=dict)
    insufficient_evidence: bool = False
    confidence_decisions: dict[str, ConfidenceDecision] = field(default_factory=dict)


def retrieve_context(
    store: VBGStore,
    index: RetrievalIndex,
    repository_version: str,
    query: str,
    top_k: int = 10,
    candidate_pool_size: int = _DEFAULT_CANDIDATE_POOL_SIZE,
    min_tfidf_score: float = _PROVISIONAL_MIN_TFIDF_SCORE,
) -> RetrievedContext:
    """Retrieves relevant nodes (via Phase 4.2's `search()`), the
    relationships among them, every evidence record attached to each, and
    any Phase 3.7 conflicts touching them -- one coherent, evidence-backed
    context for a single query, computed fresh against `index` (which the
    caller builds once via `build_retrieval_index()` and can reuse across
    many queries against the same commit).

    `min_tfidf_score` suppresses TF-IDF-tier matches below the given
    confidence (see module docstring for how this default was calibrated
    and its known limits); exact/substring name matches are never
    filtered. If nothing clears the bar, `entities` is empty and
    `insufficient_evidence` is True -- an explicit "no confident match"
    signal, not silence a caller has to infer from an empty list.

    **ARCF Fix 1**: `search()` is called with `candidate_pool_size`
    entities under consideration (wider than `top_k`), and confidence
    filtering is applied across that whole wider pool -- *then* the
    accepted results are cut to `top_k`. This is the fix for the
    mechanism where a correctly-scored, confidence-clearing entity never
    reached this filter at all because a plain `top_k`-sized candidate
    window had already excluded it before confidence was ever consulted.

    **ARCF Fix 2**: every candidate `search()` returned gets its own
    `ConfidenceDecision` (`RetrievedContext.confidence_decisions`,
    every considered candidate, not just accepted ones) -- ranking
    (`scored`'s order, driven purely by retrieval score) and acceptance
    (driven by `_decide_confidence`) are two separate passes over the
    same list, not one score doing both jobs."""
    scored = search(index, query, top_k=top_k, candidate_pool_size=candidate_pool_size)
    decisions = {s.entity.entity_id: _decide_confidence(s, min_tfidf_score) for s in scored}
    accepted = [s for s in scored if decisions[s.entity.entity_id].accepted]
    accepted = accepted[:top_k]
    entities = tuple(s.entity for s in accepted)
    entity_ids = {e.entity_id for e in entities}
    scores = {s.entity.entity_id: s.score for s in accepted}
    matched_by = {s.entity.entity_id: s.matched_by for s in accepted}
    insufficient_evidence = not entities

    evidence_by_entity = {
        entity.entity_id: tuple(store.get_evidence_for_subject(entity.entity_id, repository_version))
        for entity in entities
    }

    # Every outgoing relationship from a retrieved entity, including ones
    # pointing at an entity that wasn't itself independently retrieved --
    # Phase 4.7's grounding contract needs those to name real "unknowns"
    # (referenced but not verified in this context) rather than silently
    # dropping them.
    relationships: list[Edge] = []
    for entity in entities:
        relationships.extend(store.get_outgoing_edges(entity.entity_id, repository_version))

    all_reconciliations = reconcile_calls(store, repository_version)
    conflicts = tuple(
        r for r in all_reconciliations
        if r.is_conflict and (r.source_id in entity_ids or r.target_id in entity_ids)
    )

    return RetrievedContext(
        query=query,
        repository_version=repository_version,
        entities=entities,
        evidence_by_entity=evidence_by_entity,
        relationships=tuple(relationships),
        conflicts=conflicts,
        scores=scores,
        matched_by=matched_by,
        insufficient_evidence=insufficient_evidence,
        confidence_decisions=decisions,
    )


def _decide_confidence(scored: ScoredEntity, min_tfidf_score: float) -> ConfidenceDecision:
    """ARCF Fix 2's actual decision rule -- unchanged in *behavior* from
    what `retrieve_context` did inline before (`accepted` is identical to
    before this fix), but now a named, reusable judgment with a real,
    specific reason attached, made for every candidate `search()`
    returned, not just the ones that end up accepted.

    Name matches (`exact_name`/`substring_name`) are always accepted
    regardless of their own (deliberately low, 2.0/1.0) raw score --
    concrete proof that score and confidence are different things: an
    exact-name match with score 2.0 is accepted while a `tfidf` match
    scoring an order of magnitude higher can still be rejected for being
    below `min_tfidf_score`. `tfidf`-tier acceptance is exactly the
    existing score-threshold rule, just named and reasoned about
    explicitly."""
    entity_id = scored.entity.entity_id
    if scored.matched_by != "tfidf":
        return ConfidenceDecision(
            entity_id=entity_id,
            retrieval_score=scored.score,
            matched_by=scored.matched_by,
            accepted=True,
            reason=(
                f"{scored.matched_by}: the query names this entity directly (raw ranking score "
                f"{scored.score:.2f}) -- name matches are always accepted independent of score."
            ),
        )
    accepted = scored.score >= min_tfidf_score
    return ConfidenceDecision(
        entity_id=entity_id,
        retrieval_score=scored.score,
        matched_by=scored.matched_by,
        accepted=accepted,
        reason=(
            f"tfidf score {scored.score:.2f} "
            f"{'>=' if accepted else '<'} confidence threshold {min_tfidf_score:.2f} "
            f"-- {'accepted' if accepted else 'rejected'}."
        ),
    )
