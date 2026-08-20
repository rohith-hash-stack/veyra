"""
PLAN.md Milestone 4, Phase 4.1 -- VBG Retrieval Index.

Index: symbols, classes, methods, lexical representations, docstrings,
relationships, graph paths, neighborhoods, evidence summaries, verified
questions, repository metadata.

**What "index" means in this slice**: a single coherent read API assembling
everything a retrieval consumer needs per entity, built directly from the
existing `VBGStore` tables (nodes, edges, evidence, questions/answers) plus
Phase 3.7/3.8's reconciliation/verification-state derivations -- not a new
physical structure (no FTS5, no embeddings, no separate persisted index
table). Nothing here duplicates canonical data; `IndexedEntity` is always
built by reading real, already-persisted rows. This matches the project's
own "don't build infra a measured problem hasn't demanded yet" discipline
(D3/D11's graph-DB deferral is the direct precedent) -- if Phase 5.7's
performance audit ever shows this facade is too slow to rebuild per query,
a materialized/persisted index is the natural next step, not attempted now.

"Docstrings" are computed on the fly by re-parsing `Node.lexical_representation`
via `ast.get_docstring()` -- the same re-parse-from-lexical-representation
technique `veyra.safety.capabilities`/`veyra.scenarios.introspection` already
use. Module nodes never carry a lexical_representation (Phase 2.1's own
documented scope decision), so module-level docstrings are not indexed in
this slice.

"Repository metadata" is intentionally scoped to just `repository_version`
itself (already present on every entity) -- none of the surrounding M3/M4
retrieval functions carry a repository `source` string, and inventing one
now to join against Phase 1.2's `RepositoryRecord` table would ripple
unnecessarily for what nothing yet consumes.

"Graph paths" beyond one hop are intentionally NOT duplicated here --
`veyra.vbg.neighborhood.get_descendants()` (Phase 2.4) already does bounded
multi-depth traversal; `RetrievalIndex.neighborhood()` just calls it rather
than re-implementing it.

Acceptance: relevant VBG regions retrievable (`get`/`all_entities`);
retrieval commit-aware (every function takes `repository_version`
explicitly, never mixes commits); evidence status accompanies retrieved
info (`verification_state`/`evidence_counts` on every `IndexedEntity`);
retrieval returns graph references, not invented entities (every
`IndexedEntity` is built from a real, persisted `Node`); raw repo scanning
not required per query (everything comes from `VBGStore`).
"""

from __future__ import annotations

import ast
from dataclasses import dataclass

from veyra.vbg import (
    Edge,
    EvidenceType,
    Node,
    VBGStore,
    VerificationState,
    get_children,
    get_descendants,
    get_parents,
    get_siblings,
)
from veyra.verification import derive_verification_states


def _extract_docstring(lexical_representation: str | None) -> str | None:
    if not lexical_representation:
        return None
    try:
        tree = ast.parse(lexical_representation)
    except SyntaxError:
        return None
    body = tree.body
    if not body:
        return None
    return ast.get_docstring(body[0])


@dataclass(frozen=True)
class IndexedEntity:
    entity_id: str
    node_type: str
    name: str
    repository_version: str
    lexical_representation: str | None
    docstring: str | None
    source_location: str | None
    parents: tuple[str, ...]
    children: tuple[str, ...]
    siblings: tuple[str, ...]
    outgoing_relationships: tuple[tuple[str, str], ...]  # (relationship_type_value, target_id)
    incoming_relationships: tuple[tuple[str, str], ...]  # (relationship_type_value, source_id)
    verification_state: VerificationState
    evidence_counts: dict[str, int]  # EvidenceType.value -> count


class RetrievalIndex:
    """Commit-scoped, in-memory. Built once via `build_retrieval_index()`
    and queried repeatedly -- rebuilding for a different `repository_version`
    means calling `build_retrieval_index()` again; an index is never
    silently reused across commits."""

    def __init__(self, repository_version: str, entities: dict[str, IndexedEntity]) -> None:
        self.repository_version = repository_version
        self._entities = entities

    def get(self, entity_id: str) -> IndexedEntity | None:
        return self._entities.get(entity_id)

    def all_entities(self) -> list[IndexedEntity]:
        return list(self._entities.values())

    def __len__(self) -> int:
        return len(self._entities)

    def find_by_name(self, name: str, exact: bool = True) -> list[IndexedEntity]:
        """The "exact symbol queries retrieve exact nodes" case (Phase 4.2).
        `exact=False` does a case-insensitive substring match instead."""
        if exact:
            return sorted((e for e in self._entities.values() if e.name == name), key=lambda e: e.entity_id)
        needle = name.lower()
        return sorted(
            (e for e in self._entities.values() if needle in e.name.lower()),
            key=lambda e: e.entity_id,
        )

    def neighborhood(self, entity_id: str, max_depth: int, store: VBGStore) -> dict[int, list[str]]:
        """Bounded multi-depth structural (CONTAINS) traversal -- delegates
        to Phase 2.4's own `get_descendants()` rather than re-implementing
        it (PLAN's "graph paths")."""
        return get_descendants(store, entity_id, self.repository_version, max_depth)


def build_retrieval_index(store: VBGStore, repository_version: str) -> RetrievalIndex:
    nodes = store.get_all_nodes(repository_version)
    edges = store.get_all_edges(repository_version)
    states = derive_verification_states(store, repository_version)

    outgoing: dict[str, list[Edge]] = {}
    incoming: dict[str, list[Edge]] = {}
    for edge in edges:
        outgoing.setdefault(edge.source_id, []).append(edge)
        incoming.setdefault(edge.target_id, []).append(edge)

    entities: dict[str, IndexedEntity] = {}
    for node in nodes:
        entities[node.entity_id] = _build_entity(store, node, repository_version, states, outgoing, incoming)

    return RetrievalIndex(repository_version, entities)


def _build_entity(
    store: VBGStore,
    node: Node,
    repository_version: str,
    states: dict[str, VerificationState],
    outgoing: dict[str, list[Edge]],
    incoming: dict[str, list[Edge]],
) -> IndexedEntity:
    evidence = store.get_evidence_for_subject(node.entity_id, repository_version)
    evidence_counts: dict[str, int] = {}
    for ev in evidence:
        evidence_counts[ev.evidence_type.value] = evidence_counts.get(ev.evidence_type.value, 0) + 1

    return IndexedEntity(
        entity_id=node.entity_id,
        node_type=node.type,
        name=node.name,
        repository_version=repository_version,
        lexical_representation=node.lexical_representation,
        docstring=_extract_docstring(node.lexical_representation),
        source_location=node.source_location,
        parents=tuple(get_parents(store, node.entity_id, repository_version)),
        children=tuple(get_children(store, node.entity_id, repository_version)),
        siblings=tuple(get_siblings(store, node.entity_id, repository_version)),
        outgoing_relationships=tuple(
            (e.relationship_type.value, e.target_id) for e in outgoing.get(node.entity_id, [])
        ),
        incoming_relationships=tuple(
            (e.relationship_type.value, e.source_id) for e in incoming.get(node.entity_id, [])
        ),
        verification_state=states.get(node.entity_id, VerificationState.STRUCTURALLY_IDENTIFIED),
        evidence_counts=evidence_counts,
    )
