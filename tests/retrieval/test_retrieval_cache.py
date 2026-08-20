from __future__ import annotations

from pathlib import Path

from veyra.retrieval import (
    RetrievalCache,
    audit_cache_growth,
    build_retrieval_index,
    retrieve_context_cached,
    warm_eager_cache,
)
from veyra.vbg import VBGStore

COMMIT = "commit1"


def test_eager_cache_warms_top_n_nodes(sample_repo: Path, store: VBGStore) -> None:
    index = build_retrieval_index(store, COMMIT)
    cache = RetrievalCache()

    report = warm_eager_cache(store, index, COMMIT, cache, top_n=2)

    assert report.warmed_count == 2
    assert cache.eager_count(COMMIT) == 2


def test_eager_cache_prioritizes_higher_centrality(sample_repo: Path, store: VBGStore) -> None:
    index = build_retrieval_index(store, COMMIT)
    cache = RetrievalCache()

    # Degree centrality counts every relationship type, including CONTAINS
    # -- so the `orders` module (3 outgoing CONTAINS edges) ties with
    # `orders.process_order` (2 outgoing CALLS + 1 incoming CONTAINS) for
    # top centrality in this sample graph, a known, documented limitation
    # of plain degree centrality (see cache.py's own module docstring).
    # top_n=2 captures both without depending on the tie-break order.
    warm_eager_cache(store, index, COMMIT, cache, top_n=2)

    assert cache.get(COMMIT, "process_order") is not None


def test_lazy_retrieval_is_a_cache_miss_then_hit(sample_repo: Path, store: VBGStore) -> None:
    index = build_retrieval_index(store, COMMIT)
    cache = RetrievalCache()

    _, first_hit = retrieve_context_cached(store, index, COMMIT, "process_order", cache)
    _, second_hit = retrieve_context_cached(store, index, COMMIT, "process_order", cache)

    assert first_hit is False
    assert second_hit is True
    assert cache.hits == 1
    assert cache.misses == 1


def test_lazy_cache_counted_separately_from_eager(sample_repo: Path, store: VBGStore) -> None:
    index = build_retrieval_index(store, COMMIT)
    cache = RetrievalCache()
    warm_eager_cache(store, index, COMMIT, cache, top_n=1)

    retrieve_context_cached(store, index, COMMIT, "validate_order", cache)

    assert cache.eager_count(COMMIT) == 1
    assert cache.lazy_count(COMMIT) == 1


def test_cache_growth_report_reflects_real_counts(sample_repo: Path, store: VBGStore) -> None:
    index = build_retrieval_index(store, COMMIT)
    cache = RetrievalCache()
    warm_eager_cache(store, index, COMMIT, cache, top_n=1)
    retrieve_context_cached(store, index, COMMIT, "validate_order", cache)
    retrieve_context_cached(store, index, COMMIT, "validate_order", cache)  # second call: a hit

    report = audit_cache_growth(index, cache, COMMIT)

    assert report.index_size == len(index)
    assert report.eager_cached_count == 1
    assert report.lazy_cached_count == 1
    assert report.total_cached_count == 2
    assert report.hit_ratio == 0.5  # 1 hit, 1 miss


def test_hit_ratio_is_none_with_no_lookups(sample_repo: Path, store: VBGStore) -> None:
    cache = RetrievalCache()
    assert cache.hit_ratio is None


def test_different_commits_never_share_cache_entries(sample_repo: Path, store: VBGStore) -> None:
    index = build_retrieval_index(store, COMMIT)
    cache = RetrievalCache()
    retrieve_context_cached(store, index, COMMIT, "process_order", cache)

    assert cache.get("commit2", "process_order") is None
