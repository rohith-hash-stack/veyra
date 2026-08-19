"""
Tests for the Phase 1.5 audit_events table on VBGStore, plus the Phase 1.1
-> Phase 1.5 integration: acquisition is timed with the shared AuditTimer and
the resulting AuditRecord is persisted alongside the RepositoryRecord.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from veyra.acquisition import acquire_repository
from veyra.audit import AuditRecord, AuditTimer
from veyra.vbg import VBGStore


def _record(**overrides: object) -> AuditRecord:
    defaults: dict[object, object] = dict(
        phase="test_phase",
        started_at="2026-08-20T12:00:00+00:00",
        ended_at="2026-08-20T12:00:01+00:00",
        duration_seconds=1.0,
        success=True,
        repository_commit="commit1",
        error_reason=None,
    )
    defaults.update(overrides)
    return AuditRecord(**defaults)  # type: ignore[arg-type]


def test_insert_and_retrieve_audit_record(store: VBGStore) -> None:
    store.insert_audit_record(_record())

    history = store.get_audit_history("test_phase")

    assert len(history) == 1
    assert history[0].success is True
    assert history[0].repository_commit == "commit1"


def test_audit_history_scoped_by_commit(store: VBGStore) -> None:
    store.insert_audit_record(_record(repository_commit="commit1"))
    store.insert_audit_record(_record(repository_commit="commit2"))

    commit1_history = store.get_audit_history("test_phase", repository_commit="commit1")

    assert len(commit1_history) == 1
    assert commit1_history[0].repository_commit == "commit1"


def test_audit_history_preserves_failures_alongside_successes(store: VBGStore) -> None:
    store.insert_audit_record(_record(success=True))
    store.insert_audit_record(_record(success=False, error_reason="boom"))

    history = store.get_audit_history("test_phase")

    assert len(history) == 2
    assert [r.success for r in history] == [True, False]
    assert history[1].error_reason == "boom"


def test_store_exposes_no_update_or_delete_for_audit(store: VBGStore) -> None:
    assert not hasattr(store, "update_audit_record")
    assert not hasattr(store, "delete_audit_record")


def test_phase_1_1_acquisition_audited_and_persisted(store: VBGStore, tmp_path: Path) -> None:
    import subprocess

    source_repo = tmp_path / "source"
    source_repo.mkdir()
    subprocess.run(["git", "init"], cwd=source_repo, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "t@veyra.local"], cwd=source_repo, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.name", "Veyra Test"], cwd=source_repo, check=True, capture_output=True)
    (source_repo / "main.py").write_text("print('hi')\n")
    subprocess.run(["git", "add", "."], cwd=source_repo, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-m", "init"], cwd=source_repo, check=True, capture_output=True)

    workspace = tmp_path / "workspace"
    with AuditTimer("1.1_repository_acquisition") as timer:
        info = acquire_repository(str(source_repo), workspace)

    audit_record = timer.to_record(
        repository_commit=info.commit_sha, output_size=info.file_count
    )
    store.insert_audit_record(audit_record)
    store.record_repository(info)

    audit_history = store.get_audit_history("1.1_repository_acquisition", info.commit_sha)
    repo_history = store.get_repository_history(info.source, info.commit_sha)

    assert len(audit_history) == 1
    assert audit_history[0].success is True
    assert len(repo_history) == 1
