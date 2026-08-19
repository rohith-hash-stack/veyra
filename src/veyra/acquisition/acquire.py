"""
PLAN.md Phase 1.1 -- Repository Acquisition.

acquire_repository() clones a repository source into a fresh directory and
returns a RepositoryInfo. Ordinary, expected failure modes (repository does
not exist, clone fails, repository has no commits) are reported as
status=FAILED with a human-readable error_reason -- they are NOT raised as
exceptions, per the acceptance criterion "Invalid repository handling is
deterministic." Only a missing `git` executable (a broken environment, not a
bad input) raises.
"""

from __future__ import annotations

import shutil
import subprocess
import time
import uuid
from pathlib import Path

from .languages import identify_languages
from .models import AcquisitionStatus, RepositoryInfo

_GIT_TIMEOUT_SECONDS = 300


class GitNotAvailableError(RuntimeError):
    """Raised when the `git` executable cannot be found on PATH."""


def _run_git(args: list[str], cwd: Path | None = None) -> subprocess.CompletedProcess:
    if shutil.which("git") is None:
        raise GitNotAvailableError("git executable not found on PATH")
    return subprocess.run(
        ["git", *args],
        cwd=cwd,
        capture_output=True,
        text=True,
        timeout=_GIT_TIMEOUT_SECONDS,
    )


def _directory_size_bytes(path: Path) -> int:
    total = 0
    for entry in path.rglob("*"):
        if entry.is_file():
            try:
                total += entry.stat().st_size
            except OSError:
                continue
    return total


def _failed(
    source: str,
    *,
    local_path: Path | None,
    clone_start: float,
    clone_end: float,
    error_reason: str,
    file_count: int = 0,
    language_counts: dict[str, int] | None = None,
    repository_size_bytes: int = 0,
) -> RepositoryInfo:
    return RepositoryInfo(
        source=source,
        local_path=local_path,
        status=AcquisitionStatus.FAILED,
        commit_sha=None,
        file_count=file_count,
        language_counts=language_counts or {},
        repository_size_bytes=repository_size_bytes,
        clone_start=clone_start,
        clone_end=clone_end,
        clone_duration_seconds=clone_end - clone_start,
        error_reason=error_reason,
    )


def acquire_repository(source: str, workspace: Path) -> RepositoryInfo:
    """
    Clone `source` (a local path or remote git URL) into a fresh subdirectory
    of `workspace`, and produce a RepositoryInfo describing what was acquired.
    """
    workspace.mkdir(parents=True, exist_ok=True)
    dest = workspace / uuid.uuid4().hex

    clone_start = time.time()
    try:
        clone_result = _run_git(["clone", source, str(dest)])
    except subprocess.TimeoutExpired:
        clone_end = time.time()
        return _failed(
            source,
            local_path=None,
            clone_start=clone_start,
            clone_end=clone_end,
            error_reason="clone timed out",
        )
    clone_end = time.time()

    if clone_result.returncode != 0:
        return _failed(
            source,
            local_path=None,
            clone_start=clone_start,
            clone_end=clone_end,
            error_reason=clone_result.stderr.strip() or "git clone failed",
        )

    commit_result = _run_git(["rev-parse", "HEAD"], cwd=dest)
    commit_sha = commit_result.stdout.strip() if commit_result.returncode == 0 else None

    files = [p for p in dest.rglob("*") if p.is_file() and ".git" not in p.parts]
    file_count = len(files)
    language_counts = identify_languages(files)
    repository_size_bytes = _directory_size_bytes(dest)

    if commit_sha is None:
        # Clone succeeded but there is no HEAD -- e.g. a freshly `git init`'d,
        # empty repository. Per Phase 1.1: "analysis cannot start without an
        # identified repository version", this is a FAILED acquisition, not a
        # degraded-but-usable one.
        return _failed(
            source,
            local_path=dest,
            clone_start=clone_start,
            clone_end=clone_end,
            error_reason="repository has no commits (empty repository)",
            file_count=file_count,
            language_counts=language_counts,
            repository_size_bytes=repository_size_bytes,
        )

    return RepositoryInfo(
        source=source,
        local_path=dest,
        status=AcquisitionStatus.SUCCESS,
        commit_sha=commit_sha,
        file_count=file_count,
        language_counts=language_counts,
        repository_size_bytes=repository_size_bytes,
        clone_start=clone_start,
        clone_end=clone_end,
        clone_duration_seconds=clone_end - clone_start,
        error_reason=None,
    )
