from __future__ import annotations

from pathlib import Path
from typing import Callable

from veyra.reconciliation import ReconciliationStatus, reconcile_calls
from veyra.static_analysis import extract_repository, persist_extraction
from veyra.vbg import Evidence, EvidenceType, Provenance, RelationshipType, VBGStore, edge_evidence_key

COMMIT = "commit1"


def _runtime_call_evidence(source_id: str, target_id: str, scenario_id: str = "s1") -> Evidence:
    return Evidence(
        subject_id=edge_evidence_key(source_id, target_id, RelationshipType.CALLS),
        evidence_type=EvidenceType.RUNTIME,
        repository_version=COMMIT,
        provenance=Provenance(producer="test", method="pre-seeded", recorded_at="2026-08-20T00:00:00+00:00"),
        scenario_id=scenario_id,
        environment_id="env1",
    )


def test_static_edge_never_runtime_observed_is_static_only(
    write_file: Callable[[str, str], Path], repo_root: Path, store: VBGStore
) -> None:
    write_file("mod.py", "def helper():\n    return 1\n\n\ndef foo():\n    return helper()\n")
    extraction = extract_repository(repo_root, COMMIT)
    persist_extraction(store, extraction)

    results = reconcile_calls(store, COMMIT)

    pair = next(r for r in results if r.source_id == "mod.foo" and r.target_id == "mod.helper")
    assert pair.status is ReconciliationStatus.STATIC_ONLY
    assert pair.is_conflict is False


def test_static_edge_runtime_observed_is_confirmed(
    write_file: Callable[[str, str], Path], repo_root: Path, store: VBGStore
) -> None:
    write_file("mod.py", "def helper():\n    return 1\n\n\ndef foo():\n    return helper()\n")
    extraction = extract_repository(repo_root, COMMIT)
    persist_extraction(store, extraction)
    store.insert_evidence(_runtime_call_evidence("mod.foo", "mod.helper"))

    results = reconcile_calls(store, COMMIT)

    pair = next(r for r in results if r.source_id == "mod.foo" and r.target_id == "mod.helper")
    assert pair.status is ReconciliationStatus.CONFIRMED
    assert pair.is_conflict is False
    assert pair.runtime_observation_count == 1


def test_runtime_only_call_is_flagged_as_conflict(
    write_file: Callable[[str, str], Path], repo_root: Path, store: VBGStore
) -> None:
    write_file("mod.py", "def foo():\n    return 1\n")
    extraction = extract_repository(repo_root, COMMIT)
    persist_extraction(store, extraction)
    # A runtime observation of a call static analysis never predicted at
    # all (e.g. dynamic dispatch beyond the extractor's resolution).
    store.insert_evidence(_runtime_call_evidence("mod.foo", "mod.somewhere_else"))

    results = reconcile_calls(store, COMMIT)

    pair = next(r for r in results if r.source_id == "mod.foo" and r.target_id == "mod.somewhere_else")
    assert pair.status is ReconciliationStatus.RUNTIME_ONLY
    assert pair.is_conflict is True
    assert pair.static_edge_count == 0


def test_multiple_runtime_observations_of_the_same_edge_are_counted(
    write_file: Callable[[str, str], Path], repo_root: Path, store: VBGStore
) -> None:
    write_file("mod.py", "def helper():\n    return 1\n\n\ndef foo():\n    return helper()\n")
    extraction = extract_repository(repo_root, COMMIT)
    persist_extraction(store, extraction)
    store.insert_evidence(_runtime_call_evidence("mod.foo", "mod.helper", scenario_id="s1"))
    store.insert_evidence(_runtime_call_evidence("mod.foo", "mod.helper", scenario_id="s2"))

    results = reconcile_calls(store, COMMIT)

    pair = next(r for r in results if r.source_id == "mod.foo" and r.target_id == "mod.helper")
    assert pair.runtime_observation_count == 2
    assert pair.status is ReconciliationStatus.CONFIRMED


def test_conditional_branching_both_paths_confirmed_independently(
    write_file: Callable[[str, str], Path], repo_root: Path, store: VBGStore
) -> None:
    write_file(
        "mod.py",
        "def branch_a():\n    return 1\n\n\n"
        "def branch_b():\n    return 2\n\n\n"
        "def foo(flag):\n    return branch_a() if flag else branch_b()\n",
    )
    extraction = extract_repository(repo_root, COMMIT)
    persist_extraction(store, extraction)
    # Two different trials took two different conditional branches -- both
    # are legitimate, neither is wrong; PLAN's own "conditional behavior
    # representable" acceptance criterion.
    store.insert_evidence(_runtime_call_evidence("mod.foo", "mod.branch_a", scenario_id="s1"))
    store.insert_evidence(_runtime_call_evidence("mod.foo", "mod.branch_b", scenario_id="s2"))

    results = reconcile_calls(store, COMMIT)

    a = next(r for r in results if r.target_id == "mod.branch_a")
    b = next(r for r in results if r.target_id == "mod.branch_b")
    assert a.status is ReconciliationStatus.CONFIRMED
    assert b.status is ReconciliationStatus.CONFIRMED


def test_node_level_runtime_evidence_is_not_mistaken_for_an_edge(
    write_file: Callable[[str, str], Path], repo_root: Path, store: VBGStore
) -> None:
    write_file("mod.py", "def foo():\n    return 1\n")
    extraction = extract_repository(repo_root, COMMIT)
    persist_extraction(store, extraction)
    # Node-level RUNTIME evidence (subject_id is a plain entity_id, exactly
    # what run_scenario() persists for the target itself) must not be
    # parsed as an edge or show up in the reconciliation results at all.
    store.insert_evidence(
        Evidence(
            subject_id="mod.foo", evidence_type=EvidenceType.RUNTIME, repository_version=COMMIT,
            provenance=Provenance(producer="test", method="pre-seeded", recorded_at="2026-08-20T00:00:00+00:00"),
            scenario_id="s1", environment_id="env1",
        )
    )

    results = reconcile_calls(store, COMMIT)

    assert results == []


def test_deterministic_ordering(write_file: Callable[[str, str], Path], repo_root: Path, store: VBGStore) -> None:
    write_file(
        "mod.py",
        "def z():\n    return 1\n\n\ndef a():\n    return 1\n\n\ndef foo():\n    return z() + a()\n",
    )
    extraction = extract_repository(repo_root, COMMIT)
    persist_extraction(store, extraction)

    first = reconcile_calls(store, COMMIT)
    second = reconcile_calls(store, COMMIT)

    assert first == second
    assert [(r.source_id, r.target_id) for r in first] == sorted(
        (r.source_id, r.target_id) for r in first
    )
