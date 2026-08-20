"""
PLAN.md Milestone 5, Phase 5.3 -- End-to-End Repository Benchmark.

- Tier 1: controlled repos, known ground truth.
- Tier 2: medium real-world repos.
- Tier 3: large open-source repos.
Vary languages, frameworks, architectures, sizes, dependency structures,
dynamic behavior, external dependencies. Per the sequencing decision,
Tier 1/2/3 start Python-only; a second language is added only after the
Python pipeline clears its gates.

**`BenchmarkTier` is a distinct concept from Phase 3.6's `ExplorationTier`**,
despite sharing the numbers 1/2/3 -- that one buckets a repository by
`file_count` to bound runtime-exploration cost (D10); this one classifies
a *benchmark corpus role* (controlled-with-ground-truth vs. medium
real-world vs. large open-source). A single repository could independently
land in either tier's "1", "2", or "3" -- they answer different questions
and are never meant to be compared to each other.

**This module is the real, runnable benchmark-execution machinery** --
`run_benchmark()` genuinely drives the full M2/M3/M4 pipeline
(`run_static_analysis` -> `run_runtime_analysis` -> `run_retrieval_analysis`)
against one repository and packages every resulting report together,
tested end to end against small synthetic repositories. **Choosing real
Tier 1/2/3 candidate repositories is deliberately NOT done here** -- per
PLAN.md's own "ground-truth labeling methodology: deliberately deferred...
resolve once actual Tier 1 candidate repos are chosen," that selection (and
any decision to clone real external repositories) is a scheduled decision
point needing explicit direction, not something to invent unilaterally.
`run_benchmark()`'s `ground_truth` parameter is exactly where that future
decision plugs in -- `structural_accuracy` on the result stays `None`
without it, same as every other ground-truth-dependent field in this
milestone.
"""

from __future__ import annotations

import enum
from dataclasses import dataclass
from pathlib import Path

from veyra.execution import ExecutionBoundary
from veyra.pipeline import (
    RetrievalAuditReport,
    RuntimeAuditReport,
    StaticAuditReport,
    run_retrieval_analysis,
    run_runtime_analysis,
    run_static_analysis,
)
from veyra.safety import PolicyConfig
from veyra.vbg import VBGStore

from .structural_accuracy import GroundTruthSet, StructuralAccuracyReport, audit_structural_accuracy


class BenchmarkTier(enum.Enum):
    TIER_1_CONTROLLED = "TIER_1_CONTROLLED"
    TIER_2_MEDIUM_REAL_WORLD = "TIER_2_MEDIUM_REAL_WORLD"
    TIER_3_LARGE_OPEN_SOURCE = "TIER_3_LARGE_OPEN_SOURCE"


@dataclass(frozen=True)
class BenchmarkRunResult:
    repository_version: str
    tier: BenchmarkTier
    static_report: StaticAuditReport
    runtime_report: RuntimeAuditReport
    retrieval_report: RetrievalAuditReport
    structural_accuracy: StructuralAccuracyReport | None


def run_benchmark(
    store: VBGStore,
    repository_root: Path,
    repository_version: str,
    tier: BenchmarkTier,
    boundary: ExecutionBoundary,
    file_count: int,
    sample_queries: list[str],
    ground_truth: GroundTruthSet | None = None,
    policy: PolicyConfig | None = None,
) -> BenchmarkRunResult:
    static_report = run_static_analysis(store, repository_root, repository_version)
    runtime_report = run_runtime_analysis(store, repository_root, repository_version, boundary, file_count, policy)
    retrieval_report = run_retrieval_analysis(store, repository_version, sample_queries)
    structural_accuracy = audit_structural_accuracy(store, ground_truth) if ground_truth is not None else None

    return BenchmarkRunResult(
        repository_version=repository_version,
        tier=tier,
        static_report=static_report,
        runtime_report=runtime_report,
        retrieval_report=retrieval_report,
        structural_accuracy=structural_accuracy,
    )
