"""
PLAN.md Phase 1.2 named "Question"/"Answer" as canonical VBG entities but
deferred their definition to the phase that actually specifies their rules
(see models.py's scope note). That phase is Milestone 2 Phase 2.5
(Deterministic Question Generator) for Question; Answer follows in Phase 2.6.

Defined here in the vbg package (not in veyra.questions, which holds the
*logic* that produces/consumes these) so VBGStore can persist them without a
circular import -- veyra.questions already depends on veyra.vbg for
Evidence/RelationshipType/VBGStore, so the canonical entity shapes have to
live on this side of that dependency.
"""

from __future__ import annotations

import enum
from dataclasses import dataclass


class QuestionCategory(enum.Enum):
    SYMBOL = "SYMBOL"
    STRUCTURAL = "STRUCTURAL"
    RELATIONSHIP = "RELATIONSHIP"
    DEPENDENCY = "DEPENDENCY"
    CALL_FLOW = "CALL_FLOW"
    INHERITANCE = "INHERITANCE"
    REFERENCE = "REFERENCE"
    NEIGHBORHOOD = "NEIGHBORHOOD"
    LEXICAL = "LEXICAL"
    OCCURRENCE = "OCCURRENCE"


@dataclass(frozen=True)
class Question:
    question_id: str
    category: QuestionCategory
    template_key: str
    text: str
    entity_ids: tuple[str, ...]
    repository_version: str
    provenance: str

    def __post_init__(self) -> None:
        if not self.question_id:
            raise ValueError("Question.question_id is required.")
        if not isinstance(self.category, QuestionCategory):
            raise TypeError("Question.category must be a QuestionCategory member.")
        if not self.template_key:
            raise ValueError(
                "Question.template_key is required -- it is what lets Phase "
                "2.6 re-derive the answer without guessing the question's "
                "direction/shape from its rendered text."
            )
        if not self.text:
            raise ValueError("Question.text is required.")
        if not self.entity_ids:
            raise ValueError(
                "Question.entity_ids must reference at least one VBG entity "
                "(every question references one or more VBG entities)."
            )
        if not self.repository_version:
            raise ValueError("Question.repository_version is required.")
        if not self.provenance:
            raise ValueError(
                "Question.provenance is required (identifies the graph "
                "information used to generate the question)."
            )


class AnswerStatus(enum.Enum):
    ANSWERED = "ANSWERED"
    UNANSWERED = "UNANSWERED"


@dataclass(frozen=True)
class Answer:
    question_id: str
    status: AnswerStatus
    entity_ids: tuple[str, ...]
    value: str
    repository_version: str

    def __post_init__(self) -> None:
        if not self.question_id:
            raise ValueError("Answer.question_id is required.")
        if not isinstance(self.status, AnswerStatus):
            raise TypeError("Answer.status must be an AnswerStatus member.")
        if not self.repository_version:
            raise ValueError("Answer.repository_version is required.")
        if self.status is AnswerStatus.ANSWERED and not self.entity_ids:
            raise ValueError(
                "An ANSWERED Answer must reference at least one VBG entity "
                "(answers reference VBG entities)."
            )
        if self.status is AnswerStatus.UNANSWERED and self.entity_ids:
            raise ValueError("An UNANSWERED Answer cannot carry entity_ids.")
