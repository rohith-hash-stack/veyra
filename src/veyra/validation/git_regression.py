"""
PLAN.md Milestone 5, Phase 5.11 -- Git Regression Audit.

Changed files/symbols, invalidated nodes/edges, stale evidence, reverified
nodes/questions. Measure: incremental analysis/verification time,
unnecessary invalidation, missed invalidation.

A thin report over Phase 4.8's `analyze_impact()` -- the counts (changed
symbols, invalidated nodes, dependent questions) are all real and directly
computable. `unnecessary_invalidation_rate`/`missed_invalidation_rate` are
left `None`, same D6 discipline as `StaticAuditReport.static_precision`:
"was this specific invalidation actually necessary/sufficient" needs an
oracle (ground truth about which nodes' behavior truly changed) that
doesn't exist without Milestone 5's benchmark repos.
`incremental_reverification_duration_seconds` is an optional caller-supplied
timing (this module doesn't re-run analysis itself, so it can't measure
that duration on its own -- the caller times whatever reverification work
it actually does with the impact report and passes the result in).
"""

from __future__ import annotations

from dataclasses import dataclass

from veyra.invalidation import analyze_impact
from veyra.vbg import VBGStore


@dataclass(frozen=True)
class GitRegressionReport:
    old_repository_version: str
    new_repository_version: str
    changed_symbol_count: int
    invalidated_node_count: int
    runtime_dependent_invalidation_count: int
    dependent_question_count: int
    incremental_reverification_duration_seconds: float | None
    unnecessary_invalidation_rate: float | None
    missed_invalidation_rate: float | None


def audit_git_regression(
    store: VBGStore,
    old_repository_version: str,
    new_repository_version: str,
    reverification_duration_seconds: float | None = None,
) -> GitRegressionReport:
    impact = analyze_impact(store, old_repository_version, new_repository_version)

    return GitRegressionReport(
        old_repository_version=old_repository_version,
        new_repository_version=new_repository_version,
        changed_symbol_count=len(impact.tier_0),
        invalidated_node_count=len(impact.stale_entity_ids),
        runtime_dependent_invalidation_count=len(impact.tier_3),
        dependent_question_count=len(impact.tier_2_question_ids),
        incremental_reverification_duration_seconds=reverification_duration_seconds,
        unnecessary_invalidation_rate=None,
        missed_invalidation_rate=None,
    )
