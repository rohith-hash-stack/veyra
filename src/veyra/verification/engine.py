"""
PLAN.md Milestone 3, Phase 3.8 -- Verification State Engine.

"Every state transition must have a valid evidence basis." Per Design
Decision D15, that basis is computed fresh from evidence history on every
call -- never a mutated, persisted `Node.status` field. This is the exact
same discipline Phase 2.7's `summarize_knowledge()` and Phase 3.7's
`reconcile_calls()` already established; Phase 3.8 is the module that
finally ties classification (3.1), scenarios (3.4), reconciliation (3.7),
and every evidence type this project produces (STATIC/TEST/RUNTIME) into
one `VerificationState` per node.

**Precedence** (most specific/severe fact wins, evaluated in this order):
    1. BLOCKED_BY_SAFETY   -- latest classification is BLOCKED (Phase 3.1)
    2. CONFLICTED          -- this node is the source of a RUNTIME_ONLY
                              reconciled CALLS edge (Phase 3.7) -- a genuine
                              static/runtime disagreement, not just "unconfirmed"
    3. UNEXECUTABLE        -- every Scenario ever generated for this node
                              (Phase 3.4/3.3b) is currently non-executable
    4. RUNTIME_VERIFIED / RUNTIME_OBSERVED / CONDITIONALLY_VERIFIED
                            -- has RUNTIME evidence (Phase 3.5/3.6/3.3b);
                              VERIFIED if every observed run COMPLETED
                              cleanly, OBSERVED if any raised an exception,
                              CONDITIONALLY_VERIFIED if it COMPLETED cleanly
                              AND reconciliation confirms more than one
                              distinct outgoing call target (genuine
                              conditional branching, not disagreement)
    5. RUNTIME_VERIFIED / RUNTIME_OBSERVED (via TEST evidence)
                            -- no RUNTIME evidence, but an existing test
                              (Phase 3.3a) exercised it: VERIFIED if every
                              recorded test PASSed, OBSERVED otherwise
    6. STATICALLY_SUPPORTED -- has STATIC evidence (Phase 2.x) but nothing
                              from an actual execution yet
    7. UNEXPLORED           -- known only via a static CALLS edge that has
                              never been runtime-confirmed (Phase 3.7's
                              STATIC_ONLY) -- structurally known, never tried
    8. STRUCTURALLY_IDENTIFIED -- the honest default: nothing beyond bare
                              extraction is known about this node at all

**Not produced by this module, on purpose**:
  - `STALE` is Phase 4.8's job (Git Impact Analysis, Milestone 4, not
    built) -- staleness is about a *later* commit invalidating evidence
    from an earlier one, a concept this module has no inputs for yet.
  - `UNANSWERED` applies to Questions, not Nodes -- Phase 2.6/2.7's own
    `AnswerStatus`/`summarize_knowledge()` already serve that purpose
    directly; re-deriving it here would duplicate, not improve on, an
    already-correct mechanism.

**A stated, accepted coupling**: distinguishing a clean completion from an
exception (step 4/5 above) reads the leading `status=<VALUE>` token every
RUNTIME/TEST Evidence.detail this project writes always begins with (see
`harness/manager.py`/`runtime/engine.py`) -- Evidence itself (Phase 1.3) has
no structured outcome field, and adding one is out of scope for this slice.
`_evidence_status()` is the one place that coupling lives.
"""

from __future__ import annotations

from collections import defaultdict

from veyra.reconciliation import ReconciliationStatus, reconcile_calls
from veyra.vbg import Evidence, EvidenceType, SafetyClass, Scenario, VBGStore, VerificationState


def _evidence_status(evidence: Evidence) -> str | None:
    if not evidence.detail or not evidence.detail.startswith("status="):
        return None
    return evidence.detail[len("status="):].split(";", 1)[0]


def derive_verification_states(store: VBGStore, repository_version: str) -> dict[str, VerificationState]:
    """Bulk derivation -- computes reconciliation and scenario lookups once
    and reuses them across every node, rather than once per node. Prefer
    this over the single-entity convenience wrapper below whenever checking
    more than one entity."""
    nodes = store.get_all_nodes(repository_version)
    reconciliations = reconcile_calls(store, repository_version)
    scenarios = store.get_scenarios(repository_version)

    conflicted_sources = {r.source_id for r in reconciliations if r.is_conflict}
    static_only_sources = {
        r.source_id for r in reconciliations if r.status is ReconciliationStatus.STATIC_ONLY
    }
    confirmed_targets_by_source: dict[str, set[str]] = defaultdict(set)
    for r in reconciliations:
        if r.status is ReconciliationStatus.CONFIRMED:
            confirmed_targets_by_source[r.source_id].add(r.target_id)

    scenarios_by_target: dict[str, list[Scenario]] = defaultdict(list)
    for scenario in scenarios:
        scenarios_by_target[scenario.target_entity_id].append(scenario)

    return {
        node.entity_id: _derive_one(
            store, node.entity_id, repository_version,
            conflicted_sources, static_only_sources, confirmed_targets_by_source, scenarios_by_target,
        )
        for node in nodes
    }


def _derive_one(
    store: VBGStore,
    entity_id: str,
    repository_version: str,
    conflicted_sources: set[str],
    static_only_sources: set[str],
    confirmed_targets_by_source: dict[str, set[str]],
    scenarios_by_target: dict[str, list[Scenario]],
) -> VerificationState:
    classification = store.get_latest_classification(entity_id, repository_version)
    if classification is not None and classification.classification is SafetyClass.BLOCKED:
        return VerificationState.BLOCKED_BY_SAFETY

    if entity_id in conflicted_sources:
        return VerificationState.CONFLICTED

    node_scenarios = scenarios_by_target.get(entity_id, [])
    if node_scenarios and all(not s.executable for s in node_scenarios):
        return VerificationState.UNEXECUTABLE

    evidence = store.get_evidence_for_subject(entity_id, repository_version)
    runtime_evidence = [e for e in evidence if e.evidence_type is EvidenceType.RUNTIME]
    test_evidence = [e for e in evidence if e.evidence_type is EvidenceType.TEST]
    static_evidence = [e for e in evidence if e.evidence_type is EvidenceType.STATIC]

    if runtime_evidence:
        statuses = {_evidence_status(e) for e in runtime_evidence}
        if statuses and statuses <= {"COMPLETED"}:
            if len(confirmed_targets_by_source.get(entity_id, ())) > 1:
                return VerificationState.CONDITIONALLY_VERIFIED
            return VerificationState.RUNTIME_VERIFIED
        return VerificationState.RUNTIME_OBSERVED

    if test_evidence:
        statuses = {_evidence_status(e) for e in test_evidence}
        if statuses and statuses <= {"PASS"}:
            return VerificationState.RUNTIME_VERIFIED
        return VerificationState.RUNTIME_OBSERVED

    if static_evidence:
        return VerificationState.STATICALLY_SUPPORTED

    if entity_id in static_only_sources:
        return VerificationState.UNEXPLORED

    return VerificationState.STRUCTURALLY_IDENTIFIED


def derive_verification_state(store: VBGStore, entity_id: str, repository_version: str) -> VerificationState:
    """Single-entity convenience wrapper. Recomputes the full bulk map on
    every call (including reconciliation across the whole commit) -- fine
    for occasional lookups, wasteful for checking many entities; use
    derive_verification_states() directly in that case."""
    states = derive_verification_states(store, repository_version)
    return states.get(entity_id, VerificationState.STRUCTURALLY_IDENTIFIED)
