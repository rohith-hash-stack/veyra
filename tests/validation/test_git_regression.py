from __future__ import annotations

from pathlib import Path

from veyra.pipeline import run_static_analysis
from veyra.validation.git_regression import audit_git_regression
from veyra.vbg import VBGStore

OLD = "old_commit"
NEW = "new_commit"


def _write_repo(root: Path, body: str) -> None:
    root.mkdir()
    (root / "mod.py").write_text(f"def foo():\n    return {body}\n\n\ndef bar():\n    return foo()\n")


def test_git_regression_reflects_real_impact_counts(tmp_path: Path, store: VBGStore) -> None:
    old_root = tmp_path / "old"
    new_root = tmp_path / "new"
    _write_repo(old_root, "1")
    _write_repo(new_root, "2")
    run_static_analysis(store, old_root, OLD)
    run_static_analysis(store, new_root, NEW)

    report = audit_git_regression(store, OLD, NEW)

    assert report.changed_symbol_count == 1  # mod.foo's body changed
    assert report.invalidated_node_count >= 1
    assert report.dependent_question_count > 0


def test_rates_needing_ground_truth_are_none(tmp_path: Path, store: VBGStore) -> None:
    old_root = tmp_path / "old"
    new_root = tmp_path / "new"
    _write_repo(old_root, "1")
    _write_repo(new_root, "2")
    run_static_analysis(store, old_root, OLD)
    run_static_analysis(store, new_root, NEW)

    report = audit_git_regression(store, OLD, NEW)

    assert report.unnecessary_invalidation_rate is None
    assert report.missed_invalidation_rate is None


def test_caller_supplied_duration_is_passed_through(tmp_path: Path, store: VBGStore) -> None:
    old_root = tmp_path / "old"
    new_root = tmp_path / "new"
    _write_repo(old_root, "1")
    _write_repo(new_root, "2")
    run_static_analysis(store, old_root, OLD)
    run_static_analysis(store, new_root, NEW)

    report = audit_git_regression(store, OLD, NEW, reverification_duration_seconds=1.5)

    assert report.incremental_reverification_duration_seconds == 1.5


def test_identical_commits_yield_zero_changes(tmp_path: Path, store: VBGStore) -> None:
    root = tmp_path / "repo"
    _write_repo(root, "1")
    run_static_analysis(store, root, "commit_a")
    run_static_analysis(store, root, "commit_b")

    report = audit_git_regression(store, "commit_a", "commit_b")

    assert report.changed_symbol_count == 0
    assert report.invalidated_node_count == 0
