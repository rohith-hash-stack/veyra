from __future__ import annotations

from pathlib import Path

from veyra.invalidation import analyze_impact
from veyra.pipeline import run_static_analysis
from veyra.vbg import Evidence, EvidenceType, Provenance, RelationshipType, VBGStore, edge_evidence_key

OLD = "old_commit"
NEW = "new_commit"


def _write_repo(root: Path, helper_body: str) -> None:
    root.mkdir(exist_ok=True)
    (root / "mod.py").write_text(
        f"def helper():\n    return {helper_body}\n\n\ndef foo():\n    return helper()\n"
    )


def _build_two_commits(tmp_path: Path, store: VBGStore) -> None:
    old_root = tmp_path / "old"
    new_root = tmp_path / "new"
    _write_repo(old_root, "1")
    _write_repo(new_root, "2")  # body of helper() changes; foo() is textually unchanged
    run_static_analysis(store, old_root, OLD)
    run_static_analysis(store, new_root, NEW)


def test_tier_0_is_the_changed_symbol(tmp_path: Path, store: VBGStore) -> None:
    _build_two_commits(tmp_path, store)

    report = analyze_impact(store, OLD, NEW)

    assert report.tier_0 == {"mod.helper"}


def test_unchanged_signature_with_changed_body_still_lands_in_tier_0(tmp_path: Path, store: VBGStore) -> None:
    # helper()'s signature is identical between commits -- only its body
    # changed. PLAN's own "unchanged signatures do not prove unchanged
    # behavior" rule is satisfied precisely by this landing in tier_0 too.
    _build_two_commits(tmp_path, store)
    report = analyze_impact(store, OLD, NEW)
    assert "mod.helper" in report.tier_0


def test_textually_unchanged_caller_is_not_in_tier_0(tmp_path: Path, store: VBGStore) -> None:
    _build_two_commits(tmp_path, store)
    report = analyze_impact(store, OLD, NEW)
    assert "mod.foo" not in report.tier_0


def test_direct_caller_lands_in_tier_1(tmp_path: Path, store: VBGStore) -> None:
    _build_two_commits(tmp_path, store)
    report = analyze_impact(store, OLD, NEW)
    assert "mod.foo" in report.tier_1


def test_tier_1_excludes_tier_0_itself(tmp_path: Path, store: VBGStore) -> None:
    _build_two_commits(tmp_path, store)
    report = analyze_impact(store, OLD, NEW)
    assert report.tier_1.isdisjoint(report.tier_0)


def test_tier_2_finds_dependent_questions(tmp_path: Path, store: VBGStore) -> None:
    _build_two_commits(tmp_path, store)
    report = analyze_impact(store, OLD, NEW)
    assert len(report.tier_2_question_ids) > 0
    all_question_ids = {q.question_id for q in store.get_questions(NEW)} | {q.question_id for q in store.get_questions(OLD)}
    assert report.tier_2_question_ids <= all_question_ids


def test_tier_3_captures_runtime_observed_dependency_static_missed(tmp_path: Path, store: VBGStore) -> None:
    _build_two_commits(tmp_path, store)
    store.insert_evidence(
        Evidence(
            subject_id=edge_evidence_key("mod.foo", "mod.dynamically_reached", RelationshipType.CALLS),
            evidence_type=EvidenceType.RUNTIME, repository_version=NEW,
            provenance=Provenance(producer="test", method="test", recorded_at="2026-08-20T00:00:00+00:00"),
            scenario_id="s1", environment_id="e1",
        )
    )

    report = analyze_impact(store, OLD, NEW)

    assert "mod.dynamically_reached" in report.tier_3


def test_stale_entity_ids_is_tier_0_union_tier_1_union_tier_3(tmp_path: Path, store: VBGStore) -> None:
    _build_two_commits(tmp_path, store)
    store.insert_evidence(
        Evidence(
            subject_id=edge_evidence_key("mod.foo", "mod.dynamically_reached", RelationshipType.CALLS),
            evidence_type=EvidenceType.RUNTIME, repository_version=NEW,
            provenance=Provenance(producer="test", method="test", recorded_at="2026-08-20T00:00:00+00:00"),
            scenario_id="s1", environment_id="e1",
        )
    )

    report = analyze_impact(store, OLD, NEW)

    assert report.stale_entity_ids == report.tier_0 | report.tier_1 | report.tier_3


def test_no_changes_between_identical_commits_yields_empty_report(tmp_path: Path, store: VBGStore) -> None:
    root = tmp_path / "repo"
    _write_repo(root, "1")
    run_static_analysis(store, root, "commit_a")
    run_static_analysis(store, root, "commit_b")

    report = analyze_impact(store, "commit_a", "commit_b")

    assert report.tier_0 == frozenset()
    assert report.tier_1 == frozenset()
    assert report.tier_3 == frozenset()


def test_stale_ids_actually_produce_stale_verification_state(tmp_path: Path, store: VBGStore) -> None:
    from veyra.verification import derive_verification_states
    from veyra.vbg import VerificationState

    _build_two_commits(tmp_path, store)
    report = analyze_impact(store, OLD, NEW)

    states = derive_verification_states(store, NEW, stale_entity_ids=report.stale_entity_ids)

    assert states["mod.helper"] is VerificationState.STALE
