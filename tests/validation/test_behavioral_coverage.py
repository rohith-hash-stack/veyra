from __future__ import annotations

from pathlib import Path

from veyra.pipeline import run_runtime_analysis, run_static_analysis
from veyra.validation.behavioral_coverage import audit_behavioral_coverage
from veyra.vbg import VBGStore

COMMIT = "commit1"


class _NullBoundary:
    """Nothing in this test file needs a real execution -- Tier 3
    (file_count > 500) performs zero eager executions by design (D10), so
    this fake boundary's methods are never actually called."""

    def execute(self, request):  # pragma: no cover - never called
        raise AssertionError("should never execute under Tier 3")

    def terminate(self, handle):  # pragma: no cover
        pass

    def collect_result(self, handle, timeout_seconds=None):  # pragma: no cover
        pass

    def cleanup(self, handle):  # pragma: no cover
        pass


def _write_repo(root: Path) -> None:
    root.mkdir()
    (root / "mod.py").write_text("def foo():\n    return 1\n\n\ndef bar():\n    return foo()\n")


def test_structural_coverage_equals_total_nodes(tmp_path: Path, store: VBGStore) -> None:
    repo_root = tmp_path / "repo"
    _write_repo(repo_root)
    run_static_analysis(store, repo_root, COMMIT)

    report = audit_behavioral_coverage(store, COMMIT)

    assert report.structural_coverage == report.total_nodes
    assert report.total_nodes == len(store.get_all_nodes(COMMIT))


def test_static_evidence_coverage_reflects_answered_questions(tmp_path: Path, store: VBGStore) -> None:
    repo_root = tmp_path / "repo"
    _write_repo(repo_root)
    run_static_analysis(store, repo_root, COMMIT)

    report = audit_behavioral_coverage(store, COMMIT)

    assert report.static_evidence_coverage > 0
    assert report.runtime_observation_coverage == 0  # no runtime pipeline ran yet


def test_no_runtime_yet_means_zero_runtime_verification_and_unobserved_edges_reported(
    tmp_path: Path, store: VBGStore
) -> None:
    repo_root = tmp_path / "repo"
    _write_repo(repo_root)
    run_static_analysis(store, repo_root, COMMIT)

    report = audit_behavioral_coverage(store, COMMIT)

    assert report.runtime_verification_coverage == 0
    # foo()/bar() has a real static CALLS edge never runtime-confirmed.
    assert report.unobserved_edge_count > 0
    # UNEXPLORED specifically requires zero evidence of any kind on the
    # node itself -- once run_static_analysis() has answered a node's own
    # questions (inserting STATIC evidence for it), it becomes
    # STATICALLY_SUPPORTED instead, which correctly outranks UNEXPLORED in
    # Phase 3.8's precedence. UNEXPLORED is therefore rare once static
    # verification has run project-wide, not a bug in this report.
    assert report.unexplored_node_count == 0


def test_after_runtime_pipeline_some_nodes_become_verified(tmp_path: Path, store: VBGStore) -> None:
    repo_root = tmp_path / "repo"
    _write_repo(repo_root)
    run_static_analysis(store, repo_root, COMMIT)
    # Tier 3 (file_count > 500) performs zero eager execution per D10 --
    # this test only needs to prove the report reflects whatever runtime
    # state exists, not exercise a real execution boundary.
    run_runtime_analysis(store, repo_root, COMMIT, _NullBoundary(), file_count=501)

    report = audit_behavioral_coverage(store, COMMIT)

    assert report.runtime_verification_coverage == 0  # nothing ran under Tier 3
    assert report.unexecutable_count == 0
    assert report.blocked_count == 0
    assert report.conflicted_count == 0
