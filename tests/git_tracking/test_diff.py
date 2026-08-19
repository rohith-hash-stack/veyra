"""
Tests for PLAN.md Phase 1.4 (Git Version Tracking, file-level). Required
tests: new file, modified file, deleted file, renamed file, multiple
commits, no-change commit.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from veyra.git_tracking import ChangeType, GitDiffError, diff_commits


def test_new_file(repo: Path, repo_with_history: dict[str, str]) -> None:
    changes = diff_commits(repo, repo_with_history["commit1"], repo_with_history["commit2"])

    added = {c.path for c in changes if c.change_type is ChangeType.ADDED}
    assert "new_file.py" in added


def test_modified_file(repo: Path, repo_with_history: dict[str, str]) -> None:
    changes = diff_commits(repo, repo_with_history["commit1"], repo_with_history["commit2"])

    modified = {c.path for c in changes if c.change_type is ChangeType.MODIFIED}
    assert "to_modify.py" in modified


def test_deleted_file(repo: Path, repo_with_history: dict[str, str]) -> None:
    changes = diff_commits(repo, repo_with_history["commit1"], repo_with_history["commit2"])

    deleted = {c.path for c in changes if c.change_type is ChangeType.DELETED}
    assert "to_delete.py" in deleted


def test_renamed_file(repo: Path, repo_with_history: dict[str, str]) -> None:
    changes = diff_commits(repo, repo_with_history["commit2"], repo_with_history["commit3"])

    renames = [c for c in changes if c.change_type is ChangeType.RENAMED]
    assert len(renames) == 1
    assert renames[0].previous_path == "new_file.py"
    assert renames[0].path == "renamed_file.py"


def test_multiple_commits_spans_full_history(repo: Path, repo_with_history: dict[str, str]) -> None:
    # Diffing across all 4 commits at once should show the net effect:
    # unchanged.py never appears; to_delete.py nets to DELETED; the
    # renamed file nets to a single ADDED (git has no memory of the
    # intermediate new_file.py name once diffing endpoint-to-endpoint).
    changes = diff_commits(repo, repo_with_history["commit1"], repo_with_history["commit4"])
    paths_by_type = {c.change_type: c.path for c in changes}

    assert "unchanged.py" not in {c.path for c in changes}
    assert paths_by_type.get(ChangeType.DELETED) == "to_delete.py"
    assert paths_by_type.get(ChangeType.MODIFIED) == "to_modify.py"


def test_no_change_commit(repo: Path, repo_with_history: dict[str, str]) -> None:
    changes = diff_commits(repo, repo_with_history["commit3"], repo_with_history["commit4"])

    assert changes == []


def test_unknown_commit_raises(repo: Path, repo_with_history: dict[str, str]) -> None:
    with pytest.raises(GitDiffError):
        diff_commits(repo, repo_with_history["commit1"], "0" * 40)
