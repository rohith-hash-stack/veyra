#!/usr/bin/env python3
"""
Runs the CURRENT, unmodified Veyra static-analysis pipeline
(`veyra.pipeline.run_static_analysis`, which itself runs Phases
2.1/2.5/2.6/2.7 -- extraction, question generation, static verification,
and knowledge-arm summarization) against one real-world repository clone,
persisting the resulting VBG into a SQLite file this benchmark can later
build a retrieval index from.

This script imports `veyra` only from the installed package under
`src/veyra` -- it does NOT modify any file under `src/veyra`. It is
benchmark infrastructure, kept entirely under `benchmarks/`.

Usage:
    python run_static_pipeline.py <repo_name>

<repo_name> must be a key in repos.json's "repositories" list. Reads repo
path/commit from repos.json; writes:
  - benchmarks/real_world_python/results/<repo_name>_vbg.db   (the VBGStore)
  - benchmarks/real_world_python/results/<repo_name>_static_audit.json
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

BENCH_ROOT = Path(__file__).resolve().parents[1]
VEYRA_ROOT = BENCH_ROOT.parents[1]
sys.path.insert(0, str(VEYRA_ROOT / "src"))

from veyra.pipeline import run_static_analysis  # noqa: E402
from veyra.vbg import VBGStore  # noqa: E402


def main() -> None:
    if len(sys.argv) != 2:
        print("usage: run_static_pipeline.py <repo_name>", file=sys.stderr)
        sys.exit(2)
    repo_name = sys.argv[1]

    repos_meta = json.loads((BENCH_ROOT / "repos.json").read_text())
    entry = next((r for r in repos_meta["repositories"] if r["name"] == repo_name), None)
    if entry is None:
        print(f"unknown repo_name {repo_name!r}", file=sys.stderr)
        sys.exit(2)

    repo_path = VEYRA_ROOT / entry["local_path"]
    commit_sha = entry["commit_sha"]

    results_dir = BENCH_ROOT / "results"
    results_dir.mkdir(exist_ok=True)
    db_path = results_dir / f"{repo_name}_vbg.db"
    db_path.unlink(missing_ok=True)

    print(f"[{repo_name}] starting run_static_analysis against {repo_path} @ {commit_sha}", flush=True)
    store = VBGStore(str(db_path))

    wall_start = time.time()
    report = run_static_analysis(store, repo_path, commit_sha)
    wall_elapsed = time.time() - wall_start

    audit = {
        "repo_name": repo_name,
        "commit_sha": commit_sha,
        "wall_clock_seconds": wall_elapsed,
        "report_analysis_duration_seconds": report.analysis_duration_seconds,
        "files_analyzed": report.files_analyzed,
        "files_failed": report.files_failed,
        "unsupported_rate": report.unsupported_rate,
        "unresolved_calls": report.unresolved_calls,
        "node_count": report.node_count,
        "edge_count": report.edge_count,
        "edges_by_relationship_type": report.edges_by_relationship_type,
        "questions_generated": report.questions_generated,
        "questions_answered": report.questions_answered,
        "questions_unanswered": report.questions_unanswered,
        "questions_deduplicated": report.questions_deduplicated,
        "static_evidence_created": report.static_evidence_created,
        "static_precision": report.static_precision,
        "static_recall": report.static_recall,
    }
    out_path = results_dir / f"{repo_name}_static_audit.json"
    out_path.write_text(json.dumps(audit, indent=2))
    print(f"[{repo_name}] done in {wall_elapsed:.1f}s -- nodes={report.node_count} edges={report.edge_count} "
          f"files_failed={report.files_failed} questions={report.questions_generated}", flush=True)


if __name__ == "__main__":
    main()
