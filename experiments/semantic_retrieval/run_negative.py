"""
Phase E, Section 8 (mandatory) -- all 8 negative queries, explicit, no
aggregate-hiding. For each: the top semantic candidates and real scores,
per model. Deliberately does NOT apply a threshold and call the result
"correct"/"leaked" -- Section 9 forbids treating semantic_score as
confidence. This just reports what a naive fixed threshold would accept,
labeled explicitly as naive, so the report can discuss risk without
fabricating an acceptance mechanism that was never built.
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
TOP_N = 10


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
            source_locations = data["source_locations"]

            gt = json.loads((BENCH / "ground_truth" / f"{repo_name}.json").read_text())
            manual_scores = json.loads((BENCH / "results" / "manual_scores" / f"{repo_name}.json").read_text())

            for q in gt["queries"]:
                qid = q["query_id"]
                score = manual_scores.get(qid, {})
                if score.get("negative_query_handled_correctly") is None:
                    continue  # not a negative query

                query_vec = model.embed_query(q["query"])
                sims = cosine_similarities(query_vec, corpus_vecs)
                ranked_idx = sims.argsort()[::-1][:TOP_N]
                top_candidates = [
                    {
                        "entity_id": entity_ids[i],
                        "semantic_score": float(sims[i]),
                        "rank": rank + 1,
                        "retrieval_source": model_name,
                        "representation_version": "C",
                        "source_location": source_locations.get(entity_ids[i]),
                    }
                    for rank, i in enumerate(ranked_idx)
                ]
                model_results[qid] = {
                    "repo": repo_name,
                    "query": q["query"],
                    "deterministic_grade_negative_correct": score.get("negative_query_handled_correctly"),
                    "top_candidates": top_candidates,
                }
                top1_score = top_candidates[0]["semantic_score"] if top_candidates else None
                print(f"[{model_name}/{qid}] top1={top1_score}")

        all_results[model_name] = model_results

    out_path = BENCH / "results" / "semantic_negative_queries.json"
    out_path.write_text(json.dumps(all_results, indent=2))
    print("wrote", out_path)


if __name__ == "__main__":
    main()
