"""
PLAN.md Milestone 3, Phase 3.1 -- Policy Evaluation.

This module has zero AST/parsing knowledge -- it only ever consumes an
already-detected `tuple[Capability, ...]` and produces a (SafetyClass,
RiskLevel, reason) decision. That is the Capability Detection != Policy
Evaluation separation made structural, not just documented.

Precedence rule (PLAN.md D-series, "do not invent precedence silently"):
when multiple capabilities are present, or an allowlist entry conflicts with
a live finding, the MOST RESTRICTIVE applicable class always wins:

    BLOCKED (4) > UNKNOWN (3) > MOCKABLE (2) > SANDBOXABLE (1) > SAFE (0)

An empty capability set does not default to SAFE -- see D13/D14. It
defaults to SANDBOXABLE: nothing was flagged, so execution may proceed, but
only inside the execution boundary (Phase 3.2). SAFE is reachable only
through `PolicyConfig.explicit_safe_targets`, an explicit per-target
allowlist -- and even then, only when no detected capability implies a
class more restrictive than SANDBOXABLE. A target can be allowlisted and
still come back MOCKABLE/UNKNOWN/BLOCKED if live capability detection finds
something the allowlist didn't anticipate; the allowlist can only grant an
upgrade to SAFE, never suppress a live finding.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from veyra.vbg import Capability, RiskLevel, SafetyClass

_DEFAULT_POLICY_VERSION = "capability-policy-v1"

_CLASS_RANK: dict[SafetyClass, int] = {
    SafetyClass.SAFE: 0,
    SafetyClass.SANDBOXABLE: 1,
    SafetyClass.MOCKABLE: 2,
    SafetyClass.UNKNOWN: 3,
    SafetyClass.BLOCKED: 4,
}

_RISK_FOR_CLASS: dict[SafetyClass, RiskLevel] = {
    SafetyClass.SAFE: RiskLevel.LOW,
    SafetyClass.SANDBOXABLE: RiskLevel.MEDIUM,
    SafetyClass.MOCKABLE: RiskLevel.HIGH,
    SafetyClass.UNKNOWN: RiskLevel.HIGH,
    SafetyClass.BLOCKED: RiskLevel.CRITICAL,
}

_DEFAULT_CAPABILITY_CLASSES: dict[Capability, SafetyClass] = {
    Capability.PROCESS_EXECUTION: SafetyClass.BLOCKED,
    Capability.SUBPROCESS_EXECUTION: SafetyClass.BLOCKED,
    Capability.DYNAMIC_CODE_EXECUTION: SafetyClass.BLOCKED,
    Capability.NATIVE_CODE_ACCESS: SafetyClass.BLOCKED,
    Capability.CREDENTIAL_ACCESS: SafetyClass.BLOCKED,
    Capability.EXTERNAL_NETWORK_ACCESS: SafetyClass.MOCKABLE,
    Capability.NETWORK_ACCESS: SafetyClass.MOCKABLE,
    Capability.SOCKET_ACCESS: SafetyClass.MOCKABLE,
    Capability.DATABASE_ACCESS: SafetyClass.SANDBOXABLE,
    Capability.FILESYSTEM_WRITE: SafetyClass.SANDBOXABLE,
    Capability.FILESYSTEM_READ: SafetyClass.SANDBOXABLE,
    Capability.ENVIRONMENT_ACCESS: SafetyClass.SANDBOXABLE,
    Capability.UNKNOWN_EXTERNAL_EFFECT: SafetyClass.UNKNOWN,
}


@dataclass(frozen=True)
class PolicyConfig:
    version: str
    capability_classes: dict[Capability, SafetyClass] = field(default_factory=dict)
    explicit_safe_targets: frozenset[str] = field(default_factory=frozenset)

    @staticmethod
    def default() -> "PolicyConfig":
        return PolicyConfig(
            version=_DEFAULT_POLICY_VERSION,
            capability_classes=dict(_DEFAULT_CAPABILITY_CLASSES),
            explicit_safe_targets=frozenset(),
        )


def resolve_safety_class(
    entity_id: str,
    capabilities: tuple[Capability, ...],
    policy: PolicyConfig,
) -> tuple[SafetyClass, RiskLevel, str]:
    implied = [policy.capability_classes.get(c, SafetyClass.UNKNOWN) for c in capabilities]
    detected_class = max(implied, key=lambda c: _CLASS_RANK[c]) if implied else SafetyClass.SANDBOXABLE

    is_allowlisted = entity_id in policy.explicit_safe_targets
    if is_allowlisted and _CLASS_RANK[detected_class] <= _CLASS_RANK[SafetyClass.SANDBOXABLE]:
        final_class = SafetyClass.SAFE
        reason = (
            f"Target is explicitly allowlisted by policy {policy.version}, and no detected "
            "capability contradicts it."
        )
    elif is_allowlisted:
        final_class = detected_class
        names = ", ".join(c.value for c in capabilities)
        reason = (
            f"Target is allowlisted by policy {policy.version}, but detected capability signal(s) "
            f"[{names}] map to {final_class.value}, which is more restrictive than the allowlist "
            "would grant -- detected findings always take precedence over an allowlist entry."
        )
    elif not capabilities:
        final_class = SafetyClass.SANDBOXABLE
        reason = (
            "No risk-indicating capability was detected in the available source. This is NOT proof "
            "of safety -- absence of a detected signal is not a positive safety claim -- so the "
            "target is SANDBOXABLE (must still run inside the execution boundary), not SAFE."
        )
    else:
        final_class = detected_class
        names = ", ".join(c.value for c in capabilities)
        reason = (
            f"Detected capabilities [{names}] map to {final_class.value} under policy "
            f"{policy.version} (most restrictive applicable class wins when multiple are present)."
        )

    return final_class, _RISK_FOR_CLASS[final_class], reason
