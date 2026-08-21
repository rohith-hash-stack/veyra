"""
Offline experiment: extend _STOPWORDS with generic framing verbs
(call/calls/called/calling/actually/implement/implements/use/uses/used/
work/works/handle/handles) and re-run the REAL production pipeline
end-to-end against all 4 real persisted stores.

This is NOT a coverage-only patch -- _STOPWORDS feeds the single shared
_tokenize() function used by BOTH BM25 scoring (search.py) and coverage
(context.py), so extending it changes ranking/z-scores too, not just the
coverage floor. Measuring the real, full effect via monkeypatch + a fresh
index build (so _bm25_cache is rebuilt with the new tokenization, not
reused from disk) + genuine retrieve_context() calls -- same discipline
as every other experiment this session. NOT modifying src/veyra/ files.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, "/home/user/veyra/src")

import importlib

search_mod = importlib.import_module("veyra.retrieval.search")

EXTENDED_VERBS = frozenset({
    "call", "calls", "called", "calling",
    "actually",
    "implement", "implements",
    "use", "uses", "used",
    "work", "works",
    "handle", "handles",
})

ORIGINAL_STOPWORDS = search_mod._STOPWORDS
EXTENDED_STOPWORDS = ORIGINAL_STOPWORDS | EXTENDED_VERBS

from veyra.vbg import VBGStore  # noqa: E402
from veyra.retrieval import build_retrieval_index, retrieve_context  # noqa: E402

BENCH = Path("/home/user/veyra/benchmarks/real_world_python")
REPOS = ["flask", "fastapi", "sqlalchemy", "django"]


def run_all(stopwords: frozenset[str], label: str) -> dict:
    search_mod._STOPWORDS = stopwords
    repos_meta = json.loads((BENCH / "repos.json").read_text())
    commit_by_repo = {r["name"]: r["commit_sha"] for r in repos_meta["repositories"]}

    all_results = {}
    for repo in REPOS:
        commit = commit_by_repo[repo]
        store = VBGStore(str(BENCH / "results" / f"{repo}_vbg.db"))
        index = build_retrieval_index(store, commit)  # fresh index -> fresh _bm25_cache
        gt = json.loads((BENCH / "ground_truth" / f"{repo}.json").read_text())

        repo_results = []
        for q in gt["queries"]:
            ctx = retrieve_context(store, index, commit, q["query"], top_k=10, candidate_pool_size=200)
            repo_results.append({
                "query_id": q["query_id"],
                "insufficient_evidence": ctx.insufficient_evidence,
                "accepted_entities": [e.entity_id for e in ctx.entities],
            })
        all_results[repo] = repo_results
        print(f"[{label}] {repo} done", flush=True)

    return all_results


def main() -> None:
    before = run_all(ORIGINAL_STOPWORDS, "BEFORE (current)")
    after = run_all(EXTENDED_STOPWORDS, "AFTER (extended)")

    out = {"before": before, "after": after, "extended_verbs_added": sorted(EXTENDED_VERBS)}
    out_path = BENCH / "results" / "stopword_experiment.json"
    out_path.write_text(json.dumps(out, indent=2))
    print("wrote", out_path)


if __name__ == "__main__":
    main()
