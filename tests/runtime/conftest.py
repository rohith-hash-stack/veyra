from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Callable

import pytest

from veyra.vbg import VBGStore

COMMIT = "commit1"


@pytest.fixture
def repo_root(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    root.mkdir()
    return root


@pytest.fixture
def store(tmp_path: Path) -> VBGStore:
    return VBGStore(tmp_path / "vbg.sqlite3")


@pytest.fixture
def write_file(repo_root: Path) -> Callable[[str, str], Path]:
    def _write(rel_path: str, source: str) -> Path:
        path = repo_root / rel_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(source)
        return path

    return _write


def _docker_available() -> bool:
    try:
        result = subprocess.run(["docker", "version"], capture_output=True, timeout=5)
        return result.returncode == 0
    except (FileNotFoundError, OSError, subprocess.TimeoutExpired):
        return False


DOCKER_AVAILABLE = _docker_available()

requires_docker = pytest.mark.skipif(
    not DOCKER_AVAILABLE,
    reason="Docker is not available in this environment -- see PLAN.md D16/D17",
)
