# Codex — Structural Fact-Sheet Retrieval (Living Plan)

> A sub-project of Veyra. This is the resumable reference document for Codex specifically —
> read this before resuming or extending the work. Companion data:
> `experiments/coverage_denominator/structured_summary.py` (the proof-of-concept script) and
> `benchmarks/real_world_python/results/structured_summary_experiment.json` (its real results).

Status: **EXPERIMENTAL — not shipped, not wired into production `_entity_text()`.**
Branch: `experiment/real-world-python-benchmark`. Last updated: 2026-08-21 (proof-of-concept
run and measured; no further phases started yet).

---

## Core Principle

Veyra's retrieval already struggles with a real, measured problem: a natural-language question
and a correct entity's own docstring/source often don't share enough literal vocabulary for the
coverage floor to accept the match, even when the entity is exactly right and well-ranked. Codex's
bet is that the fix isn't to loosen the floor (every attempt at that has leaked on negative
queries) and isn't to guess a smarter tokenizer (the stopword experiment showed shared-tokenizer
tricks cut both ways) — it's to give each entity **more real, deterministic vocabulary to be
found by**, drawn entirely from relationships Veyra has *already verified*, phrased the way a
person actually asks questions about code ("what does X call," "what does X contain").

```text
Verified graph edges (CONTAINS / CALLS / INHERITS) → structured per-entity fact sheet
                                                              → appended to existing indexed text
                                                              → retrieved via the SAME BM25 +
                                                                coverage + z-score pipeline,
                                                                unchanged
```

No new confidence mechanism, no new acceptance rule, no ML, no fabricated edges — Codex only
ever changes what text an entity is *findable by*, never how retrieval decides to trust it.

---

## Why this, and not the other things tried

Three other approaches were tried this pass and are documented for context, not repeated here:

- **Loosening the coverage floor via relative signals** (percentile/z-of-coverage/margin) —
  rejected (Fix 9): every one leaks on negative queries, because a relative measure always has
  "a best candidate" whether or not the pool contains a real answer.
- **Semantic/embedding retrieval** (GloVe, TF-IDF+LSA) — NO-GO for the two models actually
  testable in this environment (Phase E): recall degrades sharply on larger repos, and negative-
  query similarity scores overlap almost entirely with positive-query scores — no safe threshold.
- **Extending the shared tokenizer's stopword list** (`experiments/coverage_denominator/`) —
  a wash: fixed real cases, broke others, because the words that dilute a *question's* denominator
  are sometimes genuine *content* in a document's own real text (`fastapi.param_functions.Depends`'s
  own docstring literally says "FastAPI will call it for you").

Codex is different in kind from all three: it never touches confidence math, and it never touches
tokenization symmetry between query and document. It only adds real, additional, already-verified
text to what an entity's document *is* — the same category of intervention as `_entity_text()`
itself, not a new mechanism layered on top of acceptance.

---

## Relevant existing Veyra mechanisms Codex builds on

Codex does not introduce new extraction, new storage, or new relationship types. Everything it
uses already exists and is already verified elsewhere in the codebase:

- **`veyra.vbg.models.RelationshipType`** — the closed relationship vocabulary (`CONTAINS`,
  `IMPORTS`, `CALLS`, `REFERENCES`, `INHERITS`, `IMPLEMENTS`, `DEPENDS_ON`, `DEFINED_IN`).
  Codex's proof-of-concept uses `CONTAINS` (via `children`), `CALLS` (in/out), and `INHERITS`
  (in/out) only — see *Scoping decisions* below for why `REFERENCES`/`IMPORTS` are excluded so far.
- **`veyra.retrieval.index.IndexedEntity`** — already carries `.parents`/`.children`/`.siblings`
  (Phase 2.4's Neighborhood Model) and `.outgoing_relationships`/`.incoming_relationships`
  (real edges, `(relationship_type.value, target_or_source_id)` tuples) for every entity, computed
  once at index-build time. Codex reads these fields directly; it queries no new storage.
  fields.
- **`veyra.questions` (Phase 2.5/2.6, `QuestionCategory`: SYMBOL/STRUCTURAL/RELATIONSHIP/
  DEPENDENCY/CALL_FLOW/INHERITANCE/REFERENCE/NEIGHBORHOOD/LEXICAL/OCCURRENCE)** — the real,
  already-implemented deterministic Question Generator + Static Verification. Built for a
  *different* purpose (M2's own structural-questions arm, per `PLAN.md`'s "three distinct
  purposes for questions" separation) and never wired into retrieval — Codex's fact-sheet
  templates are a parallel, retrieval-scoped idea, not a reuse of `Question`/`Answer` objects,
  but the category vocabulary above is a natural reference point if Codex's templates grow.
- **Structural corroboration** (the shipped Final-Hardening-pass mechanism, `src/veyra/retrieval/
  context.py`) — proved that borrowing a real CONTAINS neighbor's evidence can recover genuine
  matches without leaking on negative queries, at real, measured cost/benefit (9/28 recovered,
  0 net negative-query regression). Codex generalizes the same trust boundary (real edges only,
  never CALLS-inferred, never fabricated) into the *document representation* instead of the
  *acceptance decision*.
- **`_entity_text()` (`src/veyra/retrieval/search.py`)** — the exact, single integration point:
  `name + docstring + source`. Codex's `_augmented_entity_text()` wraps this, appending its
  fact-sheet block rather than replacing anything — the proof-of-concept never modifies this
  function in `src/veyra/`, only monkeypatches it for the duration of an experiment process.
- **The real call-resolution measurement (7.7–28.3% at best, 0% for `obj.method()`/dynamic
  dispatch)** — the known ceiling Codex does *not* escape. Confirmed directly on `authenticate()`
  itself: its real resolved `CALLS` edges are its own private helpers
  (`_clean_credentials`, `_get_compatible_backends`); the semantically important line
  (`backend.authenticate(request, **credentials)`, a dynamic dispatch inside a loop) is not a
  resolved edge at all. Codex can only ever report real edges — it will never invent the
  `ModelBackend.authenticate` connection static analysis never found.

---

## What's been measured so far (Phase 1 — proof of concept)

**Implementation** (`experiments/coverage_denominator/structured_summary.py`): for every entity,
render up to five lines, only when the real data exists (never a placeholder for an absent
relationship):

```text
What does {name} contain?        <- entity.children (short names)
What does {name} call?           <- outgoing CALLS edges
Who calls {name}?                <- incoming CALLS edges
What does {name} inherit from?   <- outgoing INHERITS edges
What inherits from {name}?       <- incoming INHERITS edges
```

Appended (not replacing) to the existing `name + docstring + source` text. Neighbor names are
rendered as their **short (last dotted segment) name**, not the full `entity_id` — a deliberate
choice to avoid reintroducing the exact dotted-qualified-path tokenization noise the stopword
experiment found (a fully-qualified path splits into separate, misleadingly-weighted tokens).

**Real result** (4 repos, 56 queries, before/after, committed at `7f6723e`):

| | Result |
|---|---|
| Negative-query regressions | **0** — same clean safety property held throughout the whole hardening pass |
| Real gains | `django-04` recovers `authenticate()` — the **second, structurally independent** mechanism to recover this exact case (structural corroboration partially did, the stopword fix did, Codex does too) — a meaningfully reproducible signal, not a fragile artifact. `flask-06` gains a third of its five needed symbols. |
| Real losses | `fastapi-05` loses `APIRoute` to **ranking crowding** (still `accepted=True`, coverage clears via a structural neighbor, but pushed to rank 13/19 — outside `top_k=10`). `fastapi-04` loses `FastAPI.add_api_route` to a **new mechanism**: z-score suppression — appending similar template phrasing to *many* corpus entities at once appears to compress the query's candidate-pool score distribution, so a genuinely good candidate stands out *less* in relative terms even as its own coverage improved. |

**Read on this**: more encouraging than the stopword experiment (no shared-tokenizer risk — this
never touches how a *question* gets tokenized, so it can't remove real matched evidence the way
stripping `call`/`use` did), and the `authenticate()` recovery reproducing via an independent
mechanism is real signal. Still a genuine trade, not a clean win — two new failure modes
(crowding, z-suppression) are real costs, not free.

---

## Scoping decisions made so far (and why)

- **CONTAINS + CALLS + INHERITS only, not REFERENCES or IMPORTS.** `REFERENCES` was measured at
  4 total edges across Django's entire 92,679-entity graph — essentially unpopulated, not a
  reliable signal to build a template on. `IMPORTS` is module-level (real, denser — 612 edges in
  Flask, 18,694 in Django), but it describes *dependency structure*, not *entity relevance* — a
  file importing a module says little about what a specific function/class inside that file does.
  Worth revisiting if a later phase specifically targets dependency-shaped queries.
- **Never use CALLS for anything beyond reporting a real, already-resolved edge.** Same standing
  rule as structural corroboration: CALLS resolution is too unreliable (7.7–28.3%) to *infer*
  anything from its *absence* — Codex's fact sheet reports what real CALLS edges exist and stays
  silent about the rest, exactly like `_neighbor_matched_idf_coverage` already does.
- **Supplement, never replace, the existing text.** A class/method with a rich docstring keeps
  every bit of that; Codex only ever adds, matching how structural corroboration is additive
  (an OR-path) rather than a replacement of the coverage floor.
- **Short names, not full `entity_id`s, in the rendered fact sheet.** Directly informed by the
  stopword experiment's dotted-path finding — this was a deliberate correction, not an oversight.

---

## Roadmap (phases — mark each as it lands, mirroring `PLAN.md`'s own discipline)

### Phase 1 — Proof of concept — **DONE, measured, not shipped**
Flat fact-sheet block, CONTAINS/CALLS/INHERITS core, appended to existing text. Real 4-repo/
56-query result recorded above.

### Phase 2 — Fix the z-suppression mechanism — **NOT STARTED**
The `fastapi-04` loss is a *ranking*-side cost, not a coverage-side one — its coverage improved,
its relative standing (z) dropped. Candidate approaches to test, each requiring the same full
before/after + negative-query validation as everything else in this project before being
preferred:
  - Down-weight the structured-summary block's contribution to BM25/ranking specifically, while
    keeping its full contribution to coverage matching (asymmetric treatment, same shape as the
    asymmetric-coverage-formula idea raised in the stopword-experiment discussion).
  - Measure whether the compression is corpus-wide or concentrated in a few high-degree entities
    (a class with unusually many children/calls could be flooding its own text disproportionately)
    before assuming a global fix is needed.

### Phase 3 — Per-node-type templates — **NOT STARTED**
The proof of concept uses one flat template for every node type. The flowchart reference image
this project started from suggests real differentiation is worth trying:
  - **Class**: Attributes (Variable children), Methods (Method children), Creates/Uses (real
    outgoing CALLS/REFERENCES to other classes).
  - **Method**: Defined in (module, from `source_location` — already deterministic, no textual
    guess needed), Calls/Flow (outgoing CALLS), Uses Variables (if extractable), Used By
    (incoming CALLS).
  - **Variable**: Defined in, Created in, Used in (methods that reference it), Related siblings.
  - Each template variant needs its own before/after measurement — no assumption that
    differentiation helps until checked, same discipline as every other change this project has
    made.

### Phase 4 — Multi-hop call hierarchy — **NOT STARTED, higher risk**
The reference image's "Call Hierarchy" panel chains several hops
(`requests.get()` → `Session.request()` → `Session.send()` → ...). Codex's Phase 1 is 1-hop only.
Multi-hop widens what's findable but also further crowds ranking and multiplies exposure to
unresolved-CALLS gaps compounding across hops. Needs its own bounded-depth experiment (real
recovery vs. real cost, same rigor as structural corroboration's own 1-hop-only decision was
justified) before being attempted — not a default extension.

### Phase 5 — Full validation before any ship decision — **NOT STARTED**
Before Codex could ever be proposed for production: full 4-repo/56-query re-run with whatever
the final template design is, explicit gain/loss table per query (not just aggregate counts, per
this project's own standing discipline), 0 negative-query regressions required (non-negotiable,
same bar as every other shipped mechanism), and a written before/after report matching the style
of `FINAL_RETRIEVAL_HARDENING_REPORT.md`.

---

## Key Design Decisions Log

| # | Decision | Rationale | Date |
|---|---|---|---|
| C1 | Supplement `_entity_text()`, never replace it | Matches structural corroboration's additive-OR-path precedent; a class with a good docstring keeps every bit of it | 2026-08-21 |
| C2 | CONTAINS + CALLS + INHERITS only; REFERENCES and IMPORTS excluded | REFERENCES measured near-unpopulated (4 edges in all of Django); IMPORTS is module-level dependency structure, not entity relevance | 2026-08-21 |
| C3 | Short (last-segment) names for neighbors in rendered text, never full `entity_id` | Directly avoids the dotted-qualified-path tokenization noise the stopword experiment found | 2026-08-21 |
| C4 | Never treat CALLS absence as a negative signal, only report real resolved edges | Same standing rule as structural corroboration; CALLS resolution (7.7-28.3%) is too unreliable to infer anything from silence | 2026-08-21 |
| C5 | No new confidence/acceptance mechanism -- text-representation change only | Keeps Codex orthogonal to the (separately open) coverage-formula and z-score-in-acceptance questions; isolates what's being tested | 2026-08-21 |

---

## Open Decisions (resume here)

- **Phase 2's exact fix for z-suppression** is not chosen yet — asymmetric ranking/coverage
  weighting is the leading candidate, not yet built or tested.
- **Whether Phase 3's per-node-type differentiation is worth the added complexity** is unmeasured
  — Phase 1's flat template already shows real signal; whether splitting it out recovers
  meaningfully more, or just adds surface area, is an open empirical question, not a foregone
  conclusion.
- **Integration point if Codex ever ships**: still undecided whether this becomes a permanent
  change to `_entity_text()` itself, a separate, parallel text field indexed alongside it, or
  something in between. Not a blocking decision for further experimentation, but should be
  settled before Phase 5.

Nothing above is scheduled — this document exists so any future session (or the next phase of
this one) can read the real state, the real numbers, and the real next step without re-deriving
any of it.
