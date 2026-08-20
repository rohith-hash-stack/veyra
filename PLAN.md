# VEYRA — Master Plan (Living Reference)

> This is the canonical reference document for VEYRA. Read this before starting or resuming any work.
> Companion file: [PROGRESS.md](PROGRESS.md) — status, implementations, descoped ideas, experiment log.

Last updated: 2026-08-19 (initial version — plan reviewed, no implementation started yet)

---

## Core Principle

Veyra builds a commit-aware **Verified Behavioral Graph (VBG)** from a repository using deterministic static
analysis and controlled runtime observation. Questions are generated to systematically probe the graph, evidence
is attached to every claim, and the LLM receives only relevant, evidence-backed repository context.

```text
Repository → Commit → Canonical VBG → Evidence + Provenance
```

No static or runtime verification exists outside this canonical model.

---

## Architecture — 5 Milestones

```text
                         REPOSITORY
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│ M1 — CORE SUBSTRATE                                          │
│ Canonical VBG • Evidence • Provenance • Git Versioning        │
└─────────────────────────────┬───────────────────────────────┘
                              ▼
┌─────────────────────────────────────────────────────────────┐
│ M2 — DETERMINISTIC STATIC KNOWLEDGE                           │
│ Analysis • Graph • Neighborhoods • Questions • Static Verify  │
└─────────────────────────────┬───────────────────────────────┘
                              ▼
┌─────────────────────────────────────────────────────────────┐
│ M3 — SAFE CONTROLLED EXECUTION                                │
│ Safety Gate • Harness • Runtime • Evidence • Conflict         │
└─────────────────────────────┬───────────────────────────────┘
                              ▼
┌─────────────────────────────────────────────────────────────┐
│ M4 — RETRIEVAL & LLM GROUNDING                                │
│ Graph-RAG • Evidence Retrieval • LLM • Git Invalidation       │
└─────────────────────────────┬───────────────────────────────┘
                              ▼
┌─────────────────────────────────────────────────────────────┐
│ M5 — VALIDATION & PRODUCTION AUDITING                         │
│ Accuracy • Coverage • Security • Performance • Regression     │
└─────────────────────────────────────────────────────────────┘
```

The three distinct purposes for "questions" across milestones — keep this separation strict:

```text
M2 — Structural Questions:    "What is connected to what?"
M3 — Behavioral Questions:    "What actually happens when this executes?"
M4 — Evidence Retrieval:      "Which already-established facts are relevant to this query?"
```

M2/M3 build and strengthen knowledge; M4 only consumes it. The LLM is downstream of evidence-building — it never
discovers repository structure itself.

---

## Sequencing Decision (agreed 2026-08-19)

Build order deviates from a strict M1→M5 waterfall in two ways:

1. **Single flagship language first.** Take Python end-to-end through all 5 milestones before attempting any
   other language. Python is dynamic enough to stress-test the safety classifier and harness logic honestly,
   has native AST access, easy tracing (`sys.settrace` / `coverage.py`), and a huge corpus of real repos for
   benchmarking. Second language (after architecture is validated): Go — statically typed, narrow safety
   surface, a deliberately contrasting case.
2. **M3 harness work is split and reordered within itself** — see Phase 3.3 below. Existing-test-suite tracing
   ships before novel scenario synthesis.

---

## Milestone 1 — Core Substrate

**Objective:** Build the foundation every later capability depends on.

### Phase 1.1 — Repository Acquisition
Accept source → clone → identify exact commit → capture metadata → inventory files → identify languages →
record size → record clone duration.

Acceptance: reproducible clone; exact commit SHA captured; invalid-repo handling deterministic; inventory
generated; clone duration recorded; analysis cannot start without an identified repository version.

Tests: valid repo, invalid repo, empty repo, clone failure, commit identification, large repo, multi-language repo.

Audit fields: `clone_start`, `clone_end`, `clone_duration`, `repository_size`, `file_count`, `language_count`, `commit`.

### Phase 1.2 — Canonical VBG Schema

```text
Node: id, type, name, language, source_location, lexical_representation,
      occurrence_count, repository_version, status
Edge: source, target, relationship_type, repository_version, evidence, status, provenance
```
Additional entities: `Repository, Commit, Question, Answer, Scenario, Evidence, Provenance,
ExecutionEnvironment, VerificationState`.

Acceptance: stable node identity; every edge has source+target; explicit relationship types; repository
version attached; static/runtime evidence coexist; unknown states representable; conflicts representable;
**historical records cannot be silently overwritten**.

**Storage decision (agreed 2026-08-19):** SQLite (Postgres if concurrent writers are needed later). Event-sourced
/ SCD-Type-2 schema — nodes and edges are never updated in place; every change is a new row keyed by
`(entity_id, repository_version, valid_from)`. Graph traversal at a given commit is a filtered query (recursive
CTEs, or materialize into an in-memory graph structure per request). Satisfies immutability without committing to
a graph database up front; migrate to Neo4j/Kùzu later only if traversal performance demands it.

### Phase 1.3 — Evidence & Provenance
Evidence types: `STATIC, RUNTIME, TEST, INFERRED, USER_SUPPLIED`.
Every evidence record identifies: `WHAT, WHERE, WHEN, HOW, COMMIT, SCENARIO, ENVIRONMENT`.

Acceptance: every verified claim has evidence; every evidence record has provenance; runtime evidence
references a scenario + execution environment; evidence is version-aware; historical evidence is immutable;
evidence strength/type explicit.

Tests: missing provenance, missing commit, runtime evidence without scenario, evidence versioning, historical
evidence retrieval.

### Phase 1.4 — Git Version Tracking
Track: `Added, Modified, Deleted, Renamed, Unchanged`.

**Extension (agreed 2026-08-19, moved up from M4):** add a lightweight **symbol-level diff pass** here, run
right after M2's structural graph exists for two commits. Match nodes across commits by stable qualified ID;
classify each as `ADDED / REMOVED / MODIFIED_SIGNATURE / MODIFIED_BODY / UNCHANGED` via a hash of normalized
source text per node. Cheap (hashing + graph diff), and gives "evidence belongs to a specific commit" real teeth
immediately instead of waiting for Phase 4.8. Phase 4.8 later *consumes* this diff for impact propagation rather
than inventing diffing from scratch.

Acceptance: exact versions distinguishable; changed files identifiable; evidence tied to a specific commit;
historical VBG info retrievable; changes never silently overwrite previous knowledge.

Tests: new file, modified file, deleted file, renamed file, multiple commits, no-change commit.

### Phase 1.5 — Audit Infrastructure
Minimum metrics every milestone must log: `duration, start/end timestamps, memory (where available), input
size, output size, success/failure, error reason, repository commit`.

**Instrumentation-vs-metrics split (agreed 2026-08-19):** log raw data now (predicted nodes/edges/answers, not
just counts) to an append-only store. Precision/recall/MRR-style *quality* metrics are computed retroactively
once M5's ground-truth benchmark exists — never treat them as an M1–M4 deliverable in their own right.

### Milestone 1 Gate — FULLY CLEARED 2026-08-20
```
☑ Repository acquisition        ☑ Evidence                    ☑ Git tracking (file-level)
☑ Canonical VBG                 ☑ Provenance                  ☑ Audit infrastructure
☑ Commit awareness              ☑ Acceptance criteria tested  ☑ Git tracking: symbol-level diff (D4)
```
Symbol-level diff (D4) was unblocked once Milestone 2 Phase 2.1's extractor existed to produce real Nodes to
diff — implemented as `veyra.git_tracking.diff_symbols()`, a pure comparison function over two Node-list
snapshots (ADDED/REMOVED/MODIFIED_SIGNATURE/MODIFIED_BODY/UNCHANGED). Wiring it to pull two arbitrary commits'
live source and run extraction at each is deliberately left for Phase 4.8, its actual named consumer.

---

## Milestone 2 — Deterministic Static Knowledge

**Objective:** Convert the repository into a deterministic structural representation and systematically
generate questions from it.

```text
Repository → Static Analysis → Structural VBG → Neighborhood Model → Question Generation
           → Static Verification → Verified / Unverified Knowledge
```

### Phase 2.1 — Static Repository Analysis
Extract where reliably supported: files, modules, packages, classes, functions, methods, imports, references,
inheritance, calls, variables, source locations, lexical representations, occurrences.

Acceptance: supported constructs deterministically extracted; unsupported constructs explicitly recorded;
every extracted entity maps to a VBG node; every supported relationship maps to a VBG edge; source locations
preserved; duplicate symbols handled.

**Terminology note (agreed 2026-08-19):** "deterministic" means *reproducible for the same input*, not
*complete or sound*. Define the supported-construct boundary per language explicitly up front — don't let it be
discovered ad hoc during implementation.

Tests: fixture repos covering classes, methods, functions, imports, calls, inheritance, references, nested
structures, duplicate names, (later) multiple languages.

### Phase 2.2 — Emerge Integration Assessment
Evaluate whether the existing Emerge repository graph can contribute (dependency graph, clusters,
relationships, git info, TF-IDF, architecture metrics).

**Decision (agreed 2026-08-19):** treat as a strictly optional plug-in behind an interface. Never block any
Veyra phase on Emerge's availability; evaluate integration opportunistically, later. Emerge cannot overwrite
stronger evidence, and its output must map deterministically to VBG or it doesn't get consumed at all.

Deliverable: Emerge Compatibility Report — `SUPPORTED / PARTIALLY_SUPPORTED / UNSUPPORTED / REQUIRES_SUPPLEMENTATION`.

### Phase 2.3 — Structural VBG Construction
Relationships: `contains, imports, calls, references, inherits, implements, depends_on, defined_in`.

Acceptance: deterministic graph per commit; unique node identity; typed relationships; cycles supported;
cross-module relationships supported; graph reconstructable.

### Phase 2.4 — Neighborhood Model
Per node, derive: parent, children, siblings, grandchildren, incoming neighbors, outgoing neighbors.
Configurable depth. Unobserved relationships stay identifiable as unobserved.

### Phase 2.5 — Deterministic Question Generator (no LLM)
Categories: `SYMBOL, STRUCTURAL, RELATIONSHIP, DEPENDENCY, CALL_FLOW, INHERITANCE, REFERENCE, NEIGHBORHOOD,
LEXICAL, OCCURRENCE`.

Acceptance: no LLM dependency; every question references ≥1 VBG entity; explicit question type; duplicates
removed; deterministic generation; question provenance identifies graph info used; unsupported constructs don't
generate false questions.

Tests: dedicated fixture tests per category.

### Phase 2.6 — Static Question Verification
Answer deterministic questions directly from the VBG, no LLM.

Acceptance: answers reference VBG entities; static evidence attached; unsupported questions become
`UNANSWERED`; static verification can never silently become runtime verification.

### Phase 2.7 — Verified / Unverified Knowledge Arms
Verified: verified static facts, evidence, provenance, commit.
Unverified: unexplored nodes, unobserved edges, unanswered questions, unsupported constructs, lexical info,
occurrences, definitions, references.

Acceptance: kept strictly separate; unknown never silently becomes verified; unanswered questions stay
queryable; static verification status explicit.

### Phase 2.8 — Static Audit
Record: analysis duration; files analyzed/failed; nodes/edges/relationship types; questions
generated/deduplicated/answered/unanswered; static evidence created; static precision/recall; unsupported rate.
(Precision/recall computed retroactively per the M1.5 instrumentation-vs-metrics split.)

### Milestone 2 Gate — FULLY CLEARED 2026-08-20
```
☑ Static extraction              ☑ Deterministic question generation
☑ Structural VBG                 ☑ Static verification
☑ Neighborhood model              ☑ Verified/unverified separation
☑ Emerge assessment (optional)    ☑ Full test coverage (138/138 project-wide)
```
"Static benchmarks" (precision/recall) deliberately not computed here — per D6, those need Milestone 5 ground
truth; `StaticAuditReport.static_precision`/`static_recall` exist as fields and are explicitly `None` until then,
not silently omitted. Entry point for the whole milestone: `veyra.pipeline.run_static_analysis()`.

---

## Milestone 3 — Safe Controlled Execution

**Objective:** Move from "what can we determine statically?" to "what can we actually observe executing?"

```text
Question → Execution Planner → Safety Gate → Execution Boundary → Harness → Runtime → Trace → Evidence
```

### Phase 3.1 — Execution Classification — IMPLEMENTED 2026-08-20
Classes: `SAFE, SANDBOXABLE, MOCKABLE, BLOCKED, UNKNOWN`.

**Safety model decision (agreed 2026-08-19):** do not attempt a sound general classifier — classifying
arbitrary code as safe-to-run is undecidable in general. Make classification **non-load-bearing for safety**:
*every* execution runs inside the sandbox boundary (3.2) regardless of its class. Classification only controls
how much is permitted inside the boundary, not whether isolation applies. A false "SAFE" verdict then costs a
mislabeled evidence record, never a sandbox escape.

**Refined design (agreed 2026-08-20, D12–D15) — three explicitly separate layers, not one AST→verdict map:**
```
Static Code → Capability/Risk Detection → Policy Evaluation → Safety Classification
```
Static analysis cannot determine the *actual* runtime environment (`requests.post(...)` doesn't prove whether
the endpoint is production, staging, or a local mock) — so detection only ever answers "what capabilities are
potentially reachable," never "is this safe." Implemented as `src/veyra/safety/`:
- `capabilities.py` — `detect_capabilities(node)`, pure, re-parses `Node.lexical_representation` (Phase 2.1) via
  `ast`. A fixed table of dotted-call patterns (`subprocess.run`, `socket.socket`, `requests.post`, `eval`,
  `os.environ[...]`, ...) maps to a `Capability` vocabulary (13 values: `NETWORK_ACCESS`,
  `EXTERNAL_NETWORK_ACCESS`, `PROCESS_EXECUTION`, `SUBPROCESS_EXECUTION`, `FILESYSTEM_READ/WRITE`,
  `CREDENTIAL_ACCESS`, `ENVIRONMENT_ACCESS`, `DATABASE_ACCESS`, `SOCKET_ACCESS`, `DYNAMIC_CODE_EXECUTION`,
  `NATIVE_CODE_ACCESS`, `UNKNOWN_EXTERNAL_EFFECT`). Any call matching none of the known patterns, and not a
  short allowlist of inert builtins, becomes `UNKNOWN_EXTERNAL_EFFECT` — the conservative catch-all.
- `policy.py` — `resolve_safety_class(entity_id, capabilities, policy)`, pure, zero AST knowledge. Precedence
  when multiple capabilities are present: most-restrictive-wins, `BLOCKED(4) > UNKNOWN(3) > MOCKABLE(2) >
  SANDBOXABLE(1) > SAFE(0)`.
- `classification.py` / `audit.py` — `classify()` (pure) and `classify_and_audit()` (the only function that
  touches `VBGStore`), producing a `ClassificationResult` persisted append-only.

**Expected-coverage note:** with a conservative classifier, most real-world functions land in
UNKNOWN/SANDBOXABLE. Documented design constant, not a defect — bounds M5's runtime-observation coverage
numbers going in.

Acceptance: no execution before classification (the whole `safety` package has zero execution capability, a
self-check test enforces this by walking its own source for forbidden `ast.Call`/`ast.Import` nodes); unknown
external behavior never auto-executed; production/destructive-looking operations blocked; policy decisions
persisted and auditable (`VBGStore.insert_classification`/`get_classification_history`). 43 tests.

### Phase 3.2 — Execution Boundary — IMPLEMENTED 2026-08-20
Filesystem isolation, network isolation, credential isolation, CPU/memory limits, timeout, process
restrictions, cleanup.

**Backend decision (agreed 2026-08-20, D16/D17):** Docker is the initial `ExecutionBoundary` backend, but the
runtime verifier depends only on the `ExecutionBoundary` interface (`execute`/`terminate`/`collect_result`/
`cleanup`), never on Docker directly — `DockerExecutionBoundary` is the first implementation, not the contract,
so `LocalProcessExecutionBoundary`/`FirecrackerExecutionBoundary`/`RemoteExecutionBoundary` can be added later
without redesigning the runtime verifier, scenario engine, trace ingestion, or evidence model. Docker is
containment, not an absolute security guarantee (D17) — non-privileged, restricted mounts, network disabled by
default, CPU/memory/timeout limits, disposable containers, deterministic cleanup, no `--privileged`, no host
Docker socket, no host credentials, unless an explicit reviewed policy reason exists. Docker Desktop + WSL2
installed on the dev machine 2026-08-20, specifically to make this phase's integration/security tests real
rather than mocked.

**Dependency installation as a security operation (agreed 2026-08-20):** `pip install -r requirements.txt` /
`npm install` / `setup.py` on an arbitrary repository is itself an execution/security operation, not a safe
precondition — folded into this phase (and Phase 3.3's harness construction) as an explicit
Dependency-Inspection → Dependency/Installation-Policy → Environment-Construction pipeline, gated by the same
Safety Gate as everything else. Unsupported environments become `UNSUPPORTED_ENVIRONMENT`/`UNEXECUTABLE`, never
a silent fallback to unsafe host execution.

Tests: filesystem escape, network escape, credential access, process creation, resource exhaustion, timeout,
cleanup. Docker-dependent tests separated from the unit suite (`pytest.mark.skipif` when Docker is unavailable)
— real behavior tested where the environment permits, never faked via string-matching a Docker command.

**Implemented as `src/veyra/execution/`**: `ExecutionBoundary` (a `typing.Protocol` — `execute`/`terminate`/
`collect_result`/`cleanup`, zero Docker vocabulary), `DockerExecutionBoundary` (structural typing only — it does
not inherit from the Protocol, proving substitutability is real, not just declared). Docker Desktop + WSL2
became available mid-session, so all 26 Docker-backed tests spin up **real disposable containers** — network
isolation, filesystem isolation (read-only root + tmpfs `/tmp` scratch), memory-limit OOM-kill, CPU/pids-limit
config, timeout+forced-termination, cleanup-after-timeout, and host-environment-variable non-inheritance are all
genuinely exercised, not mocked. A `FakeExecutionBoundary` (test-only, in `test_boundary_contract.py`) with zero
Docker knowledge proves AC1/AC2 (runtime-verifier-shaped code is identical across backends) as a demonstrated
fact rather than an assertion. `ExecutionEnvironment` (deferred from Phase 1.2, and the real referent of
Evidence's `environment_id` since Phase 1.3) now has a concrete shape and an append-only `VBGStore` table.
`DockerExecutionBoundary` itself stays storage-agnostic — persisting `ExecutionEnvironment`/evidence together is
Phase 3.5's job (the actual runtime-verifier caller), not built prematurely here. 31 tests.

### Phase 3.3 — Harness & Fixture Manager

**Split and reordered (agreed 2026-08-19) — this is the highest-difficulty phase in the plan:**

- **3.3a (build first, low risk / high yield) — IMPLEMENTED 2026-08-20:** trace the repository's *existing*
  test suite. Existing tests are already valid, already scoped, and already implicitly judged safe by the
  repo's own authors — this yields real runtime evidence with minimal synthesis risk.
  Implemented as `src/veyra/harness/`: `discovery.py` (pure AST-based pytest-convention test discovery,
  entity_ids aligned with Phase 2.1's extractor naming), `dependencies.py` + `install_policy.py` (the
  Dependency Inspection → Installation Policy stages of the pipeline below — deliberately conservative:
  stdlib-only repositories are `SUPPORTED`, anything declaring a third-party dependency is
  `UNSUPPORTED_ENVIRONMENT`, since installing arbitrary packages is itself an unreviewed
  execution/security operation not attempted in this slice), `runner_script.py` (a stdlib-only, no-pytest
  in-container runner — this is what lets 3.3a avoid needing the installation pipeline it declines to build),
  and `manager.py` (`run_existing_test_harness()`, orchestrating discovery → dependency gate → Phase 3.1's
  Safety Gate reused as-is → Phase 3.2's `ExecutionBoundary` reused unmodified → `Evidence(EvidenceType.TEST)`
  persistence). Note: 3.3a produces test-level PASS/FAIL/ERROR evidence, not per-node execution tracing inside
  the code under test — that granularity is Phase 3.5's job (Runtime Trace Engine), which will instrument an
  existing-test run the same way 3.3a already executes one. 27 new tests (25 non-Docker + 2 real-Docker
  end-to-end proving genuine PASS/FAIL/ERROR and real `--network none` enforcement).
- **3.3b (build second, high risk) — IMPLEMENTED 2026-08-20:** synthesize *novel* scenarios only for functions
  with zero test coverage, restricted to the SAFE-classified subset, using an established property-based
  library (Hypothesis) rather than a bespoke input/fixture generator.
  Implemented as `src/veyra/harness/synthesis.py`: `synthesize_novel_scenarios()`. "Zero test coverage" is
  defined directly off evidence this project already produces (no `EvidenceType.TEST` or `EvidenceType.RUNTIME`
  yet at this commit). "Restricted to SAFE" is real, not just a filter comment: `SafetyClass.SAFE` is only ever
  reachable through an explicit per-target policy allowlist (D13) -- under the default policy (no allowlist)
  this module synthesizes nothing at all, by design, proven directly by a test.
  **Where the property-based generation happens, and where it deliberately doesn't**: Hypothesis's own
  `strategies`/`@given`/`@settings` machinery generates diverse concrete values for the same 5-type primitive
  boundary Phase 3.4/3.5 already use (str/int/float/bool/bytes -- not a wider type surface), entirely on the
  HOST. Those concrete values are handed to Phase 3.5's `run_scenario()` via a new, purely additive
  `argument_overrides` parameter -- the actual invocation of repository code always still happens exactly
  where D1 requires it: inside the unmodified Phase 3.2 sandbox, through the exact same tracer Phase 3.5 uses.
  Hypothesis's own execution engine is never run inside the container (that would need installing a package
  into the sandboxed image over network access `DockerExecutionBoundary` deliberately never opens -- D17);
  Hypothesis here is Veyra's own trusted, pinned tooling dependency (added to `pyproject.toml`), not a
  repository dependency -- categorically different from what `install_policy.py` declines to solve.
  Each Hypothesis-generated value combination becomes its own scenario with a distinct `scenario_id`, so every
  trial's evidence is independently persisted and never conflated with another trial's.
  9 new tests, including one proving the default-policy-synthesizes-nothing behavior directly, and one proving
  real value diversity across trials (not a fixed placeholder).

`UNEXECUTABLE` state covers: missing configuration, missing dependency, missing fixture, unsafe dependency,
ambiguous initialization, unavailable environment. 3.3a's `UnexecutableReason` enum
(`UNSUPPORTED_ENVIRONMENT`/`MISSING_STATIC_NODE`/`BLOCKED_BY_SAFETY`/`HARNESS_EXECUTION_FAILED`/
`NO_RESULT_REPORTED`) is a concrete first instance of this state for the existing-test-tracing case.

Acceptance: dependencies identified where possible; fixture requirements identified; safe substitutions
supported; failed harness creation → `UNEXECUTABLE`; failed execution never becomes a successful behavioral
claim. All satisfied for 3.3a's scope (existing tests, no fixtures/mocking yet — fixture requirements and safe
substitutions are chiefly 3.3b's concern, since 3.3a's existing tests bring their own setup).

### Phase 3.4 — Behavioral Scenario Generator — IMPLEMENTED 2026-08-20
Generates runtime-oriented questions/scenarios from static knowledge; not all are executable. Planner converts
them into candidate scenarios with input requirements, dependencies, expected observable points, safety
classification.

**Implemented as `src/veyra/scenarios/`**, and closes the last of Phase 1.2's deferred canonical entities:
`Scenario` finally gets its shape, defined in `vbg/scenarios.py` (same "shape lives in vbg, logic lives in the
top-level package" split as Question/ClassificationResult/ExecutionEnvironment). One candidate scenario per
Function/Method node at a commit: "directly invoke this with zero/default/synthesizable-primitive arguments" --
deliberately the simplest possible scenario shape for a first slice (multi-call sequences, exception-injection,
constructed-fixture scenarios are explicitly not attempted here).
- `introspection.py` — `extract_signature(node)`, pure, re-parses `Node.lexical_representation` via `ast` (the
  same technique `veyra.safety.capabilities` uses on the same field) to determine parameters, whether each has
  a synthesizable value (a small primitive-annotation allowlist or an existing default), and whether the target
  is a bound method.
- `generator.py` — `generate_scenarios(store, repository_version, policy=None)`, reusing Phase 3.1's
  `classify_and_audit()` exactly as-is (same precedent as Phase 3.3a) so every scenario's `safety_class` is
  backed by a real, persisted classification decision, not an unearned claim. A scenario is `executable=True`
  only when: source was available to introspect, classification is not `BLOCKED`, the target is not a bound
  method (no constructor/fixture strategy exists yet -- `AMBIGUOUS_INITIALIZATION`), and every parameter is
  synthesizable (else `MISSING_FIXTURE`). `Scenario.__post_init__` structurally refuses to construct a
  non-executable Scenario without both a reason and an explanatory detail -- "unsupported scenarios →
  unexecutable" cannot be silently skipped.
- `Scenario.dependencies` is deliberately left empty in this slice -- no consumer needs it populated yet;
  the natural source (outgoing CALLS/IMPORTS edges) is a stated follow-up, not guessed at now.
- `VBGStore` gained `insert_scenario`/`get_scenario_history`/`get_latest_scenario`/`get_scenarios`, same
  append-only + current-view discipline as Node/Edge -- re-generating scenarios for the same target under a
  changed policy is a conflicting write for the same `scenario_id`, kept as history, not an overwrite.
- 37 new tests (signature introspection, generator behavior across every unexecutable reason, Scenario model
  validation, and storage round-trip/conflict-preservation).

Acceptance: scenarios reference actual VBG nodes; required inputs explicit; safety classified before execution;
unsupported scenarios → unexecutable; scenarios reproducible. All satisfied for this slice's scope (single
direct-invocation scenario per invokable node; multi-scenario/multi-step planning is future work).

### Phase 3.5 — Runtime Trace Engine — IMPLEMENTED 2026-08-20
Capture: node entered/exited, call observed, return, exception, external interaction, execution time, scenario.

**Implemented as `src/veyra/runtime/`**: `run_scenario(store, repository_root, repository_version, scenario,
boundary)` is where a Phase 3.4 `Scenario` stops being a plan and becomes an observation. Also closes a
deferral Phase 3.2 itself named: this is the first module to call `store.insert_execution_environment()`
(`DockerExecutionBoundary` deliberately stayed storage-agnostic).
- `tracer_script.py` — stdlib-only in-container code (`sys.settrace`, no `coverage.py`) that actually invokes
  the target with trivial synthesized primitive-literal arguments and traces every call/return/exception whose
  `co_filename` is under the mounted `/workspace`. A call reaching outside `/workspace` is recorded once as a
  single `external_interaction` event and not traced further inside -- proves a boundary was crossed without
  pretending to observe the other side of it. Entity identity is
  `f"{module.__name__}.{code.co_qualname}"` (`co_qualname`, Python 3.11+) -- lines up exactly with the
  extractor's own entity_id convention with no extra bookkeeping.
- `engine.py` — **re-derives executability from live state** rather than trusting the Scenario's own cached
  `executable` flag (same discipline Phase 2.6's `verify_question()` established: re-derive, don't replay a
  stale snapshot) -- the target's source or classification may have changed since the scenario was planned.
  Reconstructs the observed call stack from the flat, time-ordered event list (`call`/`return` are 1:1 per
  frame even when a frame exits via exception -- CPython still fires `return` with `arg=None`) to derive both
  which entities were genuinely observed and which caller→callee edges were actually exercised.
- **"Failed execution still counts as evidence" (Phase 3.5 AC), interpreted precisely**: an `EXCEPTION` outcome
  means the target genuinely ran and a real trace came back describing what happened -- that IS evidence, and
  is persisted like any other RUNTIME evidence. A `CONTAINER_EXECUTION_FAILED`/`NO_TRACE_REPORTED` outcome (no
  usable trace came back at all -- crashed before reaching the target, or timed out) is genuinely ambiguous
  about whether the target was ever reached, so -- matching Phase 3.3a's harness manager precedent -- it is
  UNEXECUTABLE with no evidence, not a guess.
- Persists one `Evidence(RUNTIME, subject_id=entity_id, scenario_id=..., environment_id=...)` per genuinely
  observed node, plus one per genuinely observed CALLS edge (`subject_id` is a stable edge key,
  `f"{source}--CALLS-->{target}"`, per Evidence's own "entity_id of the node, or a stable edge key" WHAT
  contract from Phase 1.3) -- this is the project's first real runtime call-graph evidence, deliberately not
  reconciled against static CALLS edges here (whether it confirms or conflicts with what Phase 2.3 predicted is
  Phase 3.7's explicit job, not pre-judged in this phase).
- Argument synthesis stays deliberately trivial (one fixed zero-value literal per already-synthesizable
  primitive parameter) -- proving the call executes, not exploring the input space; that remains Phase 3.3b's
  job.
- 15 new tests (12 non-Docker via a `FakeExecutionBoundary` covering every `RuntimeUnexecutableReason`, plus
  real classification/environment/evidence persistence and nested-call edge evidence; 3 real-Docker end-to-end
  tests proving a genuine nested-call trace, a genuine captured exception, and a genuine
  `external_interaction` event from a real blocked network call).

Acceptance: runtime observations map to VBG nodes/edges; trace tied to commit, scenario, execution environment;
failed execution still counts as evidence; multiple observations retained (append-only `insert_evidence`, same
as everywhere else -- re-running the same scenario twice adds a second independent observation, never
overwrites the first).

### Phase 3.6 — Multi-Execution Exploration — IMPLEMENTED 2026-08-20
Use prior observations to explore unexplored neighborhood, iteratively.

**Implemented as `src/veyra/exploration/`**: `explore()` is the shared core (rank Phase 3.4's live executable
scenarios by degree centrality, skip anything already carrying RUNTIME evidence, run Phase 3.5's
`run_scenario()` on the rest until a budget is hit); `explore_at_ingest()` implements D10's eager Tier 1/2
policy directly (Tier 3 performs zero executions here, by design); `explore_neighborhood()` is the general
lazy/query-driven primitive Tier 3's per-query budget describes, walking outgoing CALLS edges breadth-first
(deliberately NOT Phase 2.4's structural CONTAINS children/grandchildren -- a different relationship, left
completely untouched, which is exactly why "siblings/children/grandchildren stay visible" is a free
non-regression guarantee here rather than something this module has to reimplement). No real M4 query caller
exists yet for `explore_neighborhood()`, so it's offered as the reusable primitive Phase 4.3 will eventually
call, not wired to a fabricated trigger -- same deferral discipline Phase 3.3a used.
- Centrality is plain degree centrality (in+out edge count via Phase 2.4's edge-query primitives) --
  explicitly a simple, stated proxy for "high-value/public-API," not betweenness/eigenvector centrality.
- Per-node execution cap (D10's "max 5 scenarios/executions per node" for Tier 2) is NOT implemented: Phase 3.4
  generates exactly one deterministic scenario per node today, so a per-node cap has nothing to bound yet --
  stated as a real gap with a concrete revisit trigger (once multi-scenario generation exists), not silently
  dropped.
- 13 new tests: empty-candidate report, full-repo exploration, candidate-set restriction, skip-already-explored
  (a pre-seeded RUNTIME evidence row proves redundant re-treatment doesn't happen), execution-count budget,
  wall-clock budget, centrality-ordering (a node with both an incoming and outgoing CALLS edge goes first),
  Tier 1/2/3 policy (Tier 2's top-N cutoff verified via `monkeypatch` against a small call chain, Tier 3's zero
  eager executions verified directly), call-graph-only neighborhood traversal (a CONTAINS-only sibling is
  proven absent), max_depth, and the neighborhood primitive's defaults matching D10's Tier 3 numbers exactly.

**Budget decision (agreed 2026-08-19):** default to lazy, query-driven exploration — mirror the Eager/Lazy Q&A
split from M4 for runtime exploration too. Only high-centrality/public-API nodes get eager scenario execution
at ingest; everything else executes on demand when a query needs it.

**Numeric budgets (agreed 2026-08-20), tied to the `file_count` already captured in Phase 1.1:**
- Tier 1 (<50 files): unlimited executions, single wall-clock cap of 5 min total ingest budget.
- Tier 2 (50–500 files): eager execution limited to the top 50 centrality-ranked nodes, max 5 scenarios/
  executions per node, 30 min wall-clock cap.
- Tier 3 (>500 files): **no eager execution at ingest at all** — purely lazy/query-driven; 2 min / 20-execution
  cap per individual query.

These are starting defaults, not measured optima — revisit once Phase 5.7 performance-audit data exists on
real repos in each tier.

Acceptance: new evidence updates VBG; previously observed paths not redundantly re-treated as new;
siblings/children/grandchildren stay visible; additional executions bounded; convergence measurable; **no
completeness claim just because executions stop finding new paths**.

### Phase 3.7 — Static/Runtime Evidence Reconciliation — IMPLEMENTED 2026-08-20
Conflicting evidence (e.g. static says `A→B`, runtime observed `A→C`) — both are retained, tagged by source.
Interpretation (e.g. "B = possible path, C = observed path") is left explicit, not auto-resolved.

**Preservation/sources/nothing-silently-deleted were already true** by construction of Phase 1.2's append-only
storage and Phase 1.3's "multiple evidence records for the same subject coexist" discipline -- this phase's
real, new contribution is `src/veyra/reconciliation/engine.py`'s `reconcile_calls(store, repository_version)`:
comparing the STATIC CALLS edges Phase 2.3 extracted against the RUNTIME CALLS-edge evidence Phase 3.5/3.6/
3.3b produce, per (source, target) pair, as `CONFIRMED` / `STATIC_ONLY` / `RUNTIME_ONLY`. **Only
`RUNTIME_ONLY` is a genuine conflict** (`EdgeReconciliation.is_conflict`) -- matching PLAN's own example
exactly (runtime exercised a path static analysis never predicted at all); `STATIC_ONLY` is deliberately not
treated as a conflict, since it just means "not yet runtime-confirmed" (could be genuinely unexplored, or a
conditional branch legitimately not taken this trial). "Conditional behavior representable" needs no special
handling: two different trials confirming two different static edges from the same source both come back
`CONFIRMED` independently, which is exactly what conditional branching looks like at this level.
Purely a read-only derivation (same discipline as Phase 2.7's `summarize_knowledge()`) -- never writes to
`VBGStore`; per D15, "unresolved conflicts stay `CONFLICTED`" is Phase 3.8's job to surface as an actual
`VerificationState`, computed fresh from this function's output, never stored.
A new `VBGStore.get_all_evidence()` bulk query (mirroring `get_all_nodes`/`get_all_edges`) backs this, and
`vbg/evidence.py` gained the stable `edge_evidence_key()`/`parse_edge_evidence_key()` pair the edge-shaped
`Evidence.subject_id` convention was already implicitly using since Phase 3.5 -- `runtime/engine.py` now
reuses these instead of its own private, duplicate helper (format-compatible, verified via the full Phase 3.5
suite passing unchanged).

Acceptance: conflicting evidence preserved; sources identifiable; nothing silently deleted; conditional
behavior representable; unresolved conflicts stay `CONFLICTED`. 7 new tests.

### Phase 3.8 — Verification State Engine — IMPLEMENTED 2026-08-20
States: `STRUCTURALLY_IDENTIFIED, STATICALLY_SUPPORTED, RUNTIME_OBSERVED, RUNTIME_VERIFIED,
CONDITIONALLY_VERIFIED, UNEXPLORED, UNANSWERED, UNEXECUTABLE, BLOCKED_BY_SAFETY, CONFLICTED, STALE`.
Every state transition must have a valid evidence basis.

**Implemented as `src/veyra/verification/engine.py`**: `derive_verification_states(store, repository_version)`
(bulk) / `derive_verification_state(store, entity_id, repository_version)` (single-entity convenience). Per
D15, this is a pure, read-only derivation computed fresh from evidence every call -- exactly Phase 2.7's
`summarize_knowledge()`/Phase 3.7's `reconcile_calls()` discipline, never a mutated `Node.status`. Precedence
(most specific/severe fact wins): `BLOCKED_BY_SAFETY` (latest classification is BLOCKED) →
`CONFLICTED` (source of a Phase 3.7 `RUNTIME_ONLY` edge) → `UNEXECUTABLE` (every Scenario ever generated for
this node is currently non-executable) → `RUNTIME_VERIFIED`/`RUNTIME_OBSERVED`/`CONDITIONALLY_VERIFIED` (has
RUNTIME evidence -- VERIFIED if every observed run completed cleanly, OBSERVED if any raised, CONDITIONALLY_
VERIFIED if clean AND reconciliation confirms more than one distinct outgoing call target) →
`RUNTIME_VERIFIED`/`RUNTIME_OBSERVED` again (via TEST evidence when no RUNTIME evidence exists -- an existing
test passing is itself real behavioral verification) → `STATICALLY_SUPPORTED` (has STATIC evidence) →
`UNEXPLORED` (known only via an unconfirmed static CALLS edge, Phase 3.7's `STATIC_ONLY`) →
`STRUCTURALLY_IDENTIFIED` (the honest default -- nothing beyond bare extraction is known).
**`STALE` is not produced** -- that's Phase 4.8's job (Git Impact Analysis, Milestone 4, not built); this
module has no inputs for cross-commit invalidation yet. **`UNANSWERED` is not re-derived here either** --
Phase 2.6/2.7's own `AnswerStatus`/`summarize_knowledge()` already serve Questions directly.
**A stated, accepted coupling**: distinguishing a clean completion from an exception reads the leading
`status=<VALUE>` token every RUNTIME/TEST `Evidence.detail` this project writes already begins with (Evidence
itself has no structured outcome field; adding one was judged out of scope for this slice) --
`_evidence_status()` is the one place that coupling lives, documented as such.
14 new tests, one per named precedence branch plus bulk-coverage and unknown-entity-default checks.

### Phase 3.9 — Runtime Audit
Scenario/execution counts+duration; harness generated/successful/failed; safety
safe/mocked/sandboxed/blocked counts; runtime nodes/edges observed, exceptions, timeouts; evidence
runtime/conflicts/verified/unverified.

### Milestone 3 Gate
```
☐ Safety precedes runtime          ☐ Multi-run exploration (bounded)
☐ Execution isolation              ☐ Conflict reconciliation
☐ Harness manager (3.3a → 3.3b)    ☐ Verification states
☐ Scenario generation              ☐ Security tests
☐ Runtime tracing                  ☐ Runtime audit
```

---

## Milestone 4 — Retrieval & LLM Grounding

**Objective:** the LLM does not search the raw repository as its primary knowledge source.

```text
User Query → Graph-RAG → Relevant VBG Region → Evidence Retrieval → Grounded Context → LLM → Response
```

### Phase 4.1 — VBG Retrieval Index
Index: symbols, classes, methods, lexical representations, docstrings, relationships, graph paths,
neighborhoods, evidence summaries, verified questions, repository metadata.

Acceptance: relevant VBG regions retrievable; retrieval commit-aware; evidence status accompanies retrieved
info; retrieval returns graph references, not invented entities; raw repo scanning not required per query.

### Phase 4.2 — Semantic Repository Retrieval
Conceptual queries ("How does authentication work?") retrieve relevant graph regions and relationships; exact
symbol queries retrieve exact nodes; lexical + semantic retrieval combinable; retrieval never invents graph
entities; evidence accompanies retrieved entities.

### Phase 4.3 — Query-Time Evidence Retrieval
Primarily *retrieve* existing verified knowledge rather than continually generating huge Q&A datasets:
`Query → relevant nodes → relevant relationships → relevant evidence → verification states → context`. The LLM
explains that evidence; it does not discover it.

### Phase 4.4 — Eager Q&A Cache
Precompute only for high-value nodes: public APIs, high-centrality nodes, core services, subsystem boundaries,
frequently queried nodes. Cache is commit-aware.

### Phase 4.5 — Lazy Q&A
No permanent question set for less important internal nodes — generate/retrieve only when needed; previously
answered questions cacheable; duplicates avoided; query latency measurable.

### Phase 4.6 — Q&A Explosion Control
Measure: potential/eager/cached/lazy question counts, deduplication ratio, index size. Question count stays
bounded; storage growth measurable; eager strategy has configurable limits.

### Phase 4.7 — LLM Grounding Contract
LLM receives: relevant nodes, relationships, evidence, provenance, verification state, conflicts, unknowns,
repository commit.

Acceptance: LLM can distinguish verified/unverified; conflicts exposed; unknowns stay unknown; repository scope
explicit; LLM cannot silently claim unsupported repository behavior; evidence references returnable with
responses.

**Calibration gap (agreed 2026-08-19):** the contract defines what data the LLM *receives*, not whether its
prose *respects* it (LLMs are known to flatten hedged context into confident answers). Don't rely on the field
existing in a JSON payload the model may skim past — surface verification state as prominent inline
natural-language flags (e.g. "NOTE: this call path was never executed, only inferred") rather than burying it
in structured metadata. Add a dedicated M5 eval for this — see Phase 5.9 note.

**Threshold decision (2026-08-20):** deliberately deferred, not defaulted. Build the eval set and run it once
real Python-pipeline output exists (post-M3/M4), observe the model's actual baseline hedge-compliance rate,
then set the pass threshold from that observed baseline rather than guessing a number now. Do not skip setting
a threshold once baseline data exists — this is a scheduled decision point, not a permanently open item.

### Phase 4.8 — Git Impact Analysis & Invalidation
```text
Git change → Changed symbols → Impact analysis → Tier 0 → Tier 1 → Tier 2 → Tier 3 if required
```
- Tier 0: changed symbol/body.
- Tier 1: direct callers/callees/references/inheritance.
- Tier 2: questions/evidence directly dependent on affected nodes.
- Tier 3: wider behavioral dependencies.

Important rule: unchanged signatures do not prove unchanged behavior.

**Note:** this phase now *consumes* the symbol-level diff built in M1.4/M2, rather than building diffing from
scratch here.

Acceptance: changed evidence goes stale where appropriate; unaffected evidence stays valid; historical evidence
stays accessible; reverification targeted, not a full-repo re-scan by default.

### Phase 4.9 — Retrieval Audit
Index build duration/size; query latency; Recall@K/Precision@K/MRR (computed once M5 ground truth exists);
relevant nodes/edges/evidence retrieved; grounded vs unsupported answers.

### Milestone 4 Gate
```
☐ VBG retrieval          ☐ Q&A explosion control
☐ Semantic retrieval     ☐ LLM grounding (+ calibration eval)
☐ Evidence retrieval     ☐ Git impact analysis (consumes M1/M2 diff)
☐ Eager Q&A              ☐ Tiered invalidation
☐ Lazy Q&A               ☐ Retrieval benchmark + tests
```

---

## Milestone 5 — Production Validation & Auditing

**Objective:** no major new functionality here. Answers: *does Veyra actually work reliably enough to be trusted?*

### Phase 5.1 — Acceptance-Criteria Traceability
`Requirement → Acceptance Criterion → Test Case → Result`. Every acceptance criterion has an automated test;
critical security requirements have negative tests; no milestone marked complete with untested criteria.

### Phase 5.2 — Full Integration Testing
Every subsystem in the full pipeline (Repository → VBG → Question Generator → Static Verification → Safety →
Harness → Runtime → Evidence → Graph-RAG → LLM) preserves identity, version, evidence, provenance, status,
failure information end to end.

### Phase 5.3 — End-to-End Repository Benchmark
- Tier 1: controlled repos, known ground truth.
- Tier 2: medium real-world repos.
- Tier 3: large open-source repos.
Vary languages, frameworks, architectures, sizes, dependency structures, dynamic behavior, external
dependencies. **Per the sequencing decision, Tier 1/2/3 start Python-only; a second language is added only
after the Python pipeline clears its gates.**

**Ground-truth labeling methodology (2026-08-20): deliberately deferred.** Decide once actual Tier 1 candidate
repos are chosen — the right approach (semi-automated from tests/types + spot-check, vs. fully manual) may
depend on what test/type coverage each candidate repo actually has. This is a scheduled decision point at the
start of Phase 5.3, not a permanently open item.

### Phase 5.4 — Structural Accuracy Audit
Node precision/recall, edge precision/recall, symbol/call/inheritance/import accuracy.

### Phase 5.5 — Question Quality Audit
Questions generated/valid/duplicate/answerable/unanswered/unsupported/verified.

### Phase 5.6 — Behavioral Coverage Audit
Report separately, never collapsed into one misleading percentage: structural coverage, static evidence
coverage, runtime observation coverage, runtime verification coverage, unexplored nodes, unobserved edges,
unexecutable behaviors, blocked behaviors, conflicted behaviors.

**Expectation set in M3.1:** given the conservative safety classifier, runtime observation/verification
coverage on real-world repos is expected to be low by design. Report against that expectation, not against 100%.

### Phase 5.7 — Performance Audit
Time every stage: clone, analysis, graph construction, question generation, static verification, harness
generation, runtime, evidence processing, index construction, retrieval latency, incremental update duration.
Also: CPU, memory, storage, graph size, evidence count, question count, trace size, index size.

### Phase 5.8 — Safety & Security Audit
Test: filesystem escape, network escape, credential leakage, process creation, resource exhaustion, timeout
bypass, production API access, destructive commands, sandbox escape.
**Release criterion:** no known execution-boundary escape exists in the security benchmark.

### Phase 5.9 — False Verification Audit
```text
False Verification Rate = Incorrectly verified claims / All verified claims
```
**Release criterion:** no known false-verification cases in the release benchmark. Do not claim arbitrary
software can mathematically achieve zero false verification.

**Added sub-check (agreed 2026-08-19) — LLM answer calibration:** distinct from the VBG-level false-verification
rate above. Build a small held-out eval set of evidence bundles that deliberately include
UNVERIFIED/CONFLICTED cases; score whether the model's *answer text* actually hedges on them. Fail this gate if
the model states unverified/conflicted claims as fact above an agreed threshold — this is what the user
actually sees, independent of whether the underlying VBG data was correct.

### Phase 5.10 — Static vs Runtime Conflict Audit
Static agreement, runtime agreement, conflicts, unresolved/resolved conflicts. Validate: conflict ≠ failure;
conflict = evidence requiring interpretation. The LLM may explain a conflict but must not silently resolve it
as fact.

### Phase 5.11 — Git Regression Audit
Changed files/symbols, invalidated nodes/edges, stale evidence, reverified nodes/questions. Measure:
incremental analysis/verification time, unnecessary invalidation, missed invalidation.

### Phase 5.12 — Final Production Report
Standard report format covering repository, structural analysis, question engine, static verification,
runtime, evidence, retrieval, git, security, quality, and final status (`PASS / FAIL / PARTIALLY VERIFIED`).
(Full template preserved from original spec — see git history of this file if the inline copy is ever trimmed.)

### Milestone 5 Gate
```
☐ Acceptance traceability    ☐ Performance
☐ Integration testing        ☐ Security
☐ E2E repositories (Python first) ☐ False verification (+ LLM calibration)
☐ Structural accuracy        ☐ Conflict audit
☐ Question quality           ☐ Git regression
☐ Behavioral coverage        ☐ Final release report
```

---

## Key Design Decisions Log

| # | Decision | Rationale | Date |
|---|----------|-----------|------|
| D1 | Safety classification is non-load-bearing; sandbox boundary applies regardless of class | Generic safe-code classification is undecidable; cap blast radius instead of solving classification | 2026-08-19 |
| D2 | Harness Manager split: trace existing tests (3.3a) before synthesizing novel scenarios (3.3b) | Input/fixture synthesis for arbitrary functions is a hard research problem; existing tests are free, safe evidence | 2026-08-19 |
| D3 | Storage: SQLite/Postgres, event-sourced SCD-Type-2 schema, not a graph DB | Satisfies immutability requirement without committing to graph-DB infra before it's needed | 2026-08-19 |
| D4 | Symbol-level diff moved into M1.4/M2, consumed (not built) in M4.8 | M1/M2 already make per-commit evidence claims that need this earlier | 2026-08-19 |
| D5 | Single flagship language (Python) end-to-end before any second language | De-risk the architecture before paying for N-language breadth | 2026-08-19 |
| D6 | Audit metrics split: instrumentation now, quality metrics (precision/recall/MRR) computed retroactively once M5 ground truth exists | Those metrics are undefined without ground truth that doesn't exist until M5 | 2026-08-19 |
| D7 | Runtime exploration is lazy/query-driven by default, with explicit per-tier numeric budgets | Prevent unbounded cost on Tier 3 repos | 2026-08-19 |
| D8 | Dedicated LLM answer-calibration eval, separate from VBG false-verification rate | Contract compliance (data shape) ≠ behavior compliance (model actually hedges) | 2026-08-19 |
| D9 | Emerge integration is a strictly optional plug-in, never a blocking dependency | External tool of unknown availability/license; Veyra must remain independent | 2026-08-19 |
| D10 | Numeric runtime-exploration budgets set per tier (Tier 1: 5 min uncapped; Tier 2: top-50 nodes × 5 scenarios, 30 min; Tier 3: no eager execution, 2 min/20 executions per query) | Concrete starting defaults so 3.6 is implementable now; explicitly revisited once real perf data exists | 2026-08-20 |
| D11 | Graph-DB migration trigger: p95 neighborhood-retrieval latency > 300ms on Tier 3 repos, sustained across 3 consecutive benchmark runs | Makes the "revisit SQLite" decision measurable instead of a vague future feeling | 2026-08-20 |
| D12 | Capability detection is architecturally separate from policy evaluation (`capabilities.py` has zero `SafetyClass` knowledge; `policy.py` has zero AST/parsing knowledge) | Static analysis can identify *potential* capabilities but can never determine the actual runtime environment (`requests.post(...)` doesn't prove prod/staging/local) — conflating the two would smuggle an unearned safety claim into detection | 2026-08-20 |
| D13 | Absence of detected risk does not imply SAFE — an empty capability set classifies as `SANDBOXABLE`, never `SAFE` | "No dangerous signal detected" and "proven safe" are different concepts; SANDBOXABLE still requires the full execution boundary, so nothing is exempted by default | 2026-08-20 |
| D14 | `UNKNOWN` is the conservative default whenever evidence is insufficient (parse failure, missing source, or an unrecognized call pattern via `UNKNOWN_EXTERNAL_EFFECT`) | Matches AC "unknown operations are never automatically executed" — ambiguity must never resolve toward permissiveness | 2026-08-20 |
| D15 | Verification state continues to be derived from immutable evidence history, never from a mutated `Node.status` field — M3 produces immutable runtime evidence the same way M2 produces static evidence | `VBGStore` never issues UPDATE (D3); a "state transition" can only be a new Evidence row, consistent with how Phase 2.7's `summarize_knowledge()` already derives verified/unverified from `has_evidence()`, not from a status label | 2026-08-20 |
| D16 | Docker is the planned initial `ExecutionBoundary` backend (Phase 3.2), but the runtime verifier depends only on the `ExecutionBoundary` interface, never on Docker directly | Keeps the sandboxing technology swappable (`LocalProcessExecutionBoundary`, `FirecrackerExecutionBoundary`, `RemoteExecutionBoundary` later) without redesigning the runtime verifier, scenario engine, trace ingestion, or evidence model | 2026-08-20 |
| D17 | Docker is treated as a containment mechanism, not an absolute security guarantee — non-privileged, restricted mounts, network off by default, resource/timeout limits, disposable containers, no `--privileged`/host socket/host credentials without an explicit reviewed reason | Consistent with D1's "sandbox boundary is real containment, not a proof of safety" framing; avoids overclaiming what Docker actually provides | 2026-08-20 |

---

## Open Decisions (deliberately deferred, with a scheduled resolution point — not abandoned)

- **LLM calibration threshold** (Phase 5.9 sub-check): not set yet by design. Resolve once the eval set has been
  run against real Python-pipeline output and a baseline hedge-compliance rate is observed — set the threshold
  from that baseline, not a guess made before any data exists.
- **Ground-truth labeling methodology for Tier 1 benchmark repos** (Phase 5.3): not set yet by design. Resolve
  once actual Tier 1 candidate repos are chosen, since the right method depends on each repo's existing test/
  type coverage.

Both items are scheduled decision points tied to a specific future milestone gate, not open-ended TBDs — do not
proceed past that gate without resolving them.
