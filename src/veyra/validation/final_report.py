"""
PLAN.md Milestone 5, Phase 5.12 -- Final Production Report.

Standard report format covering repository, structural analysis, question
engine, static verification, runtime, evidence, retrieval, git, security,
quality, and final status (PASS / FAIL / PARTIALLY VERIFIED).

**Status logic, stated precisely**: `FAIL` is reserved for a *definitive*
negative signal this session can actually check without external ground
truth -- an acceptance-criteria traceability gap (Phase 5.1), incomplete
security test coverage (Phase 5.8), or (when ground-truth *was* supplied) a
known false-verification case (Phase 5.9). `PASS` requires the
ground-truth-dependent release criterion to have been checked for real and
come back clean -- not merely "not yet disproven." Anything checkable is
clean, but the ground-truth-dependent criterion was never run (no
`FalseVerificationGroundTruth` supplied) is reported as
`PARTIALLY_VERIFIED`, the honest middle state: this project's whole
discipline (D6 and every `None` field alongside it) has been "don't claim
what isn't proven," and `PASS` without a real false-verification check
would violate that discipline at the one place PLAN.md calls a genuine
release gate.

`structural_accuracy` follows the same pattern -- present only if ground
truth was supplied, `None` otherwise -- but it is deliberately NOT part of
the status decision, since PLAN.md never states a specific accuracy
threshold as a release criterion the way it does for security coverage and
false verification.
"""

from __future__ import annotations

import enum
from dataclasses import dataclass
from pathlib import Path

from veyra.vbg import VBGStore

from .behavioral_coverage import BehavioralCoverageReport, audit_behavioral_coverage
from .conflict_audit import ConflictAuditReport, audit_conflicts
from .false_verification import FalseVerificationGroundTruth, FalseVerificationReport, audit_false_verification
from .performance import PerformanceAuditReport, audit_performance
from .question_quality import QuestionQualityReport, audit_question_quality
from .security_audit import SecurityBenchmarkReport, audit_security_coverage
from .structural_accuracy import GroundTruthSet, StructuralAccuracyReport, audit_structural_accuracy
from .traceability import TraceabilityReport, check_traceability


class ReleaseStatus(enum.Enum):
    PASS = "PASS"
    FAIL = "FAIL"
    PARTIALLY_VERIFIED = "PARTIALLY_VERIFIED"


@dataclass(frozen=True)
class FinalProductionReport:
    repository_version: str
    status: ReleaseStatus
    status_reasons: tuple[str, ...]

    performance: PerformanceAuditReport
    question_quality: QuestionQualityReport
    behavioral_coverage: BehavioralCoverageReport
    conflict_audit: ConflictAuditReport
    security: SecurityBenchmarkReport
    traceability: TraceabilityReport
    structural_accuracy: StructuralAccuracyReport | None
    false_verification: FalseVerificationReport


def _determine_status(
    traceability: TraceabilityReport,
    security: SecurityBenchmarkReport,
    false_verification: FalseVerificationReport,
) -> tuple[ReleaseStatus, tuple[str, ...]]:
    reasons: list[str] = []
    if not traceability.fully_traceable:
        reasons.append(f"{len(traceability.gaps)} acceptance-criteria traceability gap(s)")
    if not security.coverage_complete:
        reasons.append("security test coverage is incomplete")
    if reasons:
        return ReleaseStatus.FAIL, tuple(reasons)

    if false_verification.release_criterion_met is False:
        return (
            ReleaseStatus.FAIL,
            (f"{false_verification.known_incorrect_count} known false-verification case(s)",),
        )

    if false_verification.release_criterion_met is None:
        return (
            ReleaseStatus.PARTIALLY_VERIFIED,
            ("false-verification rate not yet computed -- no ground truth was supplied",),
        )

    return ReleaseStatus.PASS, ()


def build_final_report(
    store: VBGStore,
    repository_version: str,
    veyra_repo_root: Path,
    ground_truth: GroundTruthSet | None = None,
    false_verification_ground_truth: FalseVerificationGroundTruth | None = None,
) -> FinalProductionReport:
    performance = audit_performance(store, repository_version)
    question_quality = audit_question_quality(store, repository_version)
    behavioral_coverage = audit_behavioral_coverage(store, repository_version)
    conflict_audit = audit_conflicts(store, repository_version)
    security = audit_security_coverage(veyra_repo_root)
    traceability = check_traceability(veyra_repo_root)
    structural_accuracy = audit_structural_accuracy(store, ground_truth) if ground_truth is not None else None
    false_verification = audit_false_verification(store, repository_version, false_verification_ground_truth)

    status, reasons = _determine_status(traceability, security, false_verification)

    return FinalProductionReport(
        repository_version=repository_version,
        status=status,
        status_reasons=reasons,
        performance=performance,
        question_quality=question_quality,
        behavioral_coverage=behavioral_coverage,
        conflict_audit=conflict_audit,
        security=security,
        traceability=traceability,
        structural_accuracy=structural_accuracy,
        false_verification=false_verification,
    )
