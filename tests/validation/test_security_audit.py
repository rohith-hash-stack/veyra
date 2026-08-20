from __future__ import annotations

from pathlib import Path

from veyra.validation.security_audit import audit_security_coverage

_VEYRA_REPO_ROOT = Path(__file__).resolve().parents[2]


def test_real_repo_has_full_security_coverage() -> None:
    report = audit_security_coverage(_VEYRA_REPO_ROOT)

    assert report.test_module_exists is True
    assert report.coverage_complete is True
    assert all(r.fully_covered for r in report.results)


def test_every_named_property_is_present() -> None:
    report = audit_security_coverage(_VEYRA_REPO_ROOT)
    property_ids = {r.property_id for r in report.results}
    assert property_ids == {
        "filesystem_escape", "network_escape", "credential_leakage",
        "sandbox_escape", "resource_exhaustion", "timeout_bypass", "destructive_commands",
    }


def test_missing_repo_reports_incomplete_coverage(tmp_path: Path) -> None:
    report = audit_security_coverage(tmp_path)

    assert report.test_module_exists is False
    assert report.coverage_complete is False


def test_results_are_deterministically_ordered() -> None:
    report = audit_security_coverage(_VEYRA_REPO_ROOT)
    ids = [r.property_id for r in report.results]
    assert ids == sorted(ids)
