# Veyra Real-World Python Benchmark -- Baseline Report (v1)

**Status: DRAFT -- results sections pending baseline pipeline completion.**

## 1. Executive Summary

_[TODO: fill in after scoring is complete]_

## 2. Experimental Setup

- **Git branch:** `experiment/real-world-python-benchmark`, branched from `claude/veyra-progress-plan-h7kthq`.
  All benchmark infrastructure lives under `benchmarks/real_world_python/`. No file under `src/veyra` was
  modified to produce the baseline results in this report.
- **Veyra commit under test:** `30b883f702b422525bcd6c37fb844635cea5c542`.
- **Python:** 3.11.15. **OS:** Linux 6.18.5-fc-v20 x86_64.
- **Benchmark date:** 2026-08-20.
- **Model/provider configuration:** none. Veyra calls no LLM anywhere in this codebase, by design (confirmed
  in `PROGRESS.md`/`PLAN.md` from the prior implementation work on this project). This benchmark exercises
  Veyra's static analysis (Phases 2.1-2.8) and retrieval (Phases 4.1-4.7) pipelines directly -- `search()`,
  `retrieve_context()`, `build_grounding_context()` -- not an LLM consuming Veyra's output. See Section 5 for
  what this means for how "final answer correctness" is scored.
- **Runtime execution (Milestone 3) not exercised:** no Docker daemon is reachable in this environment (CLI
  present, daemon unreachable -- the same limitation noted throughout this project's own test suite). Every
  entity in this benchmark's results is therefore expected to cap out at `STATICALLY_SUPPORTED` or
  `STRUCTURALLY_IDENTIFIED` verification state; no `RUNTIME_*` state should appear anywhere in the raw
  results, and the harness (`run_queries.py`) explicitly flags `any_runtime_state_present` per query so this
  claim is checked, not assumed.

## 3. Repository Details

| Repository | Commit SHA | Commit Date | Python Files | Clone Method |
|---|---|---|---|---|
| Flask | `d318b683471101618febed18996405ad26462110` | 2026-08-16 | 83 | `git clone --depth 1` |
| SQLAlchemy | `16d00eca61cfc690b2709642f4a2656fb6424875` | 2026-08-18 | 668 | `git clone --depth 1` |
| FastAPI | `c3f316b7e814667e8ee81e03a7330d00ee61e45c` | 2026-08-19 | 1138 (incl. docs_src examples) | `git clone --depth 1` |
| Django | `cccc004b46f71b4e54d87b376be691a17de6b903` | 2026-08-19 | 2929 (incl. tests/) | `git clone --depth 1` |

Full metadata (URLs, reproduction instructions) in `repos.json`.

## 4. Query Methodology

56 queries total (14 per repository), authored by hand against categories A-G specified for this benchmark:
A. symbol/location, B. relationship, C. architecture, D. behavioral, E. debugging/diagnostic, F. cross-file,
G. negative/boundary. Each repo got 3 symbol/location, 2 relationship, 2 architecture, 2 behavioral,
2 debugging, 1-2 cross-file, and 2 negative queries. Questions were written to resemble what a developer
unfamiliar with the codebase might actually ask (e.g. "How does Flask dispatch an incoming WSGI request to
the correct view function, end to end?"), not phrased around Veyra's own internal vocabulary or entity-ID
scheme.

## 5. Ground-Truth Methodology

Ground truth for every query was established by directly reading the cloned repository source at the pinned
commit (via Grep/Read against the actual clone under `benchmarks/real_world_python/repos/`), independently of
Veyra. General knowledge of these codebases was used only to form an initial hypothesis about where to look;
every file path, class name, and line number recorded in `ground_truth/*.json` was verified against the real
clone before being written down. **Veyra was not used to produce any ground truth.**

Each query's ground truth records: relevant file(s), relevant symbol(s), a line/range where practical, an
`expected_answer_summary` describing the real behavior in the developer's own terms, and three boolean flags:
`directly_supported_by_repo_evidence`, `ambiguous`, `unanswerable_from_repo`. 8 of the 56 queries (2 per repo)
are deliberate negative/boundary queries where `unanswerable_from_repo: true` -- asking about functionality
that genuinely does not exist in that repository (e.g. "Where does Flask implement CSRF protection?" -- it
doesn't; that's the separate Flask-WTF package). One query (`sqla-09`) is marked `ambiguous: true` because a
fully correct answer requires tracing one hop deeper than the rest of this query set goes.

**Important, stated scope limitation on what "Veyra's answer" means in this benchmark:** Veyra has no
answer-generation component -- there is no LLM anywhere in this codebase (see Section 2). What
`retrieve_context()`/`build_grounding_context()` produce is a *grounding context*: a ranked set of real VBG
entities, their evidence, verification states, conflicts, and unknowns, each with a natural-language hedge
note -- the payload a downstream LLM would consume to answer the user's question, not a generated
natural-language answer itself. This benchmark therefore scores what Veyra's retrieval and static-verification
layers actually produce: whether the *right entities and evidence* were retrieved and correctly labeled, not
whether a fluent English sentence was generated. This is a real, stated boundary of what Veyra is today, not
a benchmark design flaw -- and it is itself one of this report's findings (Section 9/11).

## 6. Baseline Results

_[TODO: fill in after scoring is complete -- see results/evaluation_table.json and results/*_static_audit.json]_

## 7. Per-Repository Results

_[TODO]_

## 8. Per-Query Results

Full machine-readable table: `results/evaluation_table.json`. Raw retrieval output per repo:
`results/<repo>_raw_results.json`. Static-analysis pipeline audit per repo: `results/<repo>_static_audit.json`.

## 9. Failure Analysis

Per-query scoring and reasoning is in `results/manual_scores/<repo>.json`; this section summarizes the
patterns behind the failures, established from Flask (12 answerable + 2 negative queries), FastAPI (12 + 2),
and SQLAlchemy (12 + 2), with Django scoring following the same methodology once its query run completes.

**Complete retrieval misses (correct file never in top 10) are common and get sharply worse, not better, as
repo/entity count grows:** Flask 3/12 (25%), FastAPI 6/12 (50%), SQLAlchemy 8/12 (67%) -- a clean, monotonic
trend tracking indexed-entity count (2,607 -> 13,891 -> 87,782), the opposite of what "more code to search"
alone would predict, and traceable to specific, root-caused mechanisms below rather than a vague "harder on
bigger repos" story.

**Root cause 1 -- TF-IDF favors short documents over the correct answer.** `search_semantic()`
(`veyra/retrieval/search.py`) scores entities by cosine similarity over TF-IDF vectors built from
`name + docstring + lexical_representation`. A `Variable`-typed node whose entire indexed text is its own
short name (e.g. a local variable literally named `called`, `debug`, or `test_client`) gets a term frequency
of 1.0 on that single token; the correct answer -- typically a `Class`/`Method` with hundreds of lines of
`lexical_representation` -- has the same query token diluted across many other terms, so its cosine
similarity score is frequently *lower* than a same-named or synonym-matching one-line variable. Confirmed
directly (not just inferred) by inspecting Flask's real TF-IDF vectors: `src.flask.app.Flask`'s highest-weighted
term for the word "flask" itself sits far down a 200+-term vector, while a variable node named exactly
`application` has a single dominant term. This produced 3 of Flask's 3 complete misses and is visible in
half its "PARTIAL" scores (right file, wrong entity within it).

**Root cause 2 -- no distinction between core library code and tests/docs/tooling, and it compounds with
root cause 1.** Every indexed entity, regardless of whether it lives in the actual package, a test file, a
documentation example, or a CI script, is weighted identically by `search()`. FastAPI's repository is
proportionally much heavier in these categories than Flask's -- a large `tests/` tree, a `docs_src/` tree
containing many near-duplicate tutorial variants of the same example (`tutorial001_py310.py`,
`tutorial001_an_py310.py`, `tutorial002_py310.py`, ... often 5-7 copies of essentially the same short
snippet), and top-level `scripts/`. Each near-duplicate file contributes its own short-named local variable
(e.g. 7 separate `oauth2_scheme` variables across `docs_src/security/tutorial*.py`), and root cause 1 means
each one individually outranks the real answer -- collectively burying it under repeated noise instead of
one instance of it. `fastapi-10` retrieved two unrelated CI scripts (`scripts/label_approved.py`,
`scripts/notify_translations.py`) purely because they share a `Settings.debug` field with the query's
"debug" token. This is the specific, evidenced mechanism behind FastAPI's retrieval quality being worse than
Flask's despite having ~5x more indexed entities to search -- more entities did not mean better coverage, it
meant more noise.

**Root cause 3 -- retrieval has no relevance/confidence threshold, so negative queries are handled poorly.**
`search_semantic()` returns any entity with `score > 0.0`; `search()` always returns up to `top_k` results.
There is no floor below which "no good match" is reported instead. Both repositories' negative/boundary
queries (asking about functionality that genuinely does not exist -- CSRF in Flask, an ORM in FastAPI)
returned Veyra's best-effort top 10 regardless, with nothing in the output distinguishing "solid match" from
"nothing here is actually relevant." In FastAPI's case (`fastapi-13`) the retrieved entities' own *names*
(`docs_src.sql_databases`, `test_read_with_orm_mode`) could plausibly mislead a downstream reader into
confirming the query's false premise. This traces to a structural gap, not a missing heuristic: `ScoredEntity.score`
is computed in `search()` but discarded by `retrieve_context()` before it ever reaches `RetrievedContext`/
`GroundingContext` -- there is no score left for any caller, however careful, to threshold on.

**Root cause 4 -- no stopword filtering, and incidental vocabulary collisions get more likely as a codebase
grows.** `_tokenize()` (`retrieval/search.py`) has no stopword list -- every word in a natural-language
query, including "a", "the", "is", "and", becomes a real TF-IDF term. `sqla-12`'s query contains the word
"a" ("declaring **a** class with...") and SQLAlchemy's large test suite happens to contain many local
variables named exactly `a` -- each one a perfect single-token match for that one incidental word, burying
the actual 4-file cross-file answer entirely. Separately, `sqla-01` ("Where is the Session class
**defined**?") and `sqla-03` ("Where is the Table class **defined**?") -- two queries about two unrelated
classes -- returned the *same* top 5 results, because SQLAlchemy happens to have several entities with
"defined"/"is_user_defined" baked into their own names (an unrelated `UserDefinedType` feature), and the
shared word "defined" dominates both queries' rankings regardless of subject. A larger, more vocabulary-rich
codebase mechanically increases the odds of this kind of incidental collision -- another reason retrieval
quality degrades with scale rather than improving.

**A more concerning shape of negative-query failure, confirmed across two repositories.** Beyond root cause 3's
generic irrelevant noise, SQLAlchemy's negative queries surfaced entities whose *names themselves* plausibly
confirm the false premise: `sqla-13` (asking about nonexistent HTTP routing) retrieved a real class named
`RoutingSession` and classes named `RequestA`/`RequestB` -- ordinary ORM test fixtures, but named in a way
that could easily mislead a downstream reader into believing SQLAlchemy has an HTTP routing layer. `sqla-14`
(asking about nonexistent password-hashing) retrieved `engine.url.URL.password` -- a real, correctly-identified
field, but for a database connection string, not user authentication. Combined with `fastapi-13`'s
`docs_src.sql_databases`/`test_read_with_orm_mode`, this is a 3-for-4 pattern across the negative queries
reviewed so far: a large, real-world codebase's ordinary vocabulary (test fixture names, module names, field
names) is likely to contain at least one plausible-sounding false positive for almost any "does X exist"
question, and nothing in Veyra's retrieval output flags that risk.

**Two severe, compounding performance pathologies, orthogonal to retrieval quality.** (1) SQLAlchemy's
static-analysis pipeline (`run_static_analysis()`) took 9,926s (2h 45m) for 668 files -- FastAPI, with more
files (1,138) and more nodes, took 522s (8.7 min), an ~19x difference despite FastAPI being the larger
repository by file/node count. SQLAlchemy generated 305,981 questions against 90,159 nodes (3.4
questions/node) versus FastAPI's 47,647 against 13,989 (3.4 questions/node) -- the same per-node question
density, so the gap is not question-generation volume alone. SQLAlchemy's extraction also left 159,528 calls
unresolved (far higher proportionally than any other repo), consistent with its heavy use of `@overload`-based
type stubs, deep inheritance, and dynamically-constructed classes (`Manager(BaseManager.from_queryset(QuerySet))`-style
metaprogramming is common there) defeating the extractor's same-file-only resolution and likely making the
verification stage's own graph lookups far more expensive per question. (2) `build_retrieval_index()` itself
(Phase 4.1, independent of the static-analysis stage above) also degrades sharply faster than linearly with
entity count: Flask processed 2,607 entities at ~317/s, FastAPI 13,891 at ~98/s, SQLAlchemy 87,782 at only
~23/s -- a roughly 14x throughput collapse across a 34x entity-count increase. `_build_entity()` calls
`get_parents`/`get_children`/`get_siblings`/`get_evidence_for_subject` once per node, each opening its own
SQLite connection (`VBGStore._connect()`); as the graph grows, both the per-call connection overhead and
(likely) the underlying table scans get more expensive, compounding rather than merely accumulating. Together,
these need no ground truth to state plainly: Veyra's current pipeline does not scale predictably by repo size
alone -- specific, identifiable code patterns and structural per-call storage overhead can make a smaller
repository take an order of magnitude longer than a larger one, and simply getting *to* a queryable retrieval
index on an 87K-entity codebase took nearly 4 hours end to end (static analysis + index build combined).

## 10. Strong Areas

- **No architectural hallucination of nonexistent code.** Every retrieved entity is a real, persisted VBG
  node built from actual extracted source (`IndexedEntity` is always constructed from a real `Node` -- see
  `retrieval/index.py`'s own design note). Across every query reviewed, Veyra never fabricated a class,
  function, or file that doesn't exist. Failures are retrieval/ranking misses and reasoning gaps, not invented
  facts about the codebase's structure.
- **Exact and near-exact symbol lookups work reliably.** Queries whose answer is a single, distinctively-named
  top-level symbol (`fastapi-01` FastAPI class, `fastapi-03` Depends function, `flask-02` session interface)
  consistently succeed -- `search()`'s exact/substring name-match tier (ranked above TF-IDF) does what it's
  designed to do.
- **When a multi-hop/cross-file answer does land, it lands well.** `flask-04` (route -> add_url_rule) and
  `flask-12` (blueprint registration spanning two files) show that when the relevant entities happen to score
  well individually, `retrieve_context()`'s relationship/evidence assembly genuinely produces a coherent,
  multi-entity, cross-file context -- the retrieval *architecture* is sound; its *ranking* is the bottleneck.
- **The verification-state/evidence-hedging machinery works as designed.** Every fact in this benchmark
  correctly carries `STATICALLY_SUPPORTED` (never a fabricated `RUNTIME_VERIFIED` -- checked explicitly per
  query via `any_runtime_state_present`, always `false`, exactly as expected with no Docker daemon available)
  with its corresponding hedge note. The Phase 4.7 grounding contract's honesty guarantees hold up against
  real code, even though nothing yet enforces that a downstream consumer actually reads them (Section 9,
  root cause 3).

## 11. Weak Areas

- **Ranking/precision, not recall in the aggregate, is the dominant problem.** File-level recall is
  frequently 1.0 (the right file gets indexed and is somewhere in the top 10), but the entities that actually
  answer the question are often absent, buried below noise, or represented only via a tangential `Variable`
  node -- visible only by reading past the automated file-level metric into the actual retrieved symbols
  (Section 9's root causes 1-2).
- **Multi-hop queries are systematically weaker than single-hop ones**, even when every needed fact
  individually exists in the graph: `flask-06` needed 5 methods from one file and surfaced 1; `flask-10`
  needed 2 specific methods and surfaced 0 of them (both only visible in the "unknowns" list -- referenced by
  a retrieved entity's edges, but never independently retrieved).
- **No source/test/docs/tooling weighting** turns a repository's ordinary project structure (tests, tutorial
  docs, CI scripts) into an active liability for retrieval quality on exactly the kind of well-maintained,
  well-documented, well-tested open-source project this benchmark targets.
- **No confidence signal reaches the output.** This is the single fix most likely to improve every other
  weak area at once: even without solving the ranking problem, a caller that could see "nothing scored above
  threshold" could at least suppress a misleading answer instead of confidently presenting noise.

## 12. Common Failure Patterns

1. Short-named `Variable` node (a local variable, parameter, or one-line module constant) outranks the
   correct, longer `Class`/`Method` answer via TF-IDF document-length bias.
2. Repeated near-duplicate files (test parametrizations, tutorial variants) each contribute their own
   short-named entity, collectively burying one correct answer under many small wrong ones.
3. Incidental token overlap with test/tooling/CI code (e.g. a `debug` field on an unrelated `Settings` class
   in a maintenance script) pulls in confidently-presented, entirely irrelevant results.
4. A multi-hop answer's *later* steps (the specific method 2-3 calls deep that actually explains the
   mechanism) rank below the *first* step or an unrelated same-named entity, leaving the real explanation
   sitting in the `unknowns` list rather than the retrieved facts.
5. Negative/boundary queries never come back empty or flagged low-confidence -- the same ranking noise from
   patterns 1-3 fills the top 10 regardless of whether anything is actually relevant, and in a real-world
   codebase's large surface area, some of that noise's *names* often happen to superficially support the
   query's false premise (`RoutingSession`, `URL.password`, `docs_src.sql_databases`).
6. A natural-language query's own stopwords ("a", "the", "is") get real TF-IDF weight with no filtering,
   and in a large enough codebase there is usually *some* real identifier that collides with one of them.
7. Retrieval quality (complete-miss rate) degrades monotonically with repo/entity size across all three
   repositories measured so far (25% -> 50% -> 67%), and getting to a queryable index at all becomes a
   multi-hour undertaking well before code-search quality would be the limiting factor for practical use.

## 13. Reproducibility Information

```
git clone <this repo> && git checkout experiment/real-world-python-benchmark
cd benchmarks/real_world_python
git clone --depth 1 https://github.com/pallets/flask.git repos/flask && (cd repos/flask && git checkout d318b683471101618febed18996405ad26462110)
git clone --depth 1 https://github.com/sqlalchemy/sqlalchemy.git repos/sqlalchemy && (cd repos/sqlalchemy && git checkout 16d00eca61cfc690b2709642f4a2656fb6424875)
git clone --depth 1 https://github.com/fastapi/fastapi.git repos/fastapi && (cd repos/fastapi && git checkout c3f316b7e814667e8ee81e03a7330d00ee61e45c)
git clone --depth 1 https://github.com/django/django.git repos/django && (cd repos/django && git checkout cccc004b46f71b4e54d87b376be691a17de6b903)
cd ../..
python benchmarks/real_world_python/scripts/run_static_pipeline.py <repo_name>   # per repo
python benchmarks/real_world_python/scripts/run_queries.py <repo_name>           # per repo
python benchmarks/real_world_python/scripts/merge_and_score.py
```

Repo clones and generated `.db` files are gitignored (reproducible from the pinned SHAs above, not committed
as binary/third-party blobs). Everything else in `benchmarks/real_world_python/` -- scripts, `repos.json`,
`queries/`, `ground_truth/`, `results/*.json` (excluding `.db` files), and this report -- is committed to the
experiment branch.

## 14. Honest Conclusion

_[TODO]_

## 15. Recommended Next Step

_[TODO]_
