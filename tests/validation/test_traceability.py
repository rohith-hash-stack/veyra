from __future__ import annotations

from pathlib import Path

from veyra.validation.traceability import check_traceability

_VEYRA_REPO_ROOT = Path(__file__).resolve().parents[2]


def test_real_repo_is_fully_traceable() -> None:
    report = check_traceability(_VEYRA_REPO_ROOT)

    assert report.gaps == ()
    assert report.fully_traceable is True
    assert report.fully_covered_count == report.total_requirements


def test_no_security_critical_gaps_in_the_real_repo() -> None:
    report = check_traceability(_VEYRA_REPO_ROOT)
    assert report.security_critical_gaps == ()


def test_covers_every_milestone_1_through_4() -> None:
    from veyra.validation.traceability import _REQUIREMENTS

    milestones = {r.milestone for r in _REQUIREMENTS}
    assert milestones == {1, 2, 3, 4}


def test_missing_repo_reports_gaps_not_a_crash(tmp_path: Path) -> None:
    report = check_traceability(tmp_path)

    assert report.fully_traceable is False
    assert len(report.gaps) > 0
    # the assessment-only requirement (2.2) is still trivially satisfied
    assert not any(g.requirement.requirement_id == "2.2" for g in report.gaps)


def test_assessment_only_requirement_is_never_a_gap(tmp_path: Path) -> None:
    # Even against an empty repo root (no test files exist at all), the
    # desk-review requirement (2.2) is still trivially satisfied -- it was
    # never meant to have a covering test module.
    report = check_traceability(tmp_path)
    assert not any(g.requirement.requirement_id == "2.2" for g in report.gaps)
