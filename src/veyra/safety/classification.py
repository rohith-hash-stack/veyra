"""
PLAN.md Milestone 3, Phase 3.1 -- ties capability detection (capabilities.py)
and policy evaluation (policy.py) together into one auditable
ClassificationResult. Still pure -- no VBGStore access here; persistence is
audit.py's job, matching the extraction/persist_extraction and
generate_questions/persist_questions separation used throughout M2.
"""

from __future__ import annotations

from veyra.vbg import ClassificationResult, Node

from .capabilities import detect_capabilities
from .policy import PolicyConfig, resolve_safety_class


def classify(node: Node, repository_commit: str, policy: PolicyConfig | None = None) -> ClassificationResult:
    policy = policy or PolicyConfig.default()

    signals = detect_capabilities(node)
    # Order is deterministic (sorted by enum value) regardless of AST walk
    # order, which can vary run to run only in theory (ast.walk is actually
    # stable, but sorting removes any doubt and is what "same input + same
    # policy = deterministic result" is tested against).
    capabilities = tuple(sorted({s.capability for s in signals}, key=lambda c: c.value))
    matched_rules = tuple(sorted({s.matched_pattern for s in signals}))
    evidence = tuple(sorted({s.evidence for s in signals}))

    safety_class, risk_level, reason = resolve_safety_class(node.entity_id, capabilities, policy)

    return ClassificationResult(
        target=node.entity_id,
        classification=safety_class,
        risk_level=risk_level,
        capabilities_detected=capabilities,
        matched_rules=matched_rules,
        reason=reason,
        evidence=evidence,
        repository_commit=repository_commit,
        policy_version=policy.version,
    )
