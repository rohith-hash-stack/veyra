"""
PLAN.md Milestone 4, Phase 4.7 -- LLM Grounding Contract.

LLM receives: relevant nodes, relationships, evidence, provenance,
verification state, conflicts, unknowns, repository commit.

**The calibration gap, addressed directly, not just noted**: PLAN.md's own
text warns that a verification-state field sitting in structured JSON can
be skimmed past by a model that then states things too confidently anyway
-- "surface verification state as prominent inline natural-language flags
... rather than burying it in structured metadata." `_VERIFICATION_NOTES`
below is exactly that: a fixed, human-authored hedge sentence per
`VerificationState`, attached to every fact as its own natural-language
field (`GroundedFact.verification_note`), not something a consumer has to
infer from an enum value. `GroundingContext.disclaimer` is the standing
instruction tying it together.

**The LLM calibration threshold itself stays deliberately unset** (per
PLAN.md's own Phase 5.9 note): this module produces the grounding payload;
whether a downstream model actually respects the hedges here is a Milestone
5 eval question (Phase 5.9), not something this module can verify on its
own -- there is no LLM call anywhere in this codebase.

Acceptance: LLM can distinguish verified/unverified (`verification_note`
per fact); conflicts exposed (`GroundingContext.conflicts`, human-readable);
unknowns stay unknown (`GroundingContext.unknowns` -- entities referenced
in relationships but never independently retrieved, so nothing is claimed
about them beyond "referenced"); repository scope explicit
(`GroundingContext.repository_version`); LLM cannot silently claim
unsupported repository behavior (the disclaimer says so explicitly);
evidence references returnable with responses (`GroundedFact.entity_id`
is always the real, citable VBG identity).

**Retrieval-quality remediation, Phase B.** `GroundedFact.confidence`/
`matched_by` now carry `context.py`'s `RetrievedContext.scores`/
`matched_by` through to this final payload -- the real-world benchmark
found this information was computed by `search()` and then discarded
before ever reaching an LLM-facing consumer. When `RetrievedContext.insufficient_evidence`
is set (nothing cleared `retrieve_context()`'s confidence bar),
`GroundingContext.insufficient_evidence` is set here too and the
disclaimer is prefixed with an explicit `NO_SUFFICIENT_EVIDENCE`
instruction, rather than leaving a caller to infer "nothing found" from
an empty `facts` tuple with no explanation.
"""

from __future__ import annotations

from dataclasses import dataclass

from veyra.vbg import VerificationState

from .context import RetrievedContext
from .index import IndexedEntity

_VERIFICATION_NOTES: dict[VerificationState, str] = {
    VerificationState.STRUCTURALLY_IDENTIFIED: (
        "NOTE: this was found in the code, but nothing about its behavior has been verified."
    ),
    VerificationState.STATICALLY_SUPPORTED: (
        "NOTE: this is supported by static analysis only -- it has never actually been executed."
    ),
    VerificationState.RUNTIME_OBSERVED: (
        "NOTE: this was executed, but the execution did not complete cleanly or was not otherwise "
        "confirmed successful."
    ),
    VerificationState.RUNTIME_VERIFIED: (
        "This was executed and completed successfully -- a real, observed behavior."
    ),
    VerificationState.CONDITIONALLY_VERIFIED: (
        "NOTE: this behaves differently depending on conditions; multiple distinct paths have each "
        "been separately confirmed, but no single path is the whole story."
    ),
    VerificationState.UNEXPLORED: (
        "NOTE: this relationship is known from static analysis but has never been exercised at runtime."
    ),
    VerificationState.UNANSWERED: "NOTE: this question could not be answered from available knowledge.",
    VerificationState.UNEXECUTABLE: (
        "NOTE: this could not be executed (missing dependency, unsafe classification, or another "
        "environmental limitation) -- no runtime behavior is known."
    ),
    VerificationState.BLOCKED_BY_SAFETY: (
        "NOTE: execution of this was blocked by safety policy -- no runtime behavior is known, and "
        "this may involve dangerous operations."
    ),
    VerificationState.CONFLICTED: (
        "NOTE: static analysis and runtime observation disagree here -- treat this as an open "
        "question, not a settled fact."
    ),
    VerificationState.STALE: (
        "NOTE: this information may be outdated relative to the current commit -- a later change may "
        "have invalidated it."
    ),
}

_DISCLAIMER = (
    "Only state as fact what the verification notes below actually confirm. For anything marked "
    "unverified, conditionally verified, conflicted, unexecutable, blocked, or stale, you must "
    "explicitly hedge using the same qualifying language provided. Do not claim repository behavior "
    "beyond what the evidence in this context establishes. If asked about something not covered here, "
    "say so rather than guessing."
)


@dataclass(frozen=True)
class GroundedFact:
    entity_id: str
    node_type: str
    summary: str
    verification_state: VerificationState
    verification_note: str
    evidence_excerpts: tuple[str, ...]
    confidence: float = 0.0
    matched_by: str = "tfidf"


@dataclass(frozen=True)
class GroundingContext:
    query: str
    repository_version: str
    facts: tuple[GroundedFact, ...]
    conflicts: tuple[str, ...]
    unknowns: tuple[str, ...]
    disclaimer: str
    insufficient_evidence: bool = False


def _summarize(entity: IndexedEntity) -> str:
    location = f" at {entity.source_location}" if entity.source_location else ""
    return f"{entity.node_type} `{entity.name}`{location}"


_NO_EVIDENCE_DISCLAIMER = (
    "NO_SUFFICIENT_EVIDENCE: nothing in this repository scored as a confident match for this query. "
    "Do not answer as if the queried functionality exists -- say plainly that no relevant evidence was "
    "found, rather than presenting a weak or coincidental lexical match as if it were a real answer."
)


def build_grounding_context(retrieved: RetrievedContext) -> GroundingContext:
    known_ids = {e.entity_id for e in retrieved.entities}

    facts = tuple(
        GroundedFact(
            entity_id=entity.entity_id,
            node_type=entity.node_type,
            summary=_summarize(entity),
            verification_state=entity.verification_state,
            verification_note=_VERIFICATION_NOTES[entity.verification_state],
            evidence_excerpts=tuple(
                ev.detail for ev in retrieved.evidence_by_entity.get(entity.entity_id, ()) if ev.detail
            ),
            confidence=retrieved.scores.get(entity.entity_id, 0.0),
            matched_by=retrieved.matched_by.get(entity.entity_id, "tfidf"),
        )
        for entity in retrieved.entities
    )

    conflicts = tuple(
        f"Static analysis and runtime observation disagree: `{c.source_id}` was observed at runtime "
        f"calling `{c.target_id}`, which static analysis never predicted."
        for c in retrieved.conflicts
    )

    unknowns = tuple(
        sorted(
            {
                edge.target_id
                for edge in retrieved.relationships
                if edge.target_id not in known_ids
            }
            | {
                edge.source_id
                for edge in retrieved.relationships
                if edge.source_id not in known_ids
            }
        )
    )

    disclaimer = f"{_NO_EVIDENCE_DISCLAIMER} {_DISCLAIMER}" if retrieved.insufficient_evidence else _DISCLAIMER

    return GroundingContext(
        query=retrieved.query,
        repository_version=retrieved.repository_version,
        facts=facts,
        conflicts=conflicts,
        unknowns=unknowns,
        disclaimer=disclaimer,
        insufficient_evidence=retrieved.insufficient_evidence,
    )
