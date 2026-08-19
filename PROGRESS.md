# VEYRA — Progress, Implementations, Descoped Ideas, Experiment Log

> Read this file at the start of every session, alongside [PLAN.md](PLAN.md).
> Update it (with date/time) after every meaningful change: a merge, a shipped phase, a descoped idea, or a
> finished experiment (success or failure). Keep entries newest-first within each section.

---

## Current Status

**Stage:** M1 and M2 BOTH FULLY cleared. M3 (Safe Controlled Execution) started: Phase 3.1 done, stopped there
per explicit instruction ("do NOT proceed to 3.2 automatically").
**Current milestone:** 181/181 tests passing project-wide. Docker + WSL2 now installed on the dev machine
(2026-08-20), specifically so Phase 3.2's container tests can be real rather than mocked when that phase starts.
**Language scope:** Python-only (flagship language per PLAN.md D5), until the pipeline clears its M5 gates.
**Repo/storage:** `src/veyra/acquisition/`, `src/veyra/vbg/` (Node/Edge/Evidence/Repository/Audit/Question/
Answer/Classification, all append-only), `src/veyra/git_tracking/`, `src/veyra/audit.py`,
`src/veyra/static_analysis/`, `src/veyra/questions/`, `src/veyra/pipeline.py`, `src/veyra/safety/` (new, Phase
3.1) all implemented. SQLite event-sourced store (D3) live.

---

## Timeline Log

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
18. **Next up: Phase 3.2 (Execution Boundary)** — `ExecutionBoundary` protocol + `DockerExecutionBoundary`
    (D16/D17). Docker + WSL2 are now installed specifically for this phase's real (non-mocked) container tests.
    On hold pending explicit go-ahead — not to be started automatically per the current instruction.
