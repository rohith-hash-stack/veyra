"""
Phase E, Section 10 -- simple hybrid candidate union. Deliberately NOT a
weighted-score combination (the directive explicitly says not to invent
one yet) -- just: does deterministic-top-N UNION semantic-top-N recover
more ground-truth symbols than either alone? Reuses run_complementarity.py's
already-computed D/S membership per symbol (same K=50, same real data) --
"union recall" is exactly `both | deterministic_only | semantic_only`,
so this script derives it from that file rather than re-running retrieval.
"""
from __future__ import annotations

import json
from pathlib import Path

BENCH = Path(__file__).resolve().parents[2] / "benchmarks" / "real_world_python"


def main() -> None:
    complementarity = json.loads((BENCH / "results" / "semantic_complementarity.json").read_text())

    results = {}
    for model_name, data in complementarity.items():
        counts = data["counts"]
        total = sum(counts.values())
        det_recall = counts["both"] + counts["deterministic_only"]
        sem_recall = counts["both"] + counts["semantic_only"]
        union_recall = counts["both"] + counts["deterministic_only"] + counts["semantic_only"]
        results[model_name] = {
            "total_symbols": total,
            "deterministic_only_recall": det_recall,
            "semantic_only_recall": sem_recall,
            "union_recall": union_recall,
            "deterministic_recall_fraction": det_recall / total if total else 0.0,
            "semantic_recall_fraction": sem_recall / total if total else 0.0,
            "union_recall_fraction": union_recall / total if total else 0.0,
            "net_new_from_union": counts["semantic_only"],
        }
        print(f"[{model_name}] deterministic={det_recall}/{total} semantic={sem_recall}/{total} "
              f"union={union_recall}/{total} (net new from semantic: {counts['semantic_only']})")

    out_path = BENCH / "results" / "semantic_hybrid_union.json"
    out_path.write_text(json.dumps(results, indent=2))
    print("wrote", out_path)


if __name__ == "__main__":
    main()
