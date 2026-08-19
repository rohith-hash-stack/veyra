"""
PLAN.md Phase 1.3 -- Evidence & Provenance.

Evidence fields map to the plan's WHAT/WHERE/WHEN/HOW/COMMIT/SCENARIO/
ENVIRONMENT requirement as follows:
    WHAT        -> subject_id (the node/edge this evidence supports)
    WHERE       -> location
    WHEN        -> provenance.recorded_at
    HOW         -> evidence_type + provenance.method
    COMMIT      -> repository_version
    SCENARIO    -> scenario_id   (required when evidence_type is RUNTIME)
    ENVIRONMENT -> environment_id (required when evidence_type is RUNTIME)

Evidence and Provenance are separate dataclasses (not one flattened record)
because "every evidence record has provenance" is stated as an independent
acceptance criterion -- Provenance answers "who/what produced this claim",
Evidence answers "what claim, about what, backed by what observation".
"""

from __future__ import annotations

import enum
from dataclasses import dataclass


class EvidenceType(enum.Enum):
    STATIC = "STATIC"
    RUNTIME = "RUNTIME"
    TEST = "TEST"
    INFERRED = "INFERRED"
    USER_SUPPLIED = "USER_SUPPLIED"


@dataclass(frozen=True)
class Provenance:
    producer: str  # e.g. "veyra.static_analysis.python_extractor"
    method: str  # e.g. "AST call-site scan" -- the HOW
    recorded_at: str  # ISO 8601 timestamp -- the WHEN

    def __post_init__(self) -> None:
        if not self.producer:
            raise ValueError("Provenance.producer is required.")
        if not self.method:
            raise ValueError("Provenance.method is required.")
        if not self.recorded_at:
            raise ValueError("Provenance.recorded_at is required.")


@dataclass(frozen=True)
class Evidence:
    subject_id: str  # WHAT: entity_id of the node, or a stable edge key
    evidence_type: EvidenceType
    repository_version: str  # COMMIT
    provenance: Provenance
    location: str | None = None  # WHERE
    detail: str | None = None
    scenario_id: str | None = None  # SCENARIO
    environment_id: str | None = None  # ENVIRONMENT

    def __post_init__(self) -> None:
        if not self.subject_id:
            raise ValueError("Evidence.subject_id is required (WHAT).")
        if not isinstance(self.evidence_type, EvidenceType):
            raise TypeError("Evidence.evidence_type must be an EvidenceType member.")
        if not self.repository_version:
            raise ValueError("Evidence.repository_version is required (COMMIT).")
        if not isinstance(self.provenance, Provenance):
            raise TypeError(
                "Evidence.provenance is required and must be a Provenance instance "
                "(every evidence record has provenance)."
            )
        if self.evidence_type is EvidenceType.RUNTIME:
            if not self.scenario_id:
                raise ValueError(
                    "RUNTIME evidence must reference a scenario_id (SCENARIO)."
                )
            if not self.environment_id:
                raise ValueError(
                    "RUNTIME evidence must reference an environment_id (ENVIRONMENT)."
                )
