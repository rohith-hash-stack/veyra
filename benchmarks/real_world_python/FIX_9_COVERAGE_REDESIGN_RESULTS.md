# Fix 9 — Redesigning `matched_idf_coverage`: Experiment Results

Offline experiment only. **No production code changed.** Confidence mechanism stays
frozen at `z >= 1.0 AND matched_idf_coverage >= 0.5` (plus the unconditional
exact/substring-name acceptance), exactly as it entered this pass.

## Correction found while building this experiment

The prior investigation (`CANDIDATE_GENERATION_INVESTIGATION.md`) computed
`matched_idf_coverage` with a hand-rolled tokenizer bug (see that file's erratum).
Recomputed with the real `_tokenize()` across all four repos before running any
experiment on top of it — the dominant-category count moves from 19/35 (54%) to
**16/35 (46%)** of all non-fully-correct answerable queries. Still the largest single
category by a wide margin (low-z: 9/35=26%, pool-truncation: 7/35=20%,
top_k-crowding: 3/35=9%). This report is built on the corrected numbers throughout.

## A. Baseline

13/48 fully correct (27.1%), 6/8 negative queries correct (75%), gate 39/48 (81.25%).

## Methodology

Two real datasets gathered directly against the persisted stores, using the actual
production functions (`_relative_confidence_scores`, `_matched_idf_coverage`,
`_build_bm25_index`), not simulated:

- **Positive set** (28 entries): every ground-truth entity for the 16 coverage-floor
  failures plus their queries' other named symbols (28 total resolvable symbols across
  those 16 queries) — real `z`, real `matched_idf_coverage`, plus each entity's position
  in its own query's full 200-candidate coverage distribution.
- **Negative set** (215 entries): *every* candidate across all 8 negative queries whose
  `z >= 1.0` (i.e., every candidate that would survive the z-score gate alone) — 1,600
  total tfidf candidates scanned, 215 clear `z >= 1.0`. This is the real "risk pool" any
  loosened coverage mechanism has to keep rejecting.

## B. Mechanisms evaluated

| Mechanism | Positive recovery @ a real operating point | Negative leakage @ same point | Decision |
|---|---|---|---|
| A. Current absolute coverage (`>= 0.5`) | 0/28 (baseline, by definition) | 3/1,600 candidates (2 queries: `flask-14`, `sqla-14`) | Baseline |
| B. Coverage percentile within query's pool | 11/28 @ `>= 0.90` | **58/215 (27%)** @ same threshold | **Rejected** |
| C. Coverage z-score within query's pool | 13/28 @ `>= 1.0` | **81/215 (38%)** @ same threshold | **Rejected** |
| D. Coverage margin vs. next-best candidate | 6/28 @ `>= 0.01` | 23/215 (11%) @ same threshold, but recovery is negligible everywhere | **Rejected** |
| E. Combined (BM25 z + coverage z + percentile) | not tested as a distinct mechanism | — | **Not attempted** — see below |

None of B/C/D produced a usable operating point. Full threshold sweep (not just one
row per mechanism):

| Percentile threshold | Positives recovered /28 | Negatives leaked /215 |
|---:|---:|---:|
| ≥0.50 | 25 | 176 (82%) |
| ≥0.70 | 21 | 151 (70%) |
| ≥0.80 | 14 | 81 (38%) |
| ≥0.90 | 11 | 58 (27%) |
| ≥0.95 | 3 | 41 (19%) |
| ≥0.98 | 2 | 22 (10%) |

| Coverage-z threshold | Positives recovered /28 | Negatives leaked /215 |
|---:|---:|---:|
| ≥0.5 | 18 | 148 (69%) |
| ≥1.0 | 13 | 81 (38%) |
| ≥1.5 | 9 | 67 (31%) |
| ≥2.0 | 2 | 45 (21%) |
| ≥2.5 | 1 | 30 (14%) |
| ≥3.0 | 1 | 29 (13%) |

| Margin threshold | Positives recovered /28 | Negatives leaked /215 |
|---:|---:|---:|
| ≥0.01 | 6 | 23 (11%) |
| ≥0.02 | 3 | 19 (9%) |
| ≥0.05 | 1 | 13 (6%) |
| ≥0.10 | 0 | 5 (2%) |

**The structural finding, not just the numbers**: negative leakage never reaches zero for
percentile or coverage-z, no matter how strict the threshold (22/215 still leak even at
the 98th percentile). This is not a calibration problem solvable by picking a stricter
cutoff — it's a structural property of any *relative* measure: every query's candidate
pool has *something* at its own 99th percentile, whether or not anything in that pool is
actually a correct answer for a genuinely unanswerable query. This is exactly the same
failure mode Fix 3's original z-score-alone design already had for raw BM25 score (z≥1.0
alone leaks 23–35 candidates on *every one* of the 8 negative queries, which is precisely
why `matched_idf_coverage` was added as an absolute floor in the first place). Mechanism
E (a weighted combination) was not built as its own experiment: combining two signals
that are each individually unable to reach zero-leakage at any threshold does not have a
principled reason to succeed where either alone failed, and constructing a combined
formula without a real, non-arbitrary weighting would itself be exactly the
benchmark-fitting this task prohibits.

## C. Statistical evidence (the actual distributions)

Positive-case values (16 queries, 28 resolvable symbols) span coverage 0.13–0.57,
percentile 0.10–0.99, coverage-z −1.16–5.48. Negative-case values (215 candidates,
z≥1.0): coverage mean 0.209/median 0.196/p90 0.342/max 0.654; percentile mean
0.690/median 0.770/**p90 0.980**; coverage-z mean 1.192/median 0.753/p90 3.223. The
populations substantially overlap on every relative measure tried — there is no clean
separating line, only a shrinking, never-zero leak rate as the threshold tightens.

## D. Representative cases

| Entity | z | Absolute coverage | Percentile | Coverage-z | Verdict under every tested mechanism |
|---|---:|---:|---:|---:|---|
| `FlaskClient` (`flask-11`) | 7.57 | 0.488 | 0.99 | 5.48 | Recovered by every mechanism, including current (0.488 is close to 0.5) |
| `OAuth2PasswordBearer` (`fastapi-12`) | 4.36 | 0.573 | 0.98 | 2.31 | **Already clears the current 0.5 floor** — corrected coverage shows this was never actually coverage-rejected |
| `authenticate()` (`django-04`) | 2.48 | 0.405 | 0.80 | 0.61 | Rejected by current; recovered only by the loosest, most leak-prone thresholds (percentile≥0.70, coverage-z≥0.5) |
| `APIRoute` symbol (`fastapi-02`) | 2.04 | 0.347 | 0.87 | 1.63 | Same shape as `authenticate()` |
| `FastAPI.add_api_route` (`fastapi-04`) | 1.15 | 0.323 | 0.77 | 0.85 | Recovered only at the leakiest thresholds |
| `QuerySet` (`django-01`) | 2.11 | 0.72 | — | — | **Already correctly accepted** (position 9, TRUE) — not part of this problem; its issue is BM25 length normalization (Checkpoint B), explicitly out of scope for Fix 9 |

## E. Negative-query analysis (all 8)

| Query | Accepted under current mechanism | Grade |
|---|---|---|
| `flask-13` | 0 entities | Correct |
| `flask-14` | 1 (`App`, cov=0.561) | **Leaks** (pre-existing, unchanged) |
| `fastapi-13` | 0 entities | Correct |
| `fastapi-14` | 0 entities | Correct |
| `sqla-13` | 0 entities | Correct |
| `sqla-14` | 2 (`PyODBCConnector` cov=0.654, `BinaryExpression` cov=0.511) | **Leaks** (pre-existing, unchanged) |
| `django-13` | 0 entities | Correct |
| `django-14` | 0 entities | Correct |

6/8 correct, matching Checkpoint B exactly — this experiment changed nothing in
production, so this is a reproduction check, not a new result. Every mechanism tested
in Section B would have made this worse, not better, at any operating point that
recovers a meaningful fraction of the 16 positive failures.

## F. Before/after benchmark

| | Phase D | Checkpoint B | Fix 9 |
|---|---:|---:|---:|
| Fully correct | 7/48 (14.6%) | 13/48 (27.1%) | **13/48 (27.1%), unchanged** |
| Negative correct | 0/8 | 6/8 | **6/8, unchanged** |

No production change was made, so no benchmark re-run was performed — the 13/48 and 6/8
figures are Checkpoint B's, reproduced here as confirmation the investigation didn't
silently touch anything.

## G. Regression matrix

Empty. No production code changed in this pass, so no query's classification changed.

## H. Test results

No new production code, so no new unit/synthetic tests were added to the suite this
pass. Full existing suite re-confirmed green before concluding: **476 passed, 0 failed,
26 skipped** (identical to the count at the start of this investigation).

## I. Decision

```
FIX 9 REJECTED — NO SAFE REPLACEMENT FOUND
```

Three concrete, real, non-benchmark-fitted mechanisms (query-relative percentile,
query-relative z-score, margin-to-next-best) were built and measured against real data
from all four repositories — not assumed, not simulated. All three fail for the same
structural reason: a purely relative measure cannot distinguish "the best candidate in a
pool that contains a real answer" from "the best candidate in a pool that doesn't,"
because every pool has a best candidate regardless. This is not a threshold-tuning
problem this pass declined to finish — tightening any of the three mechanisms toward
zero leakage also drives positive recovery toward zero, and leakage never actually
reaches zero at any threshold tested.

**`matched_idf_coverage`'s current design — an absolute floor, not a relative signal —
is correct given what a relative signal was shown not to be able to do.** The floor's
real cost (16 confirmed positive rejections, several of them the strongest z-scores
measured in the whole benchmark) is real and not dismissed — but no evidence gathered
this pass supports believing a relative replacement fixes it without reopening the
negative-query problem Fix 3 was built to close.

**Recommended next experiment** (not attempted this pass, a genuinely different
hypothesis, not a retry of this one): investigate whether **structural corroboration**
(Fix 6's already-computed CONTAINS/parent-child data — does a low-coverage candidate's
*parent or sibling* entity independently show strong coverage for the same query?) can
distinguish `authenticate()`-shaped cases (a real answer whose own text just doesn't
happen to echo the query's wording) from `PyODBCConnector`-shaped cases (a coincidental
match with no such corroboration) — a fundamentally different signal from anything
lexical, which is exactly why the three lexical-statistics variants tested here all
failed the same way.
