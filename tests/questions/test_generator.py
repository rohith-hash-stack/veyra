"""
Tests for PLAN.md Phase 2.5 (Deterministic Question Generator). Builds a
realistic graph via the real Phase 2.1/2.3 extractor (not hand-crafted
Node/Edge objects), then generates questions over it -- this also serves as
an end-to-end extractor -> storage -> question-generator integration check.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from veyra.questions import QuestionCategory, generate_questions
from veyra.static_analysis import extract_repository, persist_extraction
from veyra.vbg import VBGStore

COMMIT = "commit1"


@pytest.fixture
def populated_store(tmp_path: Path, store: VBGStore) -> VBGStore:
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    (repo_root / "base.py").write_text("class BaseService:\n    pass\n")
    (repo_root / "orders.py").write_text(
        "from base import BaseService\n"
        "\n"
        "DEFAULT_TIMEOUT = 30\n"
        "\n"
        "class OrderService(BaseService):\n"
        "    def process_order(self):\n"
        "        self.validate_order()\n"
        "\n"
        "    def validate_order(self):\n"
        "        pass\n"
        "\n"
        "def handle(order: OrderService) -> None:\n"
        "    pass\n",
    )

    result = extract_repository(repo_root, COMMIT)
    persist_extraction(store, result)
    return store


def _by_category(questions, category):
    return [q for q in questions if q.category is category]


def test_symbol_question_generated_for_every_node(populated_store: VBGStore) -> None:
    questions = generate_questions(populated_store, COMMIT)
    all_nodes = populated_store.get_all_nodes(COMMIT)

    symbol_questions = _by_category(questions, QuestionCategory.SYMBOL)
    assert len(symbol_questions) == len(all_nodes)


def test_structural_question_for_class_with_methods(populated_store: VBGStore) -> None:
    questions = generate_questions(populated_store, COMMIT)

    structural = _by_category(questions, QuestionCategory.STRUCTURAL)
    match = next(q for q in structural if q.entity_ids[0] == "orders.OrderService")
    assert "orders.OrderService.process_order" in match.entity_ids
    assert "orders.OrderService.validate_order" in match.entity_ids


def test_no_structural_question_for_variable(populated_store: VBGStore) -> None:
    questions = generate_questions(populated_store, COMMIT)

    structural_ids = {q.entity_ids[0] for q in _by_category(questions, QuestionCategory.STRUCTURAL)}
    assert "orders.DEFAULT_TIMEOUT" not in structural_ids


def test_call_flow_questions_both_directions(populated_store: VBGStore) -> None:
    questions = generate_questions(populated_store, COMMIT)

    call_flow = _by_category(questions, QuestionCategory.CALL_FLOW)
    forward = next(q for q in call_flow if q.text.startswith("What does"))
    reverse = next(q for q in call_flow if q.text.startswith("Who calls"))

    assert forward.entity_ids[0] == "orders.OrderService.process_order"
    assert "orders.OrderService.validate_order" in forward.entity_ids
    assert reverse.entity_ids[0] == "orders.OrderService.validate_order"
    assert "orders.OrderService.process_order" in reverse.entity_ids


def test_no_call_flow_question_for_node_with_no_calls(populated_store: VBGStore) -> None:
    questions = generate_questions(populated_store, COMMIT)

    call_flow_forward_ids = {
        q.entity_ids[0] for q in _by_category(questions, QuestionCategory.CALL_FLOW)
        if q.text.startswith("What does")
    }
    # validate_order() makes no calls itself -- no fabricated "what does X call?" for it.
    assert "orders.OrderService.validate_order" not in call_flow_forward_ids


def test_inheritance_questions_both_directions(populated_store: VBGStore) -> None:
    questions = generate_questions(populated_store, COMMIT)

    inheritance = _by_category(questions, QuestionCategory.INHERITANCE)
    forward = next(q for q in inheritance if q.entity_ids[0] == "orders.OrderService")
    reverse = next(q for q in inheritance if q.entity_ids[0] == "base.BaseService")

    assert "base.BaseService" in forward.entity_ids
    assert "orders.OrderService" in reverse.entity_ids


def test_relationship_and_dependency_questions(populated_store: VBGStore) -> None:
    questions = generate_questions(populated_store, COMMIT)

    relationship = _by_category(questions, QuestionCategory.RELATIONSHIP)
    dependency = _by_category(questions, QuestionCategory.DEPENDENCY)

    imports_q = next(q for q in relationship if q.entity_ids[0] == "orders")
    assert "base.BaseService" in imports_q.entity_ids

    imported_by_q = next(q for q in dependency if q.entity_ids[0] == "base.BaseService")
    assert "orders" in imported_by_q.entity_ids


def test_reference_questions(populated_store: VBGStore) -> None:
    questions = generate_questions(populated_store, COMMIT)

    reference = _by_category(questions, QuestionCategory.REFERENCE)
    match = next(q for q in reference if q.entity_ids[0] == "orders.OrderService")
    assert "orders.handle" in match.entity_ids


def test_neighborhood_questions(populated_store: VBGStore) -> None:
    questions = generate_questions(populated_store, COMMIT)

    neighborhood = _by_category(questions, QuestionCategory.NEIGHBORHOOD)
    assert len(neighborhood) > 0
    for q in neighborhood:
        assert len(q.entity_ids) > 1  # the node itself plus at least one neighbor


def test_lexical_questions_only_for_nodes_with_source_text(populated_store: VBGStore) -> None:
    questions = generate_questions(populated_store, COMMIT)
    all_nodes = {n.entity_id: n for n in populated_store.get_all_nodes(COMMIT)}

    lexical_ids = {q.entity_ids[0] for q in _by_category(questions, QuestionCategory.LEXICAL)}
    for entity_id in lexical_ids:
        assert all_nodes[entity_id].lexical_representation is not None
    # The Module node has no lexical_representation (documented Phase 2.1 scope) -- no question for it.
    assert "orders" not in lexical_ids


def test_no_occurrence_questions_generated(populated_store: VBGStore) -> None:
    # Deliberately deferred -- occurrence_count is never populated by
    # extraction yet, see the generator module docstring.
    questions = generate_questions(populated_store, COMMIT)
    assert _by_category(questions, QuestionCategory.OCCURRENCE) == []


def test_every_question_references_real_entities(populated_store: VBGStore) -> None:
    questions = generate_questions(populated_store, COMMIT)
    known_ids = {n.entity_id for n in populated_store.get_all_nodes(COMMIT)}

    for q in questions:
        for entity_id in q.entity_ids:
            assert entity_id in known_ids


def test_determinism(populated_store: VBGStore) -> None:
    first = generate_questions(populated_store, COMMIT)
    second = generate_questions(populated_store, COMMIT)

    assert [q.question_id for q in first] == [q.question_id for q in second]
    assert [q.text for q in first] == [q.text for q in second]


def test_no_duplicate_question_ids(populated_store: VBGStore) -> None:
    questions = generate_questions(populated_store, COMMIT)
    ids = [q.question_id for q in questions]
    assert len(ids) == len(set(ids))
