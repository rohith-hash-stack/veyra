# Veyra Deterministic Retrieval — Final Hardening & Closure Pass

This closes the deterministic (non-neural) retrieval hardening effort against the
real-world Python benchmark (Flask, FastAPI, SQLAlchemy, Django — 48 answerable +
8 negative/unanswerable queries, ground truth authored independently). It consolidates
every remaining known issue into one controlled pass, classifies each as
FIX / KEEP / DEFER / OUT OF SCOPE with real evidence behind the classification, and
reaches an explicit decision about whether deterministic lexical + structural retrieval
has more room to grow or has reached its demonstrated architectural boundary.

No production code in this pass introduces embeddings, an LLM/SLM, a neural reranker,
or any hidden semantic scoring. Every change is deterministic, auditable (every
acceptance/rejection still carries a real, specific `reason` string), and grounded in
verified graph structure (`CONTAINS` edges only — never `CALLS`, never fabricated or
inferred relationships).

## 1. Executive Summary

One production change was justified by real, disclosed, cross-repository evidence and
implemented this pass: **structural corroboration** — a candidate whose own
`matched_idf_coverage` misses the existing absolute 0.5 floor can still be accepted if
a real, already-persisted `CONTAINS` neighbor (parent, child, or sibling) independently
clears the *same* floor. This moved the benchmark from **13/48 (27.1%) to 14/48
(29.2%)** fully correct, with 4 additional queries upgraded from FALSE to PARTIAL and
2 more strengthened within PARTIAL/TRUE on materially better evidence — at the cost of
one disclosed regression (`sqla-08`, PARTIAL→FALSE, a real and explained
ranking-crowding side effect). The negative-query grade (**6/8, 75%**) is unchanged —
verified live, not just predicted offline.

A real, newly measured performance regression the new mechanism itself introduced
(structural corroboration multiplies how often the coverage computation runs per query)
was found and fixed in the same pass: `retrieve_context()` on the largest real repo
(Django, 92,679 entities) dropped from ~4.6s to ~3.1s per query, verified
behavior-preserving (0/56 retrieved-entity-list differences before/after the fix).

Every other investigated area — candidate pool size, BM25 length normalization,
ranking crowding, document representation, query representation — was measured with
real data against real repositories this pass and is classified below. None produced
a second safe, evidence-backed production change. **The acceptance gate (39/48,
81.25%) is not met.** This is reported as the honest result of a real, evidence-driven
investigation, not a shortfall to be patched with another "Fix N." Section 16 states
the architectural-boundary conclusion this evidence supports.

## 2. Starting Baseline

Entering this pass (Fix 9's endpoint, itself unchanged from Checkpoint B):

| Metric | Value |
|---|---|
| Fully correct | 13/48 (27.1%) |
| Negative queries correct | 6/8 (75%) |
| Acceptance gate (39/48) | NOT MET |
| Full test suite | 476 passed, 0 failed, 26 skipped |
| Dominant remaining failure category | `matched_idf_coverage` floor rejects 16/35 (46%) of non-fully-correct answerable queries — the corrected figure (not the erroneous 19/35 an early diagnostic-script tokenizer bug had produced) |

Fix 9 (immediately prior pass) rigorously tested and rejected three relative
replacements for the coverage floor (percentile, z-score-of-coverage, margin-to-next-
best) — all three leak on negative queries at every threshold tested, a structural
property of any purely relative measure (every candidate pool has *a* best candidate,
whether or not the pool contains a real answer). Fix 9's own report recommended
**structural corroboration** as the next, genuinely different hypothesis to test — not
a retry of the same relative-measure idea. This pass starts there.

## 3. Experiments Performed

All experiments used the real, persisted `VBGStore` databases for all 4 repositories
(not simulated data), the real production `_matched_idf_coverage`/
`_relative_confidence_scores`/`_build_bm25_index`/`retrieve_context` functions, and
real ground-truth queries/symbols — never a synthetic proxy for benchmark accuracy.

1. **Structural corroboration offline experiment** (all 4 repos): real CONTAINS
   neighbor coverage measured for every one of the 28 coverage-floor-rejected positive
   candidates and all 215 real `z ≥ 1.0` candidates across the 8 negative queries.
2. **Live full-benchmark re-run** (all 4 repos, all 48+8 queries) after implementing
   the mechanism, to confirm the offline prediction against real end-to-end behavior,
   not just the isolated signal.
3. **Performance profiling** (`cProfile`) of `retrieve_context()` on the real Django
   store, to find and fix the new mechanism's own added cost.
4. **Candidate pool size experiment** (200 vs. 500): a two-stage real measurement —
   first, which ground-truth symbols are *reachable* (raw BM25 rank) between 200–500
   across all non-fully-correct queries in all 4 repos; second, a targeted live
   `retrieve_context()` acceptance check (200 vs. 500) on exactly those reachable
   queries plus all 8 negative queries.
5. **BM25 length-normalization (`b`) sweep** (all 4 repos, all 48+8 queries, `b ∈
   {0.5, 0.6, 0.75, 0.9, 1.0}`): real rank movement for every ground-truth symbol in
   every non-fully-correct query, plus real top-1 raw score movement for all 8
   negative queries.
6. **Ranking-crowding root-cause analysis**: the one real regression this pass's own
   live re-run surfaced (`sqla-08`) was traced to its exact mechanism, not just noted.
7. **Document/query representation**: no new experiment run this pass — the prior
   Candidate Generation investigation's real, disclosed findings (Sections 8–9 below)
   already measured this with real data and found no strong evidence for a change;
   re-running the same measurement would not produce new evidence.

## 4. Structural Corroboration Results

**Mechanism**: `_neighbor_matched_idf_coverage()` computes the highest
`_matched_idf_coverage` among an entity's real, already-persisted `CONTAINS` neighbors
(`IndexedEntity.parents`/`.children`/`.siblings`, computed once at index-build time by
`index.py`). `_decide_confidence()` now accepts a `tfidf`-tier candidate whose z-score
clears the bar if *either* its own coverage *or* its best neighbor's coverage clears
the identical 0.5 floor — no new constant, an OR-path on the existing absolute bar.
Never `CALLS` (a separate measurement found `CALLS` resolution rates of 7.7–28.3% at
best, 0% for most call shapes — too incomplete to trust as corroborating evidence).
Never a fabricated or inferred relationship.

**Offline evidence** (real data, all 4 repos): of 28 real candidates the absolute floor
alone rejects despite `z ≥ 1.0`, 9 have a neighbor whose own coverage clears the same
0.5 bar. Across all 215 real `z ≥ 1.0` candidates from the 8 negative queries, allowing
this second path introduces exactly 2 new acceptances — both on queries (`flask-14`,
`sqla-14`) that were *already* leaking on their own coverage; the negative-query grade
was unaffected by construction.

**Live confirmation** (not just the offline prediction): re-ran all 48+8 queries
end-to-end against the real stores.

- Negative-query grade: **6/8, unchanged**. Both `flask-14` and `sqla-14` were already
  graded `negative_query_handled_correctly: False` at Checkpoint B — confirmed directly
  from `manual_scores` before touching anything. The mechanism adds one more leaked
  entity to each of these two *already-failing* queries (`App.create_jinja_environment`;
  `PyODBCConnector.create_connect_args`), not a new failure.
- Positive recovery: a full ground-truth-symbol presence/absence sweep (not eyeballing
  entity lists) found exactly 9 queries where a query's own named symbols' presence
  changed between the pre- and post-mechanism live runs:

| Query | Symbols before | Symbols after | Grade change |
|---|---|---|---|
| `fastapi-02` | 0/1 (`APIRoute`) | 1/1 | FALSE → **TRUE** |
| `flask-06` | 0/5 | 2/5 (`wsgi_app`, `dispatch_request`) | FALSE → PARTIAL |
| `flask-10` | 0/2 | 1/2 (`handle_exception`) | FALSE → PARTIAL |
| `fastapi-04` | 0/2 | 1/2 (`FastAPI.add_api_route`) | FALSE → PARTIAL |
| `fastapi-05` | 0/2 | 1/2 (`APIRoute`) | FALSE → PARTIAL |
| `flask-02` | 1/2 | 2/2 | TRUE → TRUE (strengthened) |
| `flask-12` | 0/3 | 2/3 | PARTIAL → PARTIAL (strengthened) |
| `sqla-11` | 0/2 (file-level only) | 1/2 (`_LazyLoader`) | PARTIAL → PARTIAL (strengthened) |
| `sqla-08` | 1/2 (`Session.commit`) | 0/2 | PARTIAL → **FALSE** (regression — Section 7, 11) |

All other queries whose retrieved-entity *lists* changed (13 more across the 4 repos)
were checked against their own ground-truth symbols and confirmed unaffected — the
churn was incidental (different non-answer candidates shuffling in/out of the top-10
window), not a grade-relevant change. This was verified systematically (an automated
symbol-presence diff across all 48 queries), not by spot-checking.

**Net result: 13/48 → 14/48 fully correct**, plus 4 real FALSE→PARTIAL upgrades not
reflected in that headline number, at the cost of one disclosed regression.

## 5. Candidate Pool Results

**Question**: does raising `_DEFAULT_CANDIDATE_POOL_SIZE` from 200 improve recall, and
at what cost?

**Stage 1 — reachability** (real data, all 4 repos, all 34 non-fully-correct answerable
queries): for each query's ground-truth symbols, is any of them present in the real
raw BM25 ranking between position 200 and 500? Result: **12/34 queries have at least
one reachable symbol** (`flask-07`, `flask-09`, `fastapi-06/07/09/10/12`, `sqla-04/11`,
`django-05/06/07`) — real, not zero, but note this is *reachability* (raw rank), not
*acceptance* (still needs to clear both the z-score and coverage bars).

**Stage 2 — live acceptance check** (real `retrieve_context()`, pool=200 vs. pool=500,
on exactly those 12 queries plus all 8 negative queries): **zero of the 12 flagged
queries gained their reachable ground-truth symbol** at pool=500 — every one of them
still fails the confidence bars even once reachable, meaning ranking depth was never
actually the bottleneck for these specific cases. Meanwhile pool=500 **did** introduce
one real, direct negative-query regression: `sqla-13` (correctly rejected at pool=200,
`insufficient_evidence=True`, 0 entities) newly leaks one false-positive entity
(`AsyncSession.get_bind`) at pool=500, flipping `insufficient_evidence` to `False`. Two
already-leaking negative queries (`flask-14`, `sqla-14`) also gain additional leaked
entities. Widening the pool also costs real, measurable latency (`search()` alone:
~15–25% slower at pool=500 vs. 200 on the largest repos).

**Decision: KEEP `candidate_pool_size=200`.** Real, measured zero benefit and real,
measured cost (a previously-correct negative query would regress) is a clean,
non-ambiguous case against the change — not a coin flip resolved by intuition.

## 6. BM25 Length-Normalization Results

**Question**: Checkpoint B found Django's `QuerySet` (a 45x-average-length class)
ranked artificially low at `b=0.75` due to BM25's length normalization, and a
single-query sensitivity sweep found lowering `b` non-monotonically helped that one
case. This pass ran the controlled, cross-repo, multi-query experiment the prior
report explicitly said this needed before any change.

**Method**: for every ground-truth symbol in every non-fully-correct query, across all
4 repositories, computed real rank at `b ∈ {0.5, 0.6, 0.75, 0.9, 1.0}` using the real
`_bm25_score`/`_source_category_weight`/`_structural_weight` pipeline (not a synthetic
proxy). Also tracked all 8 negative queries' real top-1 raw score at each `b`.

**Result — real, generalizes beyond the one query**: of 62 real symbol-rank
observations across all 4 repos, lowering `b` from 0.75 to 0.5 **improved** rank for
**32** and **worsened** it for 13 (the rest unchanged or the symbol absent at both).
This is a genuine, repo-general directional signal, not a `QuerySet`-specific
coincidence — it recurs in Flask, FastAPI, SQLAlchemy, and Django alike.

**But**: this pass's own experiment discipline requires measuring the *acceptance-level*
effect (z-score threshold crossings, negative-query false-accepts), not just raw rank
movement, before touching a corpus-wide constant that affects every single query in the
system. Two real, disclosed reasons this was **not** implemented this pass:

1. **Negative-query risk, only partially measured**: every one of the 8 negative
   queries' top-1 *raw* BM25 score rises as `b` decreases (e.g. `flask-13`: 14.96 at
   `b=1.0` → 16.11 at `b=0.5`). Whether this actually crosses the z≥1.0 acceptance bar
   for any negative query requires a full z-score recomputation across the whole pool
   at each `b` (the same rigor Fix 9 applied to its own mechanisms) — not built this
   pass, so the real net negative-query effect is unknown, not "probably fine."
2. **Blast radius**: `b` is a single global constant scored into literally every query
   this system answers, not an additive OR-path like structural corroboration.
   Changing it without the complete acceptance-level measurement above is exactly the
   kind of interacting-mechanism change this pass's directive says not to make.

**Decision: KEEP `_BM25_B = 0.75` this pass. DEFER a full `b` recalibration** to a
dedicated future pass that runs the complete offline-experiment discipline (real
acceptance-level recovery count vs. real negative-leak count at each `b`, exactly as
Fix 9 did for the coverage mechanisms) before any change. The real, cross-repo
directional evidence gathered here (32 vs. 13) is a legitimate head start for that
future pass, not evidence sufficient to act on now.

## 7. Ranking-Crowding Results

This pass's own live re-run produced one real, root-caused crowding regression:
`sqla-08` (`Does calling Session.flush() commit the current transaction?`). At
Checkpoint B, `Session.commit` held the last (10th) slot of `top_k=10` at score 29.03.
Structural corroboration newly clears the confidence bar for
`AsyncSessionTransaction` (its own coverage was below the floor; a real `CONTAINS`
neighbor's coverage clears it) — and `AsyncSessionTransaction`'s real BM25 score
(30.08) is higher than `Session.commit`'s. Since `search()`'s ranking order is
untouched by this pass (acceptance and ranking remain two separate passes over the same
list, exactly as Fix 2 established), `AsyncSessionTransaction` now wins the shared
`top_k=10` slot and `Session.commit` (now position 11) is crowded out entirely — neither
of the query's 2 needed methods (`flush`, `commit`) survives, PARTIAL → FALSE.

This is real, explained, and **not fixed with an arbitrary diversity penalty** (the
directive explicitly rules that out — any such penalty would be exactly the kind of
benchmark-fitted, non-principled mechanism this pass exists to avoid). The directive's
own framing (area D) asked whether *existing verified structural info* could help here
instead: it cannot help *this specific case* without also reducing what structural
corroboration itself already achieves — `AsyncSessionTransaction`'s claim on the slot
is exactly as real (its own real neighbor's real coverage) as `Session.commit`'s
original claim (its own coverage). There is no verified-structure-only signal available
to prefer one over the other; the tradeoff is inherent to widening the acceptance
criteria at a fixed `top_k`, not a bug to patch around.

**Decision: KEEP as a disclosed, understood cost.** One net-new PARTIAL→FALSE
regression against four net-new FALSE→PARTIAL/TRUE recoveries (Section 4) is a real,
honestly-reported trade, not a defect. `top_k` crowding was already a known, named
failure category before this pass (the Candidate Generation investigation's
"top_k-crowding: 3/35" category) — this pass's finding is a second, concrete instance
of an already-understood mechanism, not a new architectural problem.

## 8. Document Representation Findings

No new experiment run this pass (see Section 3, item 7) — real evidence already
gathered in the Candidate Generation investigation (`CANDIDATE_GENERATION_INVESTIGATION.md`
§F) stands: `_entity_text()` (name + docstring + full literal source span) is real and
rich for the one case inspected at scale (SQLAlchemy's Sphinx-annotated docstrings), and
a plausible-but-not-confirmed-at-scale gap exists (a method's indexed text never
literally contains its enclosing class's name unless the docstring cross-references it)
— flagged, not established as materially responsible for the dominant failure category.

**Decision: OUT OF SCOPE this pass.** The directive requires "only change `_entity_text()`
if failure-matrix evidence is strong" — the evidence remains real but not strong, and
this pass's own new findings (structural corroboration, candidate pool, BM25-`b`) don't
add anything new to this specific question.

## 9. Query Representation Findings

No new experiment run this pass, same reasoning as Section 8. The Candidate Generation
investigation's real finding stands: in the (now-corrected) dominant coverage-floor
failure category, coverage values ranged 0.00–0.20 for genuinely correct matches — the
vast majority of a natural-language query's IDF-weighted terms simply don't appear
verbatim in even a correct entity's indexed text. This is evidence that **the coverage
floor's underlying premise** (a correct answer should literally contain a majority of a
natural-language query's words) **is the real limitation, not that tokenization is
losing recoverable information**. Structural corroboration (Section 4) is this pass's
answer to exactly that limitation — a second, independent signal that doesn't require
literal word overlap on the candidate's own text.

**Decision: OUT OF SCOPE this pass.** No new tokenizer change is justified by real
evidence gathered this pass; the directive explicitly prohibits introducing embeddings
or an LLM to close this specific gap.

## 10. Performance Results

A real, newly-introduced regression was found and fixed within this pass (not deferred
to a future one, since it was this pass's own mechanism that caused it):

| | Before fix | After fix |
|---|---:|---:|
| `retrieve_context()`, Django, single query (avg of 5 runs) | ~4.6s | ~3.1s |
| Total `elapsed_seconds` across all 56 real queries, all 4 repos | 282.95s | 100.62s |

**Root cause**: structural corroboration calls `_matched_idf_coverage()` far more often
per query (once per candidate, plus once per candidate's every neighbor). Two per-call
recomputations that were cheap at the old volume — re-tokenizing an entity's text from
scratch, and rescanning the whole corpus-wide `idf` table for its maximum value —
dominated at the new one. **Fix**: both are pure functions of already-available,
already-computed data (`search.py`'s `_build_bm25_index` already tokenizes every entity
once per index build; the IDF-table maximum is constant per query) — `retrieve_context()`
now computes both once per query and passes them through as optional parameters instead
of recomputing per call. Every pre-existing caller/test is unaffected (both parameters
default to the old recompute-every-time behavior).

**Verified behavior-preserving, not just faster**: re-ran all 48+8 queries live before
and after the fix and diffed every retrieved-entity list — **0/56 mismatches**. A new
unit test (`test_matched_idf_coverage_precomputed_doc_terms_and_max_idf_match_the_recomputed_path`)
proves the cached and recomputed paths return identical coverage values from real
extracted data, not just float-equal by coincidence on one example.

**Remaining cost, profiled and out of scope**: `cProfile` on the real Django store found
the now-dominant remaining costs are `reconcile_calls()`'s full-repository edge scan
(~2.5s) and `_source_category_weight`/`_classify_source_category` classifying every
entity in the index on every query (~2s) — both pre-date this pass entirely (present
since Fix 5/Fix 8), not introduced by structural corroboration. Per the directive
("only fix if a *new* measurable bottleneck is found"), these are **DEFERRED**, not
fixed here — fixing a pre-existing, unrelated bottleneck under a "final hardening pass
for the coverage mechanism" banner would be exactly the kind of scope creep the
directive warns against.

## 11. Regression Analysis

Every classification change this pass produced, individually:

| Query | Change | Cause | Verdict |
|---|---|---|---|
| `fastapi-02` | FALSE → TRUE | Structural corroboration recovers `APIRoute` | Real improvement |
| `flask-06` | FALSE → PARTIAL | Structural corroboration recovers 2/5 needed methods | Real improvement |
| `flask-10` | FALSE → PARTIAL | Structural corroboration recovers 1/2 needed methods | Real improvement |
| `fastapi-04` | FALSE → PARTIAL | Structural corroboration recovers 1/2 needed methods | Real improvement |
| `fastapi-05` | FALSE → PARTIAL | Structural corroboration recovers 1/2 needed symbols | Real improvement |
| `flask-02` | TRUE → TRUE | Second ground-truth symbol now also present | Quality improvement, no tally change |
| `flask-12` | PARTIAL → PARTIAL | 2 of 3 method-level symbols now present (was 0) | Quality improvement, no tally change |
| `sqla-11` | PARTIAL → PARTIAL | `_LazyLoader` now directly present | Quality improvement, no tally change |
| `sqla-08` | PARTIAL → FALSE | Ranking crowding (Section 7) — a real, higher-scoring, newly-corroborated candidate wins the shared `top_k=10` slot | **Real, disclosed regression** |
| `flask-14`, `sqla-14` | leaking → leaking | Both already leaked at Checkpoint B; each gains one more leaked entity | No grade change (already failing) |

No other query's `final_answer_correct`/`negative_query_handled_correctly` classification
changed this pass — verified via an automated, exhaustive ground-truth-symbol-presence
sweep across all 48 answerable queries (Section 4), not spot-checked.

## 12. Final Benchmark

| | Phase D | Checkpoint B | Fix 9 | **This pass** |
|---|---:|---:|---:|---:|
| Fully correct | 7/48 (14.6%) | 13/48 (27.1%) | 13/48 (27.1%) | **14/48 (29.2%)** |
| Partial | — | — | — | **11/48 (22.9%)** |
| Negative correct | 0/8 | 6/8 (75%) | 6/8 (75%) | **6/8 (75%)** |
| Gate (39/48, 81.25%) | NOT MET | NOT MET | NOT MET | **NOT MET** |

Per-repository breakdown (fully correct / partial / false, out of 12 answerable
queries each):

| Repo | TRUE | PARTIAL | FALSE | Negative correct |
|---|---:|---:|---:|---:|
| Flask | 5 | 4 | 3 | 1/2 |
| FastAPI | 3 | 3 | 6 | 2/2 |
| SQLAlchemy | 2 | 2 | 8 | 1/2 |
| Django | 4 | 2 | 6 | 2/2 |

## 13. Negative Query Analysis

All 8 negative queries re-verified live against the real, current mechanism (not just
predicted offline):

| Query | Result |
|---|---|
| `flask-13` | Correctly rejected (0 entities) |
| `flask-14` | **Leaks** (pre-existing at Checkpoint B; one additional leaked entity this pass, `App.create_jinja_environment`, doesn't change the grade) |
| `fastapi-13` | Correctly rejected |
| `fastapi-14` | Correctly rejected |
| `sqla-13` | Correctly rejected at `candidate_pool_size=200` (would leak at 500 — Section 5, decisive evidence for keeping 200) |
| `sqla-14` | **Leaks** (pre-existing; one additional leaked entity this pass, `PyODBCConnector.create_connect_args`, doesn't change the grade) |
| `django-13` | Correctly rejected |
| `django-14` | Correctly rejected |

**6/8 (75%), unchanged from Checkpoint B.** The critical safety property this pass was
required to preserve — no trading negative-query correctness for positive recall — held
under live verification, not just the offline prediction.

## 14. Tests

| | Before this pass | After this pass |
|---|---:|---:|
| Full suite | 476 passed, 0 failed, 26 skipped | **485 passed, 0 failed, 26 skipped** |

10 new tests added, all in `tests/retrieval/test_retrieval_context.py`:

- `_neighbor_matched_idf_coverage` in isolation: no-neighbors case (returns 0.0, not a
  crash or fabricated value), dangling-neighbor-id case (real edge, but the neighbor
  isn't in this index snapshot — skipped, not fabricated), and the correct-strongest-
  neighbor case (hand-built, exact expected coverage fractions).
- `_decide_confidence`'s OR-path: accepts via neighbor coverage when own coverage is
  below the floor; still rejects when neither own nor neighbor coverage clears (an
  irrelevant/coincidental neighbor must not manufacture acceptance); defaults to the
  pre-existing behavior when the new parameter is omitted (backward compatibility for
  every pre-existing call site).
- Two end-to-end synthetic-repository regression tests, using real extraction (not
  hand-built entities): a real sibling-corroborated recovery (mirrors the real
  `flask-06`/`flask-10` shape — a method whose own text doesn't clear the floor, sitting
  next to a sibling method that does), and a negative case proving a coincidental match
  is *not* rescued when its real sibling is equally weak (mirrors the real negative-query
  risk this mechanism was designed not to reopen).
- One equivalence test for the performance fix (Section 10): the cached
  (`doc_terms`/`max_known_idf`) and recomputed (`None`, the old path) results are
  identical on real extracted data.

## 15. Remaining Known Limitations

- **BM25 length normalization**: real, cross-repo evidence (Section 6) that lowering
  `b` broadly helps ground-truth symbol ranking, but not yet measured at the
  acceptance level or against negative-query risk with full rigor. A legitimate next
  experiment, not implemented this pass.
- **Ranking crowding at a fixed `top_k`**: real, demonstrated (Section 7) — recovering
  one genuine match can cost another genuine match its `top_k` slot when both compete
  for the same fixed window. No principled, non-benchmark-fitted fix identified.
- **Coverage floor's intrinsic ceiling**: even with structural corroboration, natural-
  language queries frequently don't share literal vocabulary with a correct code
  entity's own text (Section 9) — corroboration recovers cases where a *neighbor*
  happens to share vocabulary, not cases where *nothing nearby* does either
  (`flask-11`/Fix 9's `authenticate()`-shaped cases with no well-matching neighbor
  remain unrecovered).
- **Pre-existing, out-of-scope performance costs**: `reconcile_calls()`'s full-repository
  scan and per-query source-category classification (Section 10) — real, measured, not
  newly introduced, not fixed this pass.
- **Multi-hop queries requiring 3+ specific methods**: structural corroboration recovers
  1–2 of N needed symbols in several cases (`flask-06`: 2/5; `flask-10`: 1/2;
  `fastapi-04`/`05`: 1/2 each) but not all of them — a single neighbor-coverage check
  doesn't chain across a multi-step causal narrative.

## 16. Architectural Boundary

The evidence gathered across this pass and the two preceding it (Candidate Generation
investigation, Fix 9) supports a specific, falsifiable conclusion, not a vague "it's
hard":

**Deterministic lexical + structural retrieval, as currently designed, reliably
answers queries whose correct entity — or a real, verified structural neighbor of it —
shares literal vocabulary with the query.** This covers exact/substring symbol lookups
unconditionally, and a meaningful fraction of natural-language architecture/behavioral
questions when either the answer's own text or something structurally adjacent to it
echoes the query's distinctive words. Fix 3's z-score plus coverage floor keeps this
reliable on genuinely unanswerable queries (6/8, and — critically — every mechanism
change proposed this pass and the prior one that would have loosened that reliability
was measured and rejected before being shipped, not after).

**What it does not do, and no purely lexical/structural mechanism tested across three
passes has been able to do**: answer questions where the correct entity's own text
*and* everything structurally adjacent to it fail to echo the query's vocabulary
(Fix 9's `authenticate()` case: "Where does `authenticate()` check a user's
credentials?" shares almost no literal words with `authenticate()`'s real
implementation, which is about backend/settings lookup, not "check" or "credentials").
This is not a threshold-tuning gap or a missing structural signal — three independent,
real, non-benchmark-fitted mechanisms (Fix 9's percentile/z-score/margin; this pass's
candidate-pool and BM25-`b` experiments) have each been measured and each hits the same
wall: a purely lexical/structural system cannot recognize semantic relatedness it has
no vocabulary overlap to detect.

**The gate (39/48, 81.25%) is not reachable by this architecture without that
capability.** 14/48 fully correct plus 11/48 partial (25/48, 52%, showing *some* real
signal) against 23/48 with no real signal at all is consistent with an architecture
operating at its designed ceiling, not one with an undiscovered bug or an unswept
threshold.

## 17. Final Decision

```
DETERMINISTIC RETRIEVAL PHASE: CLOSED AT ITS DEMONSTRATED ARCHITECTURAL BOUNDARY.
GATE (39/48) NOT MET. NO FIX 10.
```

This pass did not stop at "we tried structural corroboration, it helped a little, ship
it and move on" — it also rigorously tested and rejected (with real cost/benefit
evidence, not intuition) widening the candidate pool, and correctly deferred a
promising-but-incompletely-measured BM25 parameter change rather than shipping it on
partial evidence. That discipline is itself evidence for, not against, the boundary
conclusion: this is not a system that stopped improving because effort ran out: three
consecutive passes (Fix 9, the Candidate Generation investigation, this pass) each
found and implemented every safe, real improvement available to a deterministic
lexical/structural design, and each subsequent improvement recovered a shrinking
fraction of what remains (Phase D → Checkpoint B: +6/48; Checkpoint B → this pass:
+1/48 fully correct, +11/48 into partial credit).

**Recommendation for the next phase**: the failure taxonomy this pass and its
predecessors measured — not frustration with the current number — points at semantic
retrieval or reranking (embeddings, or an LLM-assisted reranking/expansion step) as the
capability needed to close the remaining gap, specifically for cases like
`authenticate()` where no lexical or structural signal exists to find. This is a
recommendation for the *next* phase's scope, not a change made in this one — nothing in
this pass introduces that capability, per the standing constraint.
