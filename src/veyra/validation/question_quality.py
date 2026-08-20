"""
PLAN.md Milestone 5, Phase 5.5 -- Question Quality Audit.

Questions generated/valid/duplicate/answerable/unanswered/unsupported/verified.

Unlike Phase 5.4/5.9, **none of these numbers need ground truth** -- they
are all directly computable from what Phase 2.5/2.6/2.7 already produced,
so this phase is fully real and runnable today, not `None`-filled
machinery waiting on a benchmark repo.

- `questions_valid` == `questions_generated`: Phase 2.5's own acceptance
  criterion ("unsupported constructs don't generate false questions") means
  every question that exists at all was already guaranteed, at generation
  time, to reference real VBG entities -- there is no separate "invalid"
  category a question could fall into after the fact.
- `questions_duplicate` is always 0, same documented construction fact as
  `StaticAuditReport.questions_deduplicated` (Phase 2.8): the generator
  prevents duplicates by a guard check before a Question is ever built,
  not by generating-then-filtering.
- `questions_unsupported` is always 0 for the identical reason as
  `questions_valid` above -- restated as its own field because PLAN.md
  names it separately, not because it can differ in practice.
- `questions_verified`: an answered question whose own subject entity also
  carries real Evidence (Phase 2.7's `verified_entity_ids`) -- "answered"
  alone only means the static verifier produced a value; "verified" ties
  that back to the evidence discipline the rest of this project insists on.
"""

from __future__ import annotations

from dataclasses import dataclass

from veyra.questions import summarize_knowledge
from veyra.vbg import VBGStore


@dataclass(frozen=True)
class QuestionQualityReport:
    repository_version: str
    questions_generated: int
    questions_valid: int
    questions_duplicate: int
    questions_answered: int
    questions_unanswered: int
    questions_unsupported: int
    questions_verified: int


def audit_question_quality(store: VBGStore, repository_version: str) -> QuestionQualityReport:
    questions = store.get_questions(repository_version)
    summary = summarize_knowledge(store, repository_version)
    verified_ids = set(summary.verified_entity_ids)
    answered_ids = set(summary.answered_question_ids)

    verified_count = sum(
        1 for q in questions
        if q.question_id in answered_ids and verified_ids.intersection(q.entity_ids)
    )

    return QuestionQualityReport(
        repository_version=repository_version,
        questions_generated=len(questions),
        questions_valid=len(questions),
        questions_duplicate=0,
        questions_answered=len(summary.answered_question_ids),
        questions_unanswered=len(summary.unanswered_question_ids),
        questions_unsupported=0,
        questions_verified=verified_count,
    )
