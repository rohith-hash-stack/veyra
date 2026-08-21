"""
Phase E, Section 11 -- complementarity. For every ground-truth entity
(every symbol named in the benchmark's answerable queries), classify:
D = retrieved by deterministic (real, live retrieve_context() candidate
pool -- not just "somewhere in the raw ranking"), S = retrieved by
semantic (top-K, K fixed at 50 -- matches the deterministic candidate
pool's typical working size).

The key number this produces is S-only: does semantic retrieval recover
anything deterministic retrieval structurally cannot, or does it just
reproduce a subset of what BM25 already finds?
"""
from __future__ import annotations

import json
import pickle
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from veyra.retrieval import build_retrieval_index, search  # noqa: E402
from veyra.vbg import VBGStore  # noqa: E402

from models import cosine_similarities  # noqa: E402

BENCH = Path(__file__).resolve().parents[2] / "benchmarks" / "real_world_python"
INDEX_DIR = BENCH / "results" / "semantic_index"
REPOS = ["flask", "fastapi", "sqlalchemy", "django"]
MODELS = ["tfidf-lsa", "glove"]
K = 50


def _present(entity_ids: set[str], sym: str) -> str | None:
    for eid in entity_ids:
        if eid == sym or eid.endswith("." + sym) or eid.endswith("." + sym.split(".")[-1]):
            return eid
    return None


def main() -> None:
    repos_meta = json.loads((BENCH / "repos.json").read_text())
    commit_by_repo = {r["name"]: r["commit_sha"] for r in repos_meta["repositories"]}

    all_results = {}
    for model_name in MODELS:
        model_matrix = []
        for repo_name in REPOS:
            commit = commit_by_repo[repo_name]
            store = VBGStore(str(BENCH / "results" / f"{repo_name}_vbg.db"))
            index = build_retrieval_index(store, commit)

            idx_path = INDEX_DIR / f"{repo_name}_{model_name}.pkl"
            with open(idx_path, "rb") as f:
                data = pickle.load(f)
            entity_ids = data["entity_ids"]
            corpus_vecs = data["corpus_vecs"]
            model = data["model"]

            gt = json.loads((BENCH / "ground_truth" / f"{repo_name}.json").read_text())
            manual_scores = json.loads((BENCH / "results" / "manual_scores" / f"{repo_name}.json").read_text())

            for q in gt["queries"]:
                qid = q["query_id"]
                score = manual_scores.get(qid, {})
                if score.get("negative_query_handled_correctly") is not None:
                    continue
                gt_symbols = q.get("ground_truth_symbols") or []
                if not gt_symbols:
                    continue

                det_scored = search(index, q["query"], top_k=K, candidate_pool_size=K)
                det_ids = {s.entity.entity_id for s in det_scored}

                query_vec = model.embed_query(q["query"])
                sims = cosine_similarities(query_vec, corpus_vecs)
                top_idx = sims.argsort()[::-1][:K]
                sem_ids = {entity_ids[i] for i in top_idx}

                for sym in gt_symbols:
                    in_d = _present(det_ids, sym) is not None
                    in_s = _present(sem_ids, sym) is not None
                    if in_d and in_s:
                        cls = "both"
                    elif in_d:
                        cls = "deterministic_only"
                    elif in_s:
                        cls = "semantic_only"
                    else:
                        cls = "neither"
                    model_matrix.append({
                        "repo": repo_name, "query_id": qid, "symbol": sym, "classification": cls,
                    })

        counts = {"both": 0, "deterministic_only": 0, "semantic_only": 0, "neither": 0}
        for row in model_matrix:
            counts[row["classification"]] += 1
        all_results[model_name] = {"matrix": model_matrix, "counts": counts}
        print(f"[{model_name}] {counts}")

    out_path = BENCH / "results" / "semantic_complementarity.json"
    out_path.write_text(json.dumps(all_results, indent=2))
    print("wrote", out_path)


if __name__ == "__main__":
    main()
