"""
PLAN.md Milestone 5, Phase 5.4 -- Structural Accuracy Audit.

Node precision/recall, edge precision/recall, symbol/call/inheritance/
import accuracy.

**This is machinery, not a number, per D6's precedent**: computing real
precision/recall needs labeled ground truth -- a known-correct set of
nodes/edges for a real repository -- and PLAN.md's own text defers
*how* that ground truth gets produced ("Ground-truth labeling methodology:
deliberately deferred... resolve once actual Tier 1 candidate repos are
chosen"). `GroundTruthSet` is the shape that methodology will eventually
populate; nothing in this module invents or guesses at real labels.
`audit_structural_accuracy()` and `_precision_recall_f1()` are fully real
and tested against hand-constructed ground truth (proving the arithmetic
is correct), the same way `StaticAuditReport.static_precision` stayed
`None` while everything *around* it was already real code.
"""

from __future__ import annotations

from dataclasses import dataclass

from veyra.vbg import VBGStore


@dataclass(frozen=True)
class GroundTruthSet:
    repository_version: str
    expected_node_ids: frozenset[str]
    expected_edges: frozenset[tuple[str, str, str]]  # (source_id, target_id, relationship_type.value)


@dataclass(frozen=True)
class AccuracyMetrics:
    true_positive: int
    false_positive: int
    false_negative: int
    precision: float | None
    recall: float | None
    f1: float | None


def _precision_recall_f1(predicted: frozenset, expected: frozenset) -> AccuracyMetrics:
    true_positive = len(predicted & expected)
    false_positive = len(predicted - expected)
    false_negative = len(expected - predicted)
    precision = (true_positive / (true_positive + false_positive)) if (true_positive + false_positive) else None
    recall = (true_positive / (true_positive + false_negative)) if (true_positive + false_negative) else None
    f1 = (
        (2 * precision * recall / (precision + recall))
        if precision is not None and recall is not None and (precision + recall) > 0
        else None
    )
    return AccuracyMetrics(true_positive, false_positive, false_negative, precision, recall, f1)


@dataclass(frozen=True)
class StructuralAccuracyReport:
    repository_version: str
    node_accuracy: AccuracyMetrics
    edge_accuracy: AccuracyMetrics
    edge_accuracy_by_relationship_type: dict[str, AccuracyMetrics]


def audit_structural_accuracy(store: VBGStore, ground_truth: GroundTruthSet) -> StructuralAccuracyReport:
    predicted_nodes = frozenset(n.entity_id for n in store.get_all_nodes(ground_truth.repository_version))
    predicted_edges = frozenset(
        (e.source_id, e.target_id, e.relationship_type.value)
        for e in store.get_all_edges(ground_truth.repository_version)
    )

    edge_accuracy_by_relationship_type: dict[str, AccuracyMetrics] = {}
    all_relationship_types = {e[2] for e in predicted_edges} | {e[2] for e in ground_truth.expected_edges}
    for relationship_type in sorted(all_relationship_types):
        predicted_of_type = frozenset(e for e in predicted_edges if e[2] == relationship_type)
        expected_of_type = frozenset(e for e in ground_truth.expected_edges if e[2] == relationship_type)
        edge_accuracy_by_relationship_type[relationship_type] = _precision_recall_f1(predicted_of_type, expected_of_type)

    return StructuralAccuracyReport(
        repository_version=ground_truth.repository_version,
        node_accuracy=_precision_recall_f1(predicted_nodes, ground_truth.expected_node_ids),
        edge_accuracy=_precision_recall_f1(predicted_edges, ground_truth.expected_edges),
        edge_accuracy_by_relationship_type=edge_accuracy_by_relationship_type,
    )
