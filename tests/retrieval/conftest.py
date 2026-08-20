from __future__ import annotations

from pathlib import Path
from typing import Callable

import pytest

from veyra.static_analysis import extract_repository, persist_extraction
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


@pytest.fixture
def sample_repo(write_file: Callable[[str, str], Path], repo_root: Path, store: VBGStore) -> Path:
    write_file(
        "orders.py",
        '"""Order processing module."""\n\n\n'
        "def validate_order(order):\n"
        '    """Checks that an order is well-formed."""\n'
        "    return True\n\n\n"
        "def process_order(order):\n"
        '    """Processes a customer order end to end."""\n'
        "    if validate_order(order):\n"
        "        return charge_customer(order)\n"
        "    return None\n\n\n"
        "def charge_customer(order):\n"
        '    """Charges the customer for an order."""\n'
        "    return True\n",
    )
    extraction = extract_repository(repo_root, COMMIT)
    persist_extraction(store, extraction)
    return repo_root
