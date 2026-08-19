"""
Tests for PLAN.md Phase 2.7 (Verified / Unverified Knowledge Arms).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from veyra.questions import generate_questions, persist_questions, summarize_knowledge, verify_question
from veyra.static_analysis import extract_repository, persist_extraction
from veyra.vbg import VBGStore, VerificationState

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


def test_everything_starts_unverified(populated_store: VBGStore) -> None:
    # No question has been verified yet -- nothing has real Evidence.
    summary = summarize_knowledge(populated_store, COMMIT)

    all_nodes = {n.entity_id for n in populated_store.get_all_nodes(COMMIT)}
    assert set(summary.unverified_entity_ids) == all_nodes
    assert summary.verified_entity_ids == ()


def test_unknown_is_never_silently_verified_by_status_label(populated_store: VBGStore) -> None:
    # A node's default VerificationState is STRUCTURALLY_IDENTIFIED, not
    # some obviously-unverified-sounding label -- summarize_knowledge must
    # not be fooled by that label into treating it as verified.
    nodes = populated_store.get_all_nodes(COMMIT)
    assert all(n.status is VerificationState.STRUCTURALLY_IDENTIFIED for n in nodes)

    summary = summarize_knowledge(populated_store, COMMIT)
    assert summary.verified_entity_ids == ()


def test_verifying_a_question_moves_its_subject_to_verified(populated_store: VBGStore) -> None:
    questions = generate_questions(populated_store, COMMIT)
    persist_questions(populated_store, questions)

    target = next(q for q in questions if q.entity_ids[0] == "orders.OrderService")
    verify_question(populated_store, target)

    summary = summarize_knowledge(populated_store, COMMIT)
    assert "orders.OrderService" in summary.verified_entity_ids
    assert "orders.OrderService" not in summary.unverified_entity_ids


def test_verified_and_unverified_arms_stay_disjoint(populated_store: VBGStore) -> None:
    questions = generate_questions(populated_store, COMMIT)
    persist_questions(populated_store, questions)
    for q in questions[:2]:  # only verify a subset
        verify_question(populated_store, q)

    summary = summarize_knowledge(populated_store, COMMIT)
    assert set(summary.verified_entity_ids).isdisjoint(set(summary.unverified_entity_ids))
    assert len(summary.verified_entity_ids) > 0
    assert len(summary.unverified_entity_ids) > 0


def test_unanswered_questions_remain_queryable(populated_store: VBGStore) -> None:
    questions = generate_questions(populated_store, COMMIT)
    persist_questions(populated_store, questions)
    # Nothing verified yet -- every question is "unanswered" so far, but
    # every single one must still be retrievable, not dropped.
    summary = summarize_knowledge(populated_store, COMMIT)

    assert set(summary.unanswered_question_ids) == {q.question_id for q in questions}
    assert summary.answered_question_ids == ()
    stored_questions = populated_store.get_questions(COMMIT)
    assert {q.question_id for q in stored_questions} == {q.question_id for q in questions}


def test_answered_and_unanswered_questions_split_correctly(populated_store: VBGStore) -> None:
    questions = generate_questions(populated_store, COMMIT)
    persist_questions(populated_store, questions)
    verified_question = questions[0]
    verify_question(populated_store, verified_question)

    summary = summarize_knowledge(populated_store, COMMIT)

    assert verified_question.question_id in summary.answered_question_ids
    assert verified_question.question_id not in summary.unanswered_question_ids
    assert len(summary.unanswered_question_ids) == len(questions) - 1
