# Candidate Generation & Lexical Ranking Investigation

**Erratum, found and corrected during the Fix 9 follow-up investigation.** This
report's `matched_idf_coverage` figures below were computed with a hand-rolled
`query.lower().split()` in the diagnostic script, not the real `_tokenize()` production
function (which does camelCase/snake_case splitting, punctuation stripping, and stopword
removal). Recomputed with the correct tokenizer against all four repositories: the
dominant category shrinks from 19/35 (54%) to **16/35 (46%)** of all failures — three
cases (`sqla-02`, `sqla-03`, `sqla-11`) turned out to already clear both `z >= 1.0` and
`matched_idf_coverage >= 0.5`, but still fail because they get crowded out of the final
`top_k=10` by other, higher-scoring accepted candidates (a distinct mechanism from
either candidate-pool truncation or the coverage floor, not previously named). The
z-scores, raw ranks, and pool-membership figures throughout (unaffected by this bug,
computed via the real `search_semantic`/`_relative_confidence_scores` functions) are
unchanged and still accurate. The core conclusion — `matched_idf_coverage` is the single
largest failure mechanism, confirmed across all four repositories — **still holds** at
the corrected 46%; only the precise count and three specific examples were wrong. See
`FIX_9_COVERAGE_REDESIGN_RESULTS.md` for the corrected data and what was built on it.

Diagnosis-only pass, no production code changed. Every failed/partial query in the
56-query benchmark was traced entity-by-entity through the actual retrieval pipeline
(not inferred from aggregate numbers) to find the exact stage at which the ground-truth
ground-truth entity is lost. Frozen throughout: `z >= 1.0`, `matched_idf_coverage >= 0.5`,
`candidate_pool_size = 200`, BM25 `k1=1.5`/`b=0.75`, source-category and structural
weighting. Nothing tuned against individual queries.

## A. Baseline (unchanged from Checkpoint B)

13/48 fully correct (27.1%), 6/8 negative queries correct (75%), gate 39/48 (81.25%) not met.

## Methodology

For every ground-truth symbol on every FALSE/PARTIAL query (35 of 48), across all four
repositories: resolved the symbol to a real indexed entity (name + source-file match,
manually spot-checked), then computed its exact position at each pipeline stage —
raw BM25 rank across the *entire* corpus (not just the top-200 pool), candidate-pool
membership, z-score, `matched_idf_coverage`, and the actual confidence decision — using
the real production functions (`search_semantic`, `_relative_confidence_scores`,
`_matched_idf_coverage`) against the real persisted stores, not simulated.

## B. Failure taxonomy — root-cause distribution (instruction 13)

| Category | Count | % of 35 failures |
|---|---:|---:|
| **I — confidence-rejected specifically by `matched_idf_coverage` floor** (z ≥ 1.0, i.e. statistically strong, but coverage < 0.5) | **19** | **54%** |
| I — confidence-rejected, genuinely low z (< 1.0) regardless of coverage | 9 | 26% |
| E — candidate scored but never enters the 200-wide candidate pool | 7 | 20% |
| A/D — entity missing from index / zero lexical score | 0 | 0% |

**This corrects Checkpoint B's own conclusion.** That report's top-10-list read said
"the correct entity often never enters the ranked candidate set" and named this a
lexical-ranking ceiling. This deeper, per-entity trace shows that read was too shallow:
in the large majority of failures (54%, and arguably 80% counting the low-z cases too),
the correct entity **is** in the candidate pool, and often scores as a clear statistical
outlier there — it is `matched_idf_coverage`, not candidate generation, that is the
single dominant remaining mechanism. Stated plainly because the earlier conclusion was
mine and was wrong on this evidence, not because the investigation was told to find this.

## C/D. SQLAlchemy and Django — candidate-generation analysis

Zero pool-truncation failures on Django among resolved symbols; 3 on SQLAlchemy
(`Session.add` twice, `sqlalchemy.log` once — see table in Section F). Every other
SQLAlchemy/Django failure has its target entity inside the 200-candidate pool. Concretely,
`django-09`'s `authenticate()`: rank 2 of 17,766, z=3.63 — about as strong a candidate as
this mechanism can produce — rejected purely on `coverage=0.13`.

## E. Flask/FastAPI as controls

Same distribution shape, not a SQLAlchemy/Django-specific mechanism: `flask-11`
(`FlaskClient`, z=**7.57**, the single highest z-score in the entire dataset) and
`fastapi-12` (`OAuth2PasswordBearer`, z=4.36) are both coverage-floor rejections of what
are, by z-score, the *most* statistically confident candidates measured anywhere in this
investigation. This is a real, general mechanism across all four repositories, not a
large-codebase-specific one — Checkpoint B's repo-specific framing was itself part of
what this deeper trace corrects.

## F. Document representation findings (instruction 8/10)

Inspected `_entity_text()` directly (`name + docstring + full literal source of the
node's AST span`) against real failing entities, not assumed:

- **Included**: entity name, full docstring, complete literal source body (every
  parameter name, local variable, string literal, called-function name in the body),
  type annotations that appear in the signature text.
- **Not included**: decorators (`node.lineno` for a `FunctionDef`/`ClassDef` starts at
  the `def`/`class` line in Python's AST, decorators are stored separately and fall
  outside the source span used), the enclosing class/module name (a method's own
  indexed text never literally contains its class's name unless the docstring happens
  to cross-reference it), surrounding module-level imports/context.
- **Spot-checked `Session.add`** (SQLAlchemy, a stage-E pool-truncation case): its
  docstring *does* cross-reference `` :class:`_orm.Session` `` and `` :meth:`_orm.Session.add` ``
  Sphinx directives, so "session" is present in its indexed text despite the missing
  structural class-name inclusion — this specific case is not a representation gap.
  Not exhaustively checked for every stage-E case; flagged as a real, plausible,
  *not yet confirmed at scale* contributor to the E category specifically (missing
  parent-class-name context would only affect ranking on class-name-heavy queries,
  which is exactly what several of the 7 stage-E queries look like).

**Conclusion**: document representation is not the dominant problem. It's real and rich
in the case actually inspected (SQLAlchemy docstrings are Sphinx-annotated and generally
verbose); the missing-parent-context gap is a documented, real limitation but not
established as materially responsible for the dominant (coverage-floor) failure category.

## G. Query representation findings

Not the dominant mechanism either: coverage values in the 19 dominant-category failures
range 0.00–0.20, meaning the vast majority of a natural-language query's IDF-weighted
terms simply don't appear verbatim in even a *correct* entity's indexed text — this is
an intrinsic property of natural-language questions vs. literal source-code vocabulary
(e.g. "Where does `authenticate()` check a user's credentials?" shares few exact tokens
with `authenticate()`'s own real implementation, which is about backends and settings
lookups, not the word "check" or "credentials" necessarily appearing literally). This is
evidence the **coverage floor's underlying assumption — that a correct answer should
literally contain a majority of a natural-language query's words — is itself the flawed
premise**, not that query tokenization is losing information Fix 4's stopword handling
already removes filler; nothing here suggests recovering more query tokens would help.

## H. Ranking findings — BM25 length normalization (`QuerySet` case, instruction 5-7)

Measured directly, not assumed. Django's `Class`-type document lengths: mean 170.0
tokens, **median 26** — a 6.5x gap, confirming a strongly right-skewed distribution
where the current per-type normalization's *mean* is a poor "typical length" reference
(dominated by the long tail: p99=2,168, max=29,405). `QuerySet` itself: 7,668 tokens,
45.1x the mean.

`QuerySet`'s real BM25 score for `django-01` at the current `b=0.75`: rank 27 of 10,816
Class-type candidates — not catastrophic, but well outside a top-10 view. A controlled,
non-committing sensitivity sweep (same query, same corpus, varying only `b`):

| `b` | QuerySet score | QuerySet rank | top-1 candidate |
|---|---:|---:|---|
| 0.75 (current) | 17.34 | 27/10,816 | `tests...SampleTestCase` (52 tokens) |
| 0.50 | 19.77 | 14/10,816 | `tests...FixtureTestCase` (137 tokens) |
| 0.25 | 23.62 | **4**/10,816 | `db.backends.sqlite3.operations.DatabaseOperations` |
| 0.00 (no length norm at all) | 32.23 | 17/10,816 | `db.models.base.Model` |

**Non-monotonic — lowering `b` is not simply "better."** `b=0.25` measurably helps this
one query; `b=0` (removing length normalization entirely) makes it worse again, because
without *any* length discrimination other large, legitimately-relevant classes crowd back
in ahead of it. This is real evidence that BM25 length normalization contributes to
`QuerySet`'s depressed rank, but the current per-type mean is not obviously "wrong" either
— the deeper issue is that a single linear `b` parameter cannot correctly normalize a
distribution this heavily right-skewed (mean 170 vs. median 26) regardless of its value.
**Not changed this pass** — this needs its own controlled experiment across multiple
queries/repos before any parameter or normalization-statistic change, and (per the
dominant-mechanism finding above) is not currently gating the majority of failures anyway.

**Ranking crowding**: not exhaustively re-measured this pass beyond the `QuerySet` case
above (real, but secondary, evidence — small, near-identical test-fixture classes
crowding out a correct large one). Checkpoint A already established the general
mechanism (near-identical sibling methods) exists on FastAPI; this pass did not have
budget to fully re-quantify it on SQLAlchemy/Django and is not claiming to have done so.

## I. Confidence findings

**28 of 35 (80%) of all remaining failures reach the confidence stage** (are present in
the candidate pool) before being lost. Of those, 19 (68% of the 28, 54% of all 35) are
lost specifically to `matched_idf_coverage`, not to the z-score. This is the header
number: confidence — specifically one of its two signals — is not a downstream footnote
here, it is the dominant mechanism.

## J. Failure matrix

Full per-query trace (repo, query, resolved symbol, raw rank/corpus size, pool
membership, z-score, coverage, stage) saved as structured data:
`benchmarks/real_world_python/results/failure_matrix.json` (committed alongside this
report). 35 rows, one per non-fully-correct answerable query; stage-E (pool-truncation)
rows include the deep raw rank (216–1,191) that shows those misses are not narrowly missed.

## K. Recommended next fix

**Problem**: `matched_idf_coverage >= 0.5` (Fix 3's second confidence signal, added to
stop a genuinely unanswerable query's single weak match from being accepted) rejects 19
of 35 remaining failures — including some of the statistically strongest candidates
measured in this entire investigation (z up to 7.57) — because natural-language questions
rarely share a literal majority of their words with even a correct code entity's indexed
text.

**Evidence**: Section B/I above — 54% of all failures, consistent across all four
repositories (not a large-codebase-specific artifact), with real numbers per query in the
failure matrix.

**Why this is general, not a benchmark-specific tune**: the mechanism (natural-language
query vocabulary vs. literal source-code vocabulary) is intrinsic to the query/document
pair, not to any specific repository, symbol, or benchmark query — the same shape
(few-percent to ~20% coverage on a correct match) recurs identically on Flask, FastAPI,
SQLAlchemy, and Django.

**Proposed mechanism** (for the *next* implementation pass, not built this pass): replace
a flat majority-coverage floor with a mechanism that asks a different, better-justified
question — e.g. coverage *relative to the query's own candidate pool* (the same
query-relative principle Fix 3's z-score already uses for the score signal), rather than
an absolute 50% floor no natural-language query realistically clears against source code.
This is a hypothesis to validate next, not a decision made here.

**Expected benefit**: recovering some meaningful fraction of the 19 coverage-floor
failures (several already clear every other bar cleanly).

**Risk**: this is exactly the mechanism that makes `flask-14`/`sqla-14`'s negative-query
handling work (a coincidental weak match's low coverage is *correctly* rejecting it) —
any redesign must be validated against all 8 negative queries before being judged safe,
not just the 19 positive failures it's meant to fix.

**Tests required before implementation**: a synthetic case proving high-z/low-coverage
correct-candidate recovery; a synthetic case proving a genuinely coincidental match (like
`flask-14`'s) is still rejected under the new mechanism; real-repository validation on
all four repos, not just the two that motivated it; explicit before/after negative-query
count (must not regress below 6/8).

## L. Decision

```
READY TO IMPLEMENT NEXT FIX
```

The investigation is conclusive: one mechanism (`matched_idf_coverage`'s flat threshold)
accounts for 54% of all remaining failures, confirmed across all four repositories with
real per-query evidence, not aggregate correlation. BM25 length normalization is a real,
secondary, non-monotonic effect not yet ready for a parameter change of its own. Document
representation and query tokenization are not, on the evidence gathered, the dominant
problem. The next implementation pass should target `matched_idf_coverage`'s design
specifically — validated per the tests above before being called done, and not layered
together with the length-normalization or crowding questions, which remain open,
secondary, and explicitly not addressed by this recommendation.
