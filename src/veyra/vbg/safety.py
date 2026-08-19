"""
PLAN.md Milestone 3, Phase 3.1 -- data shapes for capability/risk detection
and safety classification. Lives in vbg (not veyra.safety, which holds the
detection/policy *logic*) for the same reason Question/Answer do: VBGStore
needs to persist ClassificationResult, and veyra.safety already depends on
veyra.vbg, so the shapes have to live on this side of that dependency to
avoid a circular import.
"""

from __future__ import annotations

import enum
from dataclasses import dataclass


class Capability(enum.Enum):
    NETWORK_ACCESS = "NETWORK_ACCESS"
    EXTERNAL_NETWORK_ACCESS = "EXTERNAL_NETWORK_ACCESS"
    PROCESS_EXECUTION = "PROCESS_EXECUTION"
    SUBPROCESS_EXECUTION = "SUBPROCESS_EXECUTION"
    FILESYSTEM_READ = "FILESYSTEM_READ"
    FILESYSTEM_WRITE = "FILESYSTEM_WRITE"
    CREDENTIAL_ACCESS = "CREDENTIAL_ACCESS"
    ENVIRONMENT_ACCESS = "ENVIRONMENT_ACCESS"
    DATABASE_ACCESS = "DATABASE_ACCESS"
    SOCKET_ACCESS = "SOCKET_ACCESS"
    DYNAMIC_CODE_EXECUTION = "DYNAMIC_CODE_EXECUTION"
    NATIVE_CODE_ACCESS = "NATIVE_CODE_ACCESS"
    UNKNOWN_EXTERNAL_EFFECT = "UNKNOWN_EXTERNAL_EFFECT"


class SafetyClass(enum.Enum):
    """
    SAFE          Execution is explicitly permitted by the current policy
                  without requiring additional isolation beyond the defined
                  execution boundary. Reachable ONLY via an explicit
                  per-target policy allowlist entry -- never derived from
                  "no capability was detected" (see PLAN.md D13/D14).
    SANDBOXABLE   Execution may proceed, but only inside the controlled
                  execution boundary (Phase 3.2). This is the default for
                  "nothing concerning detected" -- not SAFE.
    MOCKABLE      Real external behavior must be replaced by an approved
                  mock/substitute before execution is permitted.
    BLOCKED       Execution is prohibited by policy.
    UNKNOWN       Available evidence is insufficient to establish a safe
                  execution classification. Never automatically executed.
    """

    SAFE = "SAFE"
    SANDBOXABLE = "SANDBOXABLE"
    MOCKABLE = "MOCKABLE"
    BLOCKED = "BLOCKED"
    UNKNOWN = "UNKNOWN"


class RiskLevel(enum.Enum):
    NONE = "NONE"
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


@dataclass(frozen=True)
class ClassificationResult:
    target: str
    classification: SafetyClass
    risk_level: RiskLevel
    capabilities_detected: tuple[Capability, ...]
    matched_rules: tuple[str, ...]
    reason: str
    evidence: tuple[str, ...]
    repository_commit: str
    policy_version: str

    def __post_init__(self) -> None:
        if not self.target:
            raise ValueError("ClassificationResult.target is required.")
        if not isinstance(self.classification, SafetyClass):
            raise TypeError("ClassificationResult.classification must be a SafetyClass member.")
        if not isinstance(self.risk_level, RiskLevel):
            raise TypeError("ClassificationResult.risk_level must be a RiskLevel member.")
        if not self.reason:
            raise ValueError("ClassificationResult.reason is required (auditability).")
        if not self.repository_commit:
            raise ValueError("ClassificationResult.repository_commit is required.")
        if not self.policy_version:
            raise ValueError("ClassificationResult.policy_version is required.")
