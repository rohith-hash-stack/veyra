"""
PLAN.md Phase 1.2 named "Scenario" as a canonical VBG entity but deferred its
definition to Milestone 3, Phase 3.4 (Behavioral Scenario Generator), the
phase that actually specifies its shape and rules -- the same deferral
pattern as Question/Answer (Phase 2.5/2.6), ClassificationResult
(Phase 3.1), and ExecutionEnvironment (Phase 3.2).

Lives in vbg (not veyra.scenarios, which holds the generation logic) for the
same circular-import reason those entities do: VBGStore needs to persist
Scenario, and veyra.scenarios already depends on veyra.vbg (Node,
ClassificationResult, VBGStore).

A Scenario is a *candidate for runtime observation* -- "what would it mean
to actually execute this node?" -- not an execution or its outcome. It is
meant to become the scenario_id an actual runtime Evidence record points at
once Phase 3.5 (Runtime Trace Engine) runs it; this entity intentionally
captures only the plan, never a result.
"""

from __future__ import annotations

import enum
from dataclasses import dataclass

from .safety import SafetyClass


class ScenarioUnexecutableReason(enum.Enum):
    BLOCKED_BY_SAFETY = "BLOCKED_BY_SAFETY"  # Phase 3.1 classification is BLOCKED
    AMBIGUOUS_INITIALIZATION = "AMBIGUOUS_INITIALIZATION"  # a bound method; no known way to obtain an instance yet
    MISSING_FIXTURE = "MISSING_FIXTURE"  # a required parameter with no synthesizable value
    NO_SOURCE_AVAILABLE = "NO_SOURCE_AVAILABLE"  # no lexical_representation to introspect a signature from


@dataclass(frozen=True)
class Scenario:
    scenario_id: str
    target_entity_id: str
    description: str
    required_inputs: tuple[str, ...]
    dependencies: tuple[str, ...]
    expected_observable_points: tuple[str, ...]
    safety_class: SafetyClass
    executable: bool
    repository_version: str
    unexecutable_reason: ScenarioUnexecutableReason | None = None
    detail: str | None = None

    def __post_init__(self) -> None:
        if not self.scenario_id:
            raise ValueError("Scenario.scenario_id is required.")
        if not self.target_entity_id:
            raise ValueError(
                "Scenario.target_entity_id is required (scenarios reference actual VBG nodes)."
            )
        if not self.description:
            raise ValueError("Scenario.description is required.")
        if not isinstance(self.safety_class, SafetyClass):
            raise TypeError(
                "Scenario.safety_class must be a SafetyClass member "
                "(safety classified before execution)."
            )
        if not self.repository_version:
            raise ValueError("Scenario.repository_version is required.")
        if self.executable and self.unexecutable_reason is not None:
            raise ValueError("An executable Scenario cannot carry an unexecutable_reason.")
        if not self.executable:
            if self.unexecutable_reason is None:
                raise ValueError(
                    "A non-executable Scenario must carry an unexecutable_reason "
                    "(unsupported scenarios become UNEXECUTABLE, not silently absent)."
                )
            if not self.detail:
                raise ValueError("A non-executable Scenario must explain why via detail.")
