"""Model-level validation tests for PLAN.md Phase 3.4's Scenario entity."""

from __future__ import annotations

import pytest

from veyra.vbg import SafetyClass, Scenario, ScenarioUnexecutableReason

COMMIT = "commit1"


def _base(**overrides: object) -> dict:
    defaults: dict[str, object] = dict(
        scenario_id="s1",
        target_entity_id="pkg.mod.foo",
        description="Directly invoke `foo` with synthesized/default arguments.",
        required_inputs=(),
        dependencies=(),
        expected_observable_points=("return_value", "raised_exception"),
        safety_class=SafetyClass.SANDBOXABLE,
        executable=True,
        repository_version=COMMIT,
    )
    defaults.update(overrides)
    return defaults


def test_missing_target_entity_id() -> None:
    with pytest.raises(ValueError):
        Scenario(**_base(target_entity_id=""))


def test_missing_repository_version() -> None:
    with pytest.raises(ValueError):
        Scenario(**_base(repository_version=""))


def test_safety_class_must_be_enum_member() -> None:
    with pytest.raises(TypeError):
        Scenario(**_base(safety_class="SANDBOXABLE"))  # type: ignore[arg-type]


def test_executable_scenario_cannot_carry_unexecutable_reason() -> None:
    with pytest.raises(ValueError):
        Scenario(**_base(executable=True, unexecutable_reason=ScenarioUnexecutableReason.MISSING_FIXTURE))


def test_unexecutable_scenario_requires_a_reason() -> None:
    with pytest.raises(ValueError):
        Scenario(**_base(executable=False, detail="something went wrong"))


def test_unexecutable_scenario_requires_detail() -> None:
    with pytest.raises(ValueError):
        Scenario(**_base(executable=False, unexecutable_reason=ScenarioUnexecutableReason.MISSING_FIXTURE))


def test_valid_unexecutable_scenario_constructs() -> None:
    scenario = Scenario(
        **_base(
            executable=False,
            unexecutable_reason=ScenarioUnexecutableReason.BLOCKED_BY_SAFETY,
            detail="target classification is BLOCKED",
        )
    )
    assert scenario.executable is False
    assert scenario.unexecutable_reason is ScenarioUnexecutableReason.BLOCKED_BY_SAFETY


def test_valid_executable_scenario_constructs() -> None:
    scenario = Scenario(**_base())
    assert scenario.executable is True
    assert scenario.unexecutable_reason is None
