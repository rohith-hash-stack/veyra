from __future__ import annotations

from pathlib import Path

from veyra.pipeline import run_static_analysis
from veyra.validation.performance import audit_performance
from veyra.vbg import VBGStore

COMMIT = "commit1"


def _write_repo(root: Path) -> None:
    root.mkdir()
    (root / "mod.py").write_text("def foo():\n    return 1\n\n\ndef bar():\n    return foo()\n")


def test_performance_report_reflects_real_pipeline_output(tmp_path: Path, store: VBGStore) -> None:
    repo_root = tmp_path / "repo"
    _write_repo(repo_root)
    run_static_analysis(store, repo_root, COMMIT)

    report = audit_performance(store, COMMIT)

    assert report.node_count == len(store.get_all_nodes(COMMIT))
    assert report.edge_count == len(store.get_all_edges(COMMIT))
    assert report.question_count > 0
    assert report.evidence_count > 0
    assert report.index_size == report.node_count


def test_stage_timings_group_by_real_phase_names(tmp_path: Path, store: VBGStore) -> None:
    repo_root = tmp_path / "repo"
    _write_repo(repo_root)
    run_static_analysis(store, repo_root, COMMIT)

    report = audit_performance(store, COMMIT)

    phases = {t.phase for t in report.stage_timings}
    assert "2.x_static_analysis_pipeline" in phases
    timing = next(t for t in report.stage_timings if t.phase == "2.x_static_analysis_pipeline")
    assert timing.run_count == 1
    assert timing.total_duration_seconds >= 0
    assert timing.average_duration_seconds == timing.total_duration_seconds


def test_multiple_runs_of_the_same_phase_are_aggregated(tmp_path: Path, store: VBGStore) -> None:
    repo_root = tmp_path / "repo"
    _write_repo(repo_root)
    run_static_analysis(store, repo_root, COMMIT)
    run_static_analysis(store, repo_root, COMMIT)  # re-run against the same commit

    report = audit_performance(store, COMMIT)

    timing = next(t for t in report.stage_timings if t.phase == "2.x_static_analysis_pipeline")
    assert timing.run_count == 2


def test_no_pipeline_run_yields_empty_timings(tmp_path: Path, store: VBGStore) -> None:
    report = audit_performance(store, "never_analyzed")
    assert report.stage_timings == ()
    assert report.node_count == 0
