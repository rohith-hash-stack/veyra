"""
PLAN.md Milestone 4, Phase 4.3 -- Query-Time Evidence Retrieval.

"Query -> relevant nodes -> relevant relationships -> relevant evidence ->
verification states -> context. The LLM explains that evidence; it does
not discover it." This module is that pipeline, built directly on Phase
4.1's index, Phase 4.2's search, and Phase 3.7's reconciliation --
primarily *retrieving* existing verified knowledge, not generating new
Q&A datasets (see PLAN.md's own three-milestone "questions" distinction:
M2 structural, M3 behavioral, M4 evidence retrieval).
"""

from __future__ import annotations

from dataclasses import dataclass

from veyra.reconciliation import EdgeReconciliation, reconcile_calls
from veyra.vbg import Edge, Evidence, VBGStore

from .index import IndexedEntity, RetrievalIndex
from .search import search


@dataclass(frozen=True)
class RetrievedContext:
    query: str
    repository_version: str
    entities: tuple[IndexedEntity, ...]
    evidence_by_entity: dict[str, tuple[Evidence, ...]]
    relationships: tuple[Edge, ...]
    conflicts: tuple[EdgeReconciliation, ...]


def retrieve_context(
    store: VBGStore, index: RetrievalIndex, repository_version: str, query: str, top_k: int = 10
) -> RetrievedContext:
    """Retrieves relevant nodes (via Phase 4.2's `search()`), the
    relationships among them, every evidence record attached to each, and
    any Phase 3.7 conflicts touching them -- one coherent, evidence-backed
    context for a single query, computed fresh against `index` (which the
    caller builds once via `build_retrieval_index()` and can reuse across
    many queries against the same commit)."""
    scored = search(index, query, top_k=top_k)
    entities = tuple(s.entity for s in scored)
    entity_ids = {e.entity_id for e in entities}

    evidence_by_entity = {
        entity.entity_id: tuple(store.get_evidence_for_subject(entity.entity_id, repository_version))
        for entity in entities
    }

    # Every outgoing relationship from a retrieved entity, including ones
    # pointing at an entity that wasn't itself independently retrieved --
    # Phase 4.7's grounding contract needs those to name real "unknowns"
    # (referenced but not verified in this context) rather than silently
    # dropping them.
    relationships: list[Edge] = []
    for entity in entities:
        relationships.extend(store.get_outgoing_edges(entity.entity_id, repository_version))

    all_reconciliations = reconcile_calls(store, repository_version)
    conflicts = tuple(
        r for r in all_reconciliations
        if r.is_conflict and (r.source_id in entity_ids or r.target_id in entity_ids)
    )

    return RetrievedContext(
        query=query,
        repository_version=repository_version,
        entities=entities,
        evidence_by_entity=evidence_by_entity,
        relationships=tuple(relationships),
        conflicts=conflicts,
    )
