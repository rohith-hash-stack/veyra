"""
Manager orchestration tests using a FakeExecutionBoundary -- no Docker
required for this file. Proves the dependency gate, safety gate, and
result/evidence handling independent of any real sandbox backend, the same
pattern tests/execution/test_boundary_contract.py already established for
Phase 3.2. Real end-to-end proof against a live container lives in
test_manager_docker.py (requires_docker).
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Callable

from veyra.execution import ExecutionHandle, ExecutionOutcome, ExecutionRequest, ExecutionStatus
from veyra.harness import (
    InstallationDecision,
    TestStatus,
    UnexecutableReason,
    run_existing_test_harness,
)
from veyra.vbg import EvidenceType, ExecutionEnvironment, Node, VBGStore

COMMIT = "commit1"


class FakeExecutionBoundary:
    def __init__(self, status: ExecutionStatus = ExecutionStatus.COMPLETED, write_results: bool = True, canned: dict | None = None) -> None:
        self.status = status
        self.write_results = write_results
        self.canned = canned or {}
        self.requests: list[ExecutionRequest] = []

    def execute(self, request: ExecutionRequest) -> ExecutionHandle:
        self.requests.append(request)
        env = ExecutionEnvironment(
            environment_id="fake", backend="fake", image=request.image, network_enabled=False,
            memory_limit_mb=request.memory_limit_mb, cpu_limit=request.cpu_limit,
            timeout_seconds=request.timeout_seconds, non_privileged=True, read_only_filesystem=True,
        )
        return ExecutionHandle(handle_id="fake-handle", environment=env, started_at=time.time())

    def terminate(self, handle: ExecutionHandle) -> None:
        pass

    def collect_result(self, handle: ExecutionHandle, timeout_seconds: float | None = None) -> ExecutionOutcome:
        request = self.requests[-1]
        if self.status is ExecutionStatus.COMPLETED and self.write_results and request.output_directory is not None:
            spec = json.loads((request.output_directory / "spec.json").read_text())
            results = [
                self.canned.get(
                    item["entity_id"],
                    {"entity_id": item["entity_id"], "status": "PASS", "message": None, "duration_seconds": 0.001},
                )
                for item in spec
            ]
            (request.output_directory / "results.json").write_text(json.dumps({"results": results}))
        return ExecutionOutcome(
            status=self.status,
            exit_code=0 if self.status is ExecutionStatus.COMPLETED else None,
            stdout="", stderr="" if self.status is ExecutionStatus.COMPLETED else "boom",
            duration_seconds=0.01, environment=handle.environment,
        )

    def cleanup(self, handle: ExecutionHandle) -> None:
        pass


def _persist_node(store: VBGStore, entity_id: str, source: str) -> None:
    store.insert_node(
        Node(
            entity_id=entity_id, type="Function", name=entity_id.rsplit(".", 1)[-1],
            repository_version=COMMIT, language="Python", lexical_representation=source,
        )
    )


def test_dependency_unsupported_short_circuits_before_any_execution(
    write_file: Callable[[str, str], Path], repo_root: Path, store: VBGStore
) -> None:
    write_file("requirements.txt", "requests\n")
    write_file("test_thing.py", "def test_ok():\n    assert True\n")
    boundary = FakeExecutionBoundary()

    report = run_existing_test_harness(store, repo_root, COMMIT, boundary)

    assert report.installation_decision is InstallationDecision.UNSUPPORTED_ENVIRONMENT
    assert report.tests_discovered == 1
    assert report.tests_executed == 0
    assert report.outcomes[0].status is TestStatus.UNEXECUTABLE
    assert report.outcomes[0].unexecutable_reason is UnexecutableReason.UNSUPPORTED_ENVIRONMENT
    assert boundary.requests == []  # never even tried to start a container


def test_missing_static_node_is_unexecutable(
    write_file: Callable[[str, str], Path], repo_root: Path, store: VBGStore
) -> None:
    write_file("test_thing.py", "def test_ok():\n    assert True\n")
    boundary = FakeExecutionBoundary()

    report = run_existing_test_harness(store, repo_root, COMMIT, boundary)

    assert report.tests_discovered == 1
    assert report.outcomes[0].status is TestStatus.UNEXECUTABLE
    assert report.outcomes[0].unexecutable_reason is UnexecutableReason.MISSING_STATIC_NODE
    assert boundary.requests == []


def test_blocked_capability_test_is_excluded_from_the_run(
    write_file: Callable[[str, str], Path], repo_root: Path, store: VBGStore
) -> None:
    write_file("test_thing.py", "import subprocess\n\ndef test_danger():\n    subprocess.run(['ls'])\n")
    _persist_node(store, "test_thing.test_danger", "import subprocess\n\ndef test_danger():\n    subprocess.run(['ls'])\n")
    boundary = FakeExecutionBoundary()

    report = run_existing_test_harness(store, repo_root, COMMIT, boundary)

    assert report.outcomes[0].status is TestStatus.UNEXECUTABLE
    assert report.outcomes[0].unexecutable_reason is UnexecutableReason.BLOCKED_BY_SAFETY
    assert boundary.requests == []  # BLOCKED tests never reach the boundary at all


def test_successful_run_persists_test_evidence(
    write_file: Callable[[str, str], Path], repo_root: Path, store: VBGStore
) -> None:
    write_file("test_thing.py", "def test_ok():\n    assert True\n")
    _persist_node(store, "test_thing.test_ok", "def test_ok():\n    assert True\n")
    boundary = FakeExecutionBoundary()

    report = run_existing_test_harness(store, repo_root, COMMIT, boundary)

    assert report.tests_executed == 1
    assert report.outcomes[0].status is TestStatus.PASS
    assert len(boundary.requests) == 1
    evidence = store.get_evidence_for_subject("test_thing.test_ok", COMMIT)
    assert len(evidence) == 1
    assert evidence[0].evidence_type is EvidenceType.TEST
    assert "PASS" in evidence[0].detail


def test_failing_test_still_produces_evidence(
    write_file: Callable[[str, str], Path], repo_root: Path, store: VBGStore
) -> None:
    write_file("test_thing.py", "def test_bad():\n    assert False\n")
    _persist_node(store, "test_thing.test_bad", "def test_bad():\n    assert False\n")
    boundary = FakeExecutionBoundary(
        canned={"test_thing.test_bad": {"entity_id": "test_thing.test_bad", "status": "FAIL", "message": "boom", "duration_seconds": 0.002}}
    )

    report = run_existing_test_harness(store, repo_root, COMMIT, boundary)

    assert report.outcomes[0].status is TestStatus.FAIL
    evidence = store.get_evidence_for_subject("test_thing.test_bad", COMMIT)
    assert len(evidence) == 1
    assert "FAIL" in evidence[0].detail
    assert "boom" in evidence[0].detail


def test_container_failure_marks_all_unexecutable_and_writes_no_evidence(
    write_file: Callable[[str, str], Path], repo_root: Path, store: VBGStore
) -> None:
    write_file("test_thing.py", "def test_ok():\n    assert True\n")
    _persist_node(store, "test_thing.test_ok", "def test_ok():\n    assert True\n")
    boundary = FakeExecutionBoundary(status=ExecutionStatus.TIMED_OUT)

    report = run_existing_test_harness(store, repo_root, COMMIT, boundary)

    assert report.outcomes[0].status is TestStatus.UNEXECUTABLE
    assert report.outcomes[0].unexecutable_reason is UnexecutableReason.HARNESS_EXECUTION_FAILED
    assert store.get_evidence_for_subject("test_thing.test_ok", COMMIT) == []


def test_missing_results_file_marks_unexecutable(
    write_file: Callable[[str, str], Path], repo_root: Path, store: VBGStore
) -> None:
    write_file("test_thing.py", "def test_ok():\n    assert True\n")
    _persist_node(store, "test_thing.test_ok", "def test_ok():\n    assert True\n")
    boundary = FakeExecutionBoundary(write_results=False)

    report = run_existing_test_harness(store, repo_root, COMMIT, boundary)

    assert report.outcomes[0].status is TestStatus.UNEXECUTABLE
    assert report.outcomes[0].unexecutable_reason is UnexecutableReason.NO_RESULT_REPORTED
    assert store.get_evidence_for_subject("test_thing.test_ok", COMMIT) == []


def test_unrecognized_status_value_is_unexecutable_not_a_crash(
    write_file: Callable[[str, str], Path], repo_root: Path, store: VBGStore
) -> None:
    write_file("test_thing.py", "def test_weird():\n    assert True\n")
    _persist_node(store, "test_thing.test_weird", "def test_weird():\n    assert True\n")
    boundary = FakeExecutionBoundary(
        canned={"test_thing.test_weird": {"entity_id": "test_thing.test_weird", "status": "WEIRD", "message": None, "duration_seconds": 0.0}}
    )

    report = run_existing_test_harness(store, repo_root, COMMIT, boundary)

    assert report.outcomes[0].status is TestStatus.UNEXECUTABLE
    assert report.outcomes[0].unexecutable_reason is UnexecutableReason.NO_RESULT_REPORTED
    assert store.get_evidence_for_subject("test_thing.test_weird", COMMIT) == []


def test_no_tests_discovered_yields_empty_report(repo_root: Path, store: VBGStore) -> None:
    boundary = FakeExecutionBoundary()
    report = run_existing_test_harness(store, repo_root, COMMIT, boundary)
    assert report.tests_discovered == 0
    assert report.outcomes == ()
    assert boundary.requests == []
