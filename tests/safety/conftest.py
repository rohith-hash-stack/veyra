from __future__ import annotations

from pathlib import Path

import pytest

from veyra.vbg import Node, VBGStore

COMMIT = "commit1"


@pytest.fixture
def store(tmp_path: Path) -> VBGStore:
    return VBGStore(tmp_path / "vbg.sqlite3")


def make_node(entity_id: str, source: str, node_type: str = "Function") -> Node:
    """Builds a Node the way Phase 2.1's extractor would -- lexical_representation
    holding the exact function source -- without needing a real repo on disk."""
    return Node(
        entity_id=entity_id,
        type=node_type,
        name=entity_id.rsplit(".", 1)[-1],
        repository_version=COMMIT,
        language="Python",
        lexical_representation=source,
    )
