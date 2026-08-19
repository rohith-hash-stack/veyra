"""Tests for VBGStore's Question/Answer persistence (backs Phase 2.5/2.6/2.7)."""

from __future__ import annotations

from veyra.vbg import Answer, AnswerStatus, Question, QuestionCategory, VBGStore

COMMIT = "commit1"


def _question(question_id="q1", version=COMMIT) -> Question:
    return Question(
        question_id=question_id,
        category=QuestionCategory.SYMBOL,
        template_key="kind_of_symbol",
        text="What kind of symbol is `foo`?",
        entity_ids=("foo",),
        repository_version=version,
        provenance="type of node foo",
    )


def _answer(question_id="q1", status=AnswerStatus.ANSWERED, entity_ids=("foo",), version=COMMIT) -> Answer:
    return Answer(
        question_id=question_id,
        status=status,
        entity_ids=entity_ids,
        value="Function" if status is AnswerStatus.ANSWERED else "",
        repository_version=version,
    )


def test_insert_and_get_questions(store: VBGStore) -> None:
    store.insert_question(_question("q1"))
    store.insert_question(_question("q2"))

    questions = store.get_questions(COMMIT)

    assert {q.question_id for q in questions} == {"q1", "q2"}


def test_questions_scoped_by_commit(store: VBGStore) -> None:
    store.insert_question(_question("q1", version="commit1"))
    store.insert_question(_question("q2", version="commit2"))

    assert [q.question_id for q in store.get_questions("commit1")] == ["q1"]


def test_store_exposes_no_update_or_delete_for_questions_or_answers(store: VBGStore) -> None:
    for name in ("update_question", "delete_question", "update_answer", "delete_answer"):
        assert not hasattr(store, name)


def test_insert_and_get_answer_history(store: VBGStore) -> None:
    store.insert_answer(_answer("q1"))

    history = store.get_answer_history("q1", COMMIT)

    assert len(history) == 1
    assert history[0].status is AnswerStatus.ANSWERED
    assert history[0].value == "Function"


def test_answer_history_preserves_reverification_results(store: VBGStore) -> None:
    # Re-verifying the same question later (e.g. after a re-extraction) is a
    # new Answer row, not an overwrite -- same append-only discipline as
    # everything else in VBGStore.
    store.insert_answer(_answer("q1", status=AnswerStatus.ANSWERED, entity_ids=("foo",)))
    store.insert_answer(_answer("q1", status=AnswerStatus.UNANSWERED, entity_ids=()))

    history = store.get_answer_history("q1", COMMIT)
    assert [a.status for a in history] == [AnswerStatus.ANSWERED, AnswerStatus.UNANSWERED]
    assert store.get_latest_answer("q1", COMMIT).status is AnswerStatus.UNANSWERED


def test_get_latest_answer_none_when_never_answered(store: VBGStore) -> None:
    assert store.get_latest_answer("nonexistent", COMMIT) is None
