"""
Fixtures build small git repositories on local disk so acquisition tests are
offline and deterministic (git supports cloning from a local path, so no
network access is required).
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest


def _git(args: list[str], cwd: Path) -> None:
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True)


def _init_repo(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)
    _git(["init"], cwd=path)
    _git(["config", "user.email", "test@veyra.local"], cwd=path)
    _git(["config", "user.name", "Veyra Test"], cwd=path)


@pytest.fixture
def workspace(tmp_path: Path) -> Path:
    return tmp_path / "workspace"


@pytest.fixture
def single_commit_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "source_repo"
    _init_repo(repo)
    (repo / "main.py").write_text("def hello():\n    return 'hi'\n")
    _git(["add", "."], cwd=repo)
    _git(["commit", "-m", "initial commit"], cwd=repo)
    return repo


@pytest.fixture
def empty_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "empty_repo"
    _init_repo(repo)
    return repo


@pytest.fixture
def multi_language_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "multi_lang_repo"
    _init_repo(repo)
    (repo / "app.py").write_text("print('py')\n")
    (repo / "app2.py").write_text("print('py2')\n")
    (repo / "app.go").write_text("package main\n")
    (repo / "app.js").write_text("console.log('js');\n")
    (repo / "README.md").write_text("# multi lang\n")  # unrecognized extension
    _git(["add", "."], cwd=repo)
    _git(["commit", "-m", "multi language commit"], cwd=repo)
    return repo


@pytest.fixture
def large_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "large_repo"
    _init_repo(repo)
    for i in range(250):
        (repo / f"module_{i}.py").write_text(f"VALUE = {i}\n")
    _git(["add", "."], cwd=repo)
    _git(["commit", "-m", "large commit"], cwd=repo)
    return repo
