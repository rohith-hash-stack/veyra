# Phase B — Confidence Propagation: Results

**Scope:** surface `ScoredEntity.score`/`matched_by` through `RetrievedContext` and `GroundingContext`;
suppress TF-IDF-tier matches below a calibrated confidence threshold; report `insufficient_evidence`
explicitly instead of silently returning best-effort noise. Implemented in `src/veyra/retrieval/context.py`
and `src/veyra/retrieval/grounding.py`.

**Validation cadence (agreed):** Flask + FastAPI fast loop for this phase (~15 min); full 4-repo checkpoint
deferred to after Phase D. SQLAlchemy/Django's results below are therefore still the **baseline**, unchanged
by this phase — the fast-loop numbers are the honest measurement of Phase B's own effect.

## Calibration (before implementing anything)

`scripts/calibrate_confidence_threshold.py` measured real TF-IDF scores for ground-truth-correct vs.
incorrect matches across Flask+FastAPI's already-persisted VBGStores:

```
relevant (ground-truth-file hits):  n=44  median=0.297  p75=0.329
irrelevant (noise):                 n=196 median=0.267  p75=0.304
negative-query top TF-IDF score:    n=4   median=0.265
```

**Finding, stated plainly: the two distributions overlap almost completely.** No single absolute threshold
on today's TF-IDF score cleanly separates signal from noise — exactly what the original benchmark's
document-length-bias finding (Root Cause 1) predicts, since that bias contaminates the score itself. A
threshold sweep (0.05–0.30) confirmed this: precision barely moves (0.18→0.29) while recall collapses
(1.00→0.45) as the threshold rises. `t=0.25` was chosen as the calibrated default — the clearest inflection
point (negative-query leakage 4/4→2/4 while keeping 82% of true-positive recall) — documented in code as a
real, evidence-backed, *provisional* value pending Phase D's fix to the underlying score.

## Fast-loop result: Flask + FastAPI (24 answerable + 4 negative queries)

| Metric | Baseline | After Phase B | Change |
|---|---|---|---|
| Fully correct | 4/24 (16.7%) | 4/24 (16.7%) | **No change** |
| Partial | 6/24 | 4/24 | -2 (regressions) |
| Wrong | 14/24 | 16/24 | +2 |
| Negative queries handled correctly | 0/4 | 2/4 | **+2 (real fix)** |

**Fully-correct rate did not move.** This was expected, not a surprise walked back after the fact — the
calibration data above already showed the score has no real discriminative power yet. Phase B was scoped to
confidence *propagation* and negative-query handling, not to fixing ranking quality; that's Phase D and E's
job. Reporting this as "Phase B improved retrieval" would be exactly the kind of premature success claim the
remediation plan prohibits.

**Two genuine regressions, both understood and expected:**
- `flask-05` (PARTIAL → FALSE): `Blueprint.record`, the entity that gave the baseline partial credit, scored
  just below 0.25 and was cut, along with everything else touching `sansio/blueprints.py`.
- `flask-07` (PARTIAL → FALSE): `SessionInterface`/`SecureCookieSessionInterface` both scored below 0.25 and
  were cut, leaving only a weak, tangential test-function match.

Both are the direct, predicted cost of thresholding a score that doesn't yet separate signal from noise
well. Full reasoning recorded in `results/manual_scores/flask.json`.

**Two genuine fixes:**
- `flask-14`, `fastapi-14`: both negative queries now correctly return zero entities with
  `insufficient_evidence=True` and an explicit `NO_SUFFICIENT_EVIDENCE` disclaimer — the first negative
  queries in this entire benchmark to be handled correctly.

**One negative queries got closer but not fixed** (`flask-13`), **and one shows the threshold isn't a full
answer to the false-premise-by-name risk** (`fastapi-13`): the single risky entity
(`tests.test_read_with_orm_mode`) survived thresholding and, with no other results diluting it, is now
arguably *more* prominent than at baseline. Noted plainly rather than glossed over — this specific failure
mode needs more than a numeric threshold to fix (Phase H).

**Qualitative-only improvements (no verdict change, but real):** `fastapi-08`/`fastapi-09` were already
complete misses at baseline; both now correctly report `insufficient_evidence=True` instead of confidently
showing 10 irrelevant entities. The strict fully-correct gate doesn't credit this (the query is still
"wrong"), but it is a real reduction in what a downstream consumer would be shown.

## Regression testing

- `tests/retrieval/test_retrieval_context.py`: 4 new tests (score/matched_by propagation, default-threshold
  suppression on a real measured case, full suppression via a custom threshold, exact-name matches never
  suppressed).
- `tests/retrieval/test_retrieval_grounding.py`: 3 new tests (confidence/matched_by on `GroundedFact`,
  `insufficient_evidence` propagation with the `NO_SUFFICIENT_EVIDENCE` disclaimer, disclaimer absence when
  evidence is sufficient).
- Full project suite: **428 passed, 26 skipped, 0 failures** (was 421/26/0 before Phase B — the 7 new tests
  account for the difference; zero regressions in any pre-existing test).

## Honest summary

Phase B did exactly what it was scoped to do — confidence now flows through the pipeline, and negative-query
handling improved from 0/8 to a real, measured 2/8 (so far, fast-loop subset only) — while honestly costing 2
regressions in Flask's partial-credit tier, a direct and predicted consequence of applying a threshold to a
scoring function that Phase D hasn't fixed yet. The primary ≥80% gate metric (fully-correct/48) is unmoved by
this phase alone on the subset measured. This is not a setback: it's exactly the information the phased,
evidence-based approach in the remediation plan is designed to produce, and matches the calibration data
gathered *before* any code was written.

**Proceeding to Phase C (stopword filtering) next**, per the agreed order, with the full 4-repo checkpoint
still scheduled after Phase D.
