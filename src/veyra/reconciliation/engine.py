"""
PLAN.md Milestone 3, Phase 3.7 -- Static/Runtime Evidence Reconciliation.

"Conflicting evidence... both are retained, tagged by source. Interpretation
is left explicit, not auto-resolved." Preservation, source-tagging, and
"nothing silently deleted" are ALREADY true by construction of Phase 1.2's
append-only storage and Phase 1.3's "multiple evidence records for the same
subject coexist" discipline -- nothing new needed there. This phase's real,
new contribution is `reconcile_calls()`: actually comparing the STATIC CALLS
edges Phase 2.3 extracted against the RUNTIME CALLS-edge evidence Phase 3.5/
3.6 produced, and classifying each (source, target) pair.

**Purely a read-only derivation, same discipline as Phase 2.7's
`summarize_knowledge()`**: this module never writes to `VBGStore`. Per D15,
verification state is derived from evidence history on read, never from a
mutated/persisted status field -- there is nothing here for Phase 3.7 to
insert; `reconcile_calls()` is the thing a caller (Phase 3.8's Verification
State Engine, next) calls to get today's answer, computed fresh every time.

**Only RUNTIME_ONLY represents a genuine static-vs-runtime disagreement**,
in the sense PLAN's own example describes ("static says A->B, runtime
observed A->C"): runtime actually exercised a call path static analysis
never predicted at all -- a real, informative surprise (dynamic dispatch,
a static-extraction limitation, indirection the extractor doesn't resolve).
`STATIC_ONLY` is NOT itself a conflict or a wrong prediction -- it just
means "not yet runtime-confirmed," which could equally mean "genuinely
unexplored" or "a conditional branch that legitimately wasn't taken this
run" (PLAN's own "conditional behavior representable" acceptance
criterion: two different runtime trials confirming two different static
edges from the same source, both correct, is exactly this case, and needs
no special handling here -- it falls out naturally as two independent
CONFIRMED pairs).
"""

from __future__ import annotations

import enum
from collections import defaultdict
from dataclasses import dataclass

from veyra.vbg import EvidenceType, RelationshipType, VBGStore, parse_edge_evidence_key


class ReconciliationStatus(enum.Enum):
    CONFIRMED = "CONFIRMED"  # static predicted this edge AND it was runtime-observed at least once
    STATIC_ONLY = "STATIC_ONLY"  # static predicted it; never (yet) runtime-observed -- not a conflict
    RUNTIME_ONLY = "RUNTIME_ONLY"  # runtime observed it; static analysis never predicted it -- the real conflict case


@dataclass(frozen=True)
class EdgeReconciliation:
    source_id: str
    target_id: str
    relationship_type: RelationshipType
    status: ReconciliationStatus
    static_edge_count: int
    runtime_observation_count: int

    @property
    def is_conflict(self) -> bool:
        """True only for RUNTIME_ONLY -- see module docstring for why
        STATIC_ONLY is deliberately not treated as a conflict."""
        return self.status is ReconciliationStatus.RUNTIME_ONLY


def reconcile_calls(store: VBGStore, repository_version: str) -> list[EdgeReconciliation]:
    """Reconciles CALLS specifically -- the one relationship type Phase 3.5
    actually produces runtime edge evidence for today. Sorted by
    (source_id, target_id) for deterministic, reproducible output."""
    static_edges = {
        (e.source_id, e.target_id)
        for e in store.get_all_edges(repository_version)
        if e.relationship_type is RelationshipType.CALLS
    }

    runtime_counts: dict[tuple[str, str], int] = defaultdict(int)
    for evidence in store.get_all_evidence(repository_version, EvidenceType.RUNTIME):
        parsed = parse_edge_evidence_key(evidence.subject_id)
        if parsed is None:
            continue  # node-level RUNTIME evidence, not an edge observation
        source_id, target_id, relationship_type = parsed
        if relationship_type is RelationshipType.CALLS:
            runtime_counts[(source_id, target_id)] += 1

    all_pairs = static_edges | set(runtime_counts)
    results: list[EdgeReconciliation] = []
    for source_id, target_id in sorted(all_pairs):
        is_static = (source_id, target_id) in static_edges
        runtime_count = runtime_counts.get((source_id, target_id), 0)
        if is_static and runtime_count > 0:
            status = ReconciliationStatus.CONFIRMED
        elif is_static:
            status = ReconciliationStatus.STATIC_ONLY
        else:
            status = ReconciliationStatus.RUNTIME_ONLY
        results.append(
            EdgeReconciliation(
                source_id=source_id,
                target_id=target_id,
                relationship_type=RelationshipType.CALLS,
                status=status,
                static_edge_count=1 if is_static else 0,
                runtime_observation_count=runtime_count,
            )
        )
    return results
