from __future__ import annotations

from veyra.harness import DependencyManifest, InstallationDecision, evaluate_installation


def test_empty_manifest_is_supported() -> None:
    manifest = DependencyManifest(declared_packages=(), manifest_files=())
    decision, reason = evaluate_installation(manifest)
    assert decision is InstallationDecision.SUPPORTED
    assert "standard library" in reason


def test_manifest_with_dependencies_is_unsupported_environment() -> None:
    manifest = DependencyManifest(declared_packages=("requests", "flask"), manifest_files=("requirements.txt",))
    decision, reason = evaluate_installation(manifest)
    assert decision is InstallationDecision.UNSUPPORTED_ENVIRONMENT
    assert "requests" in reason and "flask" in reason


def test_reason_never_claims_installation_was_attempted() -> None:
    manifest = DependencyManifest(declared_packages=("numpy",), manifest_files=("requirements.txt",))
    _, reason = evaluate_installation(manifest)
    assert "does not perform" in reason or "does not attempt" in reason.lower() or "stops here" in reason
