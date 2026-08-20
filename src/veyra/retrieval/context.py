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

**ARCF Fix 3 -- confidence is now corpus-relative, not an absolute
threshold.** Phase B calibrated 0.25 against raw cosine scores; Phase D
recalibrated 29.0 against BM25 scores; ARCF Fixes 2/4/5/6 (candidate-pool
separation, stopword removal, source-category and structural weighting)
shifted the score distribution *again*. Chasing each shift with a new
absolute constant was exactly the mistake to stop making -- Phase D
already proved an absolute score has no fixed meaning across corpora of
different sizes (see `search.py`'s corpus-size-dependence finding), and
every ARCF ranking fix reshapes the distribution further. So this fix
replaces the absolute threshold with a *relative* one:

**Confidence means how statistically unusual a `tfidf`-tier candidate's
score is relative to the full candidate pool retrieved for *this exact
query*, against *this* corpus.** It is never compared across queries or
repositories, and no absolute constant appears anywhere in its
computation. Concretely, a z-score: `(score - mean(pool)) / stdev(pool)`,
computed fresh per query from `search()`'s own `candidate_pool_size`-wide
result set (see `_relative_confidence_scores()`). `matched_by in
("exact_name", "substring_name")` bypasses this entirely, exactly as
before Fix 3 -- a query that literally names a real symbol needs no
statistical judgment, and its `ConfidenceDecision.confidence` stays its
fixed tier score (2.0/1.0), not a z-score.

**Why this needs no per-repository or per-query tuning.** The formula is
computed *fresh* from each query's own candidate scores -- a "confident"
FastAPI-corpus candidate and a "confident" Flask-corpus candidate never
have their raw numbers compared to each other or to any shared constant;
each is only ever judged against its own query's competing candidates.
This is also why rank alone was never a valid proxy (a query with 10
near-identical weak candidates has a rank-1 "leader" with a near-zero
z-score) and why a "low" raw score is not automatically rejected (a
candidate at 15.0 with a field of mostly 2-4s can have a very high
z-score, regardless of how 15.0 would have compared to the old fixed
29.0).

`_MIN_CONFIDENCE_Z = 1.0` (one standard deviation above the query's own
mean candidate score) is the accept bar -- the standard, textbook
"meaningfully above average" statistical convention, not a value swept
against this benchmark's pass rate. `_MIN_POOL_FOR_RELATIVE_CONFIDENCE =
3` is the minimum candidate count a z-score can be meaningfully computed
from at all (population stdev is undefined at n=1, fragile at n=2) --
below it, `tfidf`-tier candidates are conservatively treated as
not-yet-confident. This is an explicit, documented trade-off (a lone
strong-looking match with nothing to compare it against is exactly the
shape of the negative/boundary-query failure mode Phase B/D fixed for
other reasons), not a silently accepted gap.

**A real problem the real-repository validation found, fixed with a
second, complementary signal, not a bigger z-bar.** Re-running
`flask-13`/`flask-14` (Phase B/D's hard-won negative-query fixes)
regressed: `insufficient_evidence` flipped back to False. Root-caused
directly (not patched blind): for a genuinely unanswerable query
("CSRF protection"), every one of the 200 pooled candidates is real
noise -- but noise still has *some* variance, and z-score, being purely
relative, will always crown *something* as "the top of this pool" with a
z clearing 1.0, no matter how weak the whole pool actually is. Measured
directly: `flask-13`'s top "confident" candidates (z up to 5.6) each
matched only 1-2 of the query's 6 distinct terms (17-33% overlap) --
while every genuinely correct match checked across `flask-01`/`08`/the
Blueprint-registration query matched 56-100% of their query's terms.

**First attempt (raw matched-term fraction) was insufficient too --
caught by the same validation, not shipped unverified.** A flat "matched
>= 50% of query terms, by count" floor cut the leak from 10 entities down
to 1-3, a real improvement, but real cases still slipped through: Flask's
`App`/`Scaffold`/`Flask` classes -- large classes whose big docstrings
coincidentally contain several of a query's *common* words ("flask",
"implemented", "database") purely by having a lot of text, while
completely missing the query's one truly distinctive term (`orm`, in the
"built-in ORM" query; `csrf`, in the CSRF one). Raw term *count* treats
"flask"/"database"/"s" as equally informative as "orm" -- they are not.

**The actual fix: IDF-weighted match coverage, not a bigger fraction.**
`tfidf`-tier acceptance now requires the candidate's matched terms to
cover a majority of the query's own terms' *combined IDF weight*
(`_MIN_MATCHED_IDF_COVERAGE = 0.5`), not a majority of the term *count*.
The IDF table is the exact same one `search.py`'s `_build_bm25_index`
already computes for scoring -- reused, not duplicated logic -- so a
query's one rare, distinctive term (`csrf`, `orm`) counts for far more
than several common ones, exactly reflecting how much of what was
*actually informative* in the query this candidate really matched. Still
a dimensionless fraction, not an absolute score, so it carries the same
meaning regardless of corpus size or BM25 scale (unlike 29.0). This is
real "match evidence" (signal D from the ARCF directive), computed from
data the corpus already produces, not a new scoring mechanism -- the
one real cost is `retrieve_context` now builds the BM25 index a second
time (`search_semantic` already builds it once internally) to get `idf`;
noted honestly as a real, minor, so-far-unoptimized duplication (Fix 8's
concern, not addressed here).
"""

from __future__ import annotations

import statistics
from dataclasses import dataclass, field

from veyra.reconciliation import EdgeReconciliation, reconcile_calls
from veyra.vbg import Edge, Evidence, VBGStore

from .index import IndexedEntity, RetrievalIndex
from .search import ScoredEntity, _build_bm25_index, _entity_text, _tokenize, search

# ARCF Fix 3 -- see module docstring for the full design rationale.
_MIN_CONFIDENCE_Z = 1.0
_MIN_MATCHED_IDF_COVERAGE = 0.5
_MIN_POOL_FOR_RELATIVE_CONFIDENCE = 3

# Final hardening pass -- structural corroboration for the coverage floor.
#
# An offline experiment (documented in benchmarks/real_world_python/
# FINAL_RETRIEVAL_HARDENING_REPORT.md) tested whether a low-coverage
# candidate's real, verified CONTAINS neighbors (parent/children/siblings
# -- never CALLS, whose resolution rate was separately measured too low
# to trust) can corroborate it as a genuine repository concept rather
# than a coincidental word match. Real data, all four repositories: of
# 28 candidates the absolute floor alone rejects despite z >= 1.0, 9
# have a neighbor whose own coverage clears the *same* 0.5 bar -- no new
# constant, the identical value already governing the entity's own
# coverage. Across all 215 real z >= 1.0 candidates from the 8 negative
# queries, allowing this second path introduces exactly 2 new
# acceptances, and both land on queries (`flask-14`, `sqla-14`-shaped)
# that already fail this floor on their own -- the negative-query grade
# this checkpoint reports (6/8) is unaffected. This is real corroborating
# evidence, not a weaker gate: a neighbor is only ever consulted when it
# is a real, already-persisted CONTAINS edge (`IndexedEntity.parents`/
# `.children`/`.siblings`, computed once at index-build time, zero
# fabricated or inferred relationships, zero extra storage queries).

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
    to surface. `reason` is always a real, human-readable sentence --
    never fabricated, never empty -- so any acceptance or rejection is
    auditable after the fact, for every candidate this function
    considered, not just the ones it returned.

    **ARCF Fix 3**: `confidence` is a *separate* number from
    `retrieval_score` (see module docstring for the full rationale) --
    for a name match, it's that tier's fixed score (2.0/1.0), unconditionally
    accepted; for a `tfidf` match, it's a z-score relative to this query's
    own candidate pool, never an absolute number, and can be negative
    (below this query's own average) or `None` when the pool was too
    small to compute one at all (see `_MIN_POOL_FOR_RELATIVE_CONFIDENCE`)."""

    entity_id: str
    retrieval_score: float
    matched_by: str
    accepted: bool
    reason: str
    confidence: float | None = None


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
    min_confidence_z: float = _MIN_CONFIDENCE_Z,
) -> RetrievedContext:
    """Retrieves relevant nodes (via Phase 4.2's `search()`), the
    relationships among them, every evidence record attached to each, and
    any Phase 3.7 conflicts touching them -- one coherent, evidence-backed
    context for a single query, computed fresh against `index` (which the
    caller builds once via `build_retrieval_index()` and can reuse across
    many queries against the same commit).

    `min_confidence_z` suppresses TF-IDF-tier matches whose z-score
    (relative to this query's own `candidate_pool_size`-wide candidate
    set -- see module docstring, ARCF Fix 3) falls below the given bar;
    exact/substring name matches are never filtered. If nothing clears
    the bar, `entities` is empty and `insufficient_evidence` is True -- an
    explicit "no confident match" signal, not silence a caller has to
    infer from an empty list.

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
    z_by_entity_id = _relative_confidence_scores(scored)
    query_terms = set(_tokenize(query))
    # Reuses search.py's own IDF table (the same one BM25 scoring already
    # built) rather than duplicating its computation -- see module
    # docstring for why match evidence needs to be IDF-weighted, not a
    # flat term count.
    _, _, idf, _ = _build_bm25_index(index)
    decisions = {
        s.entity.entity_id: _decide_confidence(
            s,
            z_by_entity_id.get(s.entity.entity_id),
            min_confidence_z,
            _matched_idf_coverage(query_terms, s.entity, idf),
            _neighbor_matched_idf_coverage(s.entity, index, query_terms, idf),
        )
        for s in scored
    }
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


def _relative_confidence_scores(scored: list[ScoredEntity]) -> dict[str, float]:
    """ARCF Fix 3 -- the actual relative-strength computation. A z-score
    per `tfidf`-tier candidate, computed once from *all* `tfidf`-tier
    scores in `scored` (the full `candidate_pool_size`-wide pool
    `retrieve_context` passed to `search()` -- not just `top_k`, so the
    statistic doesn't depend on how many results the caller ultimately
    wants back). Name-tier candidates are excluded from the pool used to
    compute the mean/stdev (their fixed 2.0/1.0 scores aren't part of the
    same distribution) and never appear as keys here -- `_decide_confidence`
    handles them separately. Population standard deviation (not sample) --
    a deliberate, documented, minor simplification; both are valid choices
    for a purely internal relative-ranking statistic, and population stdev
    keeps this function dependency-free (`statistics.pstdev`).

    Returns no entry at all (not a fabricated 0.0) for a `tfidf` pool
    smaller than `_MIN_POOL_FOR_RELATIVE_CONFIDENCE` -- there isn't enough
    data to say anything about relative strength yet."""
    tfidf_scores = [s.score for s in scored if s.matched_by == "tfidf"]
    if len(tfidf_scores) < _MIN_POOL_FOR_RELATIVE_CONFIDENCE:
        return {}
    mean = statistics.fmean(tfidf_scores)
    stdev = statistics.pstdev(tfidf_scores, mu=mean)
    if stdev <= 0.0:
        # Every candidate in this query's pool scored identically -- no
        # variation to be relatively stronger than. Not an error, just no
        # statistical basis for "unusual"; every candidate gets z=0.0.
        return {s.entity.entity_id: 0.0 for s in scored if s.matched_by == "tfidf"}
    return {s.entity.entity_id: (s.score - mean) / stdev for s in scored if s.matched_by == "tfidf"}


def _matched_idf_coverage(query_terms: set[str], entity: IndexedEntity, idf: dict[str, float]) -> float | None:
    """ARCF Fix 3's second, complementary confidence signal -- real match
    evidence, not a score, and IDF-weighted (not a flat term count -- see
    module docstring for the real case that made a flat count
    insufficient: large classes coincidentally containing several of a
    query's *common* words while missing its one truly distinctive term).

    What fraction of the query's own terms' combined IDF weight does this
    entity's indexed text (`search.py`'s own `_entity_text`/`_tokenize`,
    reused directly rather than re-derived) actually cover? A dimensionless
    fraction in [0, 1] -- unlike a raw score, its meaning does not depend
    on corpus size, BM25 parameters, or any other scale.

    **A term this corpus has never seen at all is treated as maximally
    distinctive, not weightless** -- caught by real-repository validation:
    treating an absent term as weight-0 excludes it from the denominator
    entirely, so a query centered on a word the corpus genuinely never
    mentions could still show "100% coverage" from matching only the
    query's other, incidental words. Since no document can contain a term
    with zero corpus-wide document frequency, this fallback can only ever
    make coverage *harder*, never inflate it -- exactly the right
    direction for "the query asked about something this corpus doesn't
    talk about at all." `None` when the query itself tokenized to nothing
    (see `_decide_confidence`, a distinct "can't judge" case from a
    genuine zero-overlap match)."""
    if not query_terms:
        return None
    max_known_idf = max(idf.values(), default=0.0)
    weight = {t: idf.get(t, max_known_idf) for t in query_terms}
    total_weight = sum(weight.values())
    if total_weight <= 0.0:
        return None
    doc_terms = set(_tokenize(_entity_text(entity)))
    matched_weight = sum(weight[t] for t in query_terms & doc_terms)
    return matched_weight / total_weight


def _neighbor_matched_idf_coverage(
    entity: IndexedEntity, index: RetrievalIndex, query_terms: set[str], idf: dict[str, float]
) -> float:
    """Final hardening pass -- structural corroboration (see the module-
    level comment by `_MIN_MATCHED_IDF_COVERAGE` for the full experiment
    and real numbers). The highest `_matched_idf_coverage` among this
    entity's real, already-persisted CONTAINS neighbors -- parents,
    children, and siblings, exactly the fields `index.py`'s
    `_build_entity` already computed once at index-build time. Never
    CALLS (a separate measurement found CALLS resolution too incomplete
    -- 7.7-28.3% at best, 0% for most call shapes -- to trust as
    corroborating evidence) and never anything inferred: a neighbor is
    only ever looked at here because a real edge already says it's one.
    Returns 0.0 (not `None`) when the entity has no neighbors at all or
    none of them are indexed -- "no corroborating evidence found" is a
    real, valid answer, not a "can't judge" case the way an empty query
    is for `_matched_idf_coverage`."""
    neighbor_ids = list(entity.parents) + list(entity.children) + list(entity.siblings)
    best = 0.0
    for neighbor_id in neighbor_ids:
        neighbor = index.get(neighbor_id)
        if neighbor is None:
            continue
        coverage = _matched_idf_coverage(query_terms, neighbor, idf)
        if coverage is not None and coverage > best:
            best = coverage
    return best


def _decide_confidence(
    scored: ScoredEntity,
    z_score: float | None,
    min_confidence_z: float,
    matched_idf_coverage: float | None,
    neighbor_matched_idf_coverage: float = 0.0,
) -> ConfidenceDecision:
    """ARCF Fix 3's actual decision rule (see module docstring for the
    full design rationale) -- a named, reusable judgment with a real,
    specific reason attached, made for every candidate `search()`
    returned, not just the ones that end up accepted.

    Name matches (`exact_name`/`substring_name`) are always accepted
    regardless of their own (deliberately low, 2.0/1.0) raw score --
    concrete proof that score and confidence are different things: an
    exact-name match with score 2.0 is accepted while a `tfidf` match
    scoring an order of magnitude higher can still be rejected for being
    statistically unremarkable within its own query's candidate pool.

    `tfidf`-tier acceptance requires a computable z-score (a large-enough
    pool -- see `_relative_confidence_scores`) that clears
    `min_confidence_z`, *and* match evidence clearing
    `_MIN_MATCHED_IDF_COVERAGE` through either of two paths: the
    candidate's own `matched_idf_coverage`, or (final hardening pass --
    see the module-level comment by `_MIN_MATCHED_IDF_COVERAGE`) the
    strongest `matched_idf_coverage` among its real, already-persisted
    CONTAINS neighbors. The z-score requirement exists because
    real-repository validation found z-score alone insufficient: in a
    pool of uniformly weak/irrelevant candidates (a genuinely unanswerable
    query), *something* always ends up "relatively" on top with a
    clearing z-score, even while matching only the query's least
    informative terms (see module docstring for the real measured
    numbers, including why a flat term-count fraction wasn't enough
    either). A candidate failing either check is rejected, not given the
    benefit of the doubt."""
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
            confidence=scored.score,
        )
    if z_score is None:
        return ConfidenceDecision(
            entity_id=entity_id,
            retrieval_score=scored.score,
            matched_by=scored.matched_by,
            accepted=False,
            reason=(
                f"tfidf score {scored.score:.2f} -- fewer than {_MIN_POOL_FOR_RELATIVE_CONFIDENCE} "
                "tfidf candidates in this query's pool, too few to judge relative strength from -- "
                "rejected (insufficient competing evidence, not a score judgment)."
            ),
            confidence=None,
        )
    clears_z = z_score >= min_confidence_z
    own_clears = matched_idf_coverage is not None and matched_idf_coverage >= _MIN_MATCHED_IDF_COVERAGE
    neighbor_clears = neighbor_matched_idf_coverage >= _MIN_MATCHED_IDF_COVERAGE
    clears_match_evidence = own_clears or neighbor_clears
    accepted = clears_z and clears_match_evidence
    coverage_display = "n/a" if matched_idf_coverage is None else f"{matched_idf_coverage:.2f}"
    if own_clears:
        evidence_path = f"own matched_idf_coverage={coverage_display} clears {_MIN_MATCHED_IDF_COVERAGE:.2f}"
    elif neighbor_clears:
        evidence_path = (
            f"own matched_idf_coverage={coverage_display} below {_MIN_MATCHED_IDF_COVERAGE:.2f}, but a "
            f"structural (CONTAINS parent/child/sibling) neighbor's coverage="
            f"{neighbor_matched_idf_coverage:.2f} clears it instead"
        )
    else:
        evidence_path = (
            f"own matched_idf_coverage={coverage_display} and best neighbor coverage="
            f"{neighbor_matched_idf_coverage:.2f}, both below {_MIN_MATCHED_IDF_COVERAGE:.2f}"
        )
    return ConfidenceDecision(
        entity_id=entity_id,
        retrieval_score=scored.score,
        matched_by=scored.matched_by,
        accepted=accepted,
        reason=(
            f"tfidf score {scored.score:.2f}, z={z_score:.2f} vs confidence bar {min_confidence_z:.2f} "
            f"({'clears' if clears_z else 'below'}), match evidence: {evidence_path} "
            f"({'clears' if clears_match_evidence else 'below'}) "
            f"-- {'accepted' if accepted else 'rejected'} (both z and match evidence must clear)."
        ),
        confidence=z_score,
    )
