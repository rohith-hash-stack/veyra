from __future__ import annotations

from pathlib import Path
from typing import Callable

from veyra.static_analysis import extract_repository, persist_extraction
from veyra.verification import derive_verification_state, derive_verification_states
from veyra.vbg import (
    ClassificationResult,
    Evidence,
    EvidenceType,
    Node,
    Provenance,
    RiskLevel,
    SafetyClass,
    Scenario,
    ScenarioUnexecutableReason,
    VBGStore,
    VerificationState,
)

COMMIT = "commit1"
_RECORDED_AT = "2026-08-20T00:00:00+00:00"


def _provenance(method: str = "test") -> Provenance:
    return Provenance(producer="test", method=method, recorded_at=_RECORDED_AT)


def _node(entity_id: str, node_type: str = "Function") -> Node:
    return Node(
        entity_id=entity_id, type=node_type, name=entity_id.rsplit(".", 1)[-1],
        repository_version=COMMIT, language="Python",
    )


def _evidence(entity_id: str, evidence_type: EvidenceType, status: str, **extra) -> Evidence:
    return Evidence(
        subject_id=entity_id, evidence_type=evidence_type, repository_version=COMMIT,
        provenance=_provenance(), detail=f"status={status}", **extra,
    )


def test_bare_node_is_structurally_identified(store: VBGStore) -> None:
    store.insert_node(_node("mod.foo"))
    assert derive_verification_state(store, "mod.foo", COMMIT) is VerificationState.STRUCTURALLY_IDENTIFIED


def test_static_evidence_only_is_statically_supported(store: VBGStore) -> None:
    store.insert_node(_node("mod.foo"))
    store.insert_evidence(
        Evidence(subject_id="mod.foo", evidence_type=EvidenceType.STATIC, repository_version=COMMIT, provenance=_provenance())
    )
    assert derive_verification_state(store, "mod.foo", COMMIT) is VerificationState.STATICALLY_SUPPORTED


def test_completed_runtime_evidence_is_runtime_verified(store: VBGStore) -> None:
    store.insert_node(_node("mod.foo"))
    store.insert_evidence(_evidence("mod.foo", EvidenceType.RUNTIME, "COMPLETED", scenario_id="s1", environment_id="e1"))
    assert derive_verification_state(store, "mod.foo", COMMIT) is VerificationState.RUNTIME_VERIFIED


def test_exception_runtime_evidence_is_runtime_observed(store: VBGStore) -> None:
    store.insert_node(_node("mod.foo"))
    store.insert_evidence(_evidence("mod.foo", EvidenceType.RUNTIME, "EXCEPTION", scenario_id="s1", environment_id="e1"))
    assert derive_verification_state(store, "mod.foo", COMMIT) is VerificationState.RUNTIME_OBSERVED


def test_passing_test_evidence_only_is_runtime_verified(store: VBGStore) -> None:
    store.insert_node(_node("mod.foo"))
    store.insert_evidence(_evidence("mod.foo", EvidenceType.TEST, "PASS"))
    assert derive_verification_state(store, "mod.foo", COMMIT) is VerificationState.RUNTIME_VERIFIED


def test_failing_test_evidence_only_is_runtime_observed(store: VBGStore) -> None:
    store.insert_node(_node("mod.foo"))
    store.insert_evidence(_evidence("mod.foo", EvidenceType.TEST, "FAIL"))
    assert derive_verification_state(store, "mod.foo", COMMIT) is VerificationState.RUNTIME_OBSERVED


def test_blocked_classification_takes_precedence_over_everything(store: VBGStore) -> None:
    store.insert_node(_node("mod.foo"))
    store.insert_evidence(_evidence("mod.foo", EvidenceType.RUNTIME, "COMPLETED", scenario_id="s1", environment_id="e1"))
    store.insert_classification(
        ClassificationResult(
            target="mod.foo", classification=SafetyClass.BLOCKED, risk_level=RiskLevel.CRITICAL,
            capabilities_detected=(), matched_rules=(), reason="blocked for test",
            evidence=(), repository_commit=COMMIT, policy_version="v1",
        )
    )
    assert derive_verification_state(store, "mod.foo", COMMIT) is VerificationState.BLOCKED_BY_SAFETY


def test_all_scenarios_unexecutable_is_unexecutable(store: VBGStore) -> None:
    store.insert_node(_node("mod.foo"))
    store.insert_scenario(
        Scenario(
            scenario_id="s1", target_entity_id="mod.foo", description="d", required_inputs=("x",),
            dependencies=(), expected_observable_points=(), safety_class=SafetyClass.UNKNOWN,
            executable=False, repository_version=COMMIT,
            unexecutable_reason=ScenarioUnexecutableReason.MISSING_FIXTURE, detail="no strategy for x",
        )
    )
    assert derive_verification_state(store, "mod.foo", COMMIT) is VerificationState.UNEXECUTABLE


def test_at_least_one_executable_scenario_is_not_unexecutable(store: VBGStore) -> None:
    store.insert_node(_node("mod.foo"))
    store.insert_scenario(
        Scenario(
            scenario_id="s1", target_entity_id="mod.foo", description="d", required_inputs=(),
            dependencies=(), expected_observable_points=(), safety_class=SafetyClass.SANDBOXABLE,
            executable=True, repository_version=COMMIT,
        )
    )
    assert derive_verification_state(store, "mod.foo", COMMIT) is not VerificationState.UNEXECUTABLE


def test_unconfirmed_static_call_is_unexplored(
    write_file: Callable[[str, str], Path], repo_root: Path, store: VBGStore
) -> None:
    write_file("mod.py", "def helper():\n    return 1\n\n\ndef foo():\n    return helper()\n")
    persist_extraction(store, extract_repository(repo_root, COMMIT))
    assert derive_verification_state(store, "mod.foo", COMMIT) is VerificationState.UNEXPLORED


def test_runtime_only_call_makes_source_conflicted(
    write_file: Callable[[str, str], Path], repo_root: Path, store: VBGStore
) -> None:
    from veyra.vbg import RelationshipType, edge_evidence_key

    write_file("mod.py", "def foo():\n    return 1\n")
    persist_extraction(store, extract_repository(repo_root, COMMIT))
    store.insert_evidence(
        Evidence(
            subject_id=edge_evidence_key("mod.foo", "mod.somewhere_else", RelationshipType.CALLS),
            evidence_type=EvidenceType.RUNTIME, repository_version=COMMIT, provenance=_provenance(),
            scenario_id="s1", environment_id="e1",
        )
    )
    assert derive_verification_state(store, "mod.foo", COMMIT) is VerificationState.CONFLICTED


def test_two_confirmed_branches_is_conditionally_verified(
    write_file: Callable[[str, str], Path], repo_root: Path, store: VBGStore
) -> None:
    from veyra.vbg import RelationshipType, edge_evidence_key

    write_file(
        "mod.py",
        "def a():\n    return 1\n\n\ndef b():\n    return 2\n\n\n"
        "def foo(flag):\n    return a() if flag else b()\n",
    )
    persist_extraction(store, extract_repository(repo_root, COMMIT))
    for target, scenario_id in (("mod.a", "s1"), ("mod.b", "s2")):
        store.insert_evidence(
            Evidence(
                subject_id=edge_evidence_key("mod.foo", target, RelationshipType.CALLS),
                evidence_type=EvidenceType.RUNTIME, repository_version=COMMIT, provenance=_provenance(),
                scenario_id=scenario_id, environment_id="e1",
            )
        )
    store.insert_evidence(_evidence("mod.foo", EvidenceType.RUNTIME, "COMPLETED", scenario_id="s3", environment_id="e1"))

    assert derive_verification_state(store, "mod.foo", COMMIT) is VerificationState.CONDITIONALLY_VERIFIED


def test_derive_verification_states_covers_every_node(
    write_file: Callable[[str, str], Path], repo_root: Path, store: VBGStore
) -> None:
    write_file("mod.py", "def foo():\n    return 1\n\n\ndef bar():\n    return 2\n")
    extraction = extract_repository(repo_root, COMMIT)
    persist_extraction(store, extraction)

    states = derive_verification_states(store, COMMIT)

    known_entity_ids = {n.entity_id for n in extraction.nodes}
    assert known_entity_ids <= states.keys()
    assert all(isinstance(v, VerificationState) for v in states.values())


def test_stale_entity_ids_overrides_every_other_signal(store: VBGStore) -> None:
    store.insert_node(_node("mod.foo"))
    store.insert_evidence(_evidence("mod.foo", EvidenceType.RUNTIME, "COMPLETED", scenario_id="s1", environment_id="e1"))
    store.insert_classification(
        ClassificationResult(
            target="mod.foo", classification=SafetyClass.BLOCKED, risk_level=RiskLevel.CRITICAL,
            capabilities_detected=(), matched_rules=(), reason="blocked for test",
            evidence=(), repository_commit=COMMIT, policy_version="v1",
        )
    )

    state = derive_verification_state(store, "mod.foo", COMMIT, stale_entity_ids=frozenset({"mod.foo"}))

    assert state is VerificationState.STALE


def test_omitting_stale_entity_ids_preserves_prior_behavior(store: VBGStore) -> None:
    store.insert_node(_node("mod.foo"))
    store.insert_evidence(_evidence("mod.foo", EvidenceType.RUNTIME, "COMPLETED", scenario_id="s1", environment_id="e1"))

    assert derive_verification_state(store, "mod.foo", COMMIT) is VerificationState.RUNTIME_VERIFIED


def test_unknown_entity_defaults_to_structurally_identified(store: VBGStore) -> None:
    assert derive_verification_state(store, "does.not.exist", COMMIT) is VerificationState.STRUCTURALLY_IDENTIFIED
