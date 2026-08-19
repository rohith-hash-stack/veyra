"""
PLAN.md Milestone 3 -- Dependency/Installation Policy, the second stage of
the dependency-installation-as-a-security-operation pipeline (Dependency
Inspection -> Installation Policy -> Environment Construction).

**Deliberate scope boundary for this slice**: installing arbitrary
third-party packages from an arbitrary repository means running that
package's own build/setup code (setup.py and modern build backends alike
can execute code at install time) with network access -- a real
supply-chain attack surface, and a materially harder security problem than
running already-installed, already-sandboxed code (Phase 3.2, which
deliberately never enables container network access at all). Building that
pipeline for real -- a reviewed allowlist/registry-pinning policy, a
network-scoped-only-during-install execution mode -- is future work, not
attempted here.

Until that exists, this policy is deliberately conservative and matches the
project's own precedent (D13/D14: absence of a signal is not a safety
proof; ambiguity resolves toward NOT proceeding, never toward a silent
best-effort fallback): a repository whose test suite needs ONLY the
standard library is SUPPORTED; any third-party dependency declared anywhere
makes the whole harness run UNSUPPORTED_ENVIRONMENT.

Revisit trigger (named, scheduled follow-up -- same pattern as D9/Emerge):
once a reviewed installation-policy design exists.
"""

from __future__ import annotations

import enum

from .dependencies import DependencyManifest


class InstallationDecision(enum.Enum):
    SUPPORTED = "SUPPORTED"  # no third-party dependency declared anywhere
    UNSUPPORTED_ENVIRONMENT = "UNSUPPORTED_ENVIRONMENT"


def evaluate_installation(manifest: DependencyManifest) -> tuple[InstallationDecision, str]:
    if not manifest.declared_packages:
        return (
            InstallationDecision.SUPPORTED,
            "No third-party dependency was declared in any recognized manifest "
            "(requirements.txt, pyproject.toml) -- the harness can run using only "
            "the standard library already present in the execution image.",
        )
    names = ", ".join(manifest.declared_packages)
    return (
        InstallationDecision.UNSUPPORTED_ENVIRONMENT,
        f"Declared third-party dependencies [{names}] would require package "
        "installation, which this slice deliberately does not perform -- "
        "installing arbitrary packages is itself an unreviewed execution/"
        "security operation (see this module's docstring). Harness construction "
        "for this repository stops here rather than silently falling back to "
        "unsafe host installation.",
    )
