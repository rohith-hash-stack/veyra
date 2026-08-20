#!/usr/bin/env python3
"""
Phase B calibration: empirically determine a confidence threshold for
`search()`'s TF-IDF tier, using the real, already-persisted Flask +
FastAPI VBGStores and this benchmark's own ground truth as labeled
data -- not an arbitrary round number.

For every answerable query, labels each of search()'s TF-IDF-tier
results as "relevant" (its source file is in ground_truth_files) or
"irrelevant" (it isn't), and reports the score distribution for each
label, plus the score of the top TF-IDF hit on every NEGATIVE query
(which should ideally be suppressed by any real threshold, since there
is no true positive to find).
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

BENCH_ROOT = Path(__file__).resolve().parents[1]
VEYRA_ROOT = BENCH_ROOT.parents[1]
sys.path.insert(0, str(VEYRA_ROOT / "src"))

from veyra.retrieval.index import build_retrieval_index  # noqa: E402
from veyra.retrieval.search import search  # noqa: E402
from veyra.vbg import VBGStore  # noqa: E402

_LOCATION_RE = re.compile(r"^(?P<path>.+):(?P<line>\d+)(-\d+)?$")


def _location_to_file(source_location: str | None) -> str | None:
    if not source_location:
        return None
    m = _LOCATION_RE.match(source_location)
    return m.group("path") if m else source_location


def main() -> None:
    repos_meta = json.loads((BENCH_ROOT / "repos.json").read_text())
    relevant_scores: list[float] = []
    irrelevant_scores: list[float] = []
    negative_top_scores: list[float] = []

    for repo_name in ("flask", "fastapi"):
        entry = next(r for r in repos_meta["repositories"] if r["name"] == repo_name)
        commit = entry["commit_sha"]
        db_path = BENCH_ROOT / "results" / f"{repo_name}_vbg.db"
        store = VBGStore(str(db_path))
        index = build_retrieval_index(store, commit)
        gt = json.loads((BENCH_ROOT / "ground_truth" / f"{repo_name}.json").read_text())

        for q in gt["queries"]:
            results = search(index, q["query"], top_k=10)
            tfidf_results = [r for r in results if r.matched_by == "tfidf"]
            gt_files = set(q.get("ground_truth_files") or [])

            if q.get("unanswerable_from_repo"):
                if tfidf_results:
                    negative_top_scores.append(max(r.score for r in tfidf_results))
                continue

            for r in tfidf_results:
                f = _location_to_file(r.entity.source_location)
                if f in gt_files:
                    relevant_scores.append(r.score)
                else:
                    irrelevant_scores.append(r.score)

    def stats(name: str, xs: list[float]) -> None:
        if not xs:
            print(f"{name}: n=0")
            return
        xs_sorted = sorted(xs)
        n = len(xs_sorted)
        print(
            f"{name}: n={n} min={xs_sorted[0]:.4f} p25={xs_sorted[n//4]:.4f} "
            f"median={xs_sorted[n//2]:.4f} p75={xs_sorted[3*n//4]:.4f} max={xs_sorted[-1]:.4f}"
        )

    print("=== TF-IDF-tier score distributions (Flask + FastAPI, real data) ===")
    stats("relevant (ground-truth-file hits)", relevant_scores)
    stats("irrelevant (noise)", irrelevant_scores)
    stats("negative-query top TF-IDF score", negative_top_scores)

    # Sweep candidate thresholds and report precision/recall against the
    # relevant/irrelevant labels, plus how many negative queries would still
    # leak a TF-IDF result through at each threshold.
    print()
    print("=== Threshold sweep ===")
    candidates = [0.05, 0.08, 0.10, 0.12, 0.15, 0.18, 0.20, 0.25, 0.30]
    for t in candidates:
        tp = sum(1 for s in relevant_scores if s >= t)
        fn = sum(1 for s in relevant_scores if s < t)
        fp = sum(1 for s in irrelevant_scores if s >= t)
        leaks = sum(1 for s in negative_top_scores if s >= t)
        precision = tp / (tp + fp) if (tp + fp) else float("nan")
        recall = tp / (tp + fn) if (tp + fn) else float("nan")
        print(
            f"t={t:.2f}: relevant_kept={tp}/{len(relevant_scores)} (recall={recall:.2f}) "
            f"irrelevant_kept={fp}/{len(irrelevant_scores)} (precision={precision:.2f}) "
            f"negative_leaks={leaks}/{len(negative_top_scores)}"
        )


if __name__ == "__main__":
    main()
