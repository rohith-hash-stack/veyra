from __future__ import annotations

import subprocess
from pathlib import Path

import pytest


def _git(args: list[str], cwd: Path) -> None:
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True)


def _commit(repo: Path, message: str) -> str:
    _git(["add", "-A"], cwd=repo)
    _git(["commit", "-m", message], cwd=repo)
    return subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=repo, capture_output=True, text=True, check=True
    ).stdout.strip()


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(["init"], cwd=repo)
    _git(["config", "user.email", "test@veyra.local"], cwd=repo)
    _git(["config", "user.name", "Veyra Test"], cwd=repo)
    return repo


@pytest.fixture
def repo_with_history(repo: Path) -> dict[str, str]:
    """
    Builds a sequence of commits exercising every required Phase 1.4 change
    type:
      commit1: initial files (unchanged.py, to_modify.py, to_delete.py)
      commit2: add new_file.py, modify to_modify.py, delete to_delete.py
      commit3: rename new_file.py -> renamed_file.py (no content change)
      commit4: identical tree to commit3 (empty diff -- "no-change commit")
    """
    (repo / "unchanged.py").write_text("VALUE = 1\n")
    (repo / "to_modify.py").write_text("VALUE = 'before'\n")
    (repo / "to_delete.py").write_text("VALUE = 'temporary'\n")
    commit1 = _commit(repo, "initial commit")

    (repo / "new_file.py").write_text("VALUE = 'new'\n")
    (repo / "to_modify.py").write_text("VALUE = 'after'\n")
    (repo / "to_delete.py").unlink()
    commit2 = _commit(repo, "add, modify, delete")

    (repo / "new_file.py").rename(repo / "renamed_file.py")
    commit3 = _commit(repo, "rename new_file.py")

    # No-change commit: an empty commit on top of commit3's identical tree.
    _git(["commit", "--allow-empty", "-m", "no-op commit"], cwd=repo)
    commit4 = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=repo, capture_output=True, text=True, check=True
    ).stdout.strip()

    return {"commit1": commit1, "commit2": commit2, "commit3": commit3, "commit4": commit4}
