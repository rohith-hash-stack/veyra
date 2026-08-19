"""
PLAN.md Milestone 3, Phase 3.2 -- ExecutionEnvironment.

PLAN.md Phase 1.2 named "ExecutionEnvironment" as a canonical VBG entity but
deferred its definition to M3, the milestone that actually specifies its
behavior -- same reasoning as Question/Answer (Phase 2.5/2.6) and
ClassificationResult (Phase 3.1). It lives here in vbg (not veyra.execution,
which holds the boundary *logic*) for the same circular-import reason as
those: VBGStore needs to persist it, and veyra.execution will depend on
veyra.vbg.

This is also the real referent of Evidence.environment_id (Phase 1.3),
which has been sitting unused since M1 -- RUNTIME evidence has required a
scenario_id and environment_id since Phase 1.3's own validation rules, but
nothing before Phase 3.2 had an actual ExecutionEnvironment to point at.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ExecutionEnvironment:
    environment_id: str
    backend: str
    image: str
    network_enabled: bool
    memory_limit_mb: int
    cpu_limit: float
    timeout_seconds: float
    non_privileged: bool
    read_only_filesystem: bool

    def __post_init__(self) -> None:
        if not self.environment_id:
            raise ValueError("ExecutionEnvironment.environment_id is required.")
        if not self.backend:
            raise ValueError("ExecutionEnvironment.backend is required.")
        if not self.image:
            raise ValueError("ExecutionEnvironment.image is required.")
        if self.memory_limit_mb <= 0:
            raise ValueError("ExecutionEnvironment.memory_limit_mb must be positive.")
        if self.cpu_limit <= 0:
            raise ValueError("ExecutionEnvironment.cpu_limit must be positive.")
        if self.timeout_seconds <= 0:
            raise ValueError("ExecutionEnvironment.timeout_seconds must be positive.")
