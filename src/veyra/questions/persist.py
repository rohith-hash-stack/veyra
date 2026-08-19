"""Mirrors veyra.static_analysis.persist: generate_questions() stays pure
(no store writes, easy to test in isolation) -- persisting is an explicit,
separate step, same discipline as extraction -> persist_extraction()."""

from __future__ import annotations

from veyra.vbg import Question, VBGStore


def persist_questions(store: VBGStore, questions: list[Question]) -> None:
    for question in questions:
        store.insert_question(question)
