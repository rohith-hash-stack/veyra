"""
PLAN.md Milestone 2, Phase 2.7 -- Verified / Unverified Knowledge Arms.

"Verified" means: a VBG entity has at least one real Evidence record at this
commit (VBGStore.has_evidence()) -- produced by Phase 2.6's
verify_question(), or later Milestone 3 runtime evidence. "Unverified" is
the strict complement: every other node currently in the graph with no
supporting evidence at all. Nothing here infers verification from a node's
mere existence, or from its VerificationState default -- only a real
Evidence row moves an entity from one arm to the other. That is what
satisfies "unknown is never silently converted to verified": a node's
status field is not consulted at all by this module, deliberately, so a
label can never substitute for real evidence.

Questions/Answers get the same treatment: a question is "answered" only if
its most recently persisted Answer (Phase 2.6) has status ANSWERED --
never-verified questions and questions that came back UNANSWERED are both
"unanswered" here, and both remain fully queryable via
VBGStore.get_questions() / get_answer_history(), never silently dropped.
"""

from __future__ import annotations

from dataclasses import dataclass

from veyra.vbg import AnswerStatus, VBGStore


@dataclass(frozen=True)
class KnowledgeSummary:
    repository_version: str
    verified_entity_ids: tuple[str, ...]
    unverified_entity_ids: tuple[str, ...]
    answered_question_ids: tuple[str, ...]
    unanswered_question_ids: tuple[str, ...]


def summarize_knowledge(store: VBGStore, repository_version: str) -> KnowledgeSummary:
    verified: list[str] = []
    unverified: list[str] = []
    for node in store.get_all_nodes(repository_version):
        if store.has_evidence(node.entity_id, repository_version):
            verified.append(node.entity_id)
        else:
            unverified.append(node.entity_id)

    answered: list[str] = []
    unanswered: list[str] = []
    for question in store.get_questions(repository_version):
        latest = store.get_latest_answer(question.question_id, repository_version)
        if latest is not None and latest.status is AnswerStatus.ANSWERED:
            answered.append(question.question_id)
        else:
            unanswered.append(question.question_id)

    return KnowledgeSummary(
        repository_version=repository_version,
        verified_entity_ids=tuple(sorted(verified)),
        unverified_entity_ids=tuple(sorted(unverified)),
        answered_question_ids=tuple(sorted(answered)),
        unanswered_question_ids=tuple(sorted(unanswered)),
    )
