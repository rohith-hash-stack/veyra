"""
PLAN.md Milestone 3, Phase 3.1 -- the only function in veyra.safety that
touches VBGStore. classify() itself stays pure and storage-free (easy to
unit test, and keeps "detection/policy have zero execution or I/O
capability" a simple, checkable fact); this is the explicit persistence step
that makes every classification decision auditable in practice.
"""

from __future__ import annotations

from veyra.vbg import ClassificationResult, Node, VBGStore

from .classification import classify
from .policy import PolicyConfig


def classify_and_audit(
    store: VBGStore,
    node: Node,
    repository_commit: str,
    policy: PolicyConfig | None = None,
) -> ClassificationResult:
    result = classify(node, repository_commit, policy)
    store.insert_classification(result)
    return result
