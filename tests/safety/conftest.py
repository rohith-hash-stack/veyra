from __future__ import annotations

from pathlib import Path

import pytest

from veyra.vbg import VBGStore


@pytest.fixture
def store(tmp_path: Path) -> VBGStore:
    return VBGStore(tmp_path / "vbg.sqlite3")


# Note: `make_node`/`COMMIT` used to live here and be imported into
# test_capabilities.py/test_classification.py/test_classification_audit.py
# via a bare `from conftest import ...`. That import is unsafe across this
# project's tests/ tree (no __init__.py anywhere, so pytest's default
# import mode can resolve "conftest" to a *different* directory's file
# depending on collection order -- see PROGRESS.md's Phase 3.6 entry for
# where this actually broke). Each of those files now defines its own local
# copy instead.
