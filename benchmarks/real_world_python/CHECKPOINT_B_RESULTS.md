# Checkpoint B — Call Resolution, Storage Performance, Full 4-Repository Validation

Covers the retrieval remediation work after confidence recalibration: call-resolution
measurement, storage performance investigation, and a full re-run of the established
56-query (48 answerable + 8 negative) benchmark across Flask, FastAPI, SQLAlchemy, and
Django against the exact same ground truth and acceptance criteria used from the start.

## A. Call-resolution measurement

Methodology: every call site across all four repositories was classified by AST shape
(`bare_name`, `self_cls_attr`, `other_obj_attr`, `module_or_chained_attr`, `other`), then
cross-referenced against the extractor's real resolution outcome by instrumenting
`_FileExtractor._resolve_call_target` during a full, unmodified `extract_repository()` run
per repo (not sampled — full extraction is now fast enough, see Section B). Confirmed
directly from the resolver's own source: only `bare_name` and `self`/`cls`-attribute calls
can *ever* resolve — every other shape returns `None` unconditionally, which the measured
0.0% rates below confirm empirically, not just by code inspection.

| Repository | Call Shape | Total | Resolved | Unresolved | Resolution % |
|---|---|---:|---:|---:|---:|
| Flask | bare_name | 1,101 | 184 | 917 | 16.7% |
| Flask | self_cls_attr | 173 | 133 | 40 | 76.9% |
| Flask | other_obj_attr | 2,209 | 0 | 2,209 | 0.0% |
| Flask | module_or_chained_attr | 584 | 0 | 584 | 0.0% |
| Flask | other | 55 | 0 | 55 | 0.0% |
| FastAPI | bare_name | 4,592 | 1,280† | 3,312 | 27.9% |
| FastAPI | self_cls_attr | 103 | 69 | 34 | 67.0% |
| FastAPI | other_obj_attr | 6,412 | 0 | 6,412 | 0.0% |
| FastAPI | module_or_chained_attr | 700 | 0 | 700 | 0.0% |
| FastAPI | other | 13 | 0 | 13 | 0.0% |
| SQLAlchemy | bare_name | 90,479 | 14,589 | 75,890 | 16.1% |
| SQLAlchemy | self_cls_attr | 14,644 | 6,087 | 8,557 | 41.6% |
| SQLAlchemy | other_obj_attr | 44,284 | 0 | 44,284 | 0.0% |
| SQLAlchemy | module_or_chained_attr | 30,522 | 0 | 30,522 | 0.0% |
| SQLAlchemy | other | 275 | 0 | 275 | 0.0% |
| Django | bare_name | 48,475 | 13,707† | 34,768 | 28.3% |
| Django | self_cls_attr | 51,181 | 6,953 | 44,228 | 13.6% |
| Django | other_obj_attr | 34,701 | 0 | 34,701 | 0.0% |
| Django | module_or_chained_attr | 37,722 | 0 | 37,722 | 0.0% |
| Django | other | 557 | 0 | 557 | 0.0% |

† `bare_name` resolved count includes the cross-module import-alias pass
(`extract_repository`'s second pass): +0 for Flask, +358 for FastAPI, +0 for SQLAlchemy,
+8,051 for Django. `self_cls_attr` never receives a cross-module retry (confirmed in
source — only bare-name references are queued for it), so its count is single-file-pass
only. The wide swing (0 extra for Flask/SQLAlchemy, thousands for FastAPI/Django) reflects
real differences in import style across these codebases, not a measurement artifact —
verified by requiring first-pass-resolved-by-shape sums to reconcile exactly against each
repo's independently-known final resolved-call total (they did, to the call, for all 4
repos).

**Unresolved-call relevance to retrieval.** All CONTAINS edges (parent/child/sibling —
what Fix 6's structural ranking signal actually uses) are structural, derived directly
from the AST, and unaffected by call resolution at all — confirmed ~97-99% populated
across all 4 repos in the original extraction audit. No part of the current retrieval
pipeline (BM25 scoring, source-category weighting, structural weighting, or the Fix 3
confidence mechanism) depends on CALLS edges. `reconcile_calls()` (static/runtime conflict
detection, a separate M3 concern) is the only consumer of CALLS edges in the codebase.

**Classification: MEASURABLE LIMITATION — DOES NOT BLOCK CURRENT RETRIEVAL.** CALLS
resolution genuinely is low (11.7-28.3% even at its best, `other_obj_attr`/
`module_or_chained_attr`/`other` at a flat 0%) — but the current retrieval architecture
was already built around that fact (Fix 6's own docstring cites the same finding as the
reason it uses CONTAINS, not CALLS, as its structural signal). No call-resolution change
was made in this pass; the extractor's own documented scope (self/cls-attribute and
bare-name calls only, no `obj.method()`/`module.func()`/chained-call inference) already
states this is a deliberate limitation, not an oversight, and nothing measured here
changes that assessment. A future call-graph-aware ranking signal would need this fixed
first, but nothing built so far depends on it.

## B. Storage/extraction performance

**Reproduced the baseline first, with the current code, before changing anything.**
`build_retrieval_index()` against FastAPI's real persisted store: 111.7s, 96,105
`sqlite3.connect()` calls (matching the original ARCF-era measurement exactly).

**Root cause 1 (found while investigating call resolution, not storage — but far more
severe): `ast.get_source_segment()` re-splits the entire file's source into lines on
*every single call*.** Called once per node, this is O(node_count × file_size) per file.
Measured directly: 25-45 real seconds to extract a single ~8,000-line SQLAlchemy file;
1,323s (22 minutes) to extract all of SQLAlchemy in memory alone — no SQLite involved at
all, disproving the assumption that connection overhead was the dominant cost for large
repos. Fixed by splitting each file's source exactly once
(`_FileExtractor._source_lines`) and reusing it for every node, verified byte-identical
against the stdlib function first. SQLAlchemy: 1,323.36s → 14.41s (92x). Django: previously
the persisted run took 3h1m; in-memory extraction alone now takes 15.33s. Node/edge/
unresolved-call counts identical before and after.

**Root cause 2 (the originally-suspected one): one SQLite connection per method call, not
per instance.** Inspected the actual lifecycle before changing anything: confirmed no
threading, multiprocessing, asyncio, or subprocess anywhere in `src/veyra` ever touches
`VBGStore` — every real usage is synchronous, single-threaded, single-process — which is
what makes one lazily-created connection per `VBGStore` instance, reused for its lifetime,
safe (each instance still gets its own; `check_same_thread=True` kept as the structural
enforcement of that invariant). Every `with closing(self._connect()) as conn:` became
`with self._connect() as conn:` — `sqlite3.Connection`'s own context-manager protocol
commits/rolls back without closing, exactly matching "still usable next call".

**Root cause 3 (found measuring root cause 2's effect): a missing index.**
`get_incoming_edges()` (the actual query behind `get_parents()`/`get_siblings()`, called
once per entity while building a retrieval index) filters by `target_id`, but the only
edges index led with `source_id` — confirmed via `EXPLAIN QUERY PLAN` a full `SCAN edges
USING COVERING INDEX` on every call. Added `idx_edges_target_version`, confirmed via the
same `EXPLAIN QUERY PLAN` check that both underlying scans became `SEARCH`.

**Root cause 4 (found while running this checkpoint): `_build_bm25_index(index)` was
being called twice per query** — once inside `search_semantic()`, once inside Fix 3's
`retrieve_context()` for the IDF-coverage lookup — despite depending only on the index,
never the query. Cached on the `RetrievalIndex` instance itself, computed once, reused by
every caller.

| Metric | Before | After | Delta |
|---|---|---|---|
| SQLite connections (FastAPI index build) | 96,105 | 0 (post-`__init__`) | -100% |
| FastAPI `build_retrieval_index()` | 111.7s | 5.89s | 18.9x |
| SQLAlchemy in-memory extraction | 1,323.36s | 14.41s | 91.8x |
| Django in-memory extraction | not measured (persisted run took 3h1m) | 15.33s | — |
| Full 4-repo, 56-query benchmark (build+query, this checkpoint) | not previously run end-to-end at this scale | ~267s total | — |

**Correctness validation:** node/edge/unresolved-call counts identical before and after
both fixes on every repo checked. Regression protection added, testing mechanism not
timing: source-split-call-count stays at exactly 1 per file regardless of node count;
connection identity is reused across calls and still functional; each `VBGStore` instance
gets its own connection; `close()`/reopen works; the edge query plan uses the new index;
the BM25 cache returns the identical cached object on a second call.

## C. Retrieval results (kept separate, per instruction 15)

**Candidate/top-k presence** was not separately re-measured at Checkpoint B (Checkpoint A
already established broad ranking improvement with the pre-Fix-3 mechanism); the numbers
below are **confidence-acceptance and final-benchmark-correctness**, kept distinct from
each other throughout.

## D. Full benchmark — before/after vs. Phase D baseline

**Correction, disclosed rather than silently fixed:** the first pass of this grading only
displayed/reviewed the first 8 of up to 10 accepted entities per query, missing real hits
at position 9-10 for two queries — `django-01` (`QuerySet` at position 9) and `sqla-08`
(`Session.commit` at position 10). Caught during the next phase's investigation work by
checking full entity lists directly, verified against real source locations, and corrected
before anything further was built on top of the wrong numbers. The table below is the
corrected count.

| Repository | Fully correct | Partial | Incorrect | Negative correct |
|---|---:|---:|---:|---:|
| Flask | 5/12 | 2/12 | 5/12 | 1/2 |
| FastAPI | 2/12 | 1/12 | 9/12 | 2/2 |
| SQLAlchemy | 2/12 | 3/12 | 7/12 | 1/2 |
| Django | 4/12 | 2/12 | 6/12 | 2/2 |
| **TOTAL** | **13/48 (27.1%)** | **8/48** | **27/48** | **6/8 (75%)** |

| | Phase D baseline | Checkpoint B (corrected) | Acceptance gate |
|---|---:|---:|---:|
| Fully correct | 7/48 (14.6%) | **13/48 (27.1%)** | 39/48 (81.25%) |
| Negative-query correct | 0/8 (0%) | **6/8 (75%)** | — |

**Gate: NOT MET.** 13/48 is real, measured progress (+6 over baseline, entirely from
genuine ranking/confidence mechanism changes, zero benchmark-specific tuning), but is not
close to 39/48. Not reporting readiness based on the directional improvement alone.

## E. Regression analysis (every meaningful regression, mechanism named)

| Query | Baseline | Now | Mechanism |
|---|---|---|---|
| `flask-06` | PARTIAL (`dispatch_request` present) | FALSE | None of the 5 needed methods clear `matched_idf_coverage>=0.5` for this long, generic-worded query — the user-flagged coverage-floor trade-off, confirmed real. |
| `flask-11` | TRUE (`FlaskClient` rank1) | FALSE | `FlaskClient` dropped out of the accepted set entirely — same coverage-floor mechanism, confirmed real. |
| `flask-14` (negative) | correctly handled | leaks 1 entity | A single weak `App` match clears both the z-score and coverage bars for a genuinely unanswerable query — the residual "weak field, not uniformly weak" risk the z-score design's own docstring already flags as an open limitation. |
| `sqla-02` | PARTIAL (`Engine.execution_options` rank6) | FALSE | Complete miss now — target no longer in the accepted set at all; not further isolated this checkpoint (see below). |
| `django-04` / `django-09` | TRUE (`authenticate()` hit directly) | FALSE (same entity for both queries) | **Root-caused after this checkpoint was first written**, during a follow-up investigation pass: `authenticate()` reaches the candidate pool with a strong z-score (2.48, well above the 1.0 bar) but is rejected by `matched_idf_coverage=0.40 < 0.5` — the same coverage-floor mechanism as `flask-06`/`flask-11`, now confirmed with real numbers rather than left unresolved. |

**Improvements, same rigor (not just listed as a win):** `flask-05`/`flask-08`/`fastapi-01`/
`fastapi-03` all recovered from FALSE to TRUE — in every case, the target's raw score was
already competitive (per Checkpoint A), and Fix 3's query-relative z-score (rather than an
absolute threshold) is what let it clear confidence. `sqla-07`/`sqla-12`/`django-10` newly
retrieve their exact target symbol for the first time in this benchmark's history
(`_LazyLoader`, `Mapper`, `MigrationExecutor`) — source-category and structural weighting
narrowing the field, not a lucky BM25 shift alone (each of these entities has real
CONTAINS-derived structural weight above 1.0). No query-specific rule was added for any of
these; the same unmodified mechanism produced all of them.

## F. Fix 3 (z-score + matched_idf_coverage) analysis across all four repositories

The dominant, cross-repo pattern in the FALSE results is **not** confidence rejection —
it's that the correct entity never enters the ranked candidate set at all. Concretely:
`sqla-01`, `sqla-03`, `sqla-04`, `sqla-09`, `sqla-10`, `django-02`, `django-06`,
`fastapi-07`, `fastapi-09` are all **complete misses** (target entity absent even from the
unfiltered top-10), not cases where a correct-but-unconfident candidate was rejected.
`fastapi-02`/`fastapi-05`/`fastapi-06`/`fastapi-10`/`sqla-01`/`sqla-03` show a distinct,
recurring shape: a **file-level hit that is the wrong entity** (`APIRouter` retrieved
instead of `APIRoute`; `MetaData` instead of `Table`; `ORMExecuteState` instead of
`Session`) — coincidental co-location in the same file, not confidence miscalibration.
`django-01` (corrected above) shows a third, related shape worth flagging on its own: the
target (`QuerySet`) *is* retrieved and accepted, but only barely (rank 9 of 10, z=2.11) —
directly measured as a real BM25 length-normalization effect (`QuerySet`'s indexed text is
7,668 tokens, ~45x the corpus's own average `Class` length, even after Fix D's per-node-
type normalization), pulling a correct, central entity down near the bottom of an
otherwise-passing result rather than out of it entirely. This is the concrete evidence a follow-up
investigation into candidate-generation/lexical-ranking failure should build on.

Applying the directive's own Case A-E framework to this evidence: this is **Case E — the
retrieval architecture (BM25 + lexical matching, however weighted) has a real ceiling on
these two larger, denser codebases**, not primarily Case A (threshold wrong) or Case B
(coverage used for the wrong purpose). SQLAlchemy and Django have far more classes with
generic, overlapping names and vocabulary (`Session`/`ORMExecuteState`/`SessionTransaction`
all plausible lexical matches for "session"; dozens of `*Middleware` classes for
"middleware") than Flask/FastAPI — no amount of confidence recalibration fixes a candidate
that was never ranked in the first place. Fix 3 itself, judged on what it can actually
control (does a *present* correct candidate get accepted; does a genuinely weak field get
correctly rejected), continues to behave as designed for the negative-query improvement
(0/8 → 6/8, real and directly attributable to it) — but **update, found in the follow-up
investigation**: the diagnostic table does show real cases of "high z, low coverage,
correct entity wrongly rejected" among entities that *did* make the ranked list.
`django-04`/`django-09`'s `authenticate()` regression is exactly this: z=2.48 (well above
the 1.0 bar, genuinely the statistically strongest candidate for its query) rejected only
because `matched_idf_coverage=0.40 < 0.5`. This is the same mechanism as `flask-06`/
`flask-11`, now confirmed with real numbers in a second, independent repository — no longer
an isolated Flask-only trade-off.

**Architectural question (instruction 18), answered with this evidence:** `matched_idf_
coverage` should remain a **separate evidence signal alongside confidence, not be folded
into a single confidence number** — it is doing real, distinguishable work (rejecting
genuinely coincidental matches on `flask-14`/`sqla-14`'s negative queries) even though it
is *also*, now confirmed across two repositories, costing real true positives. Collapsing
the two signals into one number would lose the ability to see and reason about that
trade-off at all. No change made this checkpoint — recorded as decisive evidence for the
next architectural decision, not acted on unilaterally.

## G. Remaining issues

- **RESOLVED**: SQLite connection-per-call overhead; missing `target_id` index; quadratic
  `ast.get_source_segment` extraction cost; duplicate per-query BM25 index rebuild.
- **MEASURED / ACCEPTABLE**: CALLS relationship resolution (11.7-28.3% even at best,
  0% for `obj.method()`/`module.func()`/chained shapes) — does not block current
  retrieval, since nothing in the pipeline depends on it; flagged for any future
  call-graph-aware signal, not fixed now.
- **MUST FIX BEFORE NEXT PHASE**: the retrieval-ranking ceiling on SQLAlchemy/Django
  (Section F) — this is the dominant blocker to the 80% gate, not confidence calibration.
  `django-04`/`django-09`'s regression is now root-caused (`matched_idf_coverage` rejection
  of a strong candidate) — the open item is deciding what to do about that mechanism, not
  finding it.
- **MEASURED / ACCEPTABLE, evidence strengthened**: `matched_idf_coverage`'s
  precision/recall trade-off — now confirmed real in two repositories
  (`flask-06`/`flask-11` and `django-04`/`django-09`), not tuned against in this pass.
- **DEFERRED, with justification**: folding `matched_idf_coverage` into a single
  confidence number (Section F concludes the two-signal design is currently earning its
  keep, precisely *because* the trade-off it costs is now visible and measurable; revisit
  with the next phase's fuller evidence, not unilaterally here).

## H. Recommendation

```
NOT READY — specific blockers:
  1. 13/48 (27.1%, corrected) is far below the unchanged 39/48 (81.25%) gate.
  2. The dominant failure mode on SQLAlchemy/Django is candidates never entering
     the ranked set at all (a lexical-ranking ceiling), which no confidence-layer
     change can fix -- next work belongs in ranking/retrieval, not Fix 3.
  3. matched_idf_coverage's real cost (flask-06/flask-11/django-04/django-09) is
     now confirmed across two repositories -- a decision on this trade-off is
     needed before further confidence tuning, not further data-free guessing.
```

Real, measured, honestly-attributed progress happened this pass (+6 fully-correct queries,
+6 negative queries, and four independent, verified performance fixes with zero
correctness regressions) — reported as exactly that, not as readiness.
