"""
PLAN.md Phase 1.5 -- Audit Infrastructure: "create a common audit mechanism
used by every milestone."

Per Design Decision D6 (PLAN.md), this module is instrumentation only: it
captures duration/timestamps/success/failure/sizes for any phase that uses
it. It deliberately does NOT compute precision/recall/quality metrics --
those require ground truth that doesn't exist until Milestone 5, and are
computed retroactively against stored AuditRecords once that ground truth
exists.

`AuditRecord.started_at`/`ended_at` are wall-clock ISO 8601 timestamps, not
monotonic durations -- this matches veyra.acquisition.RepositoryInfo, which
uses `time.time()` for the same reason (an audit record needs an absolute
timestamp, not just an elapsed interval).
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import datetime, timezone
from types import TracebackType


def _iso(epoch_seconds: float) -> str:
    return datetime.fromtimestamp(epoch_seconds, tz=timezone.utc).isoformat()


@dataclass(frozen=True)
class AuditRecord:
    phase: str
    started_at: str
    ended_at: str
    duration_seconds: float
    success: bool
    repository_commit: str | None
    error_reason: str | None = None
    input_size: int | None = None
    output_size: int | None = None
    memory_bytes: int | None = None

    def __post_init__(self) -> None:
        if not self.phase:
            raise ValueError("AuditRecord.phase is required.")
        if not self.started_at:
            raise ValueError("AuditRecord.started_at is required.")
        if not self.ended_at:
            raise ValueError("AuditRecord.ended_at is required.")
        if self.success and self.error_reason:
            raise ValueError("A successful AuditRecord cannot carry an error_reason.")
        if not self.success and not self.error_reason:
            raise ValueError("A failed AuditRecord must carry an error_reason.")


class AuditTimer:
    """
    Context manager that measures wall-clock duration and captures
    success/failure for a phase, without swallowing the underlying
    exception. Usage:

        with AuditTimer("2.1_static_analysis") as timer:
            result = do_the_work()
        record = timer.to_record(repository_commit=commit_sha, output_size=len(result))

    If the `with` block raises, the exception still propagates -- the timer
    only observes it (captures success=False, error_reason=str(exc)) and
    re-raises. Callers that want an AuditRecord for a failure must catch the
    exception themselves and read `timer.error_reason` / `timer.success`.
    """

    def __init__(self, phase: str) -> None:
        self.phase = phase
        self.success: bool | None = None
        self.error_reason: str | None = None
        self._start_epoch: float | None = None
        self._end_epoch: float | None = None

    def __enter__(self) -> "AuditTimer":
        self._start_epoch = time.time()
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> bool:
        self._end_epoch = time.time()
        self.success = exc_type is None
        if exc is not None:
            self.error_reason = str(exc) or (exc_type.__name__ if exc_type else "unknown error")
        return False  # never suppress the exception

    def to_record(
        self,
        *,
        repository_commit: str | None,
        error_reason: str | None = None,
        input_size: int | None = None,
        output_size: int | None = None,
        memory_bytes: int | None = None,
    ) -> AuditRecord:
        if self._start_epoch is None or self._end_epoch is None:
            raise RuntimeError("AuditTimer.to_record() called before the `with` block exited.")
        success = self.success if self.success is not None else True
        return AuditRecord(
            phase=self.phase,
            started_at=_iso(self._start_epoch),
            ended_at=_iso(self._end_epoch),
            duration_seconds=self._end_epoch - self._start_epoch,
            success=success,
            repository_commit=repository_commit,
            error_reason=error_reason if error_reason is not None else self.error_reason,
            input_size=input_size,
            output_size=output_size,
            memory_bytes=memory_bytes,
        )
