from __future__ import annotations

from veyra.retrieval import GroundedFact, GroundingContext
from veyra.validation.false_verification import (
    FalseVerificationGroundTruth,
    audit_false_verification,
    score_calibration,
)
from veyra.vbg import Evidence, EvidenceType, Provenance, VBGStore, VerificationState

COMMIT = "commit1"


def _runtime_verified_evidence(entity_id: str) -> Evidence:
    return Evidence(
        subject_id=entity_id, evidence_type=EvidenceType.RUNTIME, repository_version=COMMIT,
        provenance=Provenance(producer="test", method="test", recorded_at="2026-08-20T00:00:00+00:00"),
        detail="status=COMPLETED", scenario_id="s1", environment_id="e1",
    )


def test_without_ground_truth_rate_is_none_but_count_is_real(store: VBGStore) -> None:
    store.insert_evidence(_runtime_verified_evidence("mod.foo"))
    from veyra.vbg import Node

    store.insert_node(Node(entity_id="mod.foo", type="Function", name="foo", repository_version=COMMIT))

    report = audit_false_verification(store, COMMIT)

    assert report.verified_count == 1
    assert report.false_verification_rate is None
    assert report.release_criterion_met is None


def test_with_ground_truth_computes_a_real_rate(store: VBGStore) -> None:
    from veyra.vbg import Node

    store.insert_node(Node(entity_id="mod.foo", type="Function", name="foo", repository_version=COMMIT))
    store.insert_node(Node(entity_id="mod.bar", type="Function", name="bar", repository_version=COMMIT))
    store.insert_evidence(_runtime_verified_evidence("mod.foo"))
    store.insert_evidence(_runtime_verified_evidence("mod.bar"))
    ground_truth = FalseVerificationGroundTruth(COMMIT, frozenset({"mod.foo"}))

    report = audit_false_verification(store, COMMIT, ground_truth)

    assert report.verified_count == 2
    assert report.known_incorrect_count == 1
    assert report.false_verification_rate == 0.5
    assert report.release_criterion_met is False


def test_zero_known_incorrect_meets_the_release_criterion(store: VBGStore) -> None:
    from veyra.vbg import Node

    store.insert_node(Node(entity_id="mod.foo", type="Function", name="foo", repository_version=COMMIT))
    store.insert_evidence(_runtime_verified_evidence("mod.foo"))
    ground_truth = FalseVerificationGroundTruth(COMMIT, frozenset())

    report = audit_false_verification(store, COMMIT, ground_truth)

    assert report.false_verification_rate == 0.0
    assert report.release_criterion_met is True


def _grounding_with_fact(state: VerificationState) -> GroundingContext:
    fact = GroundedFact(
        entity_id="mod.risky_function", node_type="Function", summary="Function `risky_function`",
        verification_state=state, verification_note="NOTE: something", evidence_excerpts=(),
    )
    return GroundingContext(
        query="risky_function", repository_version=COMMIT, facts=(fact,),
        conflicts=(), unknowns=(), disclaimer="disclaimer text",
    )


def test_hedged_answer_about_unverified_fact_is_compliant() -> None:
    grounding = _grounding_with_fact(VerificationState.STATICALLY_SUPPORTED)
    answer = "risky_function has not been executed, so its behavior is unverified."

    result = score_calibration(grounding, answer)

    assert result.checks[0].compliant is True
    assert result.compliance_rate == 1.0


def test_unhedged_answer_about_unverified_fact_is_noncompliant() -> None:
    grounding = _grounding_with_fact(VerificationState.STATICALLY_SUPPORTED)
    answer = "risky_function always returns a valid order."

    result = score_calibration(grounding, answer)

    assert result.checks[0].compliant is False
    assert result.compliance_rate == 0.0


def test_runtime_verified_fact_never_requires_a_hedge() -> None:
    grounding = _grounding_with_fact(VerificationState.RUNTIME_VERIFIED)
    answer = "risky_function always returns a valid order."

    result = score_calibration(grounding, answer)

    assert result.checks[0].requires_hedge is False
    assert result.checks[0].compliant is True


def test_entity_never_mentioned_is_trivially_compliant() -> None:
    grounding = _grounding_with_fact(VerificationState.CONFLICTED)
    answer = "This talks about something else entirely."

    result = score_calibration(grounding, answer)

    assert result.checks[0].entity_mentioned is False
    assert result.checks[0].compliant is True
    assert result.compliance_rate is None  # nothing relevant was actually checked
