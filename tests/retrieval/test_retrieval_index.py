from __future__ import annotations

from pathlib import Path

from veyra.retrieval import build_retrieval_index
from veyra.vbg import VBGStore, VerificationState

COMMIT = "commit1"


def test_index_contains_every_extracted_entity(sample_repo: Path, store: VBGStore) -> None:
    index = build_retrieval_index(store, COMMIT)
    all_ids = {e.entity_id for e in index.all_entities()}
    assert "orders.process_order" in all_ids
    assert "orders.validate_order" in all_ids
    assert "orders.charge_customer" in all_ids
    assert len(index) == len(all_ids)


def test_docstring_is_extracted_from_lexical_representation(sample_repo: Path, store: VBGStore) -> None:
    index = build_retrieval_index(store, COMMIT)
    entity = index.get("orders.process_order")
    assert entity is not None
    assert entity.docstring == "Processes a customer order end to end."


def test_module_node_has_no_docstring_in_this_slice(sample_repo: Path, store: VBGStore) -> None:
    index = build_retrieval_index(store, COMMIT)
    entity = index.get("orders")
    assert entity is not None
    assert entity.docstring is None  # module nodes carry no lexical_representation (Phase 2.1 scope)


def test_relationships_are_captured(sample_repo: Path, store: VBGStore) -> None:
    index = build_retrieval_index(store, COMMIT)
    entity = index.get("orders.process_order")
    assert ("calls", "orders.validate_order") in entity.outgoing_relationships
    assert ("calls", "orders.charge_customer") in entity.outgoing_relationships


def test_structural_neighborhood_is_captured(sample_repo: Path, store: VBGStore) -> None:
    index = build_retrieval_index(store, COMMIT)
    entity = index.get("orders.process_order")
    assert "orders" in entity.parents
    assert "orders.validate_order" in entity.siblings


def test_verification_state_is_attached(sample_repo: Path, store: VBGStore) -> None:
    index = build_retrieval_index(store, COMMIT)
    entity = index.get("orders.process_order")
    assert isinstance(entity.verification_state, VerificationState)


def test_find_by_name_exact(sample_repo: Path, store: VBGStore) -> None:
    index = build_retrieval_index(store, COMMIT)
    found = index.find_by_name("process_order")
    assert [e.entity_id for e in found] == ["orders.process_order"]


def test_find_by_name_substring(sample_repo: Path, store: VBGStore) -> None:
    index = build_retrieval_index(store, COMMIT)
    found = index.find_by_name("order", exact=False)
    entity_ids = {e.entity_id for e in found}
    assert "orders.process_order" in entity_ids
    assert "orders.validate_order" in entity_ids


def test_find_by_name_no_match_returns_empty(sample_repo: Path, store: VBGStore) -> None:
    index = build_retrieval_index(store, COMMIT)
    assert index.find_by_name("does_not_exist") == []


def test_index_never_invents_entities(sample_repo: Path, store: VBGStore) -> None:
    index = build_retrieval_index(store, COMMIT)
    known_ids = {n.entity_id for n in store.get_all_nodes(COMMIT)}
    assert {e.entity_id for e in index.all_entities()} == known_ids


def test_neighborhood_delegates_to_phase_2_4(sample_repo: Path, store: VBGStore) -> None:
    index = build_retrieval_index(store, COMMIT)
    descendants = index.neighborhood("orders", max_depth=1, store=store)
    assert "orders.process_order" in descendants[1]
