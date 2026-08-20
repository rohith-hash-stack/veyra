from __future__ import annotations

from pathlib import Path

import pytest

from veyra.vbg import VBGStore


@pytest.fixture
def store(tmp_path: Path) -> VBGStore:
    return VBGStore(tmp_path / "vbg.sqlite3")
