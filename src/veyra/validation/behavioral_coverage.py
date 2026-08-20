"""
PLAN.md Milestone 5, Phase 5.6 -- Behavioral Coverage Audit.

Report separately, never collapsed into one misleading percentage:
structural coverage, static evidence coverage, runtime observation
coverage, runtime verification coverage, unexplored nodes, unobserved
edges, unexecutable behaviors, blocked behaviors, conflicted behaviors.

Fully computable from real, already-persisted pipeline output (Phase 3.7's
reconciliation + Phase 3.8's verification states) -- no ground truth
needed, unlike Phase 5.4/5.9.

**The expectation Phase 3.1 already set, restated as an interpretive
note, not asserted in code**: given the deliberately conservative safety
classifier (most real-world functions land UNKNOWN/SANDBOXABLE, not SAFE),
`runtime_observation_coverage`/`runtime_verification_coverage` are
*expected* to be low on real-world repositories, by design -- this report
should be read against that expectation, never against a 100% target. A
low number here is not automatically a defect; a `None` recall/precision
elsewhere (Phase 5.4/5.9) is where "we don't know if this is right" lives,
not this report.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass

from veyra.reconciliation import ReconciliationStatus, reconcile_calls
from veyra.vbg import EvidenceType, VBGStore, VerificationState
from veyra.verification import derive_verification_states


@dataclass(frozen=True)
class BehavioralCoverageReport:
    repository_version: str
    total_nodes: int
    structural_coverage: int
    static_evidence_coverage: int
    runtime_observation_coverage: int
    runtime_verification_coverage: int
    unexplored_node_count: int
    unobserved_edge_count: int
    unexecutable_count: int
    blocked_count: int
    conflicted_count: int


def audit_behavioral_coverage(store: VBGStore, repository_version: str) -> BehavioralCoverageReport:
    nodes = store.get_all_nodes(repository_version)
    node_ids = {n.entity_id for n in nodes}
    states = derive_verification_states(store, repository_version)
    reconciliations = reconcile_calls(store, repository_version)

    static_subjects = {e.subject_id for e in store.get_all_evidence(repository_version, EvidenceType.STATIC)} & node_ids
    runtime_subjects = {e.subject_id for e in store.get_all_evidence(repository_version, EvidenceType.RUNTIME)} & node_ids

    state_counts: dict[VerificationState, int] = defaultdict(int)
    for state in states.values():
        state_counts[state] += 1

    return BehavioralCoverageReport(
        repository_version=repository_version,
        total_nodes=len(nodes),
        structural_coverage=len(nodes),
        static_evidence_coverage=len(static_subjects),
        runtime_observation_coverage=len(runtime_subjects),
        runtime_verification_coverage=(
            state_counts[VerificationState.RUNTIME_VERIFIED] + state_counts[VerificationState.CONDITIONALLY_VERIFIED]
        ),
        unexplored_node_count=state_counts[VerificationState.UNEXPLORED],
        unobserved_edge_count=sum(1 for r in reconciliations if r.status is ReconciliationStatus.STATIC_ONLY),
        unexecutable_count=state_counts[VerificationState.UNEXECUTABLE],
        blocked_count=state_counts[VerificationState.BLOCKED_BY_SAFETY],
        conflicted_count=state_counts[VerificationState.CONFLICTED],
    )
