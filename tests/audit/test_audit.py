"""
Tests for PLAN.md Phase 1.5 (Audit Infrastructure) -- the AuditTimer/
AuditRecord primitives shared by every milestone.
"""

from __future__ import annotations

import time

import pytest

from veyra.audit import AuditRecord, AuditTimer


def test_audit_timer_success_record() -> None:
    with AuditTimer("test_phase") as timer:
        time.sleep(0.01)

    record = timer.to_record(repository_commit="abc123", output_size=42)

    assert record.phase == "test_phase"
    assert record.success is True
    assert record.error_reason is None
    assert record.duration_seconds >= 0.01
    assert record.repository_commit == "abc123"
    assert record.output_size == 42
    assert "T" in record.started_at  # ISO 8601
    assert record.ended_at >= record.started_at


def test_audit_timer_captures_failure_without_swallowing_it() -> None:
    timer = AuditTimer("test_phase")
    with pytest.raises(ValueError, match="boom"):
        with timer:
            raise ValueError("boom")

    assert timer.success is False
    assert timer.error_reason == "boom"

    record = timer.to_record(repository_commit="abc123")
    assert record.success is False
    assert record.error_reason == "boom"


def test_audit_timer_falls_back_to_exception_type_name_when_message_empty() -> None:
    timer = AuditTimer("test_phase")
    with pytest.raises(ValueError):
        with timer:
            raise ValueError()

    assert timer.error_reason == "ValueError"


def test_to_record_before_exit_raises() -> None:
    timer = AuditTimer("test_phase")
    timer.__enter__()
    with pytest.raises(RuntimeError):
        timer.to_record(repository_commit=None)


def test_successful_audit_record_cannot_carry_error_reason() -> None:
    with pytest.raises(ValueError):
        AuditRecord(
            phase="p", started_at="t1", ended_at="t2", duration_seconds=1.0,
            success=True, repository_commit=None, error_reason="should not be here",
        )


def test_failed_audit_record_must_carry_error_reason() -> None:
    with pytest.raises(ValueError):
        AuditRecord(
            phase="p", started_at="t1", ended_at="t2", duration_seconds=1.0,
            success=False, repository_commit=None, error_reason=None,
        )
