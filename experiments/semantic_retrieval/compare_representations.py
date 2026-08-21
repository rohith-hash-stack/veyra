"""
Phase E, Section 6 -- representation A vs. C comparison, real data, one
repo (Flask -- smallest, fastest to iterate on) before committing to a
representation for the full 4-repo sweep. Uses TF-IDF+LSA only (fast,
local, no GloVe load needed for this sub-experiment) -- the representation
that wins here is then used for BOTH models in the main experiment.
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from veyra.retrieval import build_retrieval_index  # noqa: E402
from veyra.vbg import VBGStore  # noqa: E402

from models import TfidfLsa, cosine_similarities  # noqa: E402
from representations import REPRESENTATIONS  # noqa: E402

BENCH = Path(__file__).resolve().parents[2] / "benchmarks" / "real_world_python"


def _rank_of(entity_ids: list[str], gt_symbol: str) -> int | None:
    for i, eid in enumerate(entity_ids):
        if eid == gt_symbol or eid.endswith("." + gt_symbol) or eid.endswith("." + gt_symbol.split(".")[-1]):
            return i + 1
    return None


def main() -> None:
    repo_name = "flask"
    repos_meta = json.loads((BENCH / "repos.json").read_text())
    entry = next(r for r in repos_meta["repositories"] if r["name"] == repo_name)
    commit = entry["commit_sha"]
    store = VBGStore(str(BENCH / "results" / f"{repo_name}_vbg.db"))
    index = build_retrieval_index(store, commit)
    entities = index.all_entities()
    print(f"[{repo_name}] {len(entities)} entities")

    gt = json.loads((BENCH / "ground_truth" / f"{repo_name}.json").read_text())
    manual_scores = json.loads((BENCH / "results" / "manual_scores" / f"{repo_name}.json").read_text())

    results = {}
    for rep_name, rep_fn in REPRESENTATIONS.items():
        t0 = time.time()
        texts = [rep_fn(e, index, repo_name) for e in entities]
        avg_len = sum(len(t) for t in texts) / len(texts)
        model = TfidfLsa(n_components=200)
        corpus_vecs = model.fit_corpus(texts)
        fit_time = time.time() - t0
        entity_ids = [e.entity_id for e in entities]

        recall_at = {1: 0, 5: 0, 10: 0, 20: 0, 50: 0, 100: 0}
        total_symbols = 0
        per_query_ranks = {}
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
            for sym in gt_symbols:
                total_symbols += 1
                rank = _rank_of(ranked_ids, sym)
                per_query_ranks.setdefault(qid, {})[sym] = rank
                if rank is not None:
                    for k in recall_at:
                        if rank <= k:
                            recall_at[k] += 1

        results[rep_name] = {
            "avg_text_length_chars": avg_len,
            "fit_time_s": fit_time,
            "total_symbols": total_symbols,
            "recall_at": {k: v / total_symbols for k, v in recall_at.items()},
            "recall_at_counts": recall_at,
            "per_query_ranks": per_query_ranks,
        }
        print(f"  representation {rep_name}: avg_len={avg_len:.0f} chars, fit={fit_time:.1f}s, "
              f"recall@10={recall_at[10]}/{total_symbols}, recall@50={recall_at[50]}/{total_symbols}")

    out_path = BENCH / "results" / "semantic_representation_comparison.json"
    out_path.write_text(json.dumps(results, indent=2))
    print("wrote", out_path)


if __name__ == "__main__":
    main()
