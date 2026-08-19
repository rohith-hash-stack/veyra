"""
PLAN.md Milestone 2, Phase 2.8 -- Static Audit, plus the orchestrator that
actually runs Phases 2.1/2.5/2.6/2.7 end to end (Milestone 2 didn't have a
single entry point tying them together until now).

Per Design Decision D6, this report is instrumentation, not a quality
benchmark: `static_precision`/`static_recall` are left as `None` rather than
computed, because computing them needs ground truth that doesn't exist until
Milestone 5's benchmark repos do. Everything else here is a real count taken
directly off what the pipeline actually produced.

`questions_deduplicated` is always 0, and that is itself a documented fact,
not a missing feature: the Phase 2.5 generator prevents duplicates by
construction (a guard check before a Question is ever built), rather than
generating-then-filtering -- there is nothing to deduplicate after the fact
because duplication was never possible in the first place.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from veyra.audit import AuditTimer
from veyra.questions import generate_questions, persist_questions, summarize_knowledge, verify_question
from veyra.static_analysis import extract_repository, persist_extraction
from veyra.vbg import EvidenceType, VBGStore


@dataclass(frozen=True)
class StaticAuditReport:
    repository_version: str
    analysis_duration_seconds: float

    files_analyzed: int
    files_failed: int
    unsupported_rate: float
    unresolved_calls: int

    node_count: int
    edge_count: int
    edges_by_relationship_type: dict[str, int]

    questions_generated: int
    questions_deduplicated: int
    questions_answered: int
    questions_unanswered: int

    static_evidence_created: int

    static_precision: float | None
    static_recall: float | None


def run_static_analysis(store: VBGStore, repository_root: Path, repository_version: str) -> StaticAuditReport:
    """Runs the full Milestone 2 static pipeline (extract -> persist ->
    generate questions -> persist -> verify every question) and returns the
    Phase 2.8 audit report. This is the pipeline's single entry point --
    Phases 2.1-2.7 are individually testable and were tested that way, but
    this is how they're actually meant to be run together."""
    with AuditTimer("2.x_static_analysis_pipeline") as timer:
        extraction = extract_repository(repository_root, repository_version)
        persist_extraction(store, extraction)

        questions = generate_questions(store, repository_version)
        persist_questions(store, questions)
        for question in questions:
            verify_question(store, question)

    audit_record = timer.to_record(
        repository_commit=repository_version,
        input_size=extraction.files_analyzed,
        output_size=len(extraction.nodes),
    )
    store.insert_audit_record(audit_record)

    summary = summarize_knowledge(store, repository_version)
    static_evidence_created = store.count_evidence(repository_version, EvidenceType.STATIC)

    edges_by_relationship_type: dict[str, int] = {}
    for edge in extraction.edges:
        key = edge.relationship_type.value
        edges_by_relationship_type[key] = edges_by_relationship_type.get(key, 0) + 1

    total_files = extraction.files_analyzed + len(extraction.files_failed)
    unsupported_rate = (len(extraction.files_failed) / total_files) if total_files else 0.0

    return StaticAuditReport(
        repository_version=repository_version,
        analysis_duration_seconds=audit_record.duration_seconds,
        files_analyzed=extraction.files_analyzed,
        files_failed=len(extraction.files_failed),
        unsupported_rate=unsupported_rate,
        unresolved_calls=extraction.unresolved_calls,
        node_count=len(extraction.nodes),
        edge_count=len(extraction.edges),
        edges_by_relationship_type=edges_by_relationship_type,
        questions_generated=len(questions),
        questions_deduplicated=0,
        questions_answered=len(summary.answered_question_ids),
        questions_unanswered=len(summary.unanswered_question_ids),
        static_evidence_created=static_evidence_created,
        static_precision=None,
        static_recall=None,
    )
