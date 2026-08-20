# ARCF — Status and Resume Point

**ARCF** ("Phase-D Defect Correction & Validation") is the user's own name for the
engineering pass following up on `PHASE_D_RESULTS.md`. It is a controlled, staged
correction of concrete mechanical weaknesses in Veyra's deterministic retrieval
pipeline, found by the real-world benchmark. This file exists so a fresh session
(no prior chat context) can resume exactly where this pass left off. The full,
extremely detailed original ARCF directive (all 17 sections: engineering
principles, per-fix requirements, stop conditions, reporting format) was given by
the user directly in chat and is **not** reproduced verbatim here — this file is
the condensed status/resume record, not a replacement for asking the user for the
full directive text if fine-grained wording ever matters.

## Non-negotiable constraints (apply to every fix, unchanged throughout)

- **Acceptance gate: ≥39/48 (80%) fully-correct queries, unchanged.** Baseline was
  7/48 (15%). Never redefine, lower, or move this gate.
- Deterministic only: no embeddings, vector DBs, LLM/SLM rerankers, external
  reranking APIs.
- No benchmark-specific hacks: no repo-name checks, no query-ID special cases, no
  thresholds chosen because they flip one observed benchmark query.
- Every ranking/confidence decision must remain explainable (a human can determine
  why candidate A outranked candidate B).
- Minimal architectural change — fix identified mechanisms, don't rewrite the
  retrieval pipeline.

## Execution order (as steered by the user)

```
Fix 1 (candidate pool vs top_k)  ✅ DONE
Fix 2 (score/confidence separation)  ✅ DONE
Fix 4 (stopwords)  ✅ DONE
Fix 5 (source-category weighting)  ✅ DONE
Fix 6 (structural graph signal)  ✅ DONE
  ↓
CHECKPOINT A  ✅ DONE (report below)
  ↓
Fix 3 (confidence recalibration)  ✅ DONE (report below)
Fix 7 (call-resolution measurement)  ✅ MEASURED during initial inspection, not yet
       formally written up as its own report section
Fix 8 (storage/connection performance)  ⏳ MEASURED (root cause + numbers known),
       NOT YET IMPLEMENTED
  ↓
CHECKPOINT B  ⏳ NOT STARTED (needs Fix 8 implemented first)
  ↓
Full 4-repo validation (Flask, FastAPI, SQLAlchemy, Django; same 48-query
benchmark; same 80% gate)  ⏳ NOT STARTED
```

**This is the actual resume point: implement Fix 8, formally write up Fix 7's
already-measured findings, run Checkpoint B, then the full 4-repo rerun.**

All work is on branch `experiment/real-world-python-benchmark`, never on
`claude/veyra-progress-plan-h7kthq` (the dev branch). Every fix so far is its own
commit (`git log --oneline` on this branch shows: Phase B, Phase D, ARCF Fix 1,
Fix 2, Fix 4, Fix 5+6, Fix 3, in that order). Full project test suite is green
after every commit (469 passed, 26 skipped, 0 failures as of Fix 3).

## What's already measured for Fix 7 (call-resolution quality)

Real numbers, pulled from the persisted static audits
(`results/<repo>_static_audit.json`), during ARCF's initial inspection phase:

| Repository | Resolved calls | Unresolved | Total call sites | Resolution % |
|---|---:|---:|---:|---:|
| Flask | 317 | 3,805 | 4,122 | 7.7% |
| FastAPI | 1,349 | 10,471 | 11,820 | 11.4% |
| SQLAlchemy | 20,676 | 159,528 | 180,204 | 11.5% |
| Django | 20,660 | 151,976 | 172,636 | 12.0% |

Root cause (`src/veyra/static_analysis/python_extractor.py::_resolve_call_target`):
only resolves bare-name calls and `self.`/`cls.`-prefixed calls — never
`module.func()` or arbitrary `obj.method()` calls. CONTAINS edges (parent/child/
sibling), by contrast, are structural (AST-derived, not call-resolution-dependent)
and ~97-99% populated — unaffected by this gap.

**Decision already made and acted on**: Fix 6's structural signal deliberately
uses only CONTAINS-derived relationships (`children`/`siblings`), not CALLS edges,
specifically because of this measurement — documented in `search.py`'s Fix 6
docstring. Per the directive's own decision rule ("measure first, don't redesign
extraction unless the evidence shows a concrete, targeted defect"), no extractor
change has been made. This satisfies Fix 7's requirement; what's still open is
writing this up formally as Fix 7's own report deliverable (table + decision
statement), not re-measuring anything.

## What's already measured for Fix 8 (storage performance) — not yet implemented

Every `VBGStore` method opens and closes its own `sqlite3.connect()`
(`src/veyra/vbg/storage.py::_connect`, called fresh in ~35 different methods).
Measured directly: building FastAPI's retrieval index (13,891 entities) took
**111.7 seconds** and issued **96,105 separate SQLite connections** (6.9 per
entity) — `get_parents`/`get_children`/`get_siblings` per node during
`build_retrieval_index()` is the dominant driver.

Confirmed safe to fix with a simple, non-global approach: no threading or
multiprocessing use of `VBGStore` found anywhere in the codebase (`harness/
manager.py` and `harness/synthesis.py` use it synchronously). Planned fix (not yet
implemented): one lazily-opened, reused connection per `VBGStore` instance,
preserving the existing append-only/no-UPDATE-DELETE semantics and commit-per-write
behavior — needs before/after timing plus a concurrency-safety check before/after,
per the directive's Fix 8 requirements.

## Checkpoint A — condensed findings (full report was given in chat, not saved verbatim)

Ran Fixes 2, 4, 5, 6 together against real Flask+FastAPI stores, measuring raw
ranking (not confidence-gated, since the 29.0 threshold was already known-stale at
that point). Result: **10/12 Flask and 10/12 FastAPI answerable queries now have a
ground-truth-file entity within the top-10 raw ranking** (up from ~6/12 and 4/12 at
Phase D), zero ranking regressions found. FastAPI crowding hypothesis (many
near-identical HTTP-verb sibling methods outranking their own parent class)
partially confirmed and partially addressed: `FastAPI`'s own class moved from rank
35 to rank 4 via Fix 6's sibling-penalty/child-bonus mechanism, though it did not
yet fully overtake every rival. Decision: evidence supported continuing to Fix 3.

## Fix 3 — condensed findings (full report was given in chat, not saved verbatim)

Replaced the absolute `29.0` confidence threshold with a fully query-relative
mechanism: `z = (score - mean(pool)) / stdev(pool)`, computed fresh per query from
that query's own candidate pool, plus a second signal (`matched_idf_coverage >=
0.5` — the query's terms' combined IDF weight actually found in the candidate's
text) added after real-repo validation showed z-score alone let something always
look "relatively confident" even in a genuinely unanswerable query's noise pool.

**Real-repo result (Flask+FastAPI, 24 answerable + 4 negative queries):**

| Metric | Phase D (pre-ARCF) | After Fix 3 |
|---|---|---|
| Fully correct | 3/24 (12.5%) | **7/24 (29.2%)** |
| Negative queries correct | 4/4 | 3/4 |

Real fixes: `flask-05`, `flask-08` (both flagship Phase D failures) and
`fastapi-01`, `fastapi-03` (the exact Checkpoint A crowding cases) all now fully
resolved. **Open, unresolved, explicitly-not-tuned-away issue**: the
`matched_idf_coverage=0.5` floor causes a few genuinely strong matches (z>5, e.g.
`flask-11`'s `FlaskClient` at coverage=0.49, `flask-07`'s
`SecureCookieSessionInterface` at coverage=0.24) to be rejected because their
wording doesn't literally overlap the query, and leaves one negative query
(`flask-14`) still leaking one weak entity. This is a real precision/recall
tension at the 0.5 boundary — flagged for reconsideration at the full 4-repo
checkpoint, deliberately not adjusted now to avoid fitting these two specific
cases. Full detail (including the exact confidence-decision output for each) is
in this conversation's history and in the Fix 3 commit message
(`git log --grep "ARCF Fix 3"` on this branch).

Full test suite after Fix 3: **469 passed, 26 skipped, 0 failures.**

## If resuming cold (no chat history available)

1. `git log --oneline` on `experiment/real-world-python-benchmark` for the exact
   commit sequence; `git show <hash>` on the Fix 1/2/4/5/6/3 commits for full
   rationale in each commit body.
2. `PHASE_B_RESULTS.md` and `PHASE_D_RESULTS.md` for the two phases that preceded
   ARCF.
3. This file for what ARCF itself covers and exactly what's left.
4. Re-run `benchmarks/real_world_python/scripts/run_queries.py` against the
   already-persisted `flask_vbg.db`/`fastapi_vbg.db` stores to reproduce current
   numbers without re-extracting anything (extraction/store-building is the
   expensive step; the stores are already committed-adjacent artifacts under
   `results/`).
