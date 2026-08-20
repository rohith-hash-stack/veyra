#!/usr/bin/env python3
"""
Runs every ground-truth query for one repository through the CURRENT,
unmodified Veyra retrieval pipeline (`veyra.retrieval.search`,
`retrieve_context`, `build_grounding_context`) against the VBGStore that
`run_static_pipeline.py` already populated, and records what Veyra
actually retrieved -- entity ids, source locations, verification states,
evidence excerpts, conflicts, and unknowns -- as raw, unscored JSON.

This script also computes a small set of OBJECTIVE, string-comparable
metrics that do not require human judgment: file-level retrieval
recall/precision against `ground_truth_files` (derived from each
retrieved entity's `source_location`, which the extractor always writes
as "<repo-relative-path>:<line-or-range>" -- see
`python_extractor.compute_module_id`/`extract_file`). Everything that
requires semantic judgment (is the retrieved evidence actually correct,
does it answer the question, is anything hallucinated) is deliberately
left for manual scoring -- see score_results.py / the benchmark report --
rather than faked here.

Imports `veyra` only from the installed package under `src/veyra`. Does
NOT modify any file under `src/veyra`.

Usage:
    python run_queries.py <repo_name>

Writes: benchmarks/real_world_python/results/<repo_name>_raw_results.json
"""
from __future__ import annotations

import json
import re
import sys
import time
from pathlib import Path

BENCH_ROOT = Path(__file__).resolve().parents[1]
VEYRA_ROOT = BENCH_ROOT.parents[1]
sys.path.insert(0, str(VEYRA_ROOT / "src"))

from veyra.retrieval import build_grounding_context, build_retrieval_index, retrieve_context  # noqa: E402
from veyra.vbg import VBGStore  # noqa: E402

_LOCATION_RE = re.compile(r"^(?P<path>.+):(?P<line>\d+)(-\d+)?$")


def _location_to_file(source_location: str | None) -> str | None:
    if not source_location:
        return None
    m = _LOCATION_RE.match(source_location)
    return m.group("path") if m else source_location


def main() -> None:
    if len(sys.argv) != 2:
        print("usage: run_queries.py <repo_name>", file=sys.stderr)
        sys.exit(2)
    repo_name = sys.argv[1]

    results_dir = BENCH_ROOT / "results"
    db_path = results_dir / f"{repo_name}_vbg.db"
    if not db_path.exists():
        print(f"no VBGStore at {db_path} -- run run_static_pipeline.py first", file=sys.stderr)
        sys.exit(1)

    repos_meta = json.loads((BENCH_ROOT / "repos.json").read_text())
    entry = next(r for r in repos_meta["repositories"] if r["name"] == repo_name)
    commit_sha = entry["commit_sha"]

    gt = json.loads((BENCH_ROOT / "ground_truth" / f"{repo_name}.json").read_text())

    store = VBGStore(str(db_path))
    print(f"[{repo_name}] building retrieval index...", flush=True)
    t0 = time.time()
    index = build_retrieval_index(store, commit_sha)
    print(f"[{repo_name}] index built in {time.time()-t0:.1f}s, {len(index)} entities", flush=True)

    raw_results = []
    for q in gt["queries"]:
        query_id = q["query_id"]
        query_text = q["query"]
        t_q = time.time()
        retrieved = retrieve_context(store, index, commit_sha, query_text, top_k=10)
        grounding = build_grounding_context(retrieved)
        elapsed = time.time() - t_q

        retrieved_files = sorted({
            f for f in (_location_to_file(e.source_location) for e in retrieved.entities) if f
        })
        retrieved_symbols = [e.entity_id for e in retrieved.entities]

        gt_files = set(q.get("ground_truth_files") or [])
        hits = gt_files & set(retrieved_files)
        # File-level recall/precision -- objective, string-comparable, no judgment involved.
        # None (not 0.0) when there's nothing to measure against, per the "mark unavailable
        # rather than invented" instruction -- a negative/unanswerable query has no ground
        # truth files to recall, so recall/precision are not meaningful for it.
        if gt_files:
            file_recall = len(hits) / len(gt_files)
            file_precision = (len(hits) / len(retrieved_files)) if retrieved_files else 0.0
        else:
            file_recall = None
            file_precision = None

        raw_results.append({
            "query_id": query_id,
            "query": query_text,
            "category": q["category"],
            "elapsed_seconds": elapsed,
            "retrieved_entities": [
                {
                    "entity_id": e.entity_id,
                    "node_type": e.node_type,
                    "name": e.name,
                    "source_location": e.source_location,
                    "verification_state": e.verification_state.value,
                    "evidence_counts": e.evidence_counts,
                    "score": retrieved.scores.get(e.entity_id),
                    "matched_by": retrieved.matched_by.get(e.entity_id),
                }
                for e in retrieved.entities
            ],
            "insufficient_evidence": retrieved.insufficient_evidence,
            "retrieved_files": retrieved_files,
            "retrieved_symbols": retrieved_symbols,
            "ground_truth_files": sorted(gt_files),
            "file_level_hits": sorted(hits),
            "file_level_recall": file_recall,
            "file_level_precision": file_precision,
            "conflicts": list(grounding.conflicts),
            "unknowns": list(grounding.unknowns),
            "facts_verification_states": [f.verification_state.value for f in grounding.facts],
            "any_runtime_state_present": any(
                f.verification_state.value.startswith("RUNTIME") for f in grounding.facts
            ),
        })

    out = {
        "repo_name": repo_name,
        "commit_sha": commit_sha,
        "index_entity_count": len(index),
        "query_count": len(raw_results),
        "results": raw_results,
    }
    out_path = results_dir / f"{repo_name}_raw_results.json"
    out_path.write_text(json.dumps(out, indent=2))
    print(f"[{repo_name}] wrote {len(raw_results)} raw query results to {out_path}", flush=True)


if __name__ == "__main__":
    main()
