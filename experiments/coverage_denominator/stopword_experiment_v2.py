"""
Same as stopword_experiment.py, but with the corrected 12-word set --
implement/implements removed after django-13 showed it causes a real
negative-query regression (verified: query "Where does Django implement
its own production-grade HTTP/2 server?" -- removing "implement" from
the denominator let runserver/production-warning test entities clear
the coverage floor on shared "production"+"server"+"django" words).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, "/home/user/veyra/src")

import importlib

search_mod = importlib.import_module("veyra.retrieval.search")

CANDIDATE_VERBS_V2 = frozenset({
    "call", "calls", "called", "calling",
    "actually",
    "use", "uses", "used",
    "work", "works",
    "handle", "handles",
})  # implement/implements excluded -- caused a real negative-query regression (django-13)

ORIGINAL_STOPWORDS = search_mod._STOPWORDS
EXTENDED_STOPWORDS_V2 = ORIGINAL_STOPWORDS | CANDIDATE_VERBS_V2

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
        index = build_retrieval_index(store, commit)
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
    after = run_all(EXTENDED_STOPWORDS_V2, "AFTER (v2, no implement)")

    out = {"before": before, "after": after, "candidate_verbs_v2": sorted(CANDIDATE_VERBS_V2)}
    out_path = BENCH / "results" / "stopword_experiment_v2.json"
    out_path.write_text(json.dumps(out, indent=2))
    print("wrote", out_path)


if __name__ == "__main__":
    main()
