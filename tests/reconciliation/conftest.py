from __future__ import annotations

from pathlib import Path
from typing import Callable

import pytest

from veyra.vbg import VBGStore


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
