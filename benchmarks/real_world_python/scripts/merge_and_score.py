#!/usr/bin/env python3
"""
Merges each repo's ground_truth/<repo>.json with results/<repo>_raw_results.json
into one evaluation-table row per query, matching the field list the
benchmark spec requires (repository, commit_sha, query_id, query, category,
ground_truth_files/symbols, expected_answer_summary, veyra_retrieved_files/
symbols, retrieval_hit, retrieval_precision, retrieval_recall,
final_answer_correct, unsupported_claim, multi_hop, negative_query,
failure_category, notes).

The objective fields (retrieval_hit/precision/recall, retrieved files/
symbols) come straight from run_queries.py's raw output -- pure string
comparison, no judgment involved. The subjective fields (final_answer_correct,
unsupported_claim, failure_category, and per-query notes) are NOT computed
here -- they require a human to actually read Veyra's retrieved evidence
against the ground truth and judge whether it's correct, which is exactly
what this benchmark's spec says must not be faked. Those fields are seeded
as null/"UNSCORED" and filled in by manual review, recorded in
results/manual_scores/<repo>.json (one small hand-written file per repo,
keyed by query_id) which this script merges in if present.

Usage:
    python merge_and_score.py
Writes: benchmarks/real_world_python/results/evaluation_table.json
"""
from __future__ import annotations

import json
from pathlib import Path

BENCH_ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    rows = []
    for gt_path in sorted((BENCH_ROOT / "ground_truth").glob("*.json")):
        repo_name = gt_path.stem
        gt = json.loads(gt_path.read_text())
        raw_path = BENCH_ROOT / "results" / f"{repo_name}_raw_results.json"
        if not raw_path.exists():
            print(f"skip {repo_name}: no raw results yet")
            continue
        raw = json.loads(raw_path.read_text())
        raw_by_id = {r["query_id"]: r for r in raw["results"]}

        manual_path = BENCH_ROOT / "results" / "manual_scores" / f"{repo_name}.json"
        manual_by_id = json.loads(manual_path.read_text()) if manual_path.exists() else {}

        for q in gt["queries"]:
            qid = q["query_id"]
            r = raw_by_id.get(qid)
            manual = manual_by_id.get(qid, {})
            if r is None:
                rows.append({"query_id": qid, "error": "no raw result found"})
                continue

            retrieval_hit = (
                bool(r["file_level_hits"]) if q.get("ground_truth_files") else None
            )
            row = {
                "repository": repo_name,
                "commit_sha": gt["commit_sha"],
                "query_id": qid,
                "query": q["query"],
                "category": q["category"],
                "ground_truth_files": q.get("ground_truth_files") or [],
                "ground_truth_symbols": q.get("ground_truth_symbols") or [],
                "expected_answer_summary": q.get("expected_answer_summary"),
                "unanswerable_from_repo": q.get("unanswerable_from_repo", False),
                "veyra_retrieved_files": r["retrieved_files"],
                "veyra_retrieved_symbols": r["retrieved_symbols"],
                "retrieval_hit": retrieval_hit,
                "retrieval_precision": r["file_level_precision"],
                "retrieval_recall": r["file_level_recall"],
                "any_runtime_state_present": r.get("any_runtime_state_present"),
                "conflicts_reported": r.get("conflicts"),
                "unknowns_reported": r.get("unknowns"),
                "elapsed_seconds": r.get("elapsed_seconds"),
                # Subjective -- filled from results/manual_scores/<repo>.json, else UNSCORED.
                "final_answer_correct": manual.get("final_answer_correct", "UNSCORED"),
                "unsupported_claim": manual.get("unsupported_claim", "UNSCORED"),
                "localization_correct": manual.get("localization_correct", "UNSCORED"),
                "multi_hop": manual.get("multi_hop", "UNSCORED"),
                "negative_query_handled_correctly": manual.get(
                    "negative_query_handled_correctly", "UNSCORED"
                ),
                "failure_category": manual.get("failure_category", "UNSCORED"),
                "notes": manual.get("notes", ""),
            }
            rows.append(row)

    out_path = BENCH_ROOT / "results" / "evaluation_table.json"
    out_path.write_text(json.dumps(rows, indent=2))
    print(f"wrote {len(rows)} rows to {out_path}")

    unscored = sum(1 for r in rows if r.get("final_answer_correct") == "UNSCORED")
    print(f"{unscored} of {len(rows)} rows still need manual scoring in results/manual_scores/<repo>.json")


if __name__ == "__main__":
    main()
