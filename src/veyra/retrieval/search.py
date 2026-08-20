"""
PLAN.md Milestone 4, Phase 4.2 -- Semantic Repository Retrieval.

**A real, stated scope decision**: "semantic" here means lightweight
lexical/TF-IDF-style token-overlap scoring, computed in pure Python over
each `IndexedEntity`'s name/docstring/lexical text -- NOT embedding-based
semantic search. A true embedding model is a materially heavier dependency
(a real ML library, likely GPU-friendly infra, a much bigger footprint than
anything else this project has added) that nothing has reviewed or
approved; TF-IDF is a well-understood, zero-new-dependency technique that
gives real, useful conceptual-query relevance ranking without that cost --
the same "start with the minimum real thing, not the maximum possible
thing" discipline as Hypothesis's use in Phase 3.3b (there: a genuine new
dependency was justified and added; here: a stdlib-only technique is
judged sufficient for this slice). This is a real, honest limitation, not
hidden: token-overlap scoring will miss true paraphrases with no shared
vocabulary (e.g. "how does auth work" won't score `check_credentials`
without a shared token). Revisit if this proves insufficient once run
against real repositories and an embedding dependency is explicitly
approved.

"exact symbol queries retrieve exact nodes" is `RetrievalIndex.find_by_name()`
(Phase 4.1) directly -- not re-implemented here. "lexical + semantic
retrieval combinable" is `search()`: exact/substring name matches (always
ranked first, since a query that literally names a symbol should always
surface it) unioned with TF-IDF-scored matches, deduplicated by entity_id.
"retrieval never invents graph entities" holds structurally -- every
`ScoredEntity` wraps a real `IndexedEntity`, itself always built from a
real Node (Phase 4.1). "evidence accompanies retrieved entities" is
already true since `IndexedEntity` carries `verification_state`/
`evidence_counts` on every result.
"""

from __future__ import annotations

import math
import re
from collections import Counter
from dataclasses import dataclass

from .index import IndexedEntity, RetrievalIndex

_TOKEN_RE = re.compile(r"[A-Za-z0-9]+")


def _tokenize(text: str) -> list[str]:
    """Splits on non-alphanumeric boundaries AND camelCase/snake_case word
    boundaries (lowercased), so `processOrder`/`process_order`/"process
    order" all tokenize to the same {"process", "order"} -- a small,
    deliberate concession that materially improves symbol-name matching
    without needing any real NLP dependency."""
    tokens: list[str] = []
    for raw in _TOKEN_RE.findall(text):
        # split camelCase: "processOrder" -> "process", "Order"
        parts = re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", raw).split()
        tokens.extend(p.lower() for p in parts)
    return tokens


def _entity_text(entity: IndexedEntity) -> str:
    parts = [entity.name]
    if entity.docstring:
        parts.append(entity.docstring)
    if entity.lexical_representation:
        parts.append(entity.lexical_representation)
    return " ".join(parts)


@dataclass(frozen=True)
class ScoredEntity:
    entity: IndexedEntity
    score: float
    matched_by: str  # "exact_name" | "substring_name" | "tfidf"


def _build_tfidf_vectors(index: RetrievalIndex) -> tuple[dict[str, dict[str, float]], dict[str, float]]:
    entities = index.all_entities()
    doc_tokens: dict[str, Counter] = {e.entity_id: Counter(_tokenize(_entity_text(e))) for e in entities}

    document_frequency: Counter = Counter()
    for tokens in doc_tokens.values():
        document_frequency.update(tokens.keys())

    total_docs = max(len(entities), 1)
    idf = {term: math.log((total_docs + 1) / (df + 1)) + 1.0 for term, df in document_frequency.items()}

    vectors: dict[str, dict[str, float]] = {}
    for entity_id, tokens in doc_tokens.items():
        total = sum(tokens.values()) or 1
        vectors[entity_id] = {term: (count / total) * idf.get(term, 0.0) for term, count in tokens.items()}
    return vectors, idf


def _cosine_similarity(a: dict[str, float], b: dict[str, float]) -> float:
    shared = set(a) & set(b)
    if not shared:
        return 0.0
    dot = sum(a[t] * b[t] for t in shared)
    norm_a = math.sqrt(sum(v * v for v in a.values())) or 1.0
    norm_b = math.sqrt(sum(v * v for v in b.values())) or 1.0
    return dot / (norm_a * norm_b)


def search_semantic(index: RetrievalIndex, query: str, top_k: int = 10) -> list[ScoredEntity]:
    """TF-IDF cosine-similarity ranking -- see module docstring for exactly
    what "semantic" does and doesn't mean here."""
    vectors, idf = _build_tfidf_vectors(index)
    query_tokens = Counter(_tokenize(query))
    if not query_tokens:
        return []
    total = sum(query_tokens.values())
    query_vector = {term: (count / total) * idf.get(term, 0.0) for term, count in query_tokens.items()}

    scored = [
        ScoredEntity(entity=entity, score=_cosine_similarity(query_vector, vectors[entity.entity_id]), matched_by="tfidf")
        for entity in index.all_entities()
    ]
    scored = [s for s in scored if s.score > 0.0]
    scored.sort(key=lambda s: (-s.score, s.entity.entity_id))
    return scored[:top_k]


def search(index: RetrievalIndex, query: str, top_k: int = 10) -> list[ScoredEntity]:
    """Combines exact-name, substring-name, and TF-IDF results, deduplicated
    by entity_id -- exact matches always rank first (score 2.0), substring
    matches next (score 1.0), TF-IDF results fill the rest, all within
    top_k. A query that is itself a real symbol name always surfaces that
    symbol, regardless of what TF-IDF alone would have ranked it."""
    seen: set[str] = set()
    results: list[ScoredEntity] = []

    for entity in index.find_by_name(query, exact=True):
        if entity.entity_id not in seen:
            seen.add(entity.entity_id)
            results.append(ScoredEntity(entity=entity, score=2.0, matched_by="exact_name"))

    for entity in index.find_by_name(query, exact=False):
        if entity.entity_id not in seen:
            seen.add(entity.entity_id)
            results.append(ScoredEntity(entity=entity, score=1.0, matched_by="substring_name"))

    for scored in search_semantic(index, query, top_k=top_k):
        if scored.entity.entity_id not in seen:
            seen.add(scored.entity.entity_id)
            results.append(scored)

    results.sort(key=lambda s: (-s.score, s.entity.entity_id))
    return results[:top_k]
