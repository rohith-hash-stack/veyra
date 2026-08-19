"""
Phase 3.2 ExecutionBoundary contract tests (spec item 1: "ExecutionBoundary
contract tests"). Proves substitutability with a fake backend -- no Docker
required for this file at all, which is itself the point: a consumer
written against the Protocol cannot tell the difference.
"""

from __future__ import annotations

import time

from veyra.execution import (
    ExecutionBoundary,
    ExecutionHandle,
    ExecutionOutcome,
    ExecutionRequest,
    ExecutionStatus,
)
from veyra.vbg import ExecutionEnvironment


class FakeExecutionBoundary:
    """In-memory stand-in with zero knowledge of Docker/containers/
    subprocess -- proves the Protocol, not one implementation, is the
    contract runtime verification code should depend on."""

    def __init__(self) -> None:
        self.terminated: set[str] = set()
        self.cleaned_up: set[str] = set()

    def execute(self, request: ExecutionRequest) -> ExecutionHandle:
        env = ExecutionEnvironment(
            environment_id="fake-env",
            backend="fake",
            image=request.image,
            network_enabled=False,
            memory_limit_mb=request.memory_limit_mb,
            cpu_limit=request.cpu_limit,
            timeout_seconds=request.timeout_seconds,
            non_privileged=True,
            read_only_filesystem=True,
        )
        return ExecutionHandle(handle_id=f"fake-{request.target}", environment=env, started_at=time.time())

    def terminate(self, handle: ExecutionHandle) -> None:
        self.terminated.add(handle.handle_id)

    def collect_result(self, handle: ExecutionHandle, timeout_seconds: float | None = None) -> ExecutionOutcome:
        return ExecutionOutcome(
            status=ExecutionStatus.COMPLETED,
            exit_code=0,
            stdout="fake output",
            stderr="",
            duration_seconds=0.01,
            environment=handle.environment,
        )

    def cleanup(self, handle: ExecutionHandle) -> None:
        self.cleaned_up.add(handle.handle_id)


def run_one_shot(boundary: ExecutionBoundary, request: ExecutionRequest) -> ExecutionOutcome:
    """Shaped exactly like what Phase 3.5's runtime verifier will do:
    execute, collect, always cleanup. Written entirely against the
    Protocol -- no backend-specific import, cast, or isinstance check."""
    handle = boundary.execute(request)
    try:
        return boundary.collect_result(handle)
    finally:
        boundary.cleanup(handle)


def _sample_request(target: str = "t") -> ExecutionRequest:
    return ExecutionRequest(target=target, command=("echo", "hi"), image="irrelevant:tag")


def test_fake_boundary_satisfies_the_protocol_shape() -> None:
    boundary: ExecutionBoundary = FakeExecutionBoundary()
    outcome = run_one_shot(boundary, _sample_request())
    assert outcome.status is ExecutionStatus.COMPLETED


def test_consumer_code_is_identical_regardless_of_backend() -> None:
    # The same run_one_shot() function, unmodified, drives a completely
    # different backend -- this is "Docker is replaceable" as a fact.
    fake = FakeExecutionBoundary()
    outcome = run_one_shot(fake, _sample_request("proof"))
    assert outcome.environment.backend == "fake"


def test_cleanup_always_called_even_if_collect_result_raises() -> None:
    class RaisingBoundary(FakeExecutionBoundary):
        def collect_result(self, handle: ExecutionHandle, timeout_seconds: float | None = None) -> ExecutionOutcome:
            raise RuntimeError("boom")

    boundary = RaisingBoundary()
    try:
        run_one_shot(boundary, _sample_request("will-fail"))
    except RuntimeError:
        pass
    assert len(boundary.cleaned_up) == 1  # cleanup ran despite the exception


def test_terminate_is_independent_of_collect_result() -> None:
    boundary = FakeExecutionBoundary()
    handle = boundary.execute(_sample_request())
    boundary.terminate(handle)
    assert handle.handle_id in boundary.terminated


def test_execution_request_rejects_empty_command() -> None:
    import pytest

    with pytest.raises(ValueError):
        ExecutionRequest(target="t", command=(), image="x")
