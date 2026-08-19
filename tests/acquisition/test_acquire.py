"""
Tests for PLAN.md Phase 1.1 (Repository Acquisition).

Each test name maps directly to a required-test bullet from PLAN.md:
  Valid repository / Invalid repository / Empty repository / Clone failure /
  Commit identification / Large repository / Multi-language repository
plus the two acceptance criteria that most need dedicated coverage:
  "Analysis cannot start without an identified repository version"
  "Clone duration is recorded"
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from veyra.acquisition import AcquisitionStatus, acquire_repository


def test_valid_repository(workspace: Path, single_commit_repo: Path) -> None:
    info = acquire_repository(str(single_commit_repo), workspace)

    assert info.status is AcquisitionStatus.SUCCESS
    assert info.commit_sha is not None
    assert len(info.commit_sha) == 40
    assert info.file_count == 1
    assert info.language_counts == {"Python": 1}
    assert info.local_path is not None and info.local_path.exists()
    assert info.error_reason is None


def test_invalid_repository(workspace: Path, tmp_path: Path) -> None:
    nonexistent = tmp_path / "does_not_exist"

    info = acquire_repository(str(nonexistent), workspace)

    assert info.status is AcquisitionStatus.FAILED
    assert info.commit_sha is None
    assert info.error_reason  # deterministic, human-readable, never silent


def test_empty_repository(workspace: Path, empty_repo: Path) -> None:
    info = acquire_repository(str(empty_repo), workspace)

    assert info.status is AcquisitionStatus.FAILED
    assert info.commit_sha is None
    assert "no commits" in (info.error_reason or "").lower()


def test_clone_failure(workspace: Path, tmp_path: Path) -> None:
    # A directory that exists but is not a git repository -- a distinct
    # clone-failure mode from "path does not exist at all".
    not_a_repo = tmp_path / "not_a_repo"
    not_a_repo.mkdir()
    (not_a_repo / "file.txt").write_text("hello")

    info = acquire_repository(str(not_a_repo), workspace)

    assert info.status is AcquisitionStatus.FAILED
    assert info.error_reason


def test_commit_identification(workspace: Path, single_commit_repo: Path) -> None:
    expected_sha = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=single_commit_repo,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()

    info = acquire_repository(str(single_commit_repo), workspace)

    assert info.commit_sha == expected_sha


def test_large_repository(workspace: Path, large_repo: Path) -> None:
    info = acquire_repository(str(large_repo), workspace)

    assert info.status is AcquisitionStatus.SUCCESS
    assert info.file_count == 250
    assert info.language_counts == {"Python": 250}


def test_multi_language_repository(workspace: Path, multi_language_repo: Path) -> None:
    info = acquire_repository(str(multi_language_repo), workspace)

    assert info.status is AcquisitionStatus.SUCCESS
    assert info.file_count == 5  # 2 .py + 1 .go + 1 .js + 1 .md (md unrecognized)
    assert info.language_counts == {"Go": 1, "JavaScript": 1, "Python": 2}
    assert info.language_count == 3


def test_clone_duration_is_recorded(workspace: Path, single_commit_repo: Path) -> None:
    info = acquire_repository(str(single_commit_repo), workspace)

    assert info.clone_start > 0
    assert info.clone_end >= info.clone_start
    assert info.clone_duration_seconds == pytest.approx(
        info.clone_end - info.clone_start
    )


def test_analysis_cannot_start_without_identified_version(
    workspace: Path, empty_repo: Path
) -> None:
    info = acquire_repository(str(empty_repo), workspace)

    with pytest.raises(ValueError, match="analysis cannot proceed"):
        info.require_commit()


def test_require_commit_succeeds_for_successful_acquisition(
    workspace: Path, single_commit_repo: Path
) -> None:
    info = acquire_repository(str(single_commit_repo), workspace)

    assert info.require_commit() == info.commit_sha
