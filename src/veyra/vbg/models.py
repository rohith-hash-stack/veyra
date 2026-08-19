"""
PLAN.md Phase 1.2 -- Canonical VBG Schema.

Scope note: this module defines Node, Edge, and the VerificationState enum --
the entities whose acceptance criteria and required tests belong to Phase 1.2
itself. Evidence and Provenance get their own dedicated model + rules in
Phase 1.3 (not yet built); Question belongs to M2, Scenario and
ExecutionEnvironment belong to M3. Rather than stub those out now as empty
placeholder fields, they are deliberately deferred to the phase that actually
defines their behavior -- see PROGRESS.md.

VerificationState is defined here with its full, final set of values (as
specified in Phase 3.8) even though most values won't be produced until M2/M3
exist, because it is explicitly named as a Milestone 1 canonical entity and
defining a closed enum now avoids an incompatible parallel enum later.
"""

from __future__ import annotations

import enum
from dataclasses import dataclass, field


class VerificationState(enum.Enum):
    STRUCTURALLY_IDENTIFIED = "STRUCTURALLY_IDENTIFIED"
    STATICALLY_SUPPORTED = "STATICALLY_SUPPORTED"
    RUNTIME_OBSERVED = "RUNTIME_OBSERVED"
    RUNTIME_VERIFIED = "RUNTIME_VERIFIED"
    CONDITIONALLY_VERIFIED = "CONDITIONALLY_VERIFIED"
    UNEXPLORED = "UNEXPLORED"
    UNANSWERED = "UNANSWERED"
    UNEXECUTABLE = "UNEXECUTABLE"
    BLOCKED_BY_SAFETY = "BLOCKED_BY_SAFETY"
    CONFLICTED = "CONFLICTED"
    STALE = "STALE"


class RelationshipType(enum.Enum):
    """The closed relationship vocabulary from PLAN.md Phase 2.3."""

    CONTAINS = "contains"
    IMPORTS = "imports"
    CALLS = "calls"
    REFERENCES = "references"
    INHERITS = "inherits"
    IMPLEMENTS = "implements"
    DEPENDS_ON = "depends_on"
    DEFINED_IN = "defined_in"


@dataclass(frozen=True)
class Node:
    entity_id: str
    type: str
    name: str
    repository_version: str
    language: str | None = None
    source_location: str | None = None
    lexical_representation: str | None = None
    occurrence_count: int = 0
    status: VerificationState = VerificationState.STRUCTURALLY_IDENTIFIED

    def __post_init__(self) -> None:
        if not self.entity_id:
            raise ValueError("Node.entity_id is required (stable identity).")
        if not self.type:
            raise ValueError("Node.type is required.")
        if not self.repository_version:
            raise ValueError("Node.repository_version is required.")
        if not isinstance(self.status, VerificationState):
            raise TypeError("Node.status must be a VerificationState member.")


@dataclass(frozen=True)
class Edge:
    source_id: str
    target_id: str
    relationship_type: RelationshipType
    repository_version: str
    status: VerificationState = VerificationState.STRUCTURALLY_IDENTIFIED

    def __post_init__(self) -> None:
        if not self.source_id:
            raise ValueError("Edge.source_id is required.")
        if not self.target_id:
            raise ValueError("Edge.target_id is required.")
        if not self.repository_version:
            raise ValueError("Edge.repository_version is required.")
        if not isinstance(self.relationship_type, RelationshipType):
            raise TypeError(
                "Edge.relationship_type must be a RelationshipType member "
                "(relationship types must be explicit, not free-form strings)."
            )
        if not isinstance(self.status, VerificationState):
            raise TypeError("Edge.status must be a VerificationState member.")


@dataclass(frozen=True)
class RepositoryRecord:
    """One acquisition event for a repository, as persisted by VBGStore.
    Mirrors veyra.acquisition.RepositoryInfo's audit fields (Phase 1.1/1.5)."""

    source: str
    commit_sha: str
    file_count: int
    language_counts: dict[str, int]
    repository_size_bytes: int
    clone_duration_seconds: float
    recorded_at: str
