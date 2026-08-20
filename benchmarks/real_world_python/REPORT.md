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

_[TODO]_

## 10. Strong Areas

_[TODO]_

## 11. Weak Areas

_[TODO]_

## 12. Common Failure Patterns

_[TODO]_

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
