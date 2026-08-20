"""
PLAN.md Milestone 5, Phase 5.10 -- Static vs Runtime Conflict Audit.

Static agreement, runtime agreement, conflicts, unresolved/resolved
conflicts. Validate: conflict != failure; conflict = evidence requiring
interpretation.

A thin, direct report over Phase 3.7's `reconcile_calls()` -- no new
computation, just PLAN.md's own M5 vocabulary applied to that phase's
existing output. `resolved_conflict_count` is always 0 in this slice: no
part of this project ever marks a `RUNTIME_ONLY` conflict "resolved" --
that would require a human or process decision this codebase deliberately
never makes on its own (per Phase 3.7's own "interpretation is left
explicit, not auto-resolved"). `unresolved_conflict_count` therefore always
equals `conflicted_count` today; the distinction exists as a field because
PLAN.md names it, not because the two can currently differ.
"""

from __future__ import annotations

from dataclasses import dataclass

from veyra.reconciliation import ReconciliationStatus, reconcile_calls
from veyra.vbg import VBGStore


@dataclass(frozen=True)
class ConflictAuditReport:
    repository_version: str
    total_relationships_checked: int
    confirmed_count: int
    static_only_count: int
    conflicted_count: int
    unresolved_conflict_count: int
    resolved_conflict_count: int


def audit_conflicts(store: VBGStore, repository_version: str) -> ConflictAuditReport:
    reconciliations = reconcile_calls(store, repository_version)
    confirmed = sum(1 for r in reconciliations if r.status is ReconciliationStatus.CONFIRMED)
    static_only = sum(1 for r in reconciliations if r.status is ReconciliationStatus.STATIC_ONLY)
    conflicted = sum(1 for r in reconciliations if r.is_conflict)

    return ConflictAuditReport(
        repository_version=repository_version,
        total_relationships_checked=len(reconciliations),
        confirmed_count=confirmed,
        static_only_count=static_only,
        conflicted_count=conflicted,
        unresolved_conflict_count=conflicted,
        resolved_conflict_count=0,
    )
