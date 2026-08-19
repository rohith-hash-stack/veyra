"""
Tests for PLAN.md Phase 2.8 (Static Audit) and the Milestone 2 pipeline
orchestrator (src/veyra/pipeline.py) that ties Phases 2.1/2.5/2.6/2.7
together end to end.
"""

from __future__ import annotations

from pathlib import Path

from veyra.pipeline import run_static_analysis
from veyra.vbg import VBGStore

COMMIT = "commit1"


def _write_sample_repo(repo_root: Path) -> None:
    repo_root.mkdir()
    (repo_root / "base.py").write_text("class BaseService:\n    pass\n")
    (repo_root / "orders.py").write_text(
        "from base import BaseService\n"
        "\n"
        "class OrderService(BaseService):\n"
        "    def process_order(self):\n"
        "        self.validate_order()\n"
        "\n"
        "    def validate_order(self):\n"
        "        pass\n",
    )
    (repo_root / "broken.py").write_text("def broken(:\n")  # deliberate syntax error


def test_run_static_analysis_end_to_end(tmp_path: Path, store: VBGStore) -> None:
    repo_root = tmp_path / "repo"
    _write_sample_repo(repo_root)

    report = run_static_analysis(store, repo_root, COMMIT)

    assert report.repository_version == COMMIT
    assert report.analysis_duration_seconds >= 0
    assert report.files_analyzed == 2  # base.py, orders.py
    assert report.files_failed == 1  # broken.py
    assert report.unsupported_rate == 1 / 3
    assert report.node_count > 0
    assert report.edge_count > 0
    assert "contains" in report.edges_by_relationship_type
    assert "inherits" in report.edges_by_relationship_type
    assert report.questions_generated > 0
    assert report.questions_answered > 0
    # Every generated question was answerable at generation time (Phase 2.5
    # only emits when there's a real fact) -- none should be unanswered here.
    assert report.questions_unanswered == 0
    assert report.static_evidence_created == report.questions_answered
    assert report.questions_deduplicated == 0


def test_precision_and_recall_deliberately_not_computed(tmp_path: Path, store: VBGStore) -> None:
    repo_root = tmp_path / "repo"
    _write_sample_repo(repo_root)

    report = run_static_analysis(store, repo_root, COMMIT)

    # Per D6: these need Milestone 5 ground truth, not computed here.
    assert report.static_precision is None
    assert report.static_recall is None


def test_pipeline_results_are_actually_persisted(tmp_path: Path, store: VBGStore) -> None:
    repo_root = tmp_path / "repo"
    _write_sample_repo(repo_root)

    run_static_analysis(store, repo_root, COMMIT)

    assert store.get_latest_node("orders.OrderService", COMMIT) is not None
    assert len(store.get_questions(COMMIT)) > 0
    assert len(store.get_audit_history("2.x_static_analysis_pipeline", COMMIT)) == 1


def test_audit_record_is_persisted_and_successful(tmp_path: Path, store: VBGStore) -> None:
    repo_root = tmp_path / "repo"
    _write_sample_repo(repo_root)

    run_static_analysis(store, repo_root, COMMIT)

    history = store.get_audit_history("2.x_static_analysis_pipeline", COMMIT)
    assert history[0].success is True
    assert history[0].error_reason is None
