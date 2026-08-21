"""
Phase E, Section 4/6 -- Recall@K against every real ground-truth entity,
for every answerable query, per repo, per model. Loads the pre-built
index (build_all.py) -- no refitting here, mirroring how a real semantic
index is built once and queried many times.

Also produces the deterministic-failure-recovery cut: of every query
whose deterministic grade is not TRUE, does the ground-truth entity show
up in this model's top-K at all (regardless of whether it would actually
be accepted -- that's a separate, later question, exactly as Phase D
kept "reachable" and "accepted" separate for candidate_pool_size)?
"""
from __future__ import annotations

import json
import pickle
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from models import cosine_similarities  # noqa: E402

BENCH = Path(__file__).resolve().parents[2] / "benchmarks" / "real_world_python"
INDEX_DIR = BENCH / "results" / "semantic_index"
REPOS = ["flask", "fastapi", "sqlalchemy", "django"]
MODELS = ["tfidf-lsa", "glove"]
K_VALUES = [1, 5, 10, 20, 50, 100]


def _rank_of(entity_ids: list[str], gt_symbol: str) -> int | None:
    for i, eid in enumerate(entity_ids):
        if eid == gt_symbol or eid.endswith("." + gt_symbol) or eid.endswith("." + gt_symbol.split(".")[-1]):
            return i + 1
    return None


def main() -> None:
    all_results = {}
    for model_name in MODELS:
        model_results = {}
        for repo_name in REPOS:
            idx_path = INDEX_DIR / f"{repo_name}_{model_name}.pkl"
            with open(idx_path, "rb") as f:
                data = pickle.load(f)
            entity_ids = data["entity_ids"]
            corpus_vecs = data["corpus_vecs"]
            model = data["model"]

            gt = json.loads((BENCH / "ground_truth" / f"{repo_name}.json").read_text())
            manual_scores = json.loads((BENCH / "results" / "manual_scores" / f"{repo_name}.json").read_text())

            recall_at = {k: 0 for k in K_VALUES}
            total_symbols = 0
            per_query = {}
            for q in gt["queries"]:
                qid = q["query_id"]
                score = manual_scores.get(qid, {})
                if score.get("negative_query_handled_correctly") is not None:
                    continue
                gt_symbols = q.get("ground_truth_symbols") or []
                if not gt_symbols:
                    continue
                query_vec = model.embed_query(q["query"])
                sims = cosine_similarities(query_vec, corpus_vecs)
                ranked_idx = sims.argsort()[::-1]
                ranked_ids = [entity_ids[i] for i in ranked_idx]

                per_query[qid] = {
                    "deterministic_grade": score.get("final_answer_correct"),
                    "symbols": {},
                }
                for sym in gt_symbols:
                    total_symbols += 1
                    rank = _rank_of(ranked_ids, sym)
                    per_query[qid]["symbols"][sym] = rank
                    if rank is not None:
                        for k in K_VALUES:
                            if rank <= k:
                                recall_at[k] += 1

            model_results[repo_name] = {
                "total_symbols": total_symbols,
                "recall_at_counts": recall_at,
                "recall_at_fraction": {k: (v / total_symbols if total_symbols else 0.0) for k, v in recall_at.items()},
                "per_query": per_query,
            }
            print(f"[{model_name}/{repo_name}] recall@10={recall_at[10]}/{total_symbols} "
                  f"recall@50={recall_at[50]}/{total_symbols}")
        all_results[model_name] = model_results

    out_path = BENCH / "results" / "semantic_recall.json"
    out_path.write_text(json.dumps(all_results, indent=2))
    print("wrote", out_path)


if __name__ == "__main__":
    main()
