"""
PLAN.md Phase 1.4 -- D4 extension: symbol-level diff.

D4 (PLAN.md Design Decisions Log): "add a lightweight symbol-level diff pass
here, run right after M2's structural graph exists for two commits. Match
nodes across commits by stable qualified ID; classify each as ADDED /
REMOVED / MODIFIED_SIGNATURE / MODIFIED_BODY / UNCHANGED via a hash of
normalized source text per node."

Scope of this slice: `diff_symbols()` is the comparison algorithm itself,
operating on two already-extracted Node lists (e.g. two
static_analysis.extract_repository() results at different commits). Wiring
this to actually check out two arbitrary commits' file content and run
extraction at each is deliberately NOT built here -- that orchestration
belongs to Phase 4.8 (Git Impact Analysis & Invalidation), which is the
actual, concrete consumer named in PLAN.md ("Phase 4.8 ... consumes this
diff for impact propagation rather than inventing diffing from scratch").
Building that plumbing now, before anything calls it, would be exactly the
kind of speculative scaffolding this project has been avoiding elsewhere.

Signature vs. body: a node's "signature" is approximated as the first line
of its lexical_representation (e.g. `def foo(x: int) -> str:` or
`class Foo(Base):`) -- this is a simple, documented heuristic, not full
semantic signature parsing (it will not catch e.g. a signature that wraps
across multiple lines and only changes on line 2). Variable nodes have no
signature/body distinction; any change to a Variable is classified as
MODIFIED_BODY.
"""

from __future__ import annotations

import enum
import hashlib
from dataclasses import dataclass

from veyra.vbg import Node


class SymbolChangeType(enum.Enum):
    ADDED = "ADDED"
    REMOVED = "REMOVED"
    MODIFIED_SIGNATURE = "MODIFIED_SIGNATURE"
    MODIFIED_BODY = "MODIFIED_BODY"
    UNCHANGED = "UNCHANGED"


@dataclass(frozen=True)
class SymbolChange:
    entity_id: str
    change_type: SymbolChangeType


def _hash(text: str | None) -> str:
    return hashlib.sha256((text or "").encode("utf-8")).hexdigest()


def _signature_text(lexical_representation: str | None) -> str:
    if not lexical_representation:
        return ""
    return lexical_representation.splitlines()[0].strip()


def _latest_by_entity_id(nodes: list[Node]) -> dict[str, Node]:
    """When a name is redefined within the same file/commit (Phase 2.1's
    documented duplicate-symbol behavior), the last-encountered definition
    wins for diffing purposes -- consistent with the extractor's own
    last-write-wins symbol table."""
    result: dict[str, Node] = {}
    for node in nodes:
        result[node.entity_id] = node
    return result


def diff_symbols(old_nodes: list[Node], new_nodes: list[Node]) -> list[SymbolChange]:
    old_by_id = _latest_by_entity_id(old_nodes)
    new_by_id = _latest_by_entity_id(new_nodes)

    changes: list[SymbolChange] = []

    for entity_id, new_node in new_by_id.items():
        old_node = old_by_id.get(entity_id)
        if old_node is None:
            changes.append(SymbolChange(entity_id, SymbolChangeType.ADDED))
            continue

        if _hash(old_node.lexical_representation) == _hash(new_node.lexical_representation):
            changes.append(SymbolChange(entity_id, SymbolChangeType.UNCHANGED))
            continue

        if new_node.type == "Variable":
            changes.append(SymbolChange(entity_id, SymbolChangeType.MODIFIED_BODY))
            continue

        old_signature = _hash(_signature_text(old_node.lexical_representation))
        new_signature = _hash(_signature_text(new_node.lexical_representation))
        if old_signature != new_signature:
            changes.append(SymbolChange(entity_id, SymbolChangeType.MODIFIED_SIGNATURE))
        else:
            changes.append(SymbolChange(entity_id, SymbolChangeType.MODIFIED_BODY))

    for entity_id in old_by_id:
        if entity_id not in new_by_id:
            changes.append(SymbolChange(entity_id, SymbolChangeType.REMOVED))

    return changes
