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
from .search import search

_PROVISIONAL_MIN_TFIDF_SCORE = 29.0


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


def retrieve_context(
    store: VBGStore,
    index: RetrievalIndex,
    repository_version: str,
    query: str,
    top_k: int = 10,
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
    signal, not silence a caller has to infer from an empty list."""
    scored = search(index, query, top_k=top_k)
    accepted = [s for s in scored if s.matched_by != "tfidf" or s.score >= min_tfidf_score]
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
    )
