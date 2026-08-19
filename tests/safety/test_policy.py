"""
Phase 3.1 policy evaluation tests (spec items 11-20 + explicit precedence).
resolve_safety_class() takes an already-decided capability tuple -- these
tests never touch AST/parsing, proving policy evaluation is genuinely
independent of capability detection.
"""

from __future__ import annotations

from veyra.safety.policy import PolicyConfig, resolve_safety_class
from veyra.vbg import Capability, RiskLevel, SafetyClass


def test_explicit_safe_policy() -> None:
    policy = PolicyConfig.default()
    policy = PolicyConfig(
        version=policy.version,
        capability_classes=policy.capability_classes,
        explicit_safe_targets=frozenset({"orders.pure_calc"}),
    )

    safety_class, risk, reason = resolve_safety_class("orders.pure_calc", (), policy)

    assert safety_class is SafetyClass.SAFE
    assert "allowlisted" in reason.lower()


def test_sandboxable_policy_for_filesystem_capability() -> None:
    policy = PolicyConfig.default()
    safety_class, risk, reason = resolve_safety_class("orders.save", (Capability.FILESYSTEM_WRITE,), policy)
    assert safety_class is SafetyClass.SANDBOXABLE


def test_mockable_policy_for_network_capability() -> None:
    policy = PolicyConfig.default()
    safety_class, risk, reason = resolve_safety_class("orders.notify", (Capability.NETWORK_ACCESS,), policy)
    assert safety_class is SafetyClass.MOCKABLE


def test_blocked_policy_for_process_execution() -> None:
    policy = PolicyConfig.default()
    safety_class, risk, reason = resolve_safety_class("orders.run_cmd", (Capability.PROCESS_EXECUTION,), policy)
    assert safety_class is SafetyClass.BLOCKED


def test_unknown_default_for_unknown_external_effect() -> None:
    policy = PolicyConfig.default()
    safety_class, risk, reason = resolve_safety_class("orders.mystery", (Capability.UNKNOWN_EXTERNAL_EFFECT,), policy)
    assert safety_class is SafetyClass.UNKNOWN


def test_empty_capabilities_default_to_sandboxable_not_safe() -> None:
    policy = PolicyConfig.default()
    safety_class, risk, reason = resolve_safety_class("orders.pure_calc", (), policy)
    assert safety_class is SafetyClass.SANDBOXABLE
    assert "not proof of safety" in reason.lower() or "not a positive safety claim" in reason.lower()


def test_conflicting_policy_rules_most_restrictive_wins() -> None:
    # A capability that would be SANDBOXABLE alone, combined with one that's
    # BLOCKED -- the documented precedence rule says the more restrictive
    # class always wins, never averaged/first-match/last-match.
    policy = PolicyConfig.default()
    safety_class, risk, reason = resolve_safety_class(
        "orders.mixed",
        (Capability.FILESYSTEM_READ, Capability.PROCESS_EXECUTION),
        policy,
    )
    assert safety_class is SafetyClass.BLOCKED


def test_allowlist_does_not_override_a_live_blocked_finding() -> None:
    # Allowlisting a target can only grant SAFE when nothing contradicts it
    # -- it must never silently suppress a detected dangerous capability.
    policy = PolicyConfig(
        version="capability-policy-v1",
        capability_classes=PolicyConfig.default().capability_classes,
        explicit_safe_targets=frozenset({"orders.run_cmd"}),
    )
    safety_class, risk, reason = resolve_safety_class("orders.run_cmd", (Capability.PROCESS_EXECUTION,), policy)

    assert safety_class is SafetyClass.BLOCKED
    assert "precedence" in reason.lower() or "override" in reason.lower()


def test_missing_policy_uses_sensible_default() -> None:
    # resolve_safety_class always requires an explicit PolicyConfig, but
    # PolicyConfig.default() is the "no policy configured" path callers use.
    policy = PolicyConfig.default()
    assert policy.version
    safety_class, risk, reason = resolve_safety_class("orders.anything", (), policy)
    assert safety_class is SafetyClass.SANDBOXABLE


def test_same_input_and_policy_is_deterministic() -> None:
    policy = PolicyConfig.default()
    first = resolve_safety_class("orders.notify", (Capability.NETWORK_ACCESS,), policy)
    second = resolve_safety_class("orders.notify", (Capability.NETWORK_ACCESS,), policy)
    assert first == second


def test_policy_version_is_recorded() -> None:
    policy = PolicyConfig(version="custom-policy-v2", capability_classes={}, explicit_safe_targets=frozenset())
    assert policy.version == "custom-policy-v2"


def test_risk_level_recorded_and_scales_with_restrictiveness() -> None:
    policy = PolicyConfig.default()
    _, blocked_risk, _ = resolve_safety_class("a", (Capability.PROCESS_EXECUTION,), policy)
    _, mockable_risk, _ = resolve_safety_class("b", (Capability.NETWORK_ACCESS,), policy)
    _, sandboxable_risk, _ = resolve_safety_class("c", (Capability.FILESYSTEM_READ,), policy)

    assert blocked_risk is RiskLevel.CRITICAL
    assert mockable_risk is RiskLevel.HIGH
    assert sandboxable_risk is RiskLevel.MEDIUM
