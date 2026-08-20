"""
PLAN.md Milestone 5, Phase 5.7 -- Performance Audit.

Time every stage: clone, analysis, graph construction, question
generation, static verification, harness generation, runtime, evidence
processing, index construction, retrieval latency, incremental update
duration. Also: CPU, memory, storage, graph size, evidence count,
question count, trace size, index size.

**Timing is grouped by phase name, not hardcoded to a known phase list**:
`VBGStore.get_all_audit_records()` (new) returns every `AuditRecord` ever
persisted for a commit, from any phase -- this module just groups and
aggregates what's actually there, so it automatically covers every stage
that already uses `AuditTimer` (Phase 1.5's shared mechanism) without this
module needing its own registry of phase-name strings to stay in sync with.

**CPU/memory are not populated**: `AuditRecord.memory_bytes` exists as a
field (Phase 1.5) but nothing in this codebase currently measures process
memory at a phase boundary -- reported as `None` per record, a real,
already-existing gap (not new to this phase), not silently invented here.

**"Trace size"** is reported as the count of RUNTIME evidence records --
individual trace *events* (Phase 3.5's `TraceEvent` list) are never
persisted on their own, only summarized into Evidence rows, so this is the
closest real, already-stored proxy, not a literal per-event count.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass

from veyra.vbg import EvidenceType, VBGStore


@dataclass(frozen=True)
class StageTiming:
    phase: str
    run_count: int
    total_duration_seconds: float
    average_duration_seconds: float


@dataclass(frozen=True)
class PerformanceAuditReport:
    repository_version: str
    stage_timings: tuple[StageTiming, ...]
    node_count: int
    edge_count: int
    evidence_count: int
    question_count: int
    trace_evidence_count: int
    index_size: int


def audit_performance(store: VBGStore, repository_version: str) -> PerformanceAuditReport:
    records = store.get_all_audit_records(repository_version)
    by_phase: dict[str, list[float]] = defaultdict(list)
    for record in records:
        by_phase[record.phase].append(record.duration_seconds)

    stage_timings = tuple(
        StageTiming(
            phase=phase,
            run_count=len(durations),
            total_duration_seconds=sum(durations),
            average_duration_seconds=sum(durations) / len(durations),
        )
        for phase, durations in sorted(by_phase.items())
    )

    node_count = len(store.get_all_nodes(repository_version))
    edge_count = len(store.get_all_edges(repository_version))

    return PerformanceAuditReport(
        repository_version=repository_version,
        stage_timings=stage_timings,
        node_count=node_count,
        edge_count=edge_count,
        evidence_count=store.count_evidence(repository_version),
        question_count=len(store.get_questions(repository_version)),
        trace_evidence_count=store.count_evidence(repository_version, EvidenceType.RUNTIME),
        index_size=node_count,  # the retrieval index (Phase 4.1) indexes exactly one entity per node
    )
