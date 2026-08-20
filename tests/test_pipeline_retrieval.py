"""
Tests for PLAN.md Phase 4.9 (Retrieval Audit) and the Milestone 4 pipeline
orchestrator (`run_retrieval_analysis()` in src/veyra/pipeline.py) that
ties Phases 4.1-4.3 together end to end.
"""

from __future__ import annotations

from pathlib import Path

from veyra.pipeline import run_retrieval_analysis, run_static_analysis
from veyra.vbg import VBGStore

COMMIT = "commit1"


def _write_sample_repo(repo_root: Path) -> None:
    repo_root.mkdir()
    (repo_root / "orders.py").write_text(
        "def validate_order(order):\n    return True\n\n\n"
        "def process_order(order):\n    return validate_order(order)\n"
    )


def test_run_retrieval_analysis_end_to_end(tmp_path: Path, store: VBGStore) -> None:
    repo_root = tmp_path / "repo"
    _write_sample_repo(repo_root)
    run_static_analysis(store, repo_root, COMMIT)

    report = run_retrieval_analysis(store, COMMIT, ["process_order", "validate order", "xylophone teapot"])

    assert report.repository_version == COMMIT
    assert report.index_build_duration_seconds >= 0
    assert report.index_size > 0
    assert report.queries_run == 3
    assert report.average_query_latency_seconds >= 0
    assert report.total_nodes_retrieved > 0
    assert report.grounded_answer_count == 2  # process_order, validate order
    assert report.unsupported_answer_count == 1  # xylophone teapot matches nothing


def test_precision_recall_mrr_deliberately_not_computed(tmp_path: Path, store: VBGStore) -> None:
    repo_root = tmp_path / "repo"
    _write_sample_repo(repo_root)
    run_static_analysis(store, repo_root, COMMIT)

    report = run_retrieval_analysis(store, COMMIT, ["process_order"])

    assert report.recall_at_k is None
    assert report.precision_at_k is None
    assert report.mrr is None


def test_audit_records_are_persisted(tmp_path: Path, store: VBGStore) -> None:
    repo_root = tmp_path / "repo"
    _write_sample_repo(repo_root)
    run_static_analysis(store, repo_root, COMMIT)

    run_retrieval_analysis(store, COMMIT, ["process_order", "validate_order"])

    assert len(store.get_audit_history("4.x_retrieval_index_build", COMMIT)) == 1
    assert len(store.get_audit_history("4.x_retrieval_query", COMMIT)) == 2


def test_zero_queries_yields_zero_latency_not_an_error(tmp_path: Path, store: VBGStore) -> None:
    repo_root = tmp_path / "repo"
    _write_sample_repo(repo_root)
    run_static_analysis(store, repo_root, COMMIT)

    report = run_retrieval_analysis(store, COMMIT, [])

    assert report.queries_run == 0
    assert report.average_query_latency_seconds == 0.0
