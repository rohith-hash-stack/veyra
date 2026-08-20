"""
PLAN.md Milestone 4, Phases 4.4-4.6 -- Eager Q&A Cache, Lazy Q&A, Q&A
Explosion Control.

**A real terminology note, resolved deliberately**: PLAN.md's own "three
distinct purposes for questions across milestones" already separates these
clearly -- "M4: Evidence Retrieval: 'Which already-established facts are
relevant to this query?'" -- so Milestone 4's "Q&A" is NOT the Question/
Answer entity M2 (Phase 2.5/2.6) already built and solved; it is about
caching *retrieval results* (Phase 4.3's `RetrievedContext`) for real
end-user queries. Reusing the M2 Question/Answer machinery here would
conflate two genuinely different concepts this project has already been
careful to keep separate.

`RetrievalCache` is in-memory and commit-scoped, never persisted to
`VBGStore` -- unlike Evidence, a cached `RetrievedContext` is not canonical
data; it is always cheaply reconstructable from the VBG, so there is
nothing here that needs the append-only durability guarantee everything
else in this project has. A cache for one commit is never reused for
another (every key is scoped by `repository_version`).

**Phase 4.4 (Eager)**: `warm_eager_cache()` precomputes and caches context
for the top-N centrality-ranked nodes (`veyra.vbg.neighborhood.centrality_score()`,
the same ranking Phase 3.6 already uses) -- PLAN's own "public APIs,
high-centrality nodes, core services, subsystem boundaries" proxy.
"Frequently queried nodes" is NOT implementable in this slice (it needs
real usage data this project has never collected) -- a stated, honest gap,
not a silent omission.

**Phase 4.5 (Lazy)**: `retrieve_context_cached()` is the on-demand path --
checks the cache first; on a miss, computes fresh via Phase 4.3's
`retrieve_context()` and stores the result. "Duplicates avoided" is the
cache key itself (deterministic per query string + commit); "query latency
measurable" is `RetrievalCache.hits`/`misses`, directly.

**Phase 4.6 (Explosion control)**: `audit_cache_growth()` reports index
size, eager vs. lazily-cached counts, and the hit ratio -- "eager strategy
has configurable limits" is `warm_eager_cache()`'s own `top_n` parameter.
"""

from __future__ import annotations

from dataclasses import dataclass

from veyra.vbg import VBGStore, centrality_score

from .context import RetrievedContext, retrieve_context
from .index import RetrievalIndex

_DEFAULT_EAGER_TOP_N = 50


class RetrievalCache:
    def __init__(self) -> None:
        self._store: dict[tuple[str, str], RetrievedContext] = {}
        self._eager_keys: set[tuple[str, str]] = set()
        self.hits = 0
        self.misses = 0

    def get(self, repository_version: str, key: str) -> RetrievedContext | None:
        result = self._store.get((repository_version, key))
        if result is None:
            self.misses += 1
        else:
            self.hits += 1
        return result

    def put(self, repository_version: str, key: str, context: RetrievedContext, eager: bool = False) -> None:
        cache_key = (repository_version, key)
        self._store[cache_key] = context
        if eager:
            self._eager_keys.add(cache_key)

    def __len__(self) -> int:
        return len(self._store)

    def eager_count(self, repository_version: str | None = None) -> int:
        if repository_version is None:
            return len(self._eager_keys)
        return sum(1 for v, _ in self._eager_keys if v == repository_version)

    def lazy_count(self, repository_version: str | None = None) -> int:
        keys = set(self._store) - self._eager_keys
        if repository_version is None:
            return len(keys)
        return sum(1 for v, _ in keys if v == repository_version)

    @property
    def hit_ratio(self) -> float | None:
        total = self.hits + self.misses
        return (self.hits / total) if total else None


@dataclass(frozen=True)
class EagerCacheReport:
    repository_version: str
    eligible_node_count: int
    warmed_count: int


def warm_eager_cache(
    store: VBGStore,
    index: RetrievalIndex,
    repository_version: str,
    cache: RetrievalCache,
    top_n: int = _DEFAULT_EAGER_TOP_N,
) -> EagerCacheReport:
    """Precomputes RetrievedContext for the top-N centrality-ranked nodes,
    keyed by their own entity_id/name (a direct symbol lookup, not a free-
    text query) -- these are exactly the entities `search()`'s exact-name
    matching will return instantly for that name anyway."""
    all_entities = index.all_entities()
    ranked = sorted(
        all_entities,
        key=lambda e: (-centrality_score(store, e.entity_id, repository_version), e.entity_id),
    )[:top_n]

    for entity in ranked:
        context = retrieve_context(store, index, repository_version, entity.name)
        cache.put(repository_version, entity.name, context, eager=True)

    return EagerCacheReport(
        repository_version=repository_version,
        eligible_node_count=len(all_entities),
        warmed_count=len(ranked),
    )


def retrieve_context_cached(
    store: VBGStore,
    index: RetrievalIndex,
    repository_version: str,
    query: str,
    cache: RetrievalCache,
    top_k: int = 10,
) -> tuple[RetrievedContext, bool]:
    """Returns (context, was_cache_hit). The lazy path: nothing is computed
    until actually asked for; a repeat query for the same string becomes a
    cache hit."""
    cached = cache.get(repository_version, query)
    if cached is not None:
        return cached, True
    context = retrieve_context(store, index, repository_version, query, top_k=top_k)
    cache.put(repository_version, query, context, eager=False)
    return context, False


@dataclass(frozen=True)
class CacheGrowthReport:
    repository_version: str
    index_size: int
    eager_cached_count: int
    lazy_cached_count: int
    total_cached_count: int
    hit_ratio: float | None


def audit_cache_growth(index: RetrievalIndex, cache: RetrievalCache, repository_version: str) -> CacheGrowthReport:
    eager = cache.eager_count(repository_version)
    lazy = cache.lazy_count(repository_version)
    return CacheGrowthReport(
        repository_version=repository_version,
        index_size=len(index),
        eager_cached_count=eager,
        lazy_cached_count=lazy,
        total_cached_count=eager + lazy,
        hit_ratio=cache.hit_ratio,
    )
