# VEYRA — Progress, Implementations, Descoped Ideas, Experiment Log

> Read this file at the start of every session, alongside [PLAN.md](PLAN.md).
> Update it (with date/time) after every meaningful change: a merge, a shipped phase, a descoped idea, or a
> finished experiment (success or failure). Keep entries newest-first within each section.

---

## Current Status

**Stage:** M1, M2, AND M3 ALL FULLY cleared. M3's gate closed 2026-08-20 (all 9 phases + security tests).
Milestone 4 (Retrieval & LLM Grounding) not started.
**Current milestone:** 314 passed, 26 skipped, 0 failures project-wide (non-Docker environment) — the 26 skips
are all Docker-gated tests (21 in `tests/execution/` from Phase 3.2, 2 in `tests/harness/` from Phase 3.3a, 3
in `tests/runtime/` from Phase 3.5) that were last proven against REAL disposable Docker containers in the
sessions that built them — this session's sandbox has the `docker` CLI but no reachable daemon, so they skip
cleanly rather than fail (same `pytest.mark.skipif` pattern Phase 3.2 established).
**Git:** `veyra` is now a git repo (`main` branch / `claude/veyra-progress-plan-h7kthq` working branch). `main`
covers M1+M2+Phase 3.1+3.2; the working branch adds the rest of M3 (3.3a/3.3b/3.4/3.5/3.6/3.7/3.8/3.9), pushed
commit by commit as this session progressed.
**Language scope:** Python-only (flagship language per PLAN.md D5), until the pipeline clears its M5 gates.
**Repo/storage:** `src/veyra/acquisition/`, `src/veyra/vbg/` (Node/Edge/Evidence/Repository/Audit/Question/
Answer/Classification/ExecutionEnvironment/Scenario, all append-only), `src/veyra/git_tracking/`,
`src/veyra/audit.py`, `src/veyra/static_analysis/`, `src/veyra/questions/`, `src/veyra/pipeline.py` (now the
entry point for BOTH `run_static_analysis()` and `run_runtime_analysis()`), `src/veyra/safety/`,
`src/veyra/execution/`, `src/veyra/harness/` (existing-test tracing + novel synthesis), `src/veyra/scenarios/`,
`src/veyra/runtime/`, `src/veyra/exploration/`, `src/veyra/reconciliation/`, `src/veyra/verification/` all
implemented. SQLite event-sourced store (D3) live. Every canonical entity Phase 1.2 originally deferred now
exists. One runtime dependency added: `hypothesis` (Veyra's own trusted tooling dependency for Phase 3.3b, not
a repository dependency).

---

### 2026-08-20 — Phase 3.9 (Runtime Audit) implemented — MILESTONE 3 GATE FULLY CLEARED — 314/314 project-wide
- **`RuntimeAuditReport` + `run_runtime_analysis()` added to `src/veyra/pipeline.py`** -- the Milestone 3
  counterpart to Phase 2.8's `run_static_analysis()`, and genuinely the **first time the whole M3 pipeline ran
  together end to end**: existing-test tracing (3.3a) → tiered eager exploration (3.6, itself running 3.4's
  scenario generation and 3.5's tracing) → novel synthesis (3.3b) → reconciliation (3.7) → verification states
  (3.8), all from one call, against real Nodes an earlier `run_static_analysis()` already extracted.
- **A real, previously-unnoticed gap found and fixed while building this**: writing the audit report's
  `scenarios_generated`/`scenarios_executable` fields required real persisted `Scenario` rows to count --
  and there weren't any. Neither `explore()` (Phase 3.6) nor `synthesize_novel_scenarios()` (Phase 3.3b) had
  ever actually called `VBGStore.insert_scenario()`, despite Phase 3.4 building full storage support for
  exactly this. `Scenario` objects were being constructed and used to drive `run_scenario()` but simply
  discarded afterward in both callers -- a genuine, previously-invisible gap (nothing before this needed to
  query persisted scenarios back out, so nothing caught it). Fixed in both modules, each covered by a new
  regression test (`test_explore_persists_every_generated_scenario`,
  `test_each_trial_scenario_is_persisted`) -- confirmed via the full suite that this didn't change either
  phase's existing behavior otherwise (48/48 in `tests/exploration`+`tests/harness` still passing).
- **`VBGStore.get_all_classifications()`** (mirrors `get_all_nodes`/`get_all_edges`/`get_all_evidence` --
  current view, latest per target) -- needed to report safety-class counts across every classified target at
  once, closing out the last of this session's "current view" bulk-read additions.
- **A real behavioral discovery, surfaced by testing the orchestration honestly rather than assuming it would
  just work**: Tier 1/2 eager exploration (3.6) runs *before* novel synthesis (3.3b) in this pipeline, and
  since exploration attempts every executable scenario regardless of `SafetyClass` (only `BLOCKED` is
  excluded, per D1), it typically leaves nothing "zero-coverage" behind for 3.3b to find in a small (Tier 1/2)
  repository -- the first draft of the synthesis-enabled test asserted `synthesis_eligible_targets >= 1` under
  Tier 1 and failed, because exploration had already covered the target first. Not a bug -- a real,
  now-documented consequence of pipeline ordering. Fixed the test to use a Tier 3 `file_count` (>500, where
  3.6 performs zero eager execution per D10), which is also a more honest demonstration of 3.3b actually doing
  something 3.6 didn't already do.
- **Tests**: 4 new, all non-Docker, reusing the by-now-standard `FakeExecutionBoundary` pattern -- full
  end-to-end report shape (existing-test/scenario/exploration/classification/runtime-evidence/verification-
  state fields all populated with real counts), audit-record persistence, default-policy-means-zero-synthesis
  (D13, consistent with every other test in this project touching `PolicyConfig`), and the Tier-3-enables-
  synthesis case above. **314/314 project-wide, 0 failures** (26 Docker-gated tests skip cleanly, same as every
  prior entry this session).
- **MILESTONE 3 GATE FULLY CLEARED.** All nine phases (3.1 Execution Classification, 3.2 Execution Boundary,
  3.3a Harness existing-test tracing, 3.3b Novel Scenario Synthesis, 3.4 Behavioral Scenario Generator, 3.5
  Runtime Trace Engine, 3.6 Multi-Execution Exploration, 3.7 Evidence Reconciliation, 3.8 Verification State
  Engine, 3.9 Runtime Audit) are implemented, tested, and now demonstrably run together via
  `run_runtime_analysis()`. "Security tests" (the gate's remaining checkbox) were already satisfied by Phase
  3.2's own real-Docker test suite. Every canonical VBG entity Phase 1.2 ever named now has a real, tested
  implementation. **314 passed, 26 skipped, 0 failures project-wide** is the number to beat going into
  Milestone 4.

### 2026-08-20 — Phase 3.7 (Evidence Reconciliation) + Phase 3.8 (Verification State Engine) — 308/308 project-wide
- **Built together deliberately**: 3.8 directly consumes 3.7's `EdgeReconciliation` output to derive
  `CONFLICTED`/`CONDITIONALLY_VERIFIED`, so implementing them in the same pass kept the interface between them
  honest (built against 3.7's real shape, not a guessed one) rather than integrating two independently-designed
  pieces afterward.
- **`src/veyra/vbg/evidence.py`** gained `edge_evidence_key()`/`parse_edge_evidence_key()` -- formalizes the
  "stable edge key" half of Evidence's own WHAT contract (Phase 1.3: "entity_id of the node, or a stable edge
  key"), which Phase 3.5 had already been using ad hoc via a private, duplicate helper in `runtime/engine.py`.
  That private helper is now deleted in favor of the shared one -- format-compatible (verified: the full Phase
  3.5 suite passes unchanged after the swap, 0 regressions). `VBGStore` also gained `get_all_evidence()`
  (mirrors `get_all_nodes`/`get_all_edges`), needed by both 3.7 (all RUNTIME evidence at once) and useful again
  for 3.9's audit below.
- **`src/veyra/reconciliation/engine.py`** — `reconcile_calls(store, repository_version)`. "Preservation/
  sources-identifiable/nothing-silently-deleted" were already true by construction of Phase 1.2/1.3's
  append-only + coexisting-evidence discipline; this function's real contribution is classifying every
  (source, target) CALLS pair as `CONFIRMED` / `STATIC_ONLY` / `RUNTIME_ONLY`. **Only `RUNTIME_ONLY` counts as
  a real conflict** (`.is_conflict`) -- matches PLAN's own example precisely (runtime exercised a path static
  analysis never predicted at all); `STATIC_ONLY` is deliberately NOT a conflict, just "not yet confirmed."
  "Conditional behavior representable" needed zero special-case code: two trials confirming two different
  static edges from the same source just come back as two independent `CONFIRMED` results, directly tested
  (`test_conditional_branching_both_paths_confirmed_independently`). Purely read-only, same discipline as
  Phase 2.7's `summarize_knowledge()` -- never writes to `VBGStore`.
- **`src/veyra/verification/engine.py`** — `derive_verification_states()` (bulk) / `derive_verification_state()`
  (single-entity convenience, recomputes the bulk map each call -- documented as fine for occasional lookups,
  wasteful for many). Per D15, this is a pure derivation from evidence, computed fresh every call, never a
  mutated `Node.status` -- the same discipline every prior "summary" function in this project already
  established. An 8-branch precedence chain (most specific/severe fact wins): `BLOCKED_BY_SAFETY` →
  `CONFLICTED` → `UNEXECUTABLE` → `RUNTIME_VERIFIED`/`RUNTIME_OBSERVED`/`CONDITIONALLY_VERIFIED` (via RUNTIME
  evidence) → `RUNTIME_VERIFIED`/`RUNTIME_OBSERVED` again (via TEST evidence, when no RUNTIME evidence exists
  -- a passing existing test IS real behavioral verification) → `STATICALLY_SUPPORTED` → `UNEXPLORED` (known
  only via an unconfirmed static CALLS edge) → `STRUCTURALLY_IDENTIFIED` (the honest default).
  - **Two states deliberately NOT produced, stated not hidden**: `STALE` needs Phase 4.8 (Git Impact Analysis,
    Milestone 4, not built) -- no cross-commit invalidation signal exists yet to derive it from. `UNANSWERED`
    is Question-specific and already correctly served by Phase 2.6/2.7's own `AnswerStatus` --
    re-deriving it here would duplicate a mechanism that already works, not improve on it.
  - **A stated, accepted coupling**: telling a clean completion from an exception reads the leading
    `status=<VALUE>` token every RUNTIME/TEST `Evidence.detail` this project's own writers (`harness/manager.py`,
    `runtime/engine.py`) already begin with -- `Evidence` itself (Phase 1.3's schema) has no structured outcome
    field, and adding one now was judged out of scope for this slice. `_evidence_status()` is the one place
    this coupling lives, documented plainly rather than silently relied upon.
- **Tests**: 7 new for reconciliation (confirmed/static-only/runtime-only classification, multiple runtime
  observations of the same edge counted correctly, conditional branching, node-level evidence never mistaken
  for an edge, deterministic ordering) + 14 new for verification state (one per named precedence branch, plus
  bulk-coverage-of-every-node and unknown-entity-defaults-to-STRUCTURALLY_IDENTIFIED checks). **308/308
  project-wide, 0 failures** (26 Docker-gated tests skip cleanly, same as prior entries -- neither phase needed
  Docker, both are pure read-side derivations over already-persisted data).
- **M3 gate progress**: "Conflict reconciliation" and "Verification states" line items are now done. Only
  "Multi-run exploration" (already done, Phase 3.6) and "Runtime audit" (3.9, next) remain before the M3 gate
  can close.

### 2026-08-20 — Phase 3.3b (Novel Scenario Synthesis) implemented — 287/287 project-wide
- **Closes out Phase 3.3 fully** (3.3a existing-test tracing + 3.3b novel synthesis, per D2's split) and the
  Harness Manager line item on the M3 gate checklist.
- **A real bug caught before any code was even run**: adding `src/veyra/exploration/conftest.py` (Phase 3.6,
  previous entry) without a `requires_docker` definition broke `tests/runtime/test_engine_docker.py`'s bare
  `from conftest import requires_docker` the moment collection order put `tests/exploration` first -- the exact
  landmine flagged as "worth a real fix if it bites again" back in the Phase 3.4 entry. It bit. Fixed properly
  this time, project-wide, not just patched locally: every bare `from conftest import X` for a
  non-fixture name (6 files: 3 Docker-gated test files, 3 in `tests/safety/`) now defines that helper locally
  instead of importing it. Verified order-independent by running the full suite with `tests/exploration`
  collected first as well as in default order -- 278/278 either way, 0 failures. Separate commit from 3.3b
  itself, since it's an unrelated fix.
- **`src/veyra/harness/synthesis.py`** — `synthesize_novel_scenarios()`. "Zero test coverage" is defined
  directly off evidence this project already produces: no `EvidenceType.TEST` (3.3a) and no
  `EvidenceType.RUNTIME` (3.5/3.6) yet at this commit. "Restricted to SAFE" is real, not just a filter comment
  -- `SafetyClass.SAFE` is only reachable through an explicit per-target policy allowlist (D13), so under the
  default policy this module synthesizes **nothing at all**, proven directly by
  `test_default_policy_synthesizes_nothing`. A caller has to deliberately configure an allowlist before
  anything gets synthesized -- the same conservative posture as everything else in `veyra.safety`.
- **Where the property-based generation happens, and where it deliberately doesn't** -- the real design
  question this phase raised: Hypothesis's own execution/shrinking engine is never run *inside* the sandbox
  (that would mean installing a third-party package into the sandboxed image over network access
  `DockerExecutionBoundary` deliberately never opens, per D17 -- the same category of problem 3.3a's
  `install_policy.py` already declined to solve for arbitrary repo dependencies). Instead: Hypothesis's
  `strategies`/`@given`/`@settings(max_examples=..., database=None)` machinery runs entirely on the HOST to
  generate diverse concrete values for the exact same 5-type primitive boundary Phase 3.4/3.5 already use
  (str/int/float/bool/bytes -- not a wider type surface than the rest of the pipeline supports), and those
  concrete values are handed unmodified to a **new, purely additive** `argument_overrides` parameter on Phase
  3.5's `run_scenario()`. The actual invocation of repository code still always happens exactly where D1
  requires it -- inside the unmodified Phase 3.2 sandbox, through the exact same tracer 3.5 already uses.
  Hypothesis itself is Veyra's own trusted, pinned tooling dependency (added to `pyproject.toml`
  `dependencies`), not a repository dependency -- a categorically different case from what `install_policy.py`
  declines to solve.
  - `_collect_samples()` uses `@given`/`@settings` with a no-op recording body to pull N examples from a
    strategy, not bare repeated `.example()` calls -- Hypothesis explicitly discourages and warns against that
    pattern outside interactive use; this is the idiomatic way to get a bounded example batch programmatically.
  - `run_scenario()`'s new `argument_overrides` param is additive-only: omitting it reproduces Phase 3.5's
    original trivial-zero-literal behavior exactly (re-ran the full Phase 3.5 test suite after the change --
    0 regressions). `tracer_script.py` gained a small, symmetric `kwargs_literal_overrides` spec field (with a
    `{"__bytes_b64__": ...}` marker for the one primitive type JSON can't carry directly) that a name present
    in always wins over the trivial literal for that type tag.
  - Each Hypothesis-generated value combination becomes its own scenario with a distinct `scenario_id`
    (`novel_synthesis|target|commit|trial_index`), so every trial's evidence is independently persisted, never
    conflated with another trial's -- directly tested (`test_allowlisted_zero_arg_function_is_synthesized`
    checks 3 distinct scenario_ids from 3 trials).
- **Tests**: 9 new, all non-Docker (reuses the `FakeExecutionBoundary` substitutability pattern, inspecting
  captured `spec.json` contents directly) -- default-policy-synthesizes-nothing, an allowlisted zero-arg
  function actually running N trials, both TEST-evidence and RUNTIME-evidence coverage skips, an unannotated
  parameter being unsynthesizable, bound methods never even being considered (filtered before the eligibility
  loop, since only `Function`-typed nodes are examined), **real value diversity across trials** (not a fixed
  placeholder -- `len(set(observed_values)) > 1` across 5 draws from a 2,000,001-value integer range, a
  vanishingly small, explicitly acknowledged flake risk), a default-valued parameter never being overridden,
  and a `bytes` parameter round-tripping correctly through the JSON transport. **287/287 project-wide, 0
  failures** (26 Docker-gated tests skip cleanly, same as prior entries -- nothing here needed Docker itself).
- **M3 gate progress**: "Harness manager (3.3a → 3.3b)" line item is now fully done. Remaining M3 gate items:
  conflict reconciliation (3.7), verification states (3.8), runtime audit (3.9) -- security tests were already
  covered by Phase 3.2's own test suite.

### 2026-08-20 — Phase 3.6 (Multi-Execution Exploration) implemented — 278/278 project-wide
- **Continued straight down the M3 dependency chain**: 3.6 is the next natural step after 3.5 (iteratively
  explore using prior observations, per the plan's own text), and now has real RUNTIME evidence from 3.5 to
  check against for "already explored."
- **`src/veyra/exploration/engine.py`** — `explore()` is the shared orchestration core: re-runs Phase 3.4's
  generator fresh to get today's live executable scenarios (same re-derive-don't-trust-a-snapshot discipline as
  3.5), ranks by plain degree centrality (in+out edge count -- an explicitly stated simple proxy, not
  betweenness/eigenvector centrality), skips anything that already carries RUNTIME evidence (whether from a
  prior direct target or an incidental nested-call observation), and calls Phase 3.5's `run_scenario()` on the
  rest until a wall-clock or execution-count budget is hit.
- **`explore_at_ingest(store, repo_root, commit, boundary, file_count)`** implements D10's tiered eager policy
  as real, executable code for the first time (it previously only existed as PLAN.md prose):
  Tier 1 (<50 files) explores everything, 5 min cap; Tier 2 (50-500 files) restricts to the top-50
  centrality-ranked nodes, 30 min cap; **Tier 3 (>500 files) performs zero eager executions, verified directly
  by a test** (`test_explore_at_ingest_tier3_performs_no_eager_execution` -- the boundary's `execute()` is
  never even called).
- **`explore_neighborhood(store, ..., entity_id, max_depth, max_executions, max_wall_clock_seconds)`** — the
  general lazy/query-driven primitive Tier 3's "2 min/20-execution cap per query" describes. Walks *outgoing
  CALLS edges* breadth-first, **deliberately not Phase 2.4's structural CONTAINS children/grandchildren** --
  those are a different relationship entirely (containment, not call graph), and are left completely untouched
  by this module. Re-reading Phase 3.6's own acceptance criterion in that light: "siblings/children/
  grandchildren stay visible" is a **non-regression guarantee inherited for free from Phase 2.4**, not a
  target for 3.6 to itself explore -- confirmed directly by a test proving a CONTAINS-only class member never
  appears as an execution candidate even though it's in the same file. No real caller exists for this function
  yet (Milestone 4's Query-Time Evidence Retrieval, Phase 4.3, isn't built) -- offered as the reusable
  primitive that phase will eventually call, not wired to a fabricated trigger, same deferral discipline as
  Phase 3.3a.
- **Convergence, without a completeness claim**: `ExplorationReport` reports `already_explored_skipped` and
  `attempted` per pass; a caller re-running `explore()` against an unchanged commit sees `attempted` trend
  toward 0 as evidence accumulates -- that's the "convergence measurable" acceptance criterion. The report's
  own docstring is explicit that this is never a completeness/soundness claim ("unreachable code, code behind
  a permanently-false condition, and code no scenario was ever planned for are... simply absent from this
  report"), directly per the AC's own "no completeness claim just because executions stop finding new paths."
- **Two things deliberately NOT built, stated not hidden**: (1) a per-node execution cap (D10's "max 5
  scenarios/executions per node" for Tier 2) has nothing to bound yet, since Phase 3.4 still only generates one
  deterministic scenario per node -- adding a cap now would be dead code; revisit once multi-scenario
  generation (3.3b or later) exists. (2) precise nested-observation counting in `ExplorationReport` (how many
  *incidental* entities got their first evidence this pass, beyond the directly-targeted ones) isn't tracked --
  would need a small API extension to Phase 3.5's `ScenarioExecutionOutcome` that nothing yet needs; the
  already-explored skip still gets the real efficiency benefit from those incidental observations even without
  reporting the count.
- **Tests**: 13 new, all non-Docker (reuses Phase 3.5's `FakeExecutionBoundary` substitutability pattern, with
  real Nodes/Edges from the actual Phase 2.1 extractor rather than hand-built ones, so CALLS edges for
  centrality/neighborhood tests are genuine) -- empty-candidate report, full-repo exploration, candidate-set
  restriction, the already-explored skip (proven via a pre-seeded RUNTIME evidence row), execution-count and
  wall-clock budgets, centrality ordering, all three tiers (Tier 2's top-N cutoff verified via `monkeypatch`
  against a small call chain), call-graph-only neighborhood traversal, `max_depth`, and the neighborhood
  primitive's defaults matching D10's Tier 3 numbers exactly. **278/278 project-wide, 0 failures** (26
  Docker-gated tests skip cleanly, same as the prior three entries -- none Docker-dependent this phase, since
  orchestration logic alone was in scope).
- **Same test-basename collision class caught again, same fix**: `tests/exploration/test_engine.py` collided
  with `tests/runtime/test_engine.py` (both directories independently chose the generic name). Renamed to
  `test_exploration_engine.py`. Confirmed no other collisions exist anywhere in `tests/` (checked directly, not
  assumed).
- **Not started yet**: 3.3b (novel scenario synthesis), 3.7 (Static/Runtime Evidence Reconciliation -- the
  named next consumer of the runtime CALLS-edge evidence 3.5/3.6 together now produce plenty of), 3.8
  (Verification State Engine), 3.9 (Runtime Audit).

### 2026-08-20 — Phase 3.5 (Runtime Trace Engine) implemented — 265/265 project-wide
- **Picked 3.5 over 3.3b again**: 3.5 is the actual executor for the `Scenario` candidates 3.4 now produces,
  and is also what would eventually give 3.3b's own acceptance criteria a real "zero test coverage" signal to
  work from. Same reasoning as the 3.4-over-3.3b choice last entry, one step further down the same dependency
  chain.
- **`src/veyra/runtime/tracer_script.py`** — stdlib-only in-container code (`sys.settrace`, no `coverage.py`)
  that invokes a target function with trivial synthesized primitive arguments and traces every call/return/
  exception whose `co_filename` is under the mounted `/workspace`. A call reaching outside `/workspace` is
  recorded once as a single `external_interaction` event and not traced further inside -- proves a boundary
  was crossed without pretending to observe the other side of it. Entity identity is
  `f"{module.__name__}.{code.co_qualname}"` -- `co_qualname` (Python 3.11+) already renders `Class.method`,
  lining up exactly with the extractor's own `f"{parent_id}.{name}"` entity_id convention with zero extra
  bookkeeping needed on either side.
- **`src/veyra/runtime/engine.py`** — `run_scenario(store, repository_root, repository_version, scenario,
  boundary)` is where a Scenario stops being a plan and becomes an observation. Also closes a deferral Phase
  3.2 itself named: this is the first module to call `store.insert_execution_environment()` for real
  (`DockerExecutionBoundary` deliberately stayed storage-agnostic since it was written).
  - **Re-derives executability from live state** rather than trusting the Scenario's own cached `executable`
    flag -- same discipline Phase 2.6's `verify_question()` established (re-derive, don't replay a stale
    generation-time snapshot). Fetches the current Node, re-runs `extract_signature()`, and re-checks the
    latest persisted classification; a scenario that no longer qualifies (code changed, policy changed) becomes
    UNEXECUTABLE now with a fresh reason, never a silently-forced run of stale intent.
  - **Reconstructs the observed call graph from a flat, time-ordered event list**: `call`/`return` are 1:1 per
    frame even when a frame exits via an exception (CPython still fires `return` with `arg=None` in that case),
    so a simple push/pop stack -- ignoring `exception` events for stack purposes, since they can fire more than
    once per frame as it unwinds through nested handlers -- is enough to derive both which entities were
    genuinely observed and which caller→callee edges were actually exercised.
  - **"Failed execution still counts as evidence" (Phase 3.5 AC), a real interpretive call**: an `EXCEPTION`
    outcome means the target genuinely ran and a real trace came back describing what happened -- that IS a
    runtime observation, persisted as Evidence like any other. A `CONTAINER_EXECUTION_FAILED`/
    `NO_TRACE_REPORTED` outcome (no usable trace at all -- crashed before reaching the target, or timed out) is
    genuinely ambiguous about whether the target was ever reached, so -- matching Phase 3.3a's harness manager
    precedent exactly -- it's treated as UNEXECUTABLE with no evidence, rather than guessing.
  - **Persists the project's first real runtime call-graph evidence**: one `Evidence(RUNTIME)` per genuinely
    observed node, plus one per genuinely observed CALLS edge, keyed by a stable edge string
    (`f"{source}--CALLS-->{target}"`) per Evidence's own WHAT contract ("entity_id of the node, or a stable
    edge key", Phase 1.3). Deliberately NOT reconciled against static CALLS edges here -- whether a runtime
    observation confirms or conflicts with what Phase 2.3 predicted is explicitly Phase 3.7's job, not
    pre-judged in this phase.
  - Argument synthesis stays deliberately trivial -- one fixed zero-value literal (0/""/0.0/False/b"") per
    already-synthesizable primitive parameter Phase 3.4 identified, nothing more. Proves the call executes;
    does not explore the input space. That stays Phase 3.3b's job.
  - Bound methods are never attempted -- Phase 3.4 already refuses to mark any bound method executable, so
    this module carries no constructor/fixture logic at all, not even a stub.
- **Real bug found and fixed by the tests, same session**: the initial `run_scenario()` draft gated on
  `node.type != "Function"` as its very first check, which meant a target that had *become* a bound method
  since scenario generation got the coarse `NO_SOURCE_AVAILABLE` verdict instead of the correct, more specific
  `AMBIGUOUS_INITIALIZATION`. Fixed by accepting both `Function` and `Method` at that first gate (matching
  Phase 3.4's own `_INVOKABLE_TYPES`) and letting `signature.is_bound_method` do the actual, precise branching
  -- caught by `test_bound_method_is_ambiguous_initialization`, left as a permanent regression test.
- **Tests**: 15 new (12 non-Docker via a `FakeExecutionBoundary` -- same substitutability pattern as
  `test_boundary_contract.py`/Phase 3.3a's harness tests -- covering every `RuntimeUnexecutableReason`, real
  classification/environment/evidence persistence, and nested-call edge evidence from a hand-built trace; 3
  real-Docker end-to-end tests proving a genuine nested-call trace with correct entity/edge evidence, a genuine
  captured exception, and a genuine `external_interaction` event from a real network call that Phase 3.2's
  unmodified `--network none` actually blocks). **265/265 project-wide, 0 failures** (26 Docker-gated tests
  skip cleanly in this sandbox: 21 Phase 3.2 + 2 Phase 3.3a + 3 Phase 3.5, none re-proven against a live
  daemon this session, same stated caveat as the prior two entries).
- **Not started yet**: 3.3b (novel scenario synthesis -- now has a real, if still narrow, coverage signal it
  could use: which entity_ids Phase 3.5 has already produced RUNTIME evidence for), 3.6 (Multi-Execution
  Exploration, tiered budgets already specified as D10), 3.7 (Static/Runtime Evidence Reconciliation -- the
  explicit next consumer of the runtime CALLS-edge evidence this phase now produces), 3.8 (Verification State
  Engine), 3.9 (Runtime Audit).

### 2026-08-20 — Phase 3.4 (Behavioral Scenario Generator) implemented — 253/253 project-wide
- **Chose 3.4 over 3.3b for this slice**: both were reasonable "go ahead" next steps after 3.3a. 3.3b (novel
  input synthesis via Hypothesis) has a real dependency this project hasn't built yet -- knowing "zero test
  coverage" needs per-node execution tracing, which is Phase 3.5's job, not built. 3.4 doesn't have that
  entanglement (it plans candidate scenarios from static knowledge + Phase 3.1 classification, nothing
  dynamic), matches the plan's own stated milestone order, and closes out `Scenario` -- the last of Phase 1.2's
  originally-deferred canonical entities.
- **`src/veyra/vbg/scenarios.py`** — `Scenario` finally defined (deferred since Phase 1.2), same
  shape-lives-in-vbg pattern as Question/ClassificationResult/ExecutionEnvironment. A Scenario is a *candidate
  for runtime observation*, not an execution or its outcome -- it's meant to become the scenario_id a future
  RUNTIME Evidence record points at once Phase 3.5 actually runs it. `__post_init__` structurally enforces
  "unsupported scenarios → unexecutable": a non-executable Scenario cannot be constructed without both an
  `unexecutable_reason` and an explanatory `detail`, and an executable one cannot carry a reason at all.
- **`src/veyra/scenarios/introspection.py`** — `extract_signature(node)`, pure, re-parses
  `Node.lexical_representation` via `ast` (same technique `veyra.safety.capabilities` already uses on the same
  field) to determine a function/method's parameters and whether each has a synthesizable value: a small
  primitive-annotation allowlist (str/int/float/bool/bytes) or an existing default. Deliberately narrow --
  this phase only decides whether a candidate scenario is *plannable* at all; it does not synthesize actual
  values (that stays 3.3b's job, restricted to SAFE-classified targets per D2, whenever it gets built).
- **`src/veyra/scenarios/generator.py`** — `generate_scenarios(store, repository_version, policy=None)`. One
  candidate scenario per Function/Method node: "directly invoke this with zero/default/synthesizable-primitive
  arguments" -- deliberately the simplest possible scenario shape; multi-call sequences, exception-injection,
  and constructed-fixture scenarios are explicit non-goals for this slice, not oversights.
  - **Reuses Phase 3.1's `classify_and_audit()` exactly as-is** (same precedent as Phase 3.3a's harness
    manager) so every scenario's `safety_class` is backed by a real, persisted classification decision, not an
    unearned claim. A scenario is `executable=True` only when source was available to introspect, the
    classification is not `BLOCKED`, the target isn't a bound method (no constructor/fixture strategy exists
    yet to obtain an instance -- `AMBIGUOUS_INITIALIZATION`), and every parameter is synthesizable (else
    `MISSING_FIXTURE`); otherwise `NO_SOURCE_AVAILABLE` when there's no lexical_representation to begin with.
  - **`Scenario.dependencies` is deliberately left empty** in this slice -- no consumer needs it populated yet;
    the natural source (the target's own outgoing CALLS/IMPORTS edges) is a stated, not-hidden follow-up.
  - **Determinism**: `scenario_id` is a stable hash of `(target_entity_id, repository_version)` only, matching
    Phase 2.5's Question identity discipline -- regenerating against an unchanged commit and policy is
    byte-identical. Regenerating under a *different* policy can legitimately produce different
    executable/safety_class content at the *same* scenario_id -- handled the same way Node/Edge already handle
    conflicting writes (kept as history, not overwritten), not a new mechanism.
- **`VBGStore`** gained `insert_scenario`/`get_scenario_history`/`get_latest_scenario`/`get_scenarios` (current
  view: latest row per scenario_id), same append-only + current-view discipline as everything else.
- **Tests**: 37 new (12 introspection: primitive/defaulted/complex/kwonly/varargs/bound-method parameter
  handling, unparsable/missing source; 10 generator: every unexecutable reason plus determinism, real
  classification persistence, non-invokable node types skipped; 8 Scenario model validation; 7 storage
  round-trip + conflict-preservation). **253/253 project-wide, 0 failures** (23 Docker-gated tests skip
  cleanly in this sandbox, same as the prior entry).
- **Real, pre-existing bug found and fixed while adding these tests**: a bare `from conftest import X` inside a
  test module is unsafe across this project's `tests/` tree -- with no `__init__.py` anywhere, pytest's default
  import mode caches whichever directory's `conftest.py` loads first under the single module name `"conftest"`,
  so a same-named import from a *different* test directory can silently resolve to the wrong file. This had
  been silently working project-wide only by coincidence (every existing `from conftest import X` happened to
  reference names that were either unique or redundantly-but-compatibly defined across colliding directories).
  My first draft of `tests/scenarios/` hit a real `ImportError`/module-identity failure both ways (importing
  `COMMIT`/`make_node` from a same-named-but-different conftest, and a `test_generator.py` basename collision
  with the pre-existing `tests/questions/test_generator.py`, the same class of bug Phase 3.1 already hit once
  for `test_audit.py`). Fixed by defining `make_node`/`COMMIT` locally in each of the two new test files
  instead of importing them, and renaming to `test_scenario_generator.py`/`test_scenario_introspection.py`.
  Not fixed project-wide (out of scope for this slice) -- this remains a latent landmine anywhere a *new* test
  file's `from conftest import X` happens to collide with an existing one; worth a real trigger-based follow-up
  (e.g. add `__init__.py` throughout `tests/` and switch to qualified imports) if it bites again.
- **Not started yet**: 3.3b (novel scenario synthesis for SAFE-classified, zero-coverage functions), 3.5
  (Runtime Trace Engine -- the actual executor for these `Scenario` candidates, and the source of real
  coverage data 3.3b will eventually need).

### 2026-08-20 — Phase 3.3a (Harness & Fixture Manager — existing-test tracing) implemented — 217/217 project-wide
- **Scope, per D2**: this is only 3.3a (trace the repository's *existing* test suite, low risk/high yield).
  3.3b (novel scenario synthesis via Hypothesis, SAFE-only) is separate, not-yet-built work — nothing here
  attempts to generate new inputs for untested code.
- **`src/veyra/harness/discovery.py`** — `discover_tests(repository_root)`, pure AST-based discovery of
  pytest-convention tests (`test_*.py`/`*_test.py` files; module-level `def test_*` functions; `Test*`-prefixed
  classes with `def test_*` methods, covering unittest.TestCase without needing to resolve base classes).
  entity_id is built with the exact same convention Phase 2.1's extractor uses
  (`compute_module_id` + `f"{parent_id}.{name}"`), so every discovered test's identity lines up with the Node
  the extractor already persisted for it — no separate identity scheme to reconcile. Explicitly out of scope:
  pytest fixtures/parametrize/conftest.py (need pytest itself, a third-party dependency) and async tests.
- **`src/veyra/harness/dependencies.py` + `install_policy.py`** — the Dependency Inspection → Installation
  Policy stages of the "dependency installation is a security operation" pipeline the user's M3 spec called for
  (PLAN.md Phase 3.2 note). Inspection parses `requirements.txt` and `pyproject.toml` (via stdlib `tomllib`,
  no new dependency) into a declared-package set, never executing or resolving anything. **Policy is
  deliberately conservative, matching D13/D14's precedent**: a repository needing only the standard library is
  `SUPPORTED`; ANY third-party dependency makes the whole harness run `UNSUPPORTED_ENVIRONMENT` — installing
  arbitrary packages executes arbitrary setup/build code with network access, a materially harder security
  problem than running already-sandboxed code, and building that pipeline for real (reviewed
  allowlist/registry-pinning, network-scoped-only-during-install) is explicitly future work, not attempted here.
  This is a real, stated scope boundary (same honesty pattern as Phase 2.2's Emerge assessment), not a silent gap.
- **`src/veyra/harness/runner_script.py` + `manager.py`** — `run_existing_test_harness(store, repository_root,
  repository_version, boundary)` orchestrates: discover → inspect dependencies → Installation Policy gate →
  Safety Gate (Phase 3.1's `classify_and_audit()`, reused as-is; only a `BLOCKED` verdict excludes a test from
  the run — everything else still only ever executes inside the boundary regardless of class, per D1) → execute
  inside `ExecutionBoundary` (Phase 3.2, unmodified — `DockerExecutionBoundary` needed zero changes, which is
  D16's "runtime verifier depends only on the interface" claim holding up in practice) → persist one
  `Evidence(EvidenceType.TEST)` row per test that actually produced a real outcome. **Closes the loop on
  `EvidenceType.TEST`**, defined in Phase 1.3 and unused until now.
  - The in-container runner (`runner_script.py`) is **stdlib-only by construction** (no `pytest`) — this is
    exactly what lets 3.3a harness a no-third-party-dependency repo without needing the installation pipeline
    it declines to build. Bare `def test_x(): assert ...` functions are called directly with `AssertionError`
    caught by hand; `unittest.TestCase` methods run through `unittest`'s own per-instance `run()`. Communicates
    via JSON files on the mounted output directory (`spec.json` in, `results.json` out), not stdout-scraping —
    reuses the same read-write-output-mount behavior Phase 3.2's own tests already proved lands on the host.
  - **"Failed harness creation never becomes a successful behavioral claim" (Phase 3.3 AC) is structural, not
    conventional**: TEST evidence is only ever written from a genuine PASS/FAIL/ERROR entry in a real
    `results.json` produced by a container that actually completed. Every other path — dependency-unsupported,
    no static node found, BLOCKED by safety, container failure/timeout, missing/corrupt results.json, or even
    an unrecognized status string inside an otherwise-valid results.json — returns an explicit `UNEXECUTABLE`
    `TestOutcome` with a `reason`, and writes no evidence at all. 8 of the 9 `_execute()`/manager tests exercise
    one of these failure paths directly (not just the happy path).
  - **Known, stated limitation**: one container runs the whole selected test batch sequentially under a single
    combined timeout, not a per-test timeout — a single hung test times out the entire batch. Kept simple for
    this first slice; per-test isolation is a natural follow-up once this runs against real repositories.
- **Tests**: 25 non-Docker tests (discovery, dependency parsing, install policy, and manager orchestration via a
  `FakeExecutionBoundary` — same substitutability pattern `test_boundary_contract.py` established for Phase
  3.2 — covering the dependency gate, the safety gate, evidence persistence on PASS/FAIL, and every
  `UNEXECUTABLE` path including container failure and a malformed results record) + 2 real-Docker end-to-end
  tests (`test_manager_docker.py`, `requires_docker`) proving genuine PASS/FAIL/ERROR round-trips through a live
  container and that `--network none` (Phase 3.2, unmodified) is what actually stops a real network call, not
  the safety classifier. **This session's sandbox has no reachable Docker daemon** (CLI present, `dockerd`
  cannot start under this container's restrictions) — the 2 Docker tests are confirmed to skip cleanly via the
  same `requires_docker` marker Phase 3.2 uses, but were not re-proven against a live container this session;
  they were exercised in the same style Phase 3.2's 26 Docker tests were, and remain here to run for real the
  next time a session has a working daemon.
- **217 passed, 23 skipped** project-wide in this session's (non-Docker) environment — 0 failures. The 23 skips
  are all Docker-gated (21 pre-existing Phase 3.2 tests + the 2 new Phase 3.3a tests above), skipped via the
  same `requires_docker` marker, not failures.
- **Not started yet**: 3.3b (novel scenario synthesis), 3.4 (Behavioral Scenario Generator), 3.5 (Runtime Trace
  Engine — the actual node-level `sys.settrace`/coverage instrumentation layer; 3.3a deliberately stops at
  test-level PASS/FAIL/ERROR evidence, not per-node execution tracing, which is 3.5's job).

### 2026-08-20 — Phase 3.2 (Execution Boundary) implemented with REAL Docker — 212/212 project-wide
- **Set up git for the first time this session**: `veyra` had never been a git repo. Initialized with `main` as
  the default branch, created `milestone-1-2-and-m3-phase-3.1`, committed all of M1/M2/Phase-3.1 there (one
  commit, 181/181 passing), merged into `main`. Since `main` had zero prior commits, git resolved this as a
  fast-forward rather than a two-parent merge commit — the honest outcome given there was no divergent history
  to merge, not a shortcut.
- **Docker Desktop was installed but stopped** (the `docker-desktop` WSL distro existed but wasn't running, and
  the `docker` CLI wasn't on this session's PATH — same PATH-snapshot issue seen earlier with the `claude` CLI).
  Located it at `%LOCALAPPDATA%\Programs\DockerDesktop`, launched it, waited for the daemon, and added its
  `resources\bin` to `PATH` for this session so the Python subprocess calls could resolve `docker`. Pulled
  `python:3.11-alpine` as the test image.
- **`src/veyra/execution/`**: `ExecutionBoundary` (`typing.Protocol`), `ExecutionRequest`/`ExecutionHandle`/
  `ExecutionOutcome`/`ExecutionStatus`, `DockerExecutionBoundary`. Every `docker run` unconditionally applies:
  `--network none`, `--memory`/`--memory-swap` caps, `--cpus`, `--pids-limit`, `--read-only` root filesystem with
  a size-capped `/tmp` tmpfs as the only writable location, `--cap-drop ALL`, `--security-opt no-new-privileges`,
  `--user 65534:65534` (never root). Never `--privileged`, never a host Docker socket mount, never more than the
  caller-specified working/output directories mounted.
- **All 26 Docker-backed tests are real** (not string-matched): network isolation (an actual outbound connection
  attempt from inside the container fails), filesystem isolation (an actual write outside `/tmp` fails; the
  mounted working directory is genuinely read-only; the output directory is genuinely read-write and content
  lands back on the host), memory limit (an actual 400MB allocation under a 64MB cap gets OOM-killed), CPU/pids
  limits (verified via real `docker inspect` on the live container, not just checking the args list this code
  built), timeout (an actual `sleep 30` gets force-terminated within ~2s, confirmed via `docker inspect` showing
  `Running: false` afterward), cleanup (the container is verified gone via `docker inspect` failing, both after
  normal completion and after a timeout), and environment isolation (a host env var set via `monkeypatch` is
  confirmed absent inside the container; only an explicitly-passed var is visible).
- **`ExecutionEnvironment`** (`vbg/execution.py`) — the entity Phase 1.2 deferred to M3, and the real referent
  of `Evidence.environment_id`, which has existed unused since Phase 1.3. Now has a concrete shape and an
  append-only `VBGStore` table (`insert_execution_environment`/`get_execution_environment_history`/
  `get_latest_execution_environment`), satisfying "container configuration is auditable" directly.
- **`DockerExecutionBoundary` deliberately does not touch `VBGStore`** — same pure-mechanism-vs-explicit-persist
  split as Phase 3.1's `classify()`/`classify_and_audit()`. Wiring execution results into real Evidence/
  `ExecutionEnvironment` persistence together is Phase 3.5's job (the actual runtime-verifier caller); building
  that wiring now, with no real caller yet, would be the same kind of premature scaffolding avoided everywhere
  else in this project.
- **Known limitation, stated not hidden**: CPU throttling itself isn't behaviorally proven (that would need a
  slow, timing-sensitive saturation test) — the test instead confirms the `--cpus` flag actually reaches the
  live container's `HostConfig.NanoCpus` via `docker inspect`, which is a real, direct proof that configuration
  was applied, short of a slower behavioral timing test.
- **Docker's own security boundary is not re-verified here** (D17 still applies): a kernel/Docker-level container
  escape is out of scope for what application-level flags can prove; this hardens everything practical at the
  `docker run` layer.

### 2026-08-20 — Milestone 3 started: Phase 3.1 (Execution Classification) implemented, then stopped as instructed
**181/181 tests passing project-wide (43 new). M1/M2's 138 unaffected — confirmed via full-suite rerun.**

- **User supplied a much more detailed, corrected M3.1 design** than my own initial proposal: instead of one
  AST-pattern → verdict function, three architecturally separate layers (Capability Detection → Policy
  Evaluation → Safety Classification), because static analysis can identify *potential* capabilities but can
  never determine the actual runtime environment (`requests.post(...)` doesn't prove prod/staging/local). This
  is a real improvement over what I'd have built — adopted as-is. See PLAN.md D12–D17.
- **`src/veyra/vbg/safety.py`**: `Capability` (13-value vocabulary), `SafetyClass` (5 values, semantics
  documented per-value in the enum's own docstring), `RiskLevel`, `ClassificationResult`. Put in `vbg`, not
  `safety/`, for the same circular-import reason `Question`/`Answer` moved there in Phase 2.7 — got this right
  the first time this round instead of needing a mid-flight fix.
- **`src/veyra/safety/capabilities.py`**: `detect_capabilities(node)`, pure, re-parses
  `Node.lexical_representation` (Phase 2.1) via `ast`. Zero `SafetyClass` knowledge. A fixed dotted-call-pattern
  table; anything unrecognized (and not a ~25-name allowlist of inert builtins) becomes
  `UNKNOWN_EXTERNAL_EFFECT` rather than silently producing no signal.
- **`src/veyra/safety/policy.py`**: `resolve_safety_class()`, pure, zero AST knowledge. Precedence when multiple
  capabilities are present: most-restrictive-wins (`BLOCKED > UNKNOWN > MOCKABLE > SANDBOXABLE > SAFE`),
  documented explicitly in the module docstring per the instruction not to invent precedence silently.
  **`SAFE` is reachable only via an explicit per-target allowlist in `PolicyConfig`** — never derived from an
  empty capability set (that gets `SANDBOXABLE`). An allowlist entry can only *grant* SAFE when nothing else
  contradicts it; a live BLOCKED/MOCKABLE/UNKNOWN-implying capability always overrides the allowlist, never the
  reverse — tested directly (`test_allowlist_does_not_override_a_live_blocked_finding`).
- **`src/veyra/safety/classification.py` + `audit.py`**: `classify()` stays pure (no `VBGStore` access, easy to
  reason about in isolation); `classify_and_audit()` is the *only* function in the whole package that touches
  storage, persisting every decision append-only via a new `VBGStore.insert_classification()` /
  `get_classification_history()` (a new table, not crammed into Phase 1.5's `AuditRecord` — that record's shape
  fits phase-timing audits, not decision audits with target/capabilities/reason, so reusing it directly would
  have been the wrong kind of reuse despite the instruction to reuse existing infra).
- **Real, meta test**: `test_no_execution_capability_anywhere_in_safety_package` reads the `safety` package's
  own source and walks its AST, asserting no real `subprocess`/`eval`/`docker` call or import exists anywhere
  in it (string literals in the pattern tables don't count — only genuine `ast.Call`/`ast.Import` nodes do).
  Directly proves "no execution capability exists in Phase 3.1" rather than just asserting it in a docstring.
- **Environment finding**: Docker + WSL2 were installed on this machine mid-session specifically so Phase 3.2's
  container tests can exercise real behavior later, per the instruction not to fake Docker-string-assertion
  tests. Not used anywhere in Phase 3.1 itself (zero Docker dependency, as instructed).
- **Real naming-collision bug caught by the test run itself**: `tests/safety/test_audit.py` collided with the
  pre-existing `tests/audit/test_audit.py` — neither test directory has `__init__.py`, so pytest's default
  import mode couldn't tell the two same-named modules apart ("import file mismatch"). Renamed to
  `test_classification_audit.py`. Confirmed no other basename collisions exist anywhere in `tests/`.
- **Stopped here deliberately** — explicit instruction: "Do NOT proceed into Phase 3.2 automatically." Next
  actual work is Phase 3.2 (Execution Boundary / `DockerExecutionBoundary`), on hold pending go-ahead.

### 2026-08-20 — Milestone 2 (Deterministic Static Knowledge) FULLY CLEARED — Phases 2.7, 2.8 + a mid-flight refactor
**138/138 tests passing project-wide (17 new).**

- **Architecture fix before continuing**: `Question`/`Answer` were originally defined inside the `questions`
  package, but Phase 1.2 names them as canonical VBG entities, and `VBGStore` now needed to persist them —
  which would have made `vbg` depend on `questions` while `questions` already depends on `vbg` (circular
  import). Moved the model definitions into `vbg/questions.py` (data shape lives with the other canonical
  entities: Node/Edge/Evidence/Repository/Audit/Question/Answer, all in one package); `veyra.questions` now
  holds only the *logic* (generator, verifier, knowledge arms) that operates on/produces them, mirroring how
  `veyra.static_analysis` is the logic layer for Node/Edge. All 121 then-existing tests still passed unchanged
  after the move — confirms the refactor didn't change behavior, only where things live.
- **New `VBGStore` capability**: Questions and Answers are now actually persisted (`insert_question`/
  `get_questions`, `insert_answer`/`get_answer_history`/`get_latest_answer`), same append-only discipline as
  everything else. Before this, `generate_questions`/`verify_question` only returned in-memory objects — Phase
  2.7's "unanswered questions remain queryable" would have been false without real storage behind it.
  `verify_question` (Phase 2.6) now persists its `Answer` unconditionally (ANSWERED or not), in addition to the
  STATIC evidence it already wrote for ANSWERED results.
- **Phase 2.7 — Verified/Unverified Knowledge Arms.** `src/veyra/questions/knowledge_arms.py`:
  `summarize_knowledge()` splits nodes into verified/unverified by checking `has_evidence()` directly — **not**
  by trusting a node's `VerificationState` label — which is what makes "unknown is never silently converted to
  verified" a real, tested guarantee rather than a naming convention (`test_unknown_is_never_silently_verified_by_status_label`
  proves every node defaults to `STRUCTURALLY_IDENTIFIED` yet still starts in the unverified arm). Questions get
  the same treatment via their latest persisted `Answer`. 6 new tests.
- **Phase 2.8 — Static Audit, plus the Milestone 2 entry point.** `src/veyra/pipeline.py`:
  `run_static_analysis(store, repo_root, commit)` is the first single call that runs the *whole* M2 pipeline
  (extract → persist → generate questions → persist → verify every question) and returns a `StaticAuditReport`
  — Milestone 2 didn't have one entry point tying Phases 2.1–2.7 together until now, even though each phase was
  independently tested. Counts (files analyzed/failed, node/edge counts, edges-by-relationship-type, questions
  generated/answered/unanswered, static evidence created) are all real, taken directly from what the run
  produced. `questions_deduplicated` is always `0` — documented as a real fact, not a gap: the generator
  prevents duplicates by construction (a guard check before a `Question` object is ever built), so there is
  nothing to deduplicate after the fact. `static_precision`/`static_recall` are `None` per D6, not computed —
  they need Milestone 5 ground truth. 4 new tests, run against a fixture repo that deliberately includes one
  file with a syntax error, so the report's `files_failed`/`unsupported_rate` numbers are exercised for real.

**Milestone 2 gate cleared.** Every phase (2.1 static extraction, 2.2 Emerge assessment, 2.3 structural VBG +
cross-module resolution, 2.4 neighborhood model, 2.5 question generation, 2.6 static verification, 2.7
verified/unverified arms, 2.8 static audit) is implemented, tested, and wired into one working pipeline.

### 2026-08-20 — Phase 2.5 (Question Generator) + Phase 2.6 (Static Verification) implemented
**121/121 tests passing project-wide (28 new).**

- **New `VBGStore` bulk-read methods**: `get_all_nodes(commit)` / `get_all_edges(commit)` — the "current view"
  (latest row per entity/edge key) over the *whole* graph, not just one entity — needed since the question
  generator has to walk every node, not look one up. 3 new tests.
- **`src/veyra/questions/` package** — new home for `Question`/`Answer`, the two canonical entities Phase 1.2
  named but explicitly deferred (see that phase's scope note) until the phase that actually specifies their rules.
  - **`generator.py` (Phase 2.5)**: `generate_questions(store, commit)`, template-based, zero LLM involvement.
    9 of the plan's 10 categories implemented (SYMBOL, STRUCTURAL, RELATIONSHIP, DEPENDENCY, CALL_FLOW×2,
    INHERITANCE×2, REFERENCE, NEIGHBORHOOD, LEXICAL). **OCCURRENCE deliberately not generated**: `occurrence_count`
    is never populated by the Phase 2.1 extractor, so every such question would have the same trivial "0" answer
    for every node — generating a real-looking question with a structurally meaningless answer would be worse
    than not generating it; documented in the module docstring as a scope decision tied to a concrete trigger
    (populate occurrence_count first). Every template is guarded by "is there a real, non-empty fact to ask
    about" — this is what satisfies "unsupported constructs do not generate false questions." Dedup +
    determinism come from a single `(category, template_key, primary_entity_id)` key checked before a question
    is ever constructed, so literal duplicates can't occur, and `question_id` is a stable hash of that same key
    — regenerating against an unchanged commit is byte-identical (tested). 14 new tests, built against a
    realistic graph produced by the real extractor (not hand-crafted nodes/edges).
  - **`verifier.py` (Phase 2.6)**: `verify_question(store, question)` **re-derives** the answer from live
    `VBGStore` state rather than replaying what was true at generation time — this is what makes it
    verification, not an echo, and is what lets a genuinely stale/unrecognized question come back `UNANSWERED`
    instead of always trivially succeeding by construction. Only `ANSWERED` results get evidence attached, and
    every evidence record it writes is `EvidenceType.STATIC` by construction (the function has no
    scenario_id/environment_id parameter to even accept RUNTIME evidence through) — directly satisfies "static
    verification cannot become runtime verification." 8 new tests.
  - **Real bug caught by a test, fixed same session**: `test_all_generated_questions_are_answerable` (Phase 2.6
    test file) found that `generate_questions()`'s STRUCTURAL template was emitted unconditionally for every
    Module/Class/Function/Method node, *without* checking whether it actually had any CONTAINS children —
    every other category correctly skipped emission when its edge list was empty, but STRUCTURAL didn't, so a
    leaf method like `validate_order()` got a "What does `validate_order` contain?" question with no real
    answer. Fixed in `generator.py` by adding the same `if children:` guard every other template already had.
    Left as a permanent regression test.

### 2026-08-20 — Phase 2.4 (Neighborhood Model) implemented
**97/97 tests passing project-wide (14 new).**

- **New `VBGStore` graph-query primitives**: `get_outgoing_edges(source_id, commit)` /
  `get_incoming_edges(target_id, commit)` — the "current view" of every distinct (other-side, relationship_type)
  pair, deduped by latest `row_id` (same "latest wins for the current view, full history stays queryable
  separately" pattern already used by `get_latest_node`/`get_latest_edge`). This closes the "graph traversal...
  deferred to Phase 2.3/2.4" note from the Phase 1.2 entry. 5 new tests.
- **`src/veyra/vbg/neighborhood.py`**: `get_parents`/`get_children`/`get_siblings`/`get_grandchildren` (all
  defined strictly via `CONTAINS` edges — the structural containment tree, not general graph adjacency),
  `get_descendants(store, entity_id, commit, max_depth)` for the plan's "configurable depth" criterion (children
  and grandchildren are just its depth=1/depth=2 special cases, kept as their own named functions since the
  plan names them individually), and `get_neighborhood()` bundling all of the above plus full incoming/outgoing
  edge lists (every relationship type, not just CONTAINS) into one `Neighborhood` result. 9 new tests, including
  one proving CALLS edges show up in incoming/outgoing without being mistaken for structural parent/child
  relationships, and one proving a root node's empty `parents`/`siblings` lists are a real "queried, found
  nothing" result rather than an error — the concrete meaning of "unobserved relationships remain identifiable
  as unobserved" here.

### 2026-08-20 — Phase 2.2 (Emerge assessment) + Phase 2.3 (cross-module resolution) implemented
**83/83 tests passing project-wide (6 new).**

- **Phase 2.2 — Emerge Integration Assessment.** [docs/emerge_compatibility_report.md](docs/emerge_compatibility_report.md).
  No "Emerge" tool is available anywhere in this environment to actually run or inspect, so this is explicitly
  flagged as a **desk assessment from general knowledge, not verified against real tool output** — the report
  says so at the top rather than presenting inference as fact. Per D9, this stays non-blocking; nothing else
  depends on it. If the user has the actual tool in mind, pointing to real output on a sample repo would let
  this get finished properly.
- **Phase 2.3 — Structural VBG Construction, cross-module relationships.** Extended
  [python_extractor.py](src/veyra/static_analysis/python_extractor.py) with a repository-wide second pass:
  each file's `from X import Y [as Z]` bindings are now recorded (`import_aliases`), and CALLS/INHERITS/
  REFERENCES that a single file couldn't resolve on its own (`unresolved: list[UnresolvedReference]`) get a
  second try in `extract_repository()` against the full repo's known entity IDs. This is what makes "cross-module
  relationships are supported" (Phase 2.3 acceptance criterion) genuinely true rather than aspirational — 5 new
  tests cover cross-module CALLS, CALLS via an alias (`import X as Y`), INHERITS, and REFERENCES, plus a test
  confirming module-qualified attribute calls (`requests.get(...)`) are honestly left unresolved rather than
  guessed at (that remains a documented, deliberate scope boundary, not a bug).
  Also added a direct test for "cycles are supported" (mutual recursion, both CALLS edges present) — nothing in
  storage or extraction prevents or collapses a cycle, but this was previously an implicit claim rather than a
  tested one.
  The other Phase 2.3 acceptance criteria (deterministic per commit, unique node identity, typed relationships,
  graph reconstructable) were already satisfied by Phase 2.1 + Phase 1.2's storage layer — this slice's real
  contribution is specifically closing the cross-module gap.

### 2026-08-20 — D4 symbol-level diff closed out; lexical_representation gap fixed
**77/77 tests passing project-wide (8 new).**

- **Gap found and fixed first**: Phase 2.1's extractor never populated `Node.lexical_representation`, even
  though it's explicitly in the plan's construct list and schema. Fixed in
  [python_extractor.py](src/veyra/static_analysis/python_extractor.py) via `ast.get_source_segment()` for
  Class/Function/Method/Variable nodes (Module is left unset — its "lexical representation" would just be the
  whole file, already covered by file-level git tracking). One new test
  (`test_lexical_representation_is_populated`) locks this in.
- **`src/veyra/git_tracking/symbol_diff.py`**: `diff_symbols(old_nodes, new_nodes)` — the actual D4 comparison
  algorithm, hashing `lexical_representation` per entity_id. A node's "signature" is approximated as the first
  line of its lexical text (documented heuristic, not full parsing); Variable nodes have no signature/body
  distinction, so any change is `MODIFIED_BODY`. Tests build realistic before/after Node lists using the real
  Phase 2.1 extractor (not hand-crafted Node objects), which also serves as an extractor/symbol-diff
  integration check. All 5 D4-named change types covered, plus a class-signature-change case.
  **Deliberately not built**: the orchestration to check out two arbitrary live commits and extract both —
  that belongs to Phase 4.8 (Git Impact Analysis), the diff's actual named consumer per D4's own text. Building
  that plumbing now, with no caller yet, would be exactly the speculative scaffolding this project has
  otherwise avoided.
- PLAN.md's Milestone 1 Gate updated: fully cleared, no more carry-forwards.

### 2026-08-20 — Milestone 2 started: Phase 2.1 (Static Repository Analysis, Python) implemented
`src/veyra/static_analysis/`: a real Python AST-based extractor producing actual `veyra.vbg.Node`/`Edge`
instances (not a placeholder). **69/69 tests passing project-wide (11 new).**

- **Two-phase design (collect, then resolve)**: a single AST traversal collects every Class/Function/Method/
  Variable definition into Nodes plus CONTAINS/IMPORTS edges, while deferring CALLS/INHERITS/REFERENCES
  resolution into pending lists. Only after the full file's symbol table is complete are those pending edges
  resolved. This matters concretely: `self.validate_order()` inside `process_order` resolves correctly even
  when `validate_order` is defined *later* in the same class — a single-pass design would have missed it, since
  Python allows methods to call sibling methods regardless of definition order (unlike module-level functions,
  which do need prior definition). `test_calls` asserts this directly.
- **Explicitly scoped, not silently incomplete**: same-file symbol resolution only (no cross-file/cross-module
  CALLS or INHERITS) — a call to an unresolved name increments `ExtractionResult.unresolved_calls` rather than
  guessing or vanishing, which is what satisfies "unsupported constructs are explicitly recorded" honestly.
  `IMPLEMENTS` and `DEPENDS_ON` (2 of the 8 closed `RelationshipType` values from Phase 1.2) are not produced by
  this extractor at all yet: `IMPLEMENTS` doesn't map cleanly onto Python; `DEPENDS_ON` is the plan's own
  service/class-level aggregate concept, which would need to be inferred from CALLS/IMPORTS rather than read
  directly off syntax. `REFERENCES` is intentionally narrow — only type annotations (parameters, return types,
  annotated assignments) resolved to a same-file symbol, not general name-load tracking.
- **Package nodes not built.** Phase 2.1's prose lists packages as extractable, but they're not in the phase's
  *required test list*, so this was scoped out rather than guessed at — every file maps directly to a Module
  today, with no intermediate package hierarchy. Straightforward, well-understood follow-up (directory + 
  `__init__.py` walk) whenever it's actually needed downstream.
- **Duplicate symbols**: two definitions of the same name in the same scope produce two separate Node entries
  with the same `entity_id` — extraction doesn't merge or drop either one. This is exactly what Phase 1.2's
  append-only storage was built to hold (`test_duplicate_names` proves this at the extraction level;
  persisting both through `VBGStore.insert_node` was already proven safe by the Phase 1.2 storage tests).
- All 8 of Phase 2.1's required test categories that apply to a single language pass (classes, methods,
  functions, imports, calls, inheritance, references, nested structures, duplicate names). "Multiple languages"
  is out of scope per D5 (Python-only until the pipeline clears M5) and was not attempted.
- `persist.py` deliberately kept separate from the extractor: extraction has no storage dependency and is
  tested without a database; `persist_extraction(store, result)` is a thin, separately-tested loop over
  `insert_node`/`insert_edge`.

### 2026-08-20 — Milestone 1 (Core Substrate) gate cleared — Phases 1.3, 1.4, 1.5 implemented
Ran continuously through the rest of M1 per the user's go-ahead. **58/58 tests passing project-wide.**

- **Phase 1.3 — Evidence & Provenance.** `src/veyra/vbg/evidence.py`: `EvidenceType` (5-value enum, exactly the
  plan's vocabulary), `Provenance`, `Evidence`. Evidence's WHAT/WHERE/WHEN/HOW/COMMIT/SCENARIO/ENVIRONMENT
  fields map onto `subject_id`/`location`/`provenance.recorded_at`/`evidence_type`+`provenance.method`/
  `repository_version`/`scenario_id`/`environment_id` respectively (mapping documented in the module
  docstring). `RUNTIME` evidence is rejected in `__post_init__` unless both `scenario_id` and `environment_id`
  are set — a direct, executable version of "runtime evidence references a scenario [and] an execution
  environment." Storage: a fourth append-only table on the same `VBGStore` (one canonical VBG database, per
  the "Canonical VBG" concept — not a separate evidence store). Multiple evidence records for the same subject
  are treated as coexisting supporting observations, not competing versions, matching Phase 3.7's later
  reconciliation model. 16 new tests, including the 5 the plan names explicitly (missing provenance, missing
  commit, runtime evidence without scenario, evidence versioning, historical evidence retrieval).
- **Phase 1.4 — Git Version Tracking (file-level only).** `src/veyra/git_tracking/`: `ChangeType`
  (ADDED/MODIFIED/DELETED/RENAMED/UNCHANGED), `FileChange`, `diff_commits()` (shells out to
  `git diff --name-status -M`, same subprocess-with-argument-list pattern as Phase 1.1, never `shell=True`).
  All 6 required tests pass (new/modified/deleted/renamed file, multiple commits, no-change commit).
  **The D4 symbol-level diff extension is NOT built yet and this is deliberate, not an oversight**: D4 itself
  says the pass runs "right after M2's structural graph exists for two commits" — there are no Nodes yet to
  hash and compare. `ChangeType.UNCHANGED` is defined now (for that future per-node classification) but never
  emitted by today's file-level `diff_commits()`, since plain `git diff` only reports deltas by nature.
- **Phase 1.5 — Audit Infrastructure.** `src/veyra/audit.py`: `AuditRecord` (all fields from the plan's minimum
  list except `memory_bytes`, which is best-effort/optional per "where available" — no memory measurement is
  wired in yet, cross-platform memory profiling without a new dependency was judged not worth it for M1) and
  `AuditTimer`, a context manager that measures wall-clock duration and captures success/failure **without
  swallowing the underlying exception** (`__exit__` returns `False`). Persisted via a fifth append-only table on
  `VBGStore`. Per D6, this is instrumentation only — no precision/recall/quality metrics are computed here.
  **Real retrofit discovered while building this**: Phase 1.1's `RepositoryInfo.clone_start`/`clone_end` used
  `time.monotonic()`, which gives precise durations but no meaningful absolute timestamp — incompatible with
  Phase 1.5's "start/end timestamps" requirement. Changed to `time.time()` (wall-clock epoch seconds) in
  [acquire.py](src/veyra/acquisition/acquire.py) — duration math is unaffected (still `end - start`), and no
  existing test needed to change since they only asserted relative ordering, not the clock source. A new
  integration test (`test_phase_1_1_acquisition_audited_and_persisted`) proves `AuditTimer` actually wraps a
  real Phase 1.1 acquisition and both the audit record and the repository record land in `VBGStore` together —
  this is what "used by every milestone" means as a tested claim, not just an available utility.
- **Milestone 1 Gate: cleared**, with one explicit carry-forward (symbol-level diff, blocked on M2 by design —
  see PLAN.md Milestone 1 Gate section for the updated checklist).

### 2026-08-20 — Phase 1.2 (Canonical VBG Schema) implemented
- `src/veyra/vbg/models.py`: `Node`, `Edge`, `RelationshipType` (closed 8-value enum, exactly PLAN.md Phase
  2.3's vocabulary), `VerificationState` (closed 11-value enum, exactly PLAN.md Phase 3.8's vocabulary — defined
  in full now since it's named as a Milestone 1 canonical entity, even though most values won't be produced
  until M2/M3 exist). Both `Node` and `Edge` validate their required fields and enum types in `__post_init__`
  (e.g. `Edge.relationship_type` must be an actual `RelationshipType` member, not a bare string) — this is what
  "relationship types are explicit" and "every edge has source and target" mean as executable checks, not just
  prose.
- `src/veyra/vbg/storage.py`: `VBGStore`, a SQLite-backed append-only store implementing the D3 event-sourced
  design. **"Historical records cannot be silently overwritten" is enforced structurally, not by convention** —
  `VBGStore` has no `update_*`/`delete_*` method for any entity, only `insert_*` and read methods; every write
  is a new row. Conflicting writes for the same `(entity_id, repository_version)` key are retained side by side
  as queryable history (`get_node_history`/`get_edge_history`), with `get_latest_*` as a convenience "current
  view" — this is also how "conflicts are representable" is satisfied at the storage level.
- `record_repository()` persists a successful Phase 1.1 `RepositoryInfo` (closing the loop noted in the Phase
  1.1 entry below: audit fields now have somewhere to land). Reuses `RepositoryInfo.require_commit()`'s guard,
  so a failed acquisition can't be recorded — you can't persist a repository version that doesn't exist.
- Tests: `tests/vbg/test_models.py` (10 tests, one per schema rule per Phase 1.2's "every schema rule receives
  unit tests" requirement) + `tests/vbg/test_storage.py` (10 tests, covering immutability, conflict
  preservation, version-scoping, and the Phase 1.1 integration). **30/30 passing project-wide.**
- **Deliberately deferred, not stubbed**: Evidence and Provenance (full behavior + tests belong to Phase 1.3,
  next up), Question (M2), Scenario and ExecutionEnvironment (M3). PLAN.md Phase 1.2 lists these as "additional
  entities" in the canonical schema, but building empty placeholder fields for them now — before the phase that
  defines their actual rules exists — would be exactly the kind of half-finished scaffolding to avoid. Edge
  does not yet carry an `evidence` field for the same reason: evidence will be its own append-only table
  (referencing edges by natural key) once Phase 1.3 defines what an evidence record actually needs to enforce,
  rather than a field bolted onto Edge today.
- Also deferred: graph traversal (neighbors, recursive queries) — that's Phase 2.3/2.4's job, once there's a
  real structural graph to traverse. Today's `get_*` methods are exact-key lookups only.

### 2026-08-20 — Phase 1.1 (Repository Acquisition) implemented
- Scaffolded the Python project: `pyproject.toml` (setuptools, src layout, Python 3.11+, pytest as the only
  dev dependency), `.venv`, `.gitignore`. Deliberately stdlib-only for the implementation itself (`subprocess`,
  `pathlib`, `dataclasses`, `enum`) — no new runtime dependencies introduced yet.
- Implemented `src/veyra/acquisition/`: `models.py` (`RepositoryInfo`, `AcquisitionStatus`), `languages.py`
  (deterministic extension-based language inventory — explicitly NOT the M2 parser), `acquire.py`
  (`acquire_repository()`, shells out to `git` via `subprocess` with argument lists, never `shell=True`).
- `RepositoryInfo.require_commit()` directly encodes the acceptance criterion "analysis cannot start without an
  identified repository version" — raises `ValueError` unless acquisition succeeded and a commit SHA exists.
- Ordinary failure modes (missing repo, empty repo, clone failure) return `status=FAILED` with a human-readable
  `error_reason` rather than raising — satisfies "invalid repository handling is deterministic." Only a missing
  `git` executable raises (`GitNotAvailableError`), since that's a broken environment, not a bad input.
- Tests (`tests/acquisition/`): all 7 required scenarios from PLAN.md Phase 1.1 (valid repo, invalid repo, empty
  repo, clone failure, commit identification, large repo, multi-language repo), plus 3 more targeting specific
  acceptance criteria (clone duration recorded, `require_commit()` blocking and succeeding). Fixtures build
  small local git repos on disk so tests are offline and deterministic — no network dependency, no flakiness.
  **10/10 passing.**
- Deliberately NOT built yet: persistent audit-log storage (Phase 1.5's append-only store, D6) — `RepositoryInfo`
  carries its own audit fields (`clone_start/end/duration`, counts) in memory for now; wiring to the persistent
  store happens once Phase 1.2's storage layer (D3, SQLite event-sourced schema) exists. Also not built: real
  per-language structural parsing (that's M2's job — `languages.py` is inventory-only, extension-based).
- Stopped here for check-in before starting Phase 1.2, per the "go cautiously, one slice at a time" approach.

### 2026-08-20 — Open items resolved (2 of 4 set, 2 deliberately re-deferred with a trigger)
- Resource budgets (Phase 3.6): set concrete numeric defaults per repo-size tier → **D10**.
- Graph DB migration trigger (D3 open item): set a measurable perf-budget metric (p95 neighborhood latency
  >300ms on Tier 3, 3 consecutive runs) → **D11**.
- LLM calibration threshold (Phase 5.9): user chose to decide after real eval baseline data exists, not before
  — left open on purpose, now tied to a specific scheduled decision point (post-M3/M4, before Phase 5.9 runs)
  instead of a floating TBD.
- Ground-truth labeling methodology (Phase 5.3): user chose to decide once actual Tier 1 candidate repos are
  picked — left open on purpose, tied to the start of Phase 5.3.
- PLAN.md updated: D10/D11 added to Design Decisions Log; the two deferred items rewritten from generic "TBD"
  bullets into an "Open Decisions (deliberately deferred, with a scheduled resolution point)" section.

### 2026-08-19 — Plan reviewed, mitigations agreed, no code yet
- Original 5-milestone VEYRA plan received and reviewed end-to-end.
- 8 structural risks identified (see "Review Findings" below) — undecidable safety classification, harness/
  scenario synthesis difficulty, missing storage decision, late symbol-level diffing, multi-language scope
  risk, premature quality metrics, unbounded runtime exploration cost, LLM calibration gap.
- Mitigations agreed for all 8; folded into [PLAN.md](PLAN.md) as Design Decisions D1–D9.
- Explicit decision: **do not start coding until the plan reaches a conclusion.** This file and PLAN.md created
  as the standing reference pair; implementation to begin only when the user says so.
- New project directory created at `Desktop/veyra`, deliberately separate from the `arcf/` project/repo.

---

## Implementations Completed

- **Phase 1.1 — Repository Acquisition** (2026-08-20). `src/veyra/acquisition/`. 10/10 tests passing, covers
  all 7 required scenarios plus 3 acceptance-criteria-specific tests. See timeline entry above for detail.
  Now wired to persistent storage via Phase 1.2's `VBGStore.record_repository()`.
- **Phase 1.2 — Canonical VBG Schema** (2026-08-20). `src/veyra/vbg/`. Node/Edge models + SQLite append-only
  storage layer (D3). 20/20 new tests passing (30/30 project-wide). See timeline entry above for detail and for
  what was deliberately deferred (Evidence/Provenance/Question/Scenario/ExecutionEnvironment, graph traversal).
- **Phase 1.3 — Evidence & Provenance** (2026-08-20). `src/veyra/vbg/evidence.py`. 16 new tests. All 5 required
  tests from the plan pass. See timeline entry above.
- **Phase 1.4 — Git Version Tracking, file-level** (2026-08-20). `src/veyra/git_tracking/`. 7 new tests, all 6
  required scenarios pass. Symbol-level diff (D4) explicitly carried forward to M2.
- **Phase 1.5 — Audit Infrastructure** (2026-08-20). `src/veyra/audit.py` + `VBGStore` audit table. 11 new tests
  (6 unit + 5 storage/integration). Retrofitted Phase 1.1 to wall-clock timestamps for compatibility — see
  timeline entry above.
- **Milestone 1 gate cleared 2026-08-20** — 58/58 tests passing project-wide.
- **Phase 2.1 — Static Repository Analysis (Python)** (2026-08-20). `src/veyra/static_analysis/`. Real AST-based
  extractor, 11 new tests, all applicable required test categories pass. 69/69 project-wide. See timeline entry
  above for the two-phase resolution design and what's deliberately out of scope.
- **Phase 1.4 D4 extension — symbol-level diff** (2026-08-20). `src/veyra/git_tracking/symbol_diff.py`. 8 new
  tests (1 lexical_representation fix + 7 diff). 77/77 project-wide. **Milestone 1 gate now fully cleared.**
- **Phase 2.2 — Emerge Assessment** (2026-08-20). [docs/emerge_compatibility_report.md](docs/emerge_compatibility_report.md).
  Desk assessment only, explicitly flagged as unverified (no tool available to test against). Non-blocking per D9.
- **Phase 2.3 — Structural VBG Construction (cross-module)** (2026-08-20). Extended
  `src/veyra/static_analysis/python_extractor.py`. 6 new tests (5 cross-module + 1 cycle-support). 83/83
  project-wide.
- **Phase 2.4 — Neighborhood Model** (2026-08-20). `src/veyra/vbg/neighborhood.py` + new `VBGStore`
  `get_outgoing_edges`/`get_incoming_edges`. 14 new tests. 97/97 project-wide.
- **Phase 2.5 — Deterministic Question Generator** (2026-08-20). `src/veyra/questions/generator.py`. 14 new
  tests. 114/114 project-wide. Caught and fixed a real bug in itself later the same session (see Phase 2.6 entry).
- **Phase 2.6 — Static Question Verification** (2026-08-20). `src/veyra/questions/verifier.py`. 8 new tests
  (one of which caught the Phase 2.5 STRUCTURAL-question bug). 121/121 project-wide.
- **Phase 2.7 — Verified/Unverified Knowledge Arms** (2026-08-20). `src/veyra/questions/knowledge_arms.py` +
  `VBGStore` Question/Answer persistence (required moving `Question`/`Answer` into `vbg/questions.py` first).
  6 new tests. 133/133 project-wide.
- **Phase 2.8 — Static Audit** (2026-08-20). `src/veyra/pipeline.py`, `run_static_analysis()` — the Milestone 2
  entry point. 4 new tests. **138/138 project-wide. Milestone 2 gate fully cleared.**
- **Phase 3.1 — Execution Classification** (2026-08-20). `src/veyra/safety/` + `vbg/safety.py`. 43 new tests.
  **181/181 project-wide.** Capability Detection / Policy Evaluation / Classification kept architecturally
  separate per user-supplied design. Stopped here per explicit instruction, not proceeding to 3.2 yet.
- **Phase 3.2 — Execution Boundary** (2026-08-20). `src/veyra/execution/` + `vbg/execution.py`. 31 new tests, 26
  against real Docker containers (Docker Desktop started + PATH configured mid-session). **212/212
  project-wide.** See timeline entry above for the full security-hardening list and what's real vs. mocked
  (nothing is mocked).
- **Phase 3.3a — Harness & Fixture Manager (existing-test tracing)** (2026-08-20). `src/veyra/harness/`. 27 new
  tests (25 non-Docker + 2 real-Docker end-to-end). **217/217 tests passing in this session's non-Docker
  environment (23 Docker-gated tests skip cleanly).** See timeline entry above for the Dependency
  Inspection/Installation Policy scope boundary, the stdlib-only in-container runner, and the
  never-a-false-success-claim evidence discipline. 3.3b (novel scenario synthesis) not started.
- **Phase 3.3b — Novel Scenario Synthesis** (2026-08-20). `src/veyra/harness/synthesis.py`. 9 new tests, all
  non-Docker. **287/287 project-wide.** Completes the Harness & Fixture Manager (3.3a + 3.3b). Hypothesis
  generates diverse primitive values on the host; the actual invocation always still happens inside the
  unmodified Phase 3.2 sandbox via a purely additive `argument_overrides` addition to `run_scenario()`. Under
  the default policy this synthesizes nothing at all (SAFE is only reachable via an explicit allowlist, D13) --
  proven directly by a test, not just claimed.
- **Phase 3.4 — Behavioral Scenario Generator** (2026-08-20). `src/veyra/scenarios/` + `vbg/scenarios.py`. 37
  new tests. **253/253 project-wide.** Closes out `Scenario`, the last of Phase 1.2's originally-deferred
  canonical entities. See timeline entry above for scope (one direct-invocation candidate per invokable node,
  Phase 3.1 classification reused for real), and for a real cross-directory test-import bug found and fixed
  along the way.
- **Phase 3.5 — Runtime Trace Engine** (2026-08-20). `src/veyra/runtime/`. 15 new tests (12 non-Docker + 3
  real-Docker end-to-end). **265/265 project-wide.** The project's first phase to persist real RUNTIME
  evidence and the first caller of `VBGStore.insert_execution_environment()`. See timeline entry above for the
  sys.settrace-based tracer, the live-state re-derivation discipline, and a real bug (imprecise UNEXECUTABLE
  reason for a currently-a-method target) found and fixed by the tests.
- **Phase 3.6 — Multi-Execution Exploration** (2026-08-20). `src/veyra/exploration/`. 13 new tests, all
  non-Docker. **278/278 project-wide.** D10's tiered budgets are now real code (`explore_at_ingest`), plus the
  general lazy/query-driven primitive (`explore_neighborhood`) Tier 3 and future Phase 4.3 will use. See
  timeline entry above for the call-graph-vs-structural-neighborhood distinction and what's deliberately not
  built yet (per-node execution caps, precise nested-observation counts).
- **Phase 3.7 — Static/Runtime Evidence Reconciliation** (2026-08-20). `src/veyra/reconciliation/`. 7 new
  tests, all non-Docker. **308/308 project-wide** (built together with 3.8). `reconcile_calls()` classifies
  every static-vs-runtime CALLS pair as `CONFIRMED`/`STATIC_ONLY`/`RUNTIME_ONLY`; only `RUNTIME_ONLY` counts as
  a real conflict. Purely read-only, same discipline as Phase 2.7's `summarize_knowledge()`.
- **Phase 3.8 — Verification State Engine** (2026-08-20). `src/veyra/verification/`. 14 new tests, all
  non-Docker. **308/308 project-wide.** `derive_verification_states()` computes a `VerificationState` per node
  fresh from evidence every call (D15 -- never a mutated `Node.status`), an 8-branch precedence chain covering
  every named state except `STALE` (needs Phase 4.8) and `UNANSWERED` (already served by Phase 2.6/2.7).
- **Phase 3.9 — Runtime Audit** (2026-08-20). `RuntimeAuditReport` + `run_runtime_analysis()` in
  `src/veyra/pipeline.py`. 4 new tests, all non-Docker. **314/314 project-wide. MILESTONE 3 GATE FULLY
  CLEARED.** The first real end-to-end M3 pipeline run, and where a real gap (Scenario objects never actually
  persisted by 3.6/3.3b) was found and fixed. See timeline entry above.

---

## Ideas Descoped / Deferred

| Idea | Why descoped | Revisit condition |
|------|--------------|--------------------|
| Building a sound general-purpose execution-safety classifier | Undecidable in general; false negatives/positives are unavoidable for arbitrary code | Not revisited — replaced by D1 (sandbox-always, classification only tunes permissions inside the boundary) |
| From-scratch input/fixture synthesis as the *primary* runtime evidence source | Equivalent to solving automatic test generation; highest risk, highest cost sub-problem in the whole plan | Only after 3.3a (existing-test tracing) ships and its coverage ceiling is known |
| Attempting multiple languages in parallel with core architecture validation | Confounds "is the architecture right" with "does language X's tooling work" | After Python clears all 5 milestone gates (D5) |
| Graph database (Neo4j/Kùzu) as the initial VBG store | No traversal-performance problem exists yet to justify the infra cost | If/when SQLite recursive-CTE traversal becomes a measured bottleneck — no trigger metric defined yet, open item |
| Treating Emerge as a required upstream dependency | External tool of unknown availability/license/API; would compromise Veyra's independence | Only as an optional, interface-gated enhancement (D9) |
| Computing precision/recall/MRR as part of M1–M4 delivery | No ground truth exists to compute them against until M5 benchmark repos are built | Retroactively, once M5 Tier 1 ground-truth repos exist (D6) |

---

## Experiments — Succeeded

_(none run yet — no implementation exists)_

---

## Experiments — Failed / Falsified

_(none run yet — no implementation exists)_

---

## Review Findings (from initial plan review, 2026-08-19)

Kept here for traceability — each maps to a Design Decision in PLAN.md.

1. **Execution classification is undecidable in general** → D1 (sandbox always applies; classification only
   tunes permissions).
2. **Harness/scenario synthesis (3.3/3.4) is the hardest sub-problem in the plan** → D2 (existing-test tracing
   first, novel synthesis second, scoped to SAFE-classified functions only).
3. **No storage/architecture decision behind "historical records cannot be silently overwritten"** → D3 (SQLite,
   event-sourced SCD-Type-2 schema).
4. **Symbol-level git impact analysis deferred too late (originally Phase 4.8 only)** → D4 (basic version moved
   into M1.4/M2, consumed not rebuilt in M4.8).
5. **Multi-language scope attempted everywhere at once** → D5 (Python flagship first, Go second).
6. **Audit metrics defined before there's anything to measure them against** → D6 (instrumentation now, quality
   metrics retroactive against M5 ground truth).
7. **Resource budgets for runtime exploration unspecified** → D7 (lazy/query-driven by default, per-tier
   numeric ceilings — exact numbers still an open item).
8. **LLM grounding contract defines data shape, not model behavior** → D8 (dedicated calibration eval, separate
   from the VBG-level false-verification rate).

Minor: Emerge dependency risk → D9. "Deterministic" vs "complete/sound" terminology conflation → clarified
inline in PLAN.md Phase 2.1.

---

## Open Questions / Decisions Pending

Resolved 2026-08-20, down to 2 remaining (both deliberately deferred with a scheduled trigger, see PLAN.md
"Open Decisions" section):

- **LLM calibration threshold** (PLAN.md Phase 5.9 sub-check) — resolve once a real hedge-compliance baseline
  exists from running the eval against actual Python-pipeline output.
- **Ground-truth labeling methodology** (PLAN.md Phase 5.3) — resolve once actual Tier 1 candidate repos are chosen.

Closed:
- ~~Exact numeric resource budgets per repo-size tier~~ → D10 (PLAN.md Phase 3.6).
- ~~Trigger metric for migrating off SQLite~~ → D11 (PLAN.md Phase 3.6 region / Decisions Log).

---

## Next Steps

1. ~~Confirm open questions~~ — done 2026-08-20 (D10/D11 resolved, 2 items deliberately deferred with triggers).
2. ~~Scaffold the `veyra/` project structure~~ — done 2026-08-20.
3. ~~Phase 1.1 (Repository Acquisition)~~ — done 2026-08-20, 10/10 tests passing.
4. ~~Phase 1.2 (Canonical VBG Schema)~~ — done 2026-08-20, 20/20 new tests passing (30/30 total).
5. ~~Phase 1.3 (Evidence & Provenance)~~ — done 2026-08-20, 16 new tests.
6. ~~Phase 1.4 (Git Version Tracking, file-level)~~ — done 2026-08-20, 7 new tests. Symbol-level diff (D4)
   carried forward to M2, by design.
7. ~~Phase 1.5 (Audit Infrastructure)~~ — done 2026-08-20, 11 new tests. **Milestone 1 gate cleared, 58/58
   tests passing project-wide.**
8. ~~Milestone 2, Phase 2.1 (Static Repository Analysis, Python)~~ — done 2026-08-20, 11 new tests, 69/69
   project-wide.
9. ~~Phase 1.4 D4 (symbol-level diff)~~ — done 2026-08-20, 8 new tests. **Milestone 1 fully cleared.**
10. ~~Phase 2.2 (Emerge assessment)~~ — done 2026-08-20, desk assessment, flagged unverified, non-blocking.
11. ~~Phase 2.3 (cross-module relationships)~~ — done 2026-08-20, 6 new tests. 83/83 project-wide.
12. ~~Phase 2.4 (Neighborhood Model)~~ — done 2026-08-20, 14 new tests. 97/97 project-wide.
13. ~~Phase 2.5 (Question Generator)~~ — done 2026-08-20, 14 new tests. 114/114 project-wide.
14. ~~Phase 2.6 (Static Question Verification)~~ — done 2026-08-20, 8 new tests. 121/121 project-wide.
15. ~~Phase 2.7 (Verified/Unverified Knowledge Arms)~~ — done 2026-08-20, 6 new tests. 133/133 project-wide.
16. ~~Phase 2.8 (Static Audit)~~ — done 2026-08-20, 4 new tests. **138/138 project-wide. M2 gate cleared.**
17. ~~Phase 3.1 (Execution Classification)~~ — done 2026-08-20, 43 new tests. **181/181 project-wide.**
18. ~~Phase 3.2 (Execution Boundary)~~ — done 2026-08-20, 31 new tests (26 real Docker). **212/212 project-wide.**
19. ~~Phase 3.3a (Harness & Fixture Manager — existing-test tracing)~~ — done 2026-08-20, 27 new tests (25
    non-Docker + 2 real-Docker). **217/217 project-wide in a non-Docker environment.** Also where the
    Dependency Inspection → Installation Policy stages of the dependency-installation-as-a-security-operation
    pipeline got built (Environment Construction is just Phase 3.2's existing `ExecutionBoundary`, reused
    unmodified).
20. ~~Phase 3.4 (Behavioral Scenario Generator)~~ — done 2026-08-20, 37 new tests. **253/253 project-wide.**
    Picked over 3.3b for this slice since it doesn't depend on coverage data Phase 3.5 hasn't been built to
    produce yet; closes out `Scenario`, the last Phase-1.2-deferred canonical entity.
21. ~~Phase 3.5 (Runtime Trace Engine)~~ — done 2026-08-20, 15 new tests (12 non-Docker + 3 real-Docker).
    **265/265 project-wide.** Picked over 3.3b again for the same reason; now the project's first source of
    real RUNTIME evidence and real runtime CALLS-edge observations.
22. ~~Phase 3.6 (Multi-Execution Exploration)~~ — done 2026-08-20, 13 new tests, all non-Docker. **278/278
    project-wide.** D10's tiered budgets are real code now, not just PLAN.md prose.
23. ~~Phase 3.3b (Novel Scenario Synthesis)~~ — done 2026-08-20, 9 new tests. **287/287 project-wide.**
    Completes the Harness & Fixture Manager (3.3a + 3.3b).
24. ~~Phase 3.7 (Evidence Reconciliation) + Phase 3.8 (Verification State Engine)~~ — done 2026-08-20 together,
    21 new tests. **308/308 project-wide.**
25. ~~Phase 3.9 (Runtime Audit)~~ — done 2026-08-20, 4 new tests. **314/314 project-wide. MILESTONE 3 GATE
    FULLY CLEARED** (all 9 phases + security tests, the latter already satisfied by Phase 3.2's own suite).
    Found and fixed a real gap along the way: `Scenario` objects generated by 3.6/3.3b had never actually been
    persisted to `VBGStore` until this phase's audit report needed to count them for real.
26. **Next up: Milestone 4 (Retrieval & LLM Grounding)** — not started. First phase is 4.1 (VBG Retrieval
    Index). M3 is done; nothing further is planned here until the user gives explicit direction on M4 (or on
    any M3 follow-up work, e.g. wiring `explore_neighborhood()` to a real caller once M4's Phase 4.3 exists).
