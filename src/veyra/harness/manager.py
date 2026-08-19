"""
PLAN.md Milestone 3, Phase 3.3a -- Harness & Fixture Manager, the
existing-test-tracing slice (Design Decision D2: trace what the repository
already has before attempting novel scenario synthesis, 3.3b, not built
yet).

Pipeline for one repository/commit:
    discover_tests()          -- what tests exist (static, no execution)
    inspect_dependencies()    -- what packages the repo declares needing
    evaluate_installation()   -- Dependency/Installation Policy gate; a
                                  repository needing third-party packages
                                  stops here (UNSUPPORTED_ENVIRONMENT), see
                                  install_policy.py
    classify_and_audit() per test -- Safety Gate (Phase 3.1), reused as-is.
                                  A BLOCKED verdict excludes that test from
                                  the run. Everything else still only ever
                                  executes inside the boundary regardless of
                                  its class (D1) -- classification is
                                  non-load-bearing for whether isolation
                                  applies, it only decides whether THIS
                                  module invokes a given test at all.
    execute inside ExecutionBoundary (Phase 3.2) -- one container per
                                  harness run, a stdlib-only runner script
                                  (runner_script.py), zero network, the
                                  repository mounted read-only.
    persist TEST evidence      -- one Evidence(EvidenceType.TEST) row per
                                  test that actually produced a real
                                  PASS/FAIL/ERROR outcome, closing the loop
                                  on EvidenceType.TEST (defined in Phase 1.3,
                                  unused until now).

"Failed harness creation never becomes a successful behavioral claim"
(Phase 3.3 AC) is enforced structurally: TEST evidence is only ever written
for a test that actually ran inside the boundary and reported a genuine
outcome via results.json. Anything that couldn't even be attempted --
dependency-unsupported, no static node for the test, BLOCKED by safety,
container-level failure/timeout, or a missing/corrupt/incomplete
results.json -- comes back as an UNEXECUTABLE TestOutcome instead, and no
evidence is written for it.

Known, stated limitation: one container runs the whole selected test batch
sequentially under a single combined timeout, not a per-test timeout -- a
single hung test times out the entire batch. Kept simple for this first
slice; per-test isolation is a natural follow-up once this is exercised
against real repositories.
"""

from __future__ import annotations

import enum
import json
import tempfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from veyra.execution import ExecutionBoundary, ExecutionRequest, ExecutionStatus
from veyra.safety import classify_and_audit
from veyra.vbg import Evidence, EvidenceType, Provenance, SafetyClass, VBGStore

from .dependencies import inspect_dependencies
from .discovery import DiscoveredTest, discover_tests
from .install_policy import InstallationDecision, evaluate_installation
from .runner_script import RUNNER_SOURCE

_HARNESS_IMAGE = "python:3.11-alpine"
_PROVENANCE_PRODUCER = "veyra.harness.manager"
_MIN_TIMEOUT_SECONDS = 30.0
_PER_TEST_TIMEOUT_BUDGET_SECONDS = 5.0


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class TestStatus(enum.Enum):
    PASS = "PASS"
    FAIL = "FAIL"
    ERROR = "ERROR"
    UNEXECUTABLE = "UNEXECUTABLE"


class UnexecutableReason(enum.Enum):
    UNSUPPORTED_ENVIRONMENT = "UNSUPPORTED_ENVIRONMENT"  # dependency policy declined
    MISSING_STATIC_NODE = "MISSING_STATIC_NODE"  # extractor never produced this entity
    BLOCKED_BY_SAFETY = "BLOCKED_BY_SAFETY"  # Phase 3.1 classification is BLOCKED
    HARNESS_EXECUTION_FAILED = "HARNESS_EXECUTION_FAILED"  # container-level failure/timeout
    NO_RESULT_REPORTED = "NO_RESULT_REPORTED"  # results.json missing/malformed/no entry


@dataclass(frozen=True)
class TestOutcome:
    entity_id: str
    status: TestStatus
    message: str | None
    duration_seconds: float | None
    unexecutable_reason: UnexecutableReason | None = None


@dataclass(frozen=True)
class HarnessReport:
    repository_version: str
    tests_discovered: int
    tests_executed: int
    tests_unexecutable: int
    installation_decision: InstallationDecision
    installation_reason: str
    outcomes: tuple[TestOutcome, ...]


def run_existing_test_harness(
    store: VBGStore,
    repository_root: Path,
    repository_version: str,
    boundary: ExecutionBoundary,
) -> HarnessReport:
    discovered = discover_tests(repository_root)
    manifest = inspect_dependencies(repository_root)
    decision, reason = evaluate_installation(manifest)

    if decision is not InstallationDecision.SUPPORTED:
        outcomes = tuple(
            TestOutcome(
                entity_id=t.entity_id,
                status=TestStatus.UNEXECUTABLE,
                message=reason,
                duration_seconds=None,
                unexecutable_reason=UnexecutableReason.UNSUPPORTED_ENVIRONMENT,
            )
            for t in discovered
        )
        return _report(repository_version, discovered, decision, reason, outcomes)

    runnable, gated_outcomes = _apply_safety_gate(store, discovered, repository_version)

    if not runnable:
        return _report(repository_version, discovered, decision, reason, tuple(gated_outcomes))

    executed_outcomes = _execute(store, repository_root, repository_version, boundary, runnable)
    return _report(repository_version, discovered, decision, reason, tuple(gated_outcomes) + executed_outcomes)


def _report(
    repository_version: str,
    discovered: list[DiscoveredTest],
    decision: InstallationDecision,
    reason: str,
    outcomes: tuple[TestOutcome, ...],
) -> HarnessReport:
    executed = sum(1 for o in outcomes if o.status is not TestStatus.UNEXECUTABLE)
    return HarnessReport(
        repository_version=repository_version,
        tests_discovered=len(discovered),
        tests_executed=executed,
        tests_unexecutable=len(outcomes) - executed,
        installation_decision=decision,
        installation_reason=reason,
        outcomes=outcomes,
    )


def _apply_safety_gate(
    store: VBGStore, discovered: list[DiscoveredTest], repository_version: str
) -> tuple[list[DiscoveredTest], list[TestOutcome]]:
    runnable: list[DiscoveredTest] = []
    blocked: list[TestOutcome] = []
    for test in discovered:
        node = store.get_latest_node(test.entity_id, repository_version)
        if node is None:
            blocked.append(
                TestOutcome(
                    entity_id=test.entity_id,
                    status=TestStatus.UNEXECUTABLE,
                    message="no static VBG node exists for this test at this commit -- "
                    "static analysis must run before the harness can trace it",
                    duration_seconds=None,
                    unexecutable_reason=UnexecutableReason.MISSING_STATIC_NODE,
                )
            )
            continue
        result = classify_and_audit(store, node, repository_version)
        if result.classification is SafetyClass.BLOCKED:
            blocked.append(
                TestOutcome(
                    entity_id=test.entity_id,
                    status=TestStatus.UNEXECUTABLE,
                    message=result.reason,
                    duration_seconds=None,
                    unexecutable_reason=UnexecutableReason.BLOCKED_BY_SAFETY,
                )
            )
            continue
        runnable.append(test)
    return runnable, blocked


def _execute(
    store: VBGStore,
    repository_root: Path,
    repository_version: str,
    boundary: ExecutionBoundary,
    tests: list[DiscoveredTest],
) -> tuple[TestOutcome, ...]:
    with tempfile.TemporaryDirectory(prefix="veyra-harness-") as harness_dir_raw:
        harness_dir = Path(harness_dir_raw)
        (harness_dir / "run_harness.py").write_text(RUNNER_SOURCE, encoding="utf-8")
        spec = [
            {
                "entity_id": t.entity_id,
                "module_id": t.module_id,
                "module_path": t.module_path,
                "class_name": t.class_name,
                "function_name": t.function_name,
            }
            for t in tests
        ]
        (harness_dir / "spec.json").write_text(json.dumps(spec), encoding="utf-8")

        request = ExecutionRequest(
            target="existing_test_harness",
            command=("python3", "/output/run_harness.py"),
            image=_HARNESS_IMAGE,
            working_directory=repository_root,
            output_directory=harness_dir,
            timeout_seconds=max(_MIN_TIMEOUT_SECONDS, _PER_TEST_TIMEOUT_BUDGET_SECONDS * len(tests)),
        )
        handle = boundary.execute(request)
        try:
            outcome = boundary.collect_result(handle)
        finally:
            boundary.cleanup(handle)

        if outcome.status is not ExecutionStatus.COMPLETED:
            return tuple(
                TestOutcome(
                    entity_id=t.entity_id,
                    status=TestStatus.UNEXECUTABLE,
                    message=f"harness container did not complete successfully: {outcome.status.value} "
                    f"(stderr: {outcome.stderr.strip()[:500]})",
                    duration_seconds=None,
                    unexecutable_reason=UnexecutableReason.HARNESS_EXECUTION_FAILED,
                )
                for t in tests
            )

        results_path = harness_dir / "results.json"
        by_entity: dict[str, dict] = {}
        if results_path.is_file():
            try:
                payload = json.loads(results_path.read_text(encoding="utf-8"))
                by_entity = {r["entity_id"]: r for r in payload["results"]}
            except (json.JSONDecodeError, KeyError, TypeError):
                by_entity = {}

        outcomes: list[TestOutcome] = []
        for t in tests:
            record = by_entity.get(t.entity_id)
            if record is None:
                outcomes.append(
                    TestOutcome(
                        entity_id=t.entity_id,
                        status=TestStatus.UNEXECUTABLE,
                        message="harness did not report a result for this test "
                        "(missing/corrupt results.json, or no matching entry)",
                        duration_seconds=None,
                        unexecutable_reason=UnexecutableReason.NO_RESULT_REPORTED,
                    )
                )
                continue
            try:
                status = TestStatus(record["status"])
            except (KeyError, ValueError):
                outcomes.append(
                    TestOutcome(
                        entity_id=t.entity_id,
                        status=TestStatus.UNEXECUTABLE,
                        message=f"harness reported an unrecognized result record: {record!r}",
                        duration_seconds=None,
                        unexecutable_reason=UnexecutableReason.NO_RESULT_REPORTED,
                    )
                )
                continue
            test_outcome = TestOutcome(
                entity_id=t.entity_id,
                status=status,
                message=record.get("message"),
                duration_seconds=record.get("duration_seconds"),
            )
            outcomes.append(test_outcome)
            _persist_test_evidence(store, repository_version, test_outcome)

        return tuple(outcomes)


def _persist_test_evidence(store: VBGStore, repository_version: str, outcome: TestOutcome) -> None:
    detail = f"status={outcome.status.value}"
    if outcome.message:
        detail += f"; message={outcome.message[:500]}"
    if outcome.duration_seconds is not None:
        detail += f"; duration_seconds={outcome.duration_seconds:.4f}"
    store.insert_evidence(
        Evidence(
            subject_id=outcome.entity_id,
            evidence_type=EvidenceType.TEST,
            repository_version=repository_version,
            provenance=Provenance(
                producer=_PROVENANCE_PRODUCER,
                method="existing-test-suite execution inside ExecutionBoundary (Phase 3.2)",
                recorded_at=_now(),
            ),
            detail=detail,
        )
    )
