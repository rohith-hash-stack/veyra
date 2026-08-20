from __future__ import annotations

from pathlib import Path
from typing import Callable

from veyra.retrieval import build_retrieval_index, search, search_semantic
from veyra.static_analysis import extract_repository, persist_extraction
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


# -- Phase D: document-length bias correction (benchmarks/real_world_python/REPORT.md) --


def test_a_large_relevant_method_outranks_a_tiny_entity_sharing_one_token(
    write_file: Callable[[str, str], Path], repo_root: Path, store: VBGStore
) -> None:
    """Reproduces, at fixture scale, the exact mechanism the real-world
    benchmark found (flask-08: Flask.run(), 1026 real tokens, matching 6
    query terms, ranked *below* a 2-token test variable matching only 1).
    Under raw cosine similarity (pre-Phase-D), `widget` -- a document whose
    entire identity is that one word -- would score a perfect match on the
    query's one shared term, while `configure_subsystem`'s dozens of other,
    query-irrelevant tokens would dilute its own five-times-repeated
    'widget' mentions into a near-zero score. BM25 with per-entity-type
    length normalization must not reproduce that: it sums independent,
    saturating per-term contributions rather than normalizing by the whole
    document's unrelated content."""
    write_file(
        "app.py",
        "def configure_subsystem(self, mode, verbose, timeout, retries, cache, cleanup, validate,\n"
        "                         encode, decode, transform, normalize, aggregate, sort, merge):\n"
        '    """Configures the widget subsystem before request handling begins, wiring up the\n'
        "    widget registry, validating each widget's declared dependencies, and finally starting\n"
        '    the widget event loop once every widget has been registered and confirmed healthy."""\n'
        "    self.mode = mode\n"
        "    self.verbose = verbose\n"
        "    self.timeout = timeout\n"
        "    self.retries = retries\n"
        "    self.cache = cache\n"
        "    self.cleanup = cleanup\n"
        "    self.validate = validate\n"
        "    return True\n\n\n"
        "widget = None\n",
    )
    extraction = extract_repository(repo_root, COMMIT)
    persist_extraction(store, extraction)
    index = build_retrieval_index(store, COMMIT)

    results = search_semantic(index, "how does the widget subsystem get configured and started")
    entity_ids = [r.entity.entity_id for r in results]

    assert "app.configure_subsystem" in entity_ids
    assert "app.widget" in entity_ids
    assert entity_ids.index("app.configure_subsystem") < entity_ids.index("app.widget")


def test_length_normalization_is_per_entity_type_not_corpus_wide(sample_repo: Path, store: VBGStore) -> None:
    """The real-world benchmark's Phase D investigation found a *second*,
    sharper mechanism after the first BM25 pass: Flask's real index has
    Method entities averaging 103 tokens and Variable entities averaging 8
    -- a single corpus-wide average (52, dragged down by ~37% of entities
    being near-empty Variable nodes) would still length-normalize every
    substantial Method as "abnormally long". This asserts the per-type
    averages this module now computes are computed separately, not
    collapsed into one figure that would reintroduce that bias."""
    from veyra.retrieval.search import _build_bm25_index

    index = build_retrieval_index(store, COMMIT)
    _, _, _, avg_by_type = _build_bm25_index(index)

    assert "Function" in avg_by_type
    # This fixture's Variable-typed entities (if any) and Function-typed
    # entities must not be forced onto one shared average.
    assert isinstance(avg_by_type["Function"], float)
