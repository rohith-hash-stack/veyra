"""
Tests for PLAN.md Phase 1.2 schema rules ("every schema rule receives unit
tests"). Storage-level immutability/conflict tests live in test_storage.py.
"""

from __future__ import annotations

import pytest

from veyra.vbg import Edge, Node, RelationshipType, VerificationState


def test_node_requires_entity_id() -> None:
    with pytest.raises(ValueError):
        Node(entity_id="", type="Function", name="foo", repository_version="abc123")


def test_node_requires_repository_version() -> None:
    with pytest.raises(ValueError):
        Node(entity_id="foo", type="Function", name="foo", repository_version="")


def test_node_default_status_is_structurally_identified() -> None:
    node = Node(entity_id="foo", type="Function", name="foo", repository_version="abc123")
    assert node.status is VerificationState.STRUCTURALLY_IDENTIFIED


def test_node_status_must_be_verification_state() -> None:
    with pytest.raises(TypeError):
        Node(
            entity_id="foo",
            type="Function",
            name="foo",
            repository_version="abc123",
            status="not_a_real_status",  # type: ignore[arg-type]
        )


def test_edge_requires_source_and_target() -> None:
    with pytest.raises(TypeError):
        Edge(relationship_type=RelationshipType.CALLS, repository_version="abc123")  # type: ignore[call-arg]


def test_edge_relationship_type_must_be_explicit_enum_member() -> None:
    with pytest.raises(TypeError):
        Edge(
            source_id="a",
            target_id="b",
            relationship_type="calls",  # type: ignore[arg-type]
            repository_version="abc123",
        )


def test_edge_requires_repository_version() -> None:
    with pytest.raises(ValueError):
        Edge(
            source_id="a",
            target_id="b",
            relationship_type=RelationshipType.CALLS,
            repository_version="",
        )


def test_edge_valid_construction() -> None:
    edge = Edge(
        source_id="OrderService.process_order",
        target_id="PaymentService.charge",
        relationship_type=RelationshipType.CALLS,
        repository_version="abc123",
    )
    assert edge.source_id == "OrderService.process_order"
    assert edge.target_id == "PaymentService.charge"
    assert edge.status is VerificationState.STRUCTURALLY_IDENTIFIED


def test_verification_state_can_represent_unknown() -> None:
    # "Unknown states are representable" -- these states describe knowledge
    # that hasn't been established yet, not a failure to record anything.
    node = Node(
        entity_id="foo",
        type="Function",
        name="foo",
        repository_version="abc123",
        status=VerificationState.UNEXPLORED,
    )
    assert node.status is VerificationState.UNEXPLORED


def test_verification_state_can_represent_conflict() -> None:
    edge = Edge(
        source_id="a",
        target_id="b",
        relationship_type=RelationshipType.CALLS,
        repository_version="abc123",
        status=VerificationState.CONFLICTED,
    )
    assert edge.status is VerificationState.CONFLICTED


def test_relationship_type_vocabulary_matches_plan() -> None:
    # Guards against silent drift from PLAN.md Phase 2.3's closed vocabulary.
    expected = {
        "contains", "imports", "calls", "references",
        "inherits", "implements", "depends_on", "defined_in",
    }
    assert {member.value for member in RelationshipType} == expected
