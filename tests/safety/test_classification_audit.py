"""
Phase 3.1 audit persistence tests -- classify_and_audit() and VBGStore's
classifications table.
"""

from __future__ import annotations

from veyra.safety import classify_and_audit
from veyra.vbg import Node, SafetyClass, VBGStore

COMMIT = "commit1"


# Defined locally, not imported from conftest -- see
# tests/execution/test_docker_boundary.py's identical comment for why.
def make_node(entity_id: str, source: str, node_type: str = "Function") -> Node:
    return Node(
        entity_id=entity_id, type=node_type, name=entity_id.rsplit(".", 1)[-1],
        repository_version=COMMIT, language="Python", lexical_representation=source,
    )


def test_classify_and_audit_persists_the_result(store: VBGStore) -> None:
    node = make_node("orders.run_cmd", "def run_cmd():\n    subprocess.run(['ls'])\n")

    result = classify_and_audit(store, node, COMMIT)

    history = store.get_classification_history("orders.run_cmd", COMMIT)
    assert len(history) == 1
    assert history[0].classification is SafetyClass.BLOCKED
    assert history[0] == result


def test_get_latest_classification(store: VBGStore) -> None:
    node = make_node("orders.run_cmd", "def run_cmd():\n    subprocess.run(['ls'])\n")
    classify_and_audit(store, node, COMMIT)

    latest = store.get_latest_classification("orders.run_cmd", COMMIT)
    assert latest is not None
    assert latest.classification is SafetyClass.BLOCKED


def test_reclassification_preserves_history_not_overwrite(store: VBGStore) -> None:
    node = make_node("orders.run_cmd", "def run_cmd():\n    subprocess.run(['ls'])\n")

    classify_and_audit(store, node, COMMIT)
    classify_and_audit(store, node, COMMIT)  # re-run under the same policy

    history = store.get_classification_history("orders.run_cmd", COMMIT)
    assert len(history) == 2  # both decisions kept, same append-only discipline as everything else


def test_no_classification_for_unrelated_target(store: VBGStore) -> None:
    assert store.get_classification_history("orders.never_classified", COMMIT) == []
    assert store.get_latest_classification("orders.never_classified", COMMIT) is None


def test_store_exposes_no_update_or_delete_for_classifications(store: VBGStore) -> None:
    assert not hasattr(store, "update_classification")
    assert not hasattr(store, "delete_classification")
