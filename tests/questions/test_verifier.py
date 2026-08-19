"""
Tests for PLAN.md Phase 2.6 (Static Question Verification).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from veyra.questions import (
    AnswerStatus,
    Question,
    QuestionCategory,
    generate_questions,
    verify_question,
)
from veyra.static_analysis import extract_repository, persist_extraction
from veyra.vbg import EvidenceType, VBGStore

COMMIT = "commit1"


@pytest.fixture
def populated_store(tmp_path: Path, store: VBGStore) -> VBGStore:
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    (repo_root / "orders.py").write_text(
        "class OrderService:\n"
        "    def process_order(self):\n"
        "        self.validate_order()\n"
        "\n"
        "    def validate_order(self):\n"
        "        pass\n",
    )
    result = extract_repository(repo_root, COMMIT)
    persist_extraction(store, result)
    return store


def _find(questions, category, template_key, primary_id):
    return next(
        q for q in questions
        if q.category is category and q.template_key == template_key and q.entity_ids[0] == primary_id
    )


def test_verify_symbol_question(populated_store: VBGStore) -> None:
    questions = generate_questions(populated_store, COMMIT)
    q = _find(questions, QuestionCategory.SYMBOL, "kind_of_symbol", "orders.OrderService")

    answer = verify_question(populated_store, q)

    assert answer.status is AnswerStatus.ANSWERED
    assert answer.value == "Class"
    assert answer.entity_ids == ("orders.OrderService",)


def test_verify_call_flow_question(populated_store: VBGStore) -> None:
    questions = generate_questions(populated_store, COMMIT)
    q = _find(questions, QuestionCategory.CALL_FLOW, "calls_from", "orders.OrderService.process_order")

    answer = verify_question(populated_store, q)

    assert answer.status is AnswerStatus.ANSWERED
    assert "orders.OrderService.validate_order" in answer.entity_ids


def test_verify_attaches_static_evidence(populated_store: VBGStore) -> None:
    questions = generate_questions(populated_store, COMMIT)
    q = _find(questions, QuestionCategory.SYMBOL, "kind_of_symbol", "orders.OrderService")

    assert populated_store.has_evidence("orders.OrderService", COMMIT) is False
    verify_question(populated_store, q)

    evidence = populated_store.get_evidence_for_subject("orders.OrderService", COMMIT)
    assert len(evidence) == 1
    assert evidence[0].evidence_type is EvidenceType.STATIC  # never RUNTIME -- see module docstring


def test_no_evidence_for_unanswered_question(populated_store: VBGStore) -> None:
    stale_question = Question(
        question_id="deadbeef",
        category=QuestionCategory.SYMBOL,
        template_key="kind_of_symbol",
        text="What kind of symbol is `ghost`?",
        entity_ids=("orders.DoesNotExist",),
        repository_version=COMMIT,
        provenance="hand-built for test",
    )

    answer = verify_question(populated_store, stale_question)

    assert answer.status is AnswerStatus.UNANSWERED
    assert answer.entity_ids == ()
    assert populated_store.has_evidence("orders.DoesNotExist", COMMIT) is False


def test_unanswered_when_edges_no_longer_hold(populated_store: VBGStore) -> None:
    # validate_order() makes no calls -- asking "what does it call" by hand
    # (generate_questions would never produce this question itself, since
    # it only emits when there's a real answer) must come back UNANSWERED.
    hand_built = Question(
        question_id="deadbeef2",
        category=QuestionCategory.CALL_FLOW,
        template_key="calls_from",
        text="What does `validate_order` call?",
        entity_ids=("orders.OrderService.validate_order",),
        repository_version=COMMIT,
        provenance="hand-built for test",
    )

    answer = verify_question(populated_store, hand_built)

    assert answer.status is AnswerStatus.UNANSWERED


def test_unrecognized_category_template_is_unanswered_not_a_crash(populated_store: VBGStore) -> None:
    hand_built = Question(
        question_id="deadbeef3",
        category=QuestionCategory.OCCURRENCE,  # generator never produces this category (see Phase 2.5 scope note)
        template_key="occurrence_count",
        text="How many times does `OrderService` occur?",
        entity_ids=("orders.OrderService",),
        repository_version=COMMIT,
        provenance="hand-built for test",
    )

    answer = verify_question(populated_store, hand_built)

    assert answer.status is AnswerStatus.UNANSWERED


def test_all_generated_questions_are_answerable(populated_store: VBGStore) -> None:
    # Every question generate_questions() produces was, by construction,
    # backed by a real non-empty edge/attribute set at generation time --
    # verifying immediately afterward (same commit, unchanged store) must
    # always succeed.
    questions = generate_questions(populated_store, COMMIT)
    for q in questions:
        answer = verify_question(populated_store, q)
        assert answer.status is AnswerStatus.ANSWERED, f"expected ANSWERED for {q.text!r}"
