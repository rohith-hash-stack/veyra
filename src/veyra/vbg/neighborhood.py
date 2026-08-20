"""
PLAN.md Milestone 2, Phase 2.4 -- Neighborhood Model.

For every node, derive: parent, children, siblings, grandchildren, incoming
neighbors, outgoing neighbors. "Parent"/"children"/"siblings"/"grandchildren"
are defined via CONTAINS edges specifically (the structural containment tree
built by static_analysis) -- "incoming"/"outgoing" cover every relationship
type, not just CONTAINS, matching the plan's own distinction between
structural nesting and general graph neighbors.

"Unobserved relationships remain identifiable as unobserved" (acceptance
criterion): this module never fabricates a relationship that isn't backed by
a real Edge in VBGStore. A node with no CONTAINS parent (e.g. a top-level
Module) legitimately gets an empty `parents` list, not a placeholder -- the
distinction between "queried and found nothing" and "not queried" is exactly
what the empty list vs. simply never calling this function means.
"""

from __future__ import annotations

from dataclasses import dataclass

from .models import Edge, RelationshipType
from .storage import VBGStore


@dataclass(frozen=True)
class Neighborhood:
    entity_id: str
    repository_version: str
    parents: list[str]
    children: list[str]
    siblings: list[str]
    grandchildren: list[str]
    incoming: list[Edge]
    outgoing: list[Edge]


def get_parents(store: VBGStore, entity_id: str, repository_version: str) -> list[str]:
    incoming = store.get_incoming_edges(entity_id, repository_version)
    return sorted(e.source_id for e in incoming if e.relationship_type is RelationshipType.CONTAINS)


def get_children(store: VBGStore, entity_id: str, repository_version: str) -> list[str]:
    outgoing = store.get_outgoing_edges(entity_id, repository_version)
    return sorted(e.target_id for e in outgoing if e.relationship_type is RelationshipType.CONTAINS)


def get_siblings(store: VBGStore, entity_id: str, repository_version: str) -> list[str]:
    siblings: set[str] = set()
    for parent_id in get_parents(store, entity_id, repository_version):
        for child_id in get_children(store, parent_id, repository_version):
            if child_id != entity_id:
                siblings.add(child_id)
    return sorted(siblings)


def get_grandchildren(store: VBGStore, entity_id: str, repository_version: str) -> list[str]:
    grandchildren: set[str] = set()
    for child_id in get_children(store, entity_id, repository_version):
        grandchildren.update(get_children(store, child_id, repository_version))
    return sorted(grandchildren)


def get_descendants(
    store: VBGStore, entity_id: str, repository_version: str, max_depth: int
) -> dict[int, list[str]]:
    """Configurable-depth CONTAINS traversal: {1: children, 2: grandchildren,
    3: great-grandchildren, ...} up to max_depth, stopping early if a level
    is empty. This is the acceptance criterion "configurable depth is
    supported" made concrete -- get_children/get_grandchildren above are
    just the depth=1/depth=2 special cases of this, kept as their own named
    functions because the plan names them individually."""
    if max_depth < 1:
        raise ValueError("max_depth must be >= 1")

    result: dict[int, list[str]] = {}
    frontier = [entity_id]
    for depth in range(1, max_depth + 1):
        next_frontier: set[str] = set()
        for node_id in frontier:
            next_frontier.update(get_children(store, node_id, repository_version))
        level = sorted(next_frontier)
        result[depth] = level
        if not level:
            break
        frontier = level
    return result


def centrality_score(store: VBGStore, entity_id: str, repository_version: str) -> int:
    """Plain degree centrality (incoming + outgoing edge count, every
    relationship type) -- a deliberately simple, stated proxy for
    "high-value/public-API," not betweenness or eigenvector centrality.
    First introduced for Phase 3.6's exploration ranking; shared here since
    Phase 4.4's eager retrieval cache needs the exact same ranking concept
    for a different purpose. Revisit if Phase 5.7 performance-audit data
    ever shows this is a poor ranking in practice."""
    return len(store.get_incoming_edges(entity_id, repository_version)) + len(
        store.get_outgoing_edges(entity_id, repository_version)
    )


def get_neighborhood(store: VBGStore, entity_id: str, repository_version: str) -> Neighborhood:
    incoming = store.get_incoming_edges(entity_id, repository_version)
    outgoing = store.get_outgoing_edges(entity_id, repository_version)

    parents = sorted(e.source_id for e in incoming if e.relationship_type is RelationshipType.CONTAINS)
    children = sorted(e.target_id for e in outgoing if e.relationship_type is RelationshipType.CONTAINS)

    siblings: set[str] = set()
    for parent_id in parents:
        for child_id in get_children(store, parent_id, repository_version):
            if child_id != entity_id:
                siblings.add(child_id)

    grandchildren: set[str] = set()
    for child_id in children:
        grandchildren.update(get_children(store, child_id, repository_version))

    return Neighborhood(
        entity_id=entity_id,
        repository_version=repository_version,
        parents=parents,
        children=children,
        siblings=sorted(siblings),
        grandchildren=sorted(grandchildren),
        incoming=incoming,
        outgoing=outgoing,
    )
