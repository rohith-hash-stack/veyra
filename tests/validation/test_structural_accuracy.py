from __future__ import annotations

from pathlib import Path

from veyra.pipeline import run_static_analysis
from veyra.validation.structural_accuracy import GroundTruthSet, audit_structural_accuracy
from veyra.vbg import VBGStore

COMMIT = "commit1"


def _write_repo(root: Path) -> None:
    root.mkdir()
    (root / "mod.py").write_text("def foo():\n    return 1\n\n\ndef bar():\n    return foo()\n")


def test_perfect_ground_truth_yields_perfect_scores(tmp_path: Path, store: VBGStore) -> None:
    repo_root = tmp_path / "repo"
    _write_repo(repo_root)
    run_static_analysis(store, repo_root, COMMIT)

    predicted_nodes = frozenset(n.entity_id for n in store.get_all_nodes(COMMIT))
    predicted_edges = frozenset(
        (e.source_id, e.target_id, e.relationship_type.value) for e in store.get_all_edges(COMMIT)
    )
    ground_truth = GroundTruthSet(COMMIT, predicted_nodes, predicted_edges)

    report = audit_structural_accuracy(store, ground_truth)

    assert report.node_accuracy.precision == 1.0
    assert report.node_accuracy.recall == 1.0
    assert report.edge_accuracy.precision == 1.0
    assert report.edge_accuracy.recall == 1.0


def test_missing_expected_node_reduces_recall_not_precision(tmp_path: Path, store: VBGStore) -> None:
    repo_root = tmp_path / "repo"
    _write_repo(repo_root)
    run_static_analysis(store, repo_root, COMMIT)

    predicted_nodes = frozenset(n.entity_id for n in store.get_all_nodes(COMMIT))
    ground_truth = GroundTruthSet(
        COMMIT, predicted_nodes | {"mod.a_symbol_the_extractor_missed"}, frozenset()
    )

    report = audit_structural_accuracy(store, ground_truth)

    assert report.node_accuracy.precision == 1.0  # everything predicted was correct
    assert report.node_accuracy.recall is not None and report.node_accuracy.recall < 1.0
    assert report.node_accuracy.false_negative == 1


def test_extra_predicted_node_reduces_precision_not_recall(tmp_path: Path, store: VBGStore) -> None:
    repo_root = tmp_path / "repo"
    _write_repo(repo_root)
    run_static_analysis(store, repo_root, COMMIT)

    predicted_nodes = frozenset(n.entity_id for n in store.get_all_nodes(COMMIT))
    ground_truth = GroundTruthSet(COMMIT, predicted_nodes - {"mod.foo"}, frozenset())

    report = audit_structural_accuracy(store, ground_truth)

    assert report.node_accuracy.recall == 1.0
    assert report.node_accuracy.precision is not None and report.node_accuracy.precision < 1.0
    assert report.node_accuracy.false_positive == 1


def test_edge_accuracy_broken_down_by_relationship_type(tmp_path: Path, store: VBGStore) -> None:
    repo_root = tmp_path / "repo"
    _write_repo(repo_root)
    run_static_analysis(store, repo_root, COMMIT)

    predicted_edges = frozenset(
        (e.source_id, e.target_id, e.relationship_type.value) for e in store.get_all_edges(COMMIT)
    )
    ground_truth = GroundTruthSet(COMMIT, frozenset(), predicted_edges)

    report = audit_structural_accuracy(store, ground_truth)

    assert "calls" in report.edge_accuracy_by_relationship_type
    assert report.edge_accuracy_by_relationship_type["calls"].precision == 1.0


def test_empty_predictions_and_empty_ground_truth_yields_none_not_zero_division(
    tmp_path: Path, store: VBGStore
) -> None:
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    run_static_analysis(store, repo_root, COMMIT)

    ground_truth = GroundTruthSet(COMMIT, frozenset(), frozenset())
    report = audit_structural_accuracy(store, ground_truth)

    assert report.node_accuracy.precision is None
    assert report.node_accuracy.recall is None
