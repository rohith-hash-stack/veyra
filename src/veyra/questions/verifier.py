"""
PLAN.md Milestone 2, Phase 2.6 -- Static Question Verification.

verify_question() re-derives an answer directly from the current VBGStore
state for a given commit -- it does NOT just replay whatever was true when
the Question was generated (Phase 2.5). This matters: if the underlying
graph has changed since the question was generated (e.g. a re-extraction
after a code change removed a call site), re-deriving against the live
store is what makes this "verification" rather than an echo, and is what
lets a genuinely unanswerable question become UNANSWERED instead of always
trivially succeeding by construction.

"Static verification cannot become runtime verification" (acceptance
criterion): every Evidence record this module writes is EvidenceType.STATIC,
never RUNTIME -- there is no code path here that could produce runtime
evidence, by construction, not by convention alone (verify_question has no
scenario_id/environment_id parameters to even accept from a caller).
"""

from __future__ import annotations

from datetime import datetime, timezone

from veyra.vbg import (
    Answer,
    AnswerStatus,
    Evidence,
    EvidenceType,
    Provenance,
    Question,
    QuestionCategory,
    RelationshipType,
    VBGStore,
)

_CALL_FLOW_FORWARD = "calls_from"
_CALL_FLOW_REVERSE = "calls_to"
_INHERITANCE_FORWARD = "inherits_from"
_INHERITANCE_REVERSE = "inherited_by"


def _unanswered(question: Question) -> Answer:
    return Answer(
        question_id=question.question_id,
        status=AnswerStatus.UNANSWERED,
        entity_ids=(),
        value="",
        repository_version=question.repository_version,
    )


def _answered(question: Question, entity_ids: list[str], value: str) -> Answer:
    return Answer(
        question_id=question.question_id,
        status=AnswerStatus.ANSWERED,
        entity_ids=tuple(entity_ids),
        value=value,
        repository_version=question.repository_version,
    )


def _derive(store: VBGStore, question: Question) -> Answer:
    version = question.repository_version
    primary_id = question.entity_ids[0]
    node = store.get_latest_node(primary_id, version)
    if node is None:
        return _unanswered(question)

    out_edges = store.get_outgoing_edges(primary_id, version)
    in_edges = store.get_incoming_edges(primary_id, version)
    key = (question.category, question.template_key)

    if key == (QuestionCategory.SYMBOL, "kind_of_symbol"):
        return _answered(question, [primary_id], node.type)

    if key == (QuestionCategory.STRUCTURAL, "contains"):
        children = sorted(e.target_id for e in out_edges if e.relationship_type is RelationshipType.CONTAINS)
        if not children:
            return _unanswered(question)
        return _answered(question, [primary_id, *children], ", ".join(children))

    if key == (QuestionCategory.LEXICAL, "source_text"):
        if not node.lexical_representation:
            return _unanswered(question)
        return _answered(question, [primary_id], node.lexical_representation)

    if key == (QuestionCategory.RELATIONSHIP, "imports"):
        targets = sorted(e.target_id for e in out_edges if e.relationship_type is RelationshipType.IMPORTS)
        if not targets:
            return _unanswered(question)
        return _answered(question, [primary_id, *targets], ", ".join(targets))

    if key == (QuestionCategory.DEPENDENCY, "imported_by"):
        sources = sorted(e.source_id for e in in_edges if e.relationship_type is RelationshipType.IMPORTS)
        if not sources:
            return _unanswered(question)
        return _answered(question, [primary_id, *sources], ", ".join(sources))

    if key == (QuestionCategory.CALL_FLOW, _CALL_FLOW_FORWARD):
        targets = sorted(e.target_id for e in out_edges if e.relationship_type is RelationshipType.CALLS)
        if not targets:
            return _unanswered(question)
        return _answered(question, [primary_id, *targets], ", ".join(targets))

    if key == (QuestionCategory.CALL_FLOW, _CALL_FLOW_REVERSE):
        sources = sorted(e.source_id for e in in_edges if e.relationship_type is RelationshipType.CALLS)
        if not sources:
            return _unanswered(question)
        return _answered(question, [primary_id, *sources], ", ".join(sources))

    if key == (QuestionCategory.INHERITANCE, _INHERITANCE_FORWARD):
        targets = sorted(e.target_id for e in out_edges if e.relationship_type is RelationshipType.INHERITS)
        if not targets:
            return _unanswered(question)
        return _answered(question, [primary_id, *targets], ", ".join(targets))

    if key == (QuestionCategory.INHERITANCE, _INHERITANCE_REVERSE):
        sources = sorted(e.source_id for e in in_edges if e.relationship_type is RelationshipType.INHERITS)
        if not sources:
            return _unanswered(question)
        return _answered(question, [primary_id, *sources], ", ".join(sources))

    if key == (QuestionCategory.REFERENCE, "referenced_by"):
        sources = sorted(e.source_id for e in in_edges if e.relationship_type is RelationshipType.REFERENCES)
        if not sources:
            return _unanswered(question)
        return _answered(question, [primary_id, *sources], ", ".join(sources))

    if key == (QuestionCategory.NEIGHBORHOOD, "neighbors"):
        neighbors = sorted({e.target_id for e in out_edges} | {e.source_id for e in in_edges})
        if not neighbors:
            return _unanswered(question)
        return _answered(question, [primary_id, *neighbors], ", ".join(neighbors))

    # Any category/template_key this verifier doesn't recognize (e.g. a
    # hand-built Question, or a future category not yet wired up here) is
    # honestly UNANSWERED rather than guessed at.
    return _unanswered(question)


def verify_question(store: VBGStore, question: Question) -> Answer:
    """Re-derives the answer from the live VBGStore, persists the Answer
    either way (this is what makes "unanswered questions remain queryable"
    -- Phase 2.7 -- true rather than aspirational), and, only when ANSWERED,
    also persists STATIC evidence. UNANSWERED questions get no evidence --
    there is nothing verified to attach evidence to."""
    answer = _derive(store, question)
    store.insert_answer(answer)

    if answer.status is AnswerStatus.ANSWERED:
        store.insert_evidence(
            Evidence(
                subject_id=question.entity_ids[0],
                evidence_type=EvidenceType.STATIC,
                repository_version=question.repository_version,
                provenance=Provenance(
                    producer="veyra.questions.verifier",
                    method=f"static re-derivation of {question.category.value}/{question.template_key}",
                    recorded_at=datetime.now(timezone.utc).isoformat(),
                ),
                detail=f"Q[{question.question_id}]: {question.text} -> {answer.value}",
            )
        )

    return answer
