"""
Cross-milestone pipeline entry points -- the orchestrators that actually run
a milestone's phases together end to end, since no single phase module is
meant to own that job itself.

PLAN.md Milestone 2, Phase 2.8 -- Static Audit, plus `run_static_analysis()`,
which runs Phases 2.1/2.5/2.6/2.7 end to end (Milestone 2 didn't have a
single entry point tying them together until now).

Per Design Decision D6, `StaticAuditReport` is instrumentation, not a
quality benchmark: `static_precision`/`static_recall` are left as `None`
rather than computed, because computing them needs ground truth that
doesn't exist until Milestone 5's benchmark repos do. Everything else here
is a real count taken directly off what the pipeline actually produced.

`questions_deduplicated` is always 0, and that is itself a documented fact,
not a missing feature: the Phase 2.5 generator prevents duplicates by
construction (a guard check before a Question is ever built), rather than
generating-then-filtering -- there is nothing to deduplicate after the fact
because duplication was never possible in the first place.

PLAN.md Milestone 3, Phase 3.9 -- Runtime Audit, plus `run_runtime_analysis()`,
the equivalent entry point for Phases 3.3a/3.3b/3.4/3.5/3.6/3.7/3.8. See
`RuntimeAuditReport`'s own docstring for what its fields mean.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from veyra.audit import AuditTimer
from veyra.execution import ExecutionBoundary
from veyra.exploration import explore_at_ingest
from veyra.harness import TestStatus, run_existing_test_harness, synthesize_novel_scenarios
from veyra.questions import generate_questions, persist_questions, summarize_knowledge, verify_question
from veyra.reconciliation import ReconciliationStatus, reconcile_calls
from veyra.safety import PolicyConfig
from veyra.static_analysis import extract_repository, persist_extraction
from veyra.vbg import EvidenceType, VBGStore, VerificationState, parse_edge_evidence_key
from veyra.verification import derive_verification_states


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


@dataclass(frozen=True)
class RuntimeAuditReport:
    """PLAN.md Milestone 3, Phase 3.9 -- Runtime Audit.

    `verified_count`/`unverified_count` mirror Phase 2.7's verified/
    unverified split, one level deeper: "verified" here means
    RUNTIME_VERIFIED or CONDITIONALLY_VERIFIED specifically (Phase 3.8) --
    a node that is merely STATICALLY_SUPPORTED or UNEXPLORED is real,
    known, evidence-backed knowledge, but it has never been runtime-
    confirmed, so it counts as unverified at this level. Nothing here is a
    quality/precision metric (D6) -- every field is a real count of what
    the pipeline actually produced this run, not a benchmark against
    ground truth (that's Milestone 5's job).
    """

    repository_version: str
    audit_duration_seconds: float

    existing_tests_discovered: int
    existing_tests_passed: int
    existing_tests_failed: int
    existing_tests_error: int
    existing_tests_unexecutable: int

    synthesis_eligible_targets: int
    synthesis_trials_run: int

    scenarios_generated: int
    scenarios_executable: int
    scenarios_unexecutable: int
    exploration_executions_attempted: int
    exploration_executions_completed: int
    exploration_executions_exception: int
    exploration_executions_unexecutable: int

    classifications_by_class: dict[str, int]

    runtime_evidence_count: int
    runtime_nodes_observed: int
    runtime_edges_observed: int
    reconciliation_confirmed: int
    reconciliation_static_only: int
    reconciliation_conflicts: int

    verification_state_counts: dict[str, int]
    verified_count: int
    unverified_count: int


def run_runtime_analysis(
    store: VBGStore,
    repository_root: Path,
    repository_version: str,
    boundary: ExecutionBoundary,
    file_count: int,
    policy: PolicyConfig | None = None,
) -> RuntimeAuditReport:
    """Runs the full Milestone 3 runtime pipeline for one commit: existing-
    test tracing (3.3a) -> tiered eager exploration (3.6, which itself
    generates scenarios per 3.4 and executes them inside the sandbox per
    3.5) -> novel synthesis for SAFE/zero-coverage targets (3.3b) -- then
    reconciles static vs. runtime evidence (3.7) and derives verification
    states (3.8) over whatever resulted, returning the Phase 3.9 audit
    report. Mirrors run_static_analysis()'s role for Milestone 2: Phases
    3.1-3.8 are each individually testable and were tested that way
    already; this is how they actually run together for real. Requires
    Milestone 2's static pipeline to have already run against this same
    commit (scenario generation needs real Nodes to classify and
    introspect)."""
    with AuditTimer("3.x_runtime_pipeline") as timer:
        harness_report = run_existing_test_harness(store, repository_root, repository_version, boundary)
        exploration_report = explore_at_ingest(store, repository_root, repository_version, boundary, file_count)
        synthesis_report = synthesize_novel_scenarios(
            store, repository_root, repository_version, boundary, policy=policy
        )

    audit_record = timer.to_record(
        repository_commit=repository_version,
        input_size=file_count,
        output_size=exploration_report.attempted + synthesis_report.trials_run,
    )
    store.insert_audit_record(audit_record)

    scenarios = store.get_scenarios(repository_version)
    scenarios_executable = sum(1 for s in scenarios if s.executable)

    classifications_by_class: dict[str, int] = {}
    for classification in store.get_all_classifications(repository_version):
        key = classification.classification.value
        classifications_by_class[key] = classifications_by_class.get(key, 0) + 1

    runtime_evidence = store.get_all_evidence(repository_version, EvidenceType.RUNTIME)
    runtime_node_ids: set[str] = set()
    runtime_edge_count = 0
    for evidence in runtime_evidence:
        if parse_edge_evidence_key(evidence.subject_id) is not None:
            runtime_edge_count += 1
        else:
            runtime_node_ids.add(evidence.subject_id)

    reconciliations = reconcile_calls(store, repository_version)

    states = derive_verification_states(store, repository_version)
    verification_state_counts: dict[str, int] = {}
    for state in states.values():
        verification_state_counts[state.value] = verification_state_counts.get(state.value, 0) + 1
    verified_count = sum(
        1 for state in states.values()
        if state in (VerificationState.RUNTIME_VERIFIED, VerificationState.CONDITIONALLY_VERIFIED)
    )

    return RuntimeAuditReport(
        repository_version=repository_version,
        audit_duration_seconds=audit_record.duration_seconds,
        existing_tests_discovered=harness_report.tests_discovered,
        existing_tests_passed=sum(1 for o in harness_report.outcomes if o.status is TestStatus.PASS),
        existing_tests_failed=sum(1 for o in harness_report.outcomes if o.status is TestStatus.FAIL),
        existing_tests_error=sum(1 for o in harness_report.outcomes if o.status is TestStatus.ERROR),
        existing_tests_unexecutable=sum(1 for o in harness_report.outcomes if o.status is TestStatus.UNEXECUTABLE),
        synthesis_eligible_targets=synthesis_report.eligible_targets,
        synthesis_trials_run=synthesis_report.trials_run,
        scenarios_generated=len(scenarios),
        scenarios_executable=scenarios_executable,
        scenarios_unexecutable=len(scenarios) - scenarios_executable,
        exploration_executions_attempted=exploration_report.attempted,
        exploration_executions_completed=exploration_report.completed,
        exploration_executions_exception=exploration_report.exceptioned,
        exploration_executions_unexecutable=exploration_report.unexecutable,
        classifications_by_class=classifications_by_class,
        runtime_evidence_count=len(runtime_evidence),
        runtime_nodes_observed=len(runtime_node_ids),
        runtime_edges_observed=runtime_edge_count,
        reconciliation_confirmed=sum(1 for r in reconciliations if r.status is ReconciliationStatus.CONFIRMED),
        reconciliation_static_only=sum(1 for r in reconciliations if r.status is ReconciliationStatus.STATIC_ONLY),
        reconciliation_conflicts=sum(1 for r in reconciliations if r.is_conflict),
        verification_state_counts=verification_state_counts,
        verified_count=verified_count,
        unverified_count=len(states) - verified_count,
    )
