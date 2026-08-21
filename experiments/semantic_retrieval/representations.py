"""
Phase E, Section 6 -- repository representation comparison.

Two representations of an `IndexedEntity`, compared with real data (not
assumed) before picking one for the full experiment. Both are pure
functions of an `IndexedEntity` plus its already-computed neighbors (no
extra storage queries, mirroring the deterministic side's own discipline
of reusing already-persisted structure rather than deriving new relationships).
"""
from __future__ import annotations

from veyra.retrieval.index import IndexedEntity, RetrievalIndex

_SOURCE_CAP_CHARS = 500  # representation C's deliberate cap -- see module docstring in build_index.py


def representation_a(entity: IndexedEntity, index: RetrievalIndex, repo_name: str) -> str:
    """name + docstring + full source -- the same shape as production's
    `_entity_text()` (search.py), included here as the baseline every
    deterministic-retrieval decision this whole project made was measured
    against. Uncapped, exactly like production. `index`/`repo_name` unused
    -- kept for a uniform call signature across representations."""
    parts = [entity.name]
    if entity.docstring:
        parts.append(entity.docstring)
    if entity.lexical_representation:
        parts.append(entity.lexical_representation)
    return " ".join(parts)


def representation_c(entity: IndexedEntity, index: RetrievalIndex, repo_name: str) -> str:
    """Structured, repository-aware text: module path (derived from
    `source_location`, the real extracted file path -- not guessed),
    parent name (the real first CONTAINS parent, looked up via the index,
    not fabricated), entity name, kind (`node_type`), docstring, and a
    *capped* source excerpt -- deliberately capped (`_SOURCE_CAP_CHARS`)
    to test the directive's own stated concern that blindly including huge
    source bodies could dilute the embedding, not to assume the cap helps."""
    module_path = "?"
    if entity.source_location:
        module_path = entity.source_location.split(":", 1)[0]

    parent_name = ""
    if entity.parents:
        parent = index.get(entity.parents[0])
        if parent is not None:
            parent_name = parent.name

    source_excerpt = (entity.lexical_representation or "")[:_SOURCE_CAP_CHARS]

    return (
        f"Repository: {repo_name}\n"
        f"Module: {module_path}\n"
        f"Parent: {parent_name}\n"
        f"Entity: {entity.name}\n"
        f"Kind: {entity.node_type}\n"
        f"Purpose: {entity.docstring or ''}\n"
        f"Relevant source: {source_excerpt}"
    )


REPRESENTATIONS = {"A": representation_a, "C": representation_c}
