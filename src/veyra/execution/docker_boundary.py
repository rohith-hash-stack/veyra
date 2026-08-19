"""
PLAN.md Milestone 3, Phase 3.2 -- DockerExecutionBoundary.

Docker is containment, not an absolute security guarantee (D17): this
implementation configures every hardening option practical for a first
slice, but a container escape vulnerability in the Docker/kernel layer
itself is not something application-level flags can rule out. Treat this as
"much stronger than running on the host directly," not "provably safe."

Hardening actually applied to every `docker run` (never conditional, never
opt-out from inside this class):
    --network none          no network access at all -- this implementation
                             does not support enabling it; a MOCKABLE-classified
                             target must be executed against a reachable mock,
                             not real opened network access
    --memory / --memory-swap  hard memory cap, no swap overflow beyond it
    --cpus                  CPU share cap
    --pids-limit            caps forkbomb-style resource exhaustion
    --read-only              root filesystem is read-only
    --tmpfs /tmp             the only writable location, size-capped
    --cap-drop ALL           no Linux capabilities beyond the bare minimum
    --security-opt no-new-privileges
    --user 65534:65534       runs as an unprivileged, non-root UID ("nobody")
    (no --privileged, ever; no host Docker socket mount, ever; no host
    filesystem mount beyond the caller-specified working/output directories)

Environment variables: only what the caller explicitly puts in
`ExecutionRequest.environment` is passed via `-e` -- the container never
inherits this process's (or the host's) environment, which is Docker's own
default behavior as long as nothing here works around it.
"""

from __future__ import annotations

import hashlib
import subprocess
import time

from veyra.vbg import ExecutionEnvironment

from .boundary import (
    ExecutionBoundaryError,
    ExecutionHandle,
    ExecutionOutcome,
    ExecutionRequest,
    ExecutionStatus,
)

_DOCKER_CLI_TIMEOUT_SECONDS = 30


def _run_docker(args: list[str], timeout: float = _DOCKER_CLI_TIMEOUT_SECONDS) -> subprocess.CompletedProcess:
    return subprocess.run(["docker", *args], capture_output=True, text=True, timeout=timeout)


def _environment_id(image: str, memory_limit_mb: int, cpu_limit: float, timeout_seconds: float) -> str:
    raw = f"docker|{image}|network=False|mem={memory_limit_mb}|cpu={cpu_limit}|timeout={timeout_seconds}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


def _build_environment(request: ExecutionRequest) -> ExecutionEnvironment:
    return ExecutionEnvironment(
        environment_id=_environment_id(request.image, request.memory_limit_mb, request.cpu_limit, request.timeout_seconds),
        backend="docker",
        image=request.image,
        network_enabled=False,  # this implementation never enables network -- see module docstring
        memory_limit_mb=request.memory_limit_mb,
        cpu_limit=request.cpu_limit,
        timeout_seconds=request.timeout_seconds,
        non_privileged=True,
        read_only_filesystem=True,
    )


def _build_run_args(request: ExecutionRequest) -> list[str]:
    args = [
        "run", "-d",
        "--network", "none",
        "--memory", f"{request.memory_limit_mb}m",
        "--memory-swap", f"{request.memory_limit_mb}m",
        "--cpus", str(request.cpu_limit),
        "--pids-limit", str(request.pids_limit),
        "--read-only",
        "--tmpfs", "/tmp:rw,size=64m",
        "--cap-drop", "ALL",
        "--security-opt", "no-new-privileges",
        "--user", "65534:65534",
        "-e", "PYTHONDONTWRITEBYTECODE=1",
    ]
    if request.working_directory is not None:
        args += ["-v", f"{request.working_directory}:/workspace:ro"]
    if request.output_directory is not None:
        args += ["-v", f"{request.output_directory}:/output:rw"]
    for key, value in request.environment.items():
        args += ["-e", f"{key}={value}"]
    args.append(request.image)
    args.extend(request.command)
    return args


class DockerExecutionBoundary:
    """Implements the ExecutionBoundary protocol. Not registered/inherited
    explicitly -- structural typing (Protocol) is the point: nothing here
    imports from `boundary.ExecutionBoundary` as a base class, proving a
    caller typed against the Protocol works with this class purely by
    having the right methods, the same way it would with any future
    backend."""

    def execute(self, request: ExecutionRequest) -> ExecutionHandle:
        environment = _build_environment(request)
        args = _build_run_args(request)
        try:
            result = _run_docker(args)
        except subprocess.TimeoutExpired as exc:
            raise ExecutionBoundaryError(f"docker run did not start within the CLI timeout: {exc}") from exc

        if result.returncode != 0:
            raise ExecutionBoundaryError(f"failed to start container: {result.stderr.strip()}")

        container_id = result.stdout.strip()
        return ExecutionHandle(handle_id=container_id, environment=environment, started_at=time.time())

    def terminate(self, handle: ExecutionHandle) -> None:
        _run_docker(["kill", handle.handle_id], timeout=15)

    def collect_result(self, handle: ExecutionHandle, timeout_seconds: float | None = None) -> ExecutionOutcome:
        timeout = timeout_seconds if timeout_seconds is not None else handle.environment.timeout_seconds

        try:
            wait_result = _run_docker(["wait", handle.handle_id], timeout=timeout)
        except subprocess.TimeoutExpired:
            self.terminate(handle)
            stdout, stderr = self._collect_logs(handle.handle_id)
            return ExecutionOutcome(
                status=ExecutionStatus.TIMED_OUT,
                exit_code=None,
                stdout=stdout,
                stderr=stderr,
                duration_seconds=time.time() - handle.started_at,
                environment=handle.environment,
            )

        duration = time.time() - handle.started_at
        stdout, stderr = self._collect_logs(handle.handle_id)

        if wait_result.returncode != 0:
            return ExecutionOutcome(
                status=ExecutionStatus.FAILED,
                exit_code=None,
                stdout=stdout,
                stderr=stderr,
                duration_seconds=duration,
                environment=handle.environment,
            )

        try:
            exit_code = int(wait_result.stdout.strip())
        except ValueError:
            exit_code = None

        return ExecutionOutcome(
            status=ExecutionStatus.COMPLETED,
            exit_code=exit_code,
            stdout=stdout,
            stderr=stderr,
            duration_seconds=duration,
            environment=handle.environment,
        )

    def cleanup(self, handle: ExecutionHandle) -> None:
        # -f: stop-if-running then remove -- cleanup must occur even after a
        # timeout/failure, so this must not assume the container already
        # exited (Phase 3.2 AC9).
        _run_docker(["rm", "-f", handle.handle_id], timeout=15)

    def _collect_logs(self, container_id: str) -> tuple[str, str]:
        result = _run_docker(["logs", container_id], timeout=15)
        return result.stdout, result.stderr
