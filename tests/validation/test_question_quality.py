from __future__ import annotations

from pathlib import Path

from veyra.pipeline import run_static_analysis
from veyra.validation.question_quality import audit_question_quality
from veyra.vbg import VBGStore

COMMIT = "commit1"


def _write_repo(root: Path) -> None:
    root.mkdir()
    (root / "mod.py").write_text("def foo():\n    return 1\n\n\ndef bar():\n    return foo()\n")


def test_question_quality_reflects_real_counts(tmp_path: Path, store: VBGStore) -> None:
    repo_root = tmp_path / "repo"
    _write_repo(repo_root)
    run_static_analysis(store, repo_root, COMMIT)

    report = audit_question_quality(store, COMMIT)

    assert report.questions_generated > 0
    assert report.questions_valid == report.questions_generated
    assert report.questions_duplicate == 0
    assert report.questions_unsupported == 0
    assert report.questions_answered + report.questions_unanswered == report.questions_generated


def test_answered_questions_with_evidence_count_as_verified(tmp_path: Path, store: VBGStore) -> None:
    repo_root = tmp_path / "repo"
    _write_repo(repo_root)
    run_static_analysis(store, repo_root, COMMIT)

    report = audit_question_quality(store, COMMIT)

    # run_static_analysis() verifies every generated question and inserts
    # STATIC evidence for each -- so every answered question should also
    # count as verified here.
    assert report.questions_verified == report.questions_answered


def test_empty_repo_yields_zero_report(tmp_path: Path, store: VBGStore) -> None:
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    run_static_analysis(store, repo_root, COMMIT)

    report = audit_question_quality(store, COMMIT)

    assert report.questions_generated == 0
    assert report.questions_verified == 0
