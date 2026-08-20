#!/usr/bin/env python3
"""Extracts the query-only dataset (query_id, query, category) from each
ground_truth/<repo>.json file into queries/<repo>.json -- kept as a
separate, derived deliverable per the benchmark's requested file layout,
generated from ground_truth/ (the source of truth) rather than maintained
by hand twice."""
from __future__ import annotations

import json
from pathlib import Path

BENCH_ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    for gt_path in sorted((BENCH_ROOT / "ground_truth").glob("*.json")):
        gt = json.loads(gt_path.read_text())
        queries = [{"query_id": q["query_id"], "query": q["query"], "category": q["category"]} for q in gt["queries"]]
        out = {"repository": gt["repository"], "commit_sha": gt["commit_sha"], "queries": queries}
        out_path = BENCH_ROOT / "queries" / gt_path.name
        out_path.write_text(json.dumps(out, indent=2))
        print(f"wrote {len(queries)} queries to {out_path}")


if __name__ == "__main__":
    main()
