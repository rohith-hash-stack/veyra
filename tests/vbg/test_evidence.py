"""
Tests for PLAN.md Phase 1.3 (Evidence & Provenance). Required tests per the
plan: missing provenance, missing commit, runtime evidence without scenario,
evidence versioning, historical evidence retrieval.
"""

from __future__ import annotations

import pytest

from veyra.vbg import Evidence, EvidenceType, Provenance, VBGStore


def _provenance(**overrides: str) -> Provenance:
    defaults = dict(
        producer="veyra.static_analysis.python_extractor",
        method="AST call-site scan",
        recorded_at="2026-08-20T12:00:00+00:00",
    )
    defaults.update(overrides)
    return Provenance(**defaults)


# -- Model-level validation --------------------------------------------------


def test_missing_provenance() -> None:
    with pytest.raises(TypeError):
        Evidence(
            subject_id="OrderService.process_order",
            evidence_type=EvidenceType.STATIC,
            repository_version="commit1",
            provenance=None,  # type: ignore[arg-type]
        )


def test_missing_commit() -> None:
    with pytest.raises(ValueError):
        Evidence(
            subject_id="OrderService.process_order",
            evidence_type=EvidenceType.STATIC,
            repository_version="",
            provenance=_provenance(),
        )


def test_runtime_evidence_without_scenario() -> None:
    with pytest.raises(ValueError, match="scenario_id"):
        Evidence(
            subject_id="OrderService.process_order",
            evidence_type=EvidenceType.RUNTIME,
            repository_version="commit1",
            provenance=_provenance(),
            environment_id="env-1",
        )


def test_runtime_evidence_without_environment() -> None:
    with pytest.raises(ValueError, match="environment_id"):
        Evidence(
            subject_id="OrderService.process_order",
            evidence_type=EvidenceType.RUNTIME,
            repository_version="commit1",
            provenance=_provenance(),
            scenario_id="scenario-1",
        )


def test_runtime_evidence_with_scenario_and_environment_is_valid() -> None:
    evidence = Evidence(
        subject_id="OrderService.process_order",
        evidence_type=EvidenceType.RUNTIME,
        repository_version="commit1",
        provenance=_provenance(),
        scenario_id="scenario-1",
        environment_id="env-1",
    )
    assert evidence.scenario_id == "scenario-1"
    assert evidence.environment_id == "env-1"


def test_static_evidence_does_not_require_scenario() -> None:
    evidence = Evidence(
        subject_id="OrderService.process_order",
        evidence_type=EvidenceType.STATIC,
        repository_version="commit1",
        provenance=_provenance(),
    )
    assert evidence.scenario_id is None


# -- Storage: versioning, historical retrieval, immutability ----------------


def test_evidence_versioning(store: VBGStore) -> None:
    store.insert_evidence(
        Evidence(
            subject_id="foo", evidence_type=EvidenceType.STATIC,
            repository_version="commit1", provenance=_provenance(),
        )
    )
    store.insert_evidence(
        Evidence(
            subject_id="foo", evidence_type=EvidenceType.STATIC,
            repository_version="commit2", provenance=_provenance(),
        )
    )

    commit1_evidence = store.get_evidence_for_subject("foo", "commit1")
    commit2_evidence = store.get_evidence_for_subject("foo", "commit2")

    assert len(commit1_evidence) == 1
    assert len(commit2_evidence) == 1
    assert commit1_evidence[0].repository_version == "commit1"
    assert commit2_evidence[0].repository_version == "commit2"


def test_historical_evidence_retrieval(store: VBGStore) -> None:
    # STATIC and RUNTIME evidence for the same subject at the same commit --
    # both must remain retrievable, neither overwrites the other.
    static_evidence = Evidence(
        subject_id="OrderService.process_order->PaymentService.charge",
        evidence_type=EvidenceType.STATIC,
        repository_version="commit1",
        provenance=_provenance(method="AST call-site scan"),
    )
    runtime_evidence = Evidence(
        subject_id="OrderService.process_order->PaymentService.charge",
        evidence_type=EvidenceType.RUNTIME,
        repository_version="commit1",
        provenance=_provenance(method="traced test execution"),
        scenario_id="scenario-1",
        environment_id="env-1",
    )
    store.insert_evidence(static_evidence)
    store.insert_evidence(runtime_evidence)

    history = store.get_evidence_for_subject(
        "OrderService.process_order->PaymentService.charge", "commit1"
    )

    assert len(history) == 2
    assert {e.evidence_type for e in history} == {EvidenceType.STATIC, EvidenceType.RUNTIME}


def test_store_exposes_no_update_or_delete_for_evidence(store: VBGStore) -> None:
    assert not hasattr(store, "update_evidence")
    assert not hasattr(store, "delete_evidence")


def test_count_evidence(store: VBGStore) -> None:
    assert store.count_evidence("commit1") == 0

    store.insert_evidence(
        Evidence(subject_id="a", evidence_type=EvidenceType.STATIC, repository_version="commit1", provenance=_provenance())
    )
    store.insert_evidence(
        Evidence(
            subject_id="b", evidence_type=EvidenceType.RUNTIME, repository_version="commit1",
            provenance=_provenance(), scenario_id="s1", environment_id="e1",
        )
    )

    assert store.count_evidence("commit1") == 2
    assert store.count_evidence("commit1", EvidenceType.STATIC) == 1
    assert store.count_evidence("commit1", EvidenceType.RUNTIME) == 1
    assert store.count_evidence("commit2") == 0


def test_has_evidence(store: VBGStore) -> None:
    assert store.has_evidence("foo", "commit1") is False

    store.insert_evidence(
        Evidence(
            subject_id="foo", evidence_type=EvidenceType.STATIC,
            repository_version="commit1", provenance=_provenance(),
        )
    )

    assert store.has_evidence("foo", "commit1") is True
