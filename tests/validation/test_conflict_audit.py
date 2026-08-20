from __future__ import annotations

from pathlib import Path

from veyra.pipeline import run_static_analysis
from veyra.validation.conflict_audit import audit_conflicts
from veyra.vbg import Evidence, EvidenceType, Provenance, RelationshipType, VBGStore, edge_evidence_key

COMMIT = "commit1"


def _write_repo(root: Path) -> None:
    root.mkdir()
    (root / "mod.py").write_text("def foo():\n    return 1\n\n\ndef bar():\n    return foo()\n")


def test_static_only_edge_counts_as_static_only_not_conflicted(tmp_path: Path, store: VBGStore) -> None:
    repo_root = tmp_path / "repo"
    _write_repo(repo_root)
    run_static_analysis(store, repo_root, COMMIT)

    report = audit_conflicts(store, COMMIT)

    assert report.static_only_count > 0
    assert report.conflicted_count == 0
    assert report.confirmed_count == 0


def test_runtime_only_edge_is_a_real_conflict(tmp_path: Path, store: VBGStore) -> None:
    repo_root = tmp_path / "repo"
    _write_repo(repo_root)
    run_static_analysis(store, repo_root, COMMIT)
    store.insert_evidence(
        Evidence(
            subject_id=edge_evidence_key("mod.bar", "mod.somewhere_else", RelationshipType.CALLS),
            evidence_type=EvidenceType.RUNTIME, repository_version=COMMIT,
            provenance=Provenance(producer="test", method="test", recorded_at="2026-08-20T00:00:00+00:00"),
            scenario_id="s1", environment_id="e1",
        )
    )

    report = audit_conflicts(store, COMMIT)

    assert report.conflicted_count == 1
    assert report.unresolved_conflict_count == 1
    assert report.resolved_conflict_count == 0


def test_confirmed_edge_counts_as_agreement(tmp_path: Path, store: VBGStore) -> None:
    repo_root = tmp_path / "repo"
    _write_repo(repo_root)
    run_static_analysis(store, repo_root, COMMIT)
    store.insert_evidence(
        Evidence(
            subject_id=edge_evidence_key("mod.bar", "mod.foo", RelationshipType.CALLS),
            evidence_type=EvidenceType.RUNTIME, repository_version=COMMIT,
            provenance=Provenance(producer="test", method="test", recorded_at="2026-08-20T00:00:00+00:00"),
            scenario_id="s1", environment_id="e1",
        )
    )

    report = audit_conflicts(store, COMMIT)

    assert report.confirmed_count == 1
