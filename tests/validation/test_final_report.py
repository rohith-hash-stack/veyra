from __future__ import annotations

from pathlib import Path

from veyra.pipeline import run_static_analysis
from veyra.validation.false_verification import FalseVerificationGroundTruth
from veyra.validation.final_report import ReleaseStatus, build_final_report
from veyra.vbg import Evidence, EvidenceType, Provenance, VBGStore

COMMIT = "commit1"
_VEYRA_REPO_ROOT = Path(__file__).resolve().parents[2]


def _write_repo(root: Path) -> None:
    root.mkdir()
    (root / "mod.py").write_text("def foo():\n    return 1\n")


def _mark_runtime_verified(store: VBGStore, entity_id: str) -> None:
    store.insert_evidence(
        Evidence(
            subject_id=entity_id, evidence_type=EvidenceType.RUNTIME, repository_version=COMMIT,
            provenance=Provenance(producer="test", method="test", recorded_at="2026-08-20T00:00:00+00:00"),
            detail="status=COMPLETED", scenario_id="s1", environment_id="e1",
        )
    )


def test_real_repo_without_false_verification_ground_truth_is_partially_verified(
    tmp_path: Path, store: VBGStore
) -> None:
    repo_root = tmp_path / "repo"
    _write_repo(repo_root)
    run_static_analysis(store, repo_root, COMMIT)

    report = build_final_report(store, COMMIT, _VEYRA_REPO_ROOT)

    assert report.status is ReleaseStatus.PARTIALLY_VERIFIED
    assert report.traceability.fully_traceable is True
    assert report.security.coverage_complete is True
    assert len(report.status_reasons) == 1
    assert "no ground truth" in report.status_reasons[0]


def test_zero_known_false_verifications_yields_pass(tmp_path: Path, store: VBGStore) -> None:
    repo_root = tmp_path / "repo"
    _write_repo(repo_root)
    run_static_analysis(store, repo_root, COMMIT)
    _mark_runtime_verified(store, "mod.foo")  # a real verified claim to check ground truth against
    ground_truth = FalseVerificationGroundTruth(COMMIT, frozenset())

    report = build_final_report(
        store, COMMIT, _VEYRA_REPO_ROOT, false_verification_ground_truth=ground_truth
    )

    assert report.status is ReleaseStatus.PASS
    assert report.status_reasons == ()


def test_known_false_verification_yields_fail(tmp_path: Path, store: VBGStore) -> None:
    repo_root = tmp_path / "repo"
    _write_repo(repo_root)
    run_static_analysis(store, repo_root, COMMIT)
    _mark_runtime_verified(store, "mod.foo")
    ground_truth = FalseVerificationGroundTruth(COMMIT, frozenset({"mod.foo"}))

    report = build_final_report(
        store, COMMIT, _VEYRA_REPO_ROOT, false_verification_ground_truth=ground_truth
    )

    assert report.status is ReleaseStatus.FAIL
    assert "known false-verification" in report.status_reasons[0]


def test_broken_veyra_repo_root_fails_on_traceability_and_security(tmp_path: Path, store: VBGStore) -> None:
    repo_root = tmp_path / "repo"
    _write_repo(repo_root)
    run_static_analysis(store, repo_root, COMMIT)
    fake_veyra_root = tmp_path / "not_a_real_veyra_checkout"
    fake_veyra_root.mkdir()

    report = build_final_report(store, COMMIT, fake_veyra_root)

    assert report.status is ReleaseStatus.FAIL
    assert len(report.status_reasons) == 2


def test_report_carries_every_named_sub_report(tmp_path: Path, store: VBGStore) -> None:
    repo_root = tmp_path / "repo"
    _write_repo(repo_root)
    run_static_analysis(store, repo_root, COMMIT)

    report = build_final_report(store, COMMIT, _VEYRA_REPO_ROOT)

    assert report.performance.node_count > 0
    assert report.question_quality.questions_generated > 0
    assert report.behavioral_coverage.total_nodes > 0
    assert report.conflict_audit.repository_version == COMMIT
    assert report.structural_accuracy is None  # no structural ground truth supplied
