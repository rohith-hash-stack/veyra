"""
PLAN.md Milestone 5, Phase 5.9 -- False Verification Audit.

False Verification Rate = Incorrectly verified claims / All verified claims
**Release criterion:** no known false-verification cases in the release
benchmark. Do not claim arbitrary software can mathematically achieve zero
false verification.

**Machinery, not a number, same D6 discipline as Phase 5.4**:
`known_incorrect_entity_ids` in `FalseVerificationGroundTruth` needs a human
or process oracle that has independently confirmed a "verified" claim is
actually wrong -- there is no way to compute that from the VBG itself
(if there were, the original verification would already have caught it).
`audit_false_verification()` runs fully real without ground truth (it
always reports the real `verified_count`), and reports a real rate only
once ground truth is supplied.

**Added sub-check -- LLM answer calibration**: distinct from the VBG-level
false-verification rate above. `score_calibration()` checks whether a
model's answer text actually hedges on facts whose `VerificationState`
implies it should -- but this module never calls a real LLM anywhere; the
`model_answer` string is always caller-supplied. Hedge detection is a
deliberately simple, stated heuristic (keyword presence across the whole
answer, not attributed to the specific sentence discussing that entity) --
a real eval would need either careful per-claim text alignment or an
LLM-as-judge call, neither attempted here. **The pass threshold itself
stays unset** (PLAN.md's own "Threshold decision: deliberately deferred...
observe the model's actual baseline hedge-compliance rate, then set the
threshold from that baseline" -- a scheduled decision point, not guessed
at here); `score_calibration()` reports `compliance_rate`, and it is the
caller's job to compare that against a threshold once one has been set
from real baseline data.
"""

from __future__ import annotations

from dataclasses import dataclass

from veyra.retrieval import GroundingContext
from veyra.vbg import VBGStore, VerificationState
from veyra.verification import derive_verification_states

_HEDGE_MARKERS = (
    "note:", "unverified", "not been executed", "not confirmed", "may ", "might ",
    "possibly", "uncertain", "unknown", "conflicting", "hasn't been", "has not been",
    "no evidence", "cannot confirm", "unclear", "not been verified", "blocked",
)


@dataclass(frozen=True)
class FalseVerificationGroundTruth:
    repository_version: str
    known_incorrect_entity_ids: frozenset[str]


@dataclass(frozen=True)
class FalseVerificationReport:
    repository_version: str
    verified_count: int
    known_incorrect_count: int
    false_verification_rate: float | None
    release_criterion_met: bool | None


def audit_false_verification(
    store: VBGStore, repository_version: str, ground_truth: FalseVerificationGroundTruth | None = None
) -> FalseVerificationReport:
    states = derive_verification_states(store, repository_version)
    verified_ids = {
        entity_id for entity_id, state in states.items()
        if state in (VerificationState.RUNTIME_VERIFIED, VerificationState.CONDITIONALLY_VERIFIED)
    }

    if ground_truth is None:
        return FalseVerificationReport(
            repository_version=repository_version, verified_count=len(verified_ids),
            known_incorrect_count=0, false_verification_rate=None, release_criterion_met=None,
        )

    known_incorrect_verified = verified_ids & ground_truth.known_incorrect_entity_ids
    return FalseVerificationReport(
        repository_version=repository_version,
        verified_count=len(verified_ids),
        known_incorrect_count=len(known_incorrect_verified),
        false_verification_rate=(len(known_incorrect_verified) / len(verified_ids)) if verified_ids else None,
        release_criterion_met=(len(known_incorrect_verified) == 0) if verified_ids else None,
    )


@dataclass(frozen=True)
class CalibrationCheck:
    entity_id: str
    requires_hedge: bool
    entity_mentioned: bool
    hedge_detected: bool
    compliant: bool


@dataclass(frozen=True)
class CalibrationEvalResult:
    query: str
    checks: tuple[CalibrationCheck, ...]
    compliance_rate: float | None


def score_calibration(grounding: GroundingContext, model_answer: str) -> CalibrationEvalResult:
    answer_lower = model_answer.lower()
    hedge_detected = any(marker in answer_lower for marker in _HEDGE_MARKERS)

    checks = []
    for fact in grounding.facts:
        requires_hedge = fact.verification_state is not VerificationState.RUNTIME_VERIFIED
        symbol_name = fact.entity_id.rsplit(".", 1)[-1].lower()
        mentioned = symbol_name in answer_lower
        compliant = (not requires_hedge) or (not mentioned) or hedge_detected
        checks.append(CalibrationCheck(fact.entity_id, requires_hedge, mentioned, hedge_detected, compliant))

    relevant = [c for c in checks if c.requires_hedge and c.entity_mentioned]
    compliance_rate = (sum(1 for c in relevant if c.compliant) / len(relevant)) if relevant else None

    return CalibrationEvalResult(query=grounding.query, checks=tuple(checks), compliance_rate=compliance_rate)
