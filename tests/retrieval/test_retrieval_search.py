from __future__ import annotations

from pathlib import Path

from veyra.retrieval import build_retrieval_index, search, search_semantic
from veyra.vbg import VBGStore

COMMIT = "commit1"


def test_exact_symbol_query_returns_exact_node_first(sample_repo: Path, store: VBGStore) -> None:
    index = build_retrieval_index(store, COMMIT)
    results = search(index, "process_order")
    assert results[0].entity.entity_id == "orders.process_order"
    assert results[0].matched_by == "exact_name"


def test_conceptual_query_matches_via_shared_vocabulary(sample_repo: Path, store: VBGStore) -> None:
    index = build_retrieval_index(store, COMMIT)
    results = search_semantic(index, "charge the customer for their order")
    entity_ids = {r.entity.entity_id for r in results}
    assert "orders.charge_customer" in entity_ids


def test_semantic_search_never_invents_entities(sample_repo: Path, store: VBGStore) -> None:
    index = build_retrieval_index(store, COMMIT)
    results = search_semantic(index, "process order")
    known_ids = {e.entity_id for e in index.all_entities()}
    assert all(r.entity.entity_id in known_ids for r in results)


def test_no_shared_vocabulary_returns_no_results(sample_repo: Path, store: VBGStore) -> None:
    index = build_retrieval_index(store, COMMIT)
    results = search_semantic(index, "xylophone quantum teapot")
    assert results == []


def test_search_combines_lexical_and_semantic_deduplicated(sample_repo: Path, store: VBGStore) -> None:
    index = build_retrieval_index(store, COMMIT)
    results = search(index, "order")
    ids = [r.entity.entity_id for r in results]
    assert len(ids) == len(set(ids))  # no duplicates
    assert "orders.process_order" in ids


def test_search_respects_top_k(sample_repo: Path, store: VBGStore) -> None:
    index = build_retrieval_index(store, COMMIT)
    results = search(index, "order", top_k=1)
    assert len(results) == 1


def test_camelcase_and_snakecase_tokenize_the_same(sample_repo: Path, store: VBGStore) -> None:
    index = build_retrieval_index(store, COMMIT)
    snake = search_semantic(index, "process_order")
    camel = search_semantic(index, "processOrder")
    assert {r.entity.entity_id for r in snake} == {r.entity.entity_id for r in camel}
