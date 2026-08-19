"""
Engine orchestration tests using a FakeExecutionBoundary -- no Docker
required for this file, same pattern tests/harness/test_manager.py and
tests/execution/test_boundary_contract.py already established. Real
end-to-end proof against a live container lives in test_engine_docker.py
(requires_docker).
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Callable

from veyra.execution import ExecutionBoundaryError, ExecutionHandle, ExecutionOutcome, ExecutionRequest, ExecutionStatus
from veyra.runtime import RuntimeUnexecutableReason, run_scenario
from veyra.safety import classify_and_audit
from veyra.vbg import EvidenceType, ExecutionEnvironment, Node, SafetyClass, Scenario, VBGStore

COMMIT = "commit1"


def _persist_node(store: VBGStore, entity_id: str, source: str, node_type: str = "Function") -> Node:
    node = Node(
        entity_id=entity_id, type=node_type, name=entity_id.rsplit(".", 1)[-1],
        repository_version=COMMIT, language="Python", lexical_representation=source,
        source_location=f"mod.py:1-{source.count(chr(10)) + 1}",
    )
    store.insert_node(node)
    classify_and_audit(store, node, COMMIT)
    return node


def _scenario(target: str, required_inputs: tuple[str, ...] = ()) -> Scenario:
    return Scenario(
        scenario_id=f"scn-{target}",
        target_entity_id=target,
        description=f"Directly invoke `{target}`.",
        required_inputs=required_inputs,
        dependencies=(),
        expected_observable_points=("return_value", "raised_exception"),
        safety_class=SafetyClass.SANDBOXABLE,
        executable=True,
        repository_version=COMMIT,
    )


class FakeExecutionBoundary:
    def __init__(
        self,
        status: ExecutionStatus = ExecutionStatus.COMPLETED,
        write_trace: bool = True,
        trace: dict | None = None,
        raise_on_execute: bool = False,
    ) -> None:
        self.status = status
        self.write_trace = write_trace
        self.trace = trace
        self.raise_on_execute = raise_on_execute
        self.requests: list[ExecutionRequest] = []

    def execute(self, request: ExecutionRequest) -> ExecutionHandle:
        if self.raise_on_execute:
            raise ExecutionBoundaryError("simulated boundary start failure")
        self.requests.append(request)
        env = ExecutionEnvironment(
            environment_id="fake-env", backend="fake", image=request.image, network_enabled=False,
            memory_limit_mb=request.memory_limit_mb, cpu_limit=request.cpu_limit,
            timeout_seconds=request.timeout_seconds, non_privileged=True, read_only_filesystem=True,
        )
        return ExecutionHandle(handle_id="fake-handle", environment=env, started_at=time.time())

    def terminate(self, handle: ExecutionHandle) -> None:
        pass

    def collect_result(self, handle: ExecutionHandle, timeout_seconds: float | None = None) -> ExecutionOutcome:
        request = self.requests[-1]
        if self.status is ExecutionStatus.COMPLETED and self.write_trace and request.output_directory is not None:
            spec = json.loads((request.output_directory / "spec.json").read_text())
            target_entity_id = f"{spec['module_id']}.{spec['function_name']}"
            trace = self.trace or {
                "status": "COMPLETED", "return_repr": "1", "exception_type": None,
                "exception_message": None, "duration_seconds": 0.001,
                "events": [
                    {"kind": "call", "entity_id": target_entity_id, "qualname": spec["function_name"], "offset_seconds": 0.0},
                    {"kind": "return", "entity_id": target_entity_id, "qualname": spec["function_name"], "offset_seconds": 0.001},
                ],
            }
            (request.output_directory / "trace.json").write_text(json.dumps(trace))
        return ExecutionOutcome(
            status=self.status, exit_code=0 if self.status is ExecutionStatus.COMPLETED else None,
            stdout="", stderr="" if self.status is ExecutionStatus.COMPLETED else "boom",
            duration_seconds=0.01, environment=handle.environment,
        )

    def cleanup(self, handle: ExecutionHandle) -> None:
        pass


def test_missing_node_is_no_source_available(repo_root: Path, store: VBGStore) -> None:
    scenario = _scenario("mod.foo")
    boundary = FakeExecutionBoundary()

    outcome = run_scenario(store, repo_root, COMMIT, scenario, boundary)

    assert outcome.status == "UNEXECUTABLE"
    assert outcome.unexecutable_reason is RuntimeUnexecutableReason.NO_SOURCE_AVAILABLE
    assert boundary.requests == []


def test_missing_classification_is_blocked_by_safety(repo_root: Path, store: VBGStore) -> None:
    # A node exists but was never classified -- treated the same as BLOCKED,
    # not silently proceeding.
    store.insert_node(
        Node(entity_id="mod.foo", type="Function", name="foo", repository_version=COMMIT,
             language="Python", lexical_representation="def foo():\n    return 1\n")
    )
    scenario = _scenario("mod.foo")
    boundary = FakeExecutionBoundary()

    outcome = run_scenario(store, repo_root, COMMIT, scenario, boundary)

    assert outcome.unexecutable_reason is RuntimeUnexecutableReason.BLOCKED_BY_SAFETY
    assert boundary.requests == []


def test_currently_blocked_capability_is_blocked_by_safety(write_file: Callable[[str, str], Path], repo_root: Path, store: VBGStore) -> None:
    source = "import subprocess\n\ndef foo():\n    subprocess.run(['ls'])\n"
    _persist_node(store, "mod.foo", source)
    write_file("mod.py", source)
    scenario = _scenario("mod.foo")
    boundary = FakeExecutionBoundary()

    outcome = run_scenario(store, repo_root, COMMIT, scenario, boundary)

    assert outcome.unexecutable_reason is RuntimeUnexecutableReason.BLOCKED_BY_SAFETY
    assert boundary.requests == []


def test_bound_method_is_ambiguous_initialization(write_file: Callable[[str, str], Path], repo_root: Path, store: VBGStore) -> None:
    source = "def foo(self):\n    return 1\n"
    _persist_node(store, "mod.Cls.foo", source, node_type="Method")
    write_file("mod.py", source)
    scenario = _scenario("mod.Cls.foo")
    boundary = FakeExecutionBoundary()

    outcome = run_scenario(store, repo_root, COMMIT, scenario, boundary)

    assert outcome.unexecutable_reason is RuntimeUnexecutableReason.AMBIGUOUS_INITIALIZATION
    assert boundary.requests == []


def test_unsynthesizable_parameter_is_missing_fixture(write_file: Callable[[str, str], Path], repo_root: Path, store: VBGStore) -> None:
    source = "def foo(x):\n    return x\n"
    _persist_node(store, "mod.foo", source)
    write_file("mod.py", source)
    scenario = _scenario("mod.foo", required_inputs=("x",))
    boundary = FakeExecutionBoundary()

    outcome = run_scenario(store, repo_root, COMMIT, scenario, boundary)

    assert outcome.unexecutable_reason is RuntimeUnexecutableReason.MISSING_FIXTURE
    assert boundary.requests == []


def test_boundary_start_failure_is_container_execution_failed(write_file: Callable[[str, str], Path], repo_root: Path, store: VBGStore) -> None:
    source = "def foo():\n    return 1\n"
    _persist_node(store, "mod.foo", source)
    write_file("mod.py", source)
    scenario = _scenario("mod.foo")
    boundary = FakeExecutionBoundary(raise_on_execute=True)

    outcome = run_scenario(store, repo_root, COMMIT, scenario, boundary)

    assert outcome.unexecutable_reason is RuntimeUnexecutableReason.CONTAINER_EXECUTION_FAILED
    assert outcome.environment_id is None


def test_container_timeout_is_container_execution_failed_with_environment_persisted(
    write_file: Callable[[str, str], Path], repo_root: Path, store: VBGStore
) -> None:
    source = "def foo():\n    return 1\n"
    _persist_node(store, "mod.foo", source)
    write_file("mod.py", source)
    scenario = _scenario("mod.foo")
    boundary = FakeExecutionBoundary(status=ExecutionStatus.TIMED_OUT)

    outcome = run_scenario(store, repo_root, COMMIT, scenario, boundary)

    assert outcome.unexecutable_reason is RuntimeUnexecutableReason.CONTAINER_EXECUTION_FAILED
    assert outcome.environment_id == "fake-env"
    assert store.get_execution_environment_history("fake-env") != []
    assert store.get_evidence_for_subject("mod.foo", COMMIT) == []


def test_missing_trace_file_is_no_trace_reported(write_file: Callable[[str, str], Path], repo_root: Path, store: VBGStore) -> None:
    source = "def foo():\n    return 1\n"
    _persist_node(store, "mod.foo", source)
    write_file("mod.py", source)
    scenario = _scenario("mod.foo")
    boundary = FakeExecutionBoundary(write_trace=False)

    outcome = run_scenario(store, repo_root, COMMIT, scenario, boundary)

    assert outcome.unexecutable_reason is RuntimeUnexecutableReason.NO_TRACE_REPORTED
    assert store.get_evidence_for_subject("mod.foo", COMMIT) == []


def test_successful_run_persists_runtime_evidence_for_target(
    write_file: Callable[[str, str], Path], repo_root: Path, store: VBGStore
) -> None:
    source = "def foo():\n    return 1\n"
    _persist_node(store, "mod.foo", source)
    write_file("mod.py", source)
    scenario = _scenario("mod.foo")
    boundary = FakeExecutionBoundary()

    outcome = run_scenario(store, repo_root, COMMIT, scenario, boundary)

    assert outcome.status == "COMPLETED"
    evidence = store.get_evidence_for_subject("mod.foo", COMMIT)
    assert len(evidence) == 1
    assert evidence[0].evidence_type is EvidenceType.RUNTIME
    assert evidence[0].scenario_id == scenario.scenario_id
    assert evidence[0].environment_id == outcome.environment_id
    assert "return=1" in evidence[0].detail


def test_successful_run_persists_execution_environment(
    write_file: Callable[[str, str], Path], repo_root: Path, store: VBGStore
) -> None:
    source = "def foo():\n    return 1\n"
    _persist_node(store, "mod.foo", source)
    write_file("mod.py", source)
    scenario = _scenario("mod.foo")
    boundary = FakeExecutionBoundary()

    outcome = run_scenario(store, repo_root, COMMIT, scenario, boundary)

    history = store.get_execution_environment_history(outcome.environment_id)
    assert len(history) == 1
    assert history[0].backend == "fake"


def test_nested_call_produces_runtime_call_edge_evidence(
    write_file: Callable[[str, str], Path], repo_root: Path, store: VBGStore
) -> None:
    source = "def foo():\n    return 1\n"
    _persist_node(store, "mod.foo", source)
    write_file("mod.py", source)
    scenario = _scenario("mod.foo")
    trace = {
        "status": "COMPLETED", "return_repr": "1", "exception_type": None,
        "exception_message": None, "duration_seconds": 0.002,
        "events": [
            {"kind": "call", "entity_id": "mod.foo", "qualname": "foo", "offset_seconds": 0.0},
            {"kind": "call", "entity_id": "mod.bar", "qualname": "bar", "offset_seconds": 0.0005},
            {"kind": "return", "entity_id": "mod.bar", "qualname": "bar", "offset_seconds": 0.001},
            {"kind": "return", "entity_id": "mod.foo", "qualname": "foo", "offset_seconds": 0.002},
        ],
    }
    boundary = FakeExecutionBoundary(trace=trace)

    run_scenario(store, repo_root, COMMIT, scenario, boundary)

    edge_evidence = store.get_evidence_for_subject("mod.foo--CALLS-->mod.bar", COMMIT)
    assert len(edge_evidence) == 1
    assert edge_evidence[0].evidence_type is EvidenceType.RUNTIME
    bar_evidence = store.get_evidence_for_subject("mod.bar", COMMIT)
    assert len(bar_evidence) == 1


def test_exception_outcome_still_persists_evidence(
    write_file: Callable[[str, str], Path], repo_root: Path, store: VBGStore
) -> None:
    source = "def foo():\n    raise ValueError('boom')\n"
    _persist_node(store, "mod.foo", source)
    write_file("mod.py", source)
    scenario = _scenario("mod.foo")
    trace = {
        "status": "EXCEPTION", "return_repr": None, "exception_type": "ValueError",
        "exception_message": "boom", "duration_seconds": 0.001,
        "events": [
            {"kind": "call", "entity_id": "mod.foo", "qualname": "foo", "offset_seconds": 0.0},
            {
                "kind": "exception", "entity_id": "mod.foo", "qualname": "foo", "offset_seconds": 0.0005,
                "exception_type": "ValueError", "exception_message": "boom",
            },
            {"kind": "return", "entity_id": "mod.foo", "qualname": "foo", "offset_seconds": 0.001},
        ],
    }
    boundary = FakeExecutionBoundary(trace=trace)

    outcome = run_scenario(store, repo_root, COMMIT, scenario, boundary)

    assert outcome.status == "EXCEPTION"
    evidence = store.get_evidence_for_subject("mod.foo", COMMIT)
    assert len(evidence) == 1
    assert "ValueError" in evidence[0].detail
    assert "boom" in evidence[0].detail
