"""
PLAN.md Milestone 3, Phase 3.2 -- ExecutionBoundary.

The generic contract every backend (Docker now; LocalProcess/Firecracker/
Remote later, per D16) must satisfy. Nothing in this module knows Docker
exists -- no container/image-registry/daemon vocabulary appears here at all,
only "run this command with these resource limits and tell me what
happened." That is what "Docker is replaceable without changing runtime
verification logic" (Phase 3.2 AC2) means in practice: a future
LocalProcessExecutionBoundary implements the exact same four methods and
any caller written against ExecutionBoundary doesn't change.
"""

from __future__ import annotations

import enum
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol

from veyra.vbg import ExecutionEnvironment


class ExecutionStatus(enum.Enum):
    COMPLETED = "COMPLETED"
    TIMED_OUT = "TIMED_OUT"
    FAILED = "FAILED"
    TERMINATED = "TERMINATED"


@dataclass(frozen=True)
class ExecutionRequest:
    target: str
    command: tuple[str, ...]
    image: str
    working_directory: Path | None = None
    output_directory: Path | None = None
    environment: dict[str, str] = field(default_factory=dict)
    timeout_seconds: float = 30.0
    memory_limit_mb: int = 256
    cpu_limit: float = 1.0
    pids_limit: int = 128

    def __post_init__(self) -> None:
        if not self.target:
            raise ValueError("ExecutionRequest.target is required.")
        if not self.command:
            raise ValueError("ExecutionRequest.command is required.")
        if not self.image:
            raise ValueError("ExecutionRequest.image is required.")
        if self.timeout_seconds <= 0:
            raise ValueError("ExecutionRequest.timeout_seconds must be positive.")
        if self.memory_limit_mb <= 0:
            raise ValueError("ExecutionRequest.memory_limit_mb must be positive.")
        if self.cpu_limit <= 0:
            raise ValueError("ExecutionRequest.cpu_limit must be positive.")


@dataclass(frozen=True)
class ExecutionHandle:
    handle_id: str
    environment: ExecutionEnvironment
    started_at: float


@dataclass(frozen=True)
class ExecutionOutcome:
    status: ExecutionStatus
    exit_code: int | None
    stdout: str
    stderr: str
    duration_seconds: float
    environment: ExecutionEnvironment


class ExecutionBoundaryError(RuntimeError):
    """Raised only for boundary-level failures (couldn't start the sandbox
    at all) -- never for the target code's own exit code/exceptions, which
    are ordinary ExecutionOutcome data, not an error in the boundary."""


class ExecutionBoundary(Protocol):
    def execute(self, request: ExecutionRequest) -> ExecutionHandle: ...

    def terminate(self, handle: ExecutionHandle) -> None: ...

    def collect_result(self, handle: ExecutionHandle, timeout_seconds: float | None = None) -> ExecutionOutcome: ...

    def cleanup(self, handle: ExecutionHandle) -> None: ...
