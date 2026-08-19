"""
PLAN.md Phase 1.4 -- file-level git diff between two commits.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

from .models import ChangeType, FileChange

_STATUS_CODES = {
    "A": ChangeType.ADDED,
    "M": ChangeType.MODIFIED,
    "D": ChangeType.DELETED,
}


class GitDiffError(RuntimeError):
    """Raised when `git diff` itself fails (e.g. an unknown commit)."""


def _run_git(args: list[str], cwd: Path) -> subprocess.CompletedProcess:
    if shutil.which("git") is None:
        raise RuntimeError("git executable not found on PATH")
    return subprocess.run(
        ["git", *args], cwd=cwd, capture_output=True, text=True, timeout=120
    )


def _parse_status_line(line: str) -> FileChange:
    parts = line.split("\t")
    status = parts[0]

    if status.startswith("R"):
        # e.g. "R100\told_path\tnew_path"
        if len(parts) != 3:
            raise GitDiffError(f"Malformed rename line from git diff: {line!r}")
        return FileChange(path=parts[2], change_type=ChangeType.RENAMED, previous_path=parts[1])

    change_type = _STATUS_CODES.get(status)
    if change_type is None:
        raise GitDiffError(f"Unrecognized git diff status code {status!r} in line: {line!r}")
    if len(parts) != 2:
        raise GitDiffError(f"Malformed diff line from git diff: {line!r}")
    return FileChange(path=parts[1], change_type=change_type)


def diff_commits(repo_path: Path, from_commit: str, to_commit: str) -> list[FileChange]:
    """
    File-level changes between two commits of an already-acquired repository.
    Returns an empty list for a no-change commit (from_commit == to_commit,
    or an otherwise identical tree) -- git diff naturally reports no lines
    for unchanged files, so ChangeType.UNCHANGED is never emitted here; it
    exists for the symbol-level diff (D4 extension, deferred to M2) where
    every node is classified explicitly, changed or not.
    """
    result = _run_git(
        ["diff", "--name-status", "-M", from_commit, to_commit], cwd=repo_path
    )
    if result.returncode != 0:
        raise GitDiffError(result.stderr.strip() or "git diff failed")

    lines = [line for line in result.stdout.splitlines() if line.strip()]
    return [_parse_status_line(line) for line in lines]
