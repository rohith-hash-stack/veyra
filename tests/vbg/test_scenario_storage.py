"""Tests for VBGStore's Scenario persistence (backs Phase 3.4)."""

from __future__ import annotations

from veyra.vbg import Scenario, ScenarioUnexecutableReason, SafetyClass, VBGStore

COMMIT = "commit1"


def _executable_scenario(scenario_id="s1", target="pkg.mod.foo", version=COMMIT) -> Scenario:
    return Scenario(
        scenario_id=scenario_id,
        target_entity_id=target,
        description=f"Directly invoke `{target}` with synthesized/default arguments.",
        required_inputs=(),
        dependencies=(),
        expected_observable_points=("return_value", "raised_exception"),
        safety_class=SafetyClass.SANDBOXABLE,
        executable=True,
        repository_version=version,
    )


def _unexecutable_scenario(scenario_id="s1", target="pkg.mod.foo", version=COMMIT) -> Scenario:
    return Scenario(
        scenario_id=scenario_id,
        target_entity_id=target,
        description=f"Directly invoke `{target}` with synthesized/default arguments.",
        required_inputs=("x",),
        dependencies=(),
        expected_observable_points=(),
        safety_class=SafetyClass.UNKNOWN,
        executable=False,
        repository_version=version,
        unexecutable_reason=ScenarioUnexecutableReason.MISSING_FIXTURE,
        detail="no synthesizable value strategy for parameter(s): x",
    )


def test_insert_and_get_scenarios(store: VBGStore) -> None:
    store.insert_scenario(_executable_scenario("s1", "pkg.mod.foo"))
    store.insert_scenario(_executable_scenario("s2", "pkg.mod.bar"))

    scenarios = store.get_scenarios(COMMIT)

    assert {s.scenario_id for s in scenarios} == {"s1", "s2"}


def test_scenarios_scoped_by_commit(store: VBGStore) -> None:
    store.insert_scenario(_executable_scenario("s1", version="commit1"))
    store.insert_scenario(_executable_scenario("s2", version="commit2"))

    assert [s.scenario_id for s in store.get_scenarios("commit1")] == ["s1"]


def test_store_exposes_no_update_or_delete_for_scenarios(store: VBGStore) -> None:
    for name in ("update_scenario", "delete_scenario"):
        assert not hasattr(store, name)


def test_conflicting_regeneration_preserved_as_history_not_overwrite(store: VBGStore) -> None:
    # Re-generating scenarios for the same target/commit under a changed
    # policy is a conflicting write for the same scenario_id -- both stay
    # queryable, matching Node/Edge's "conflicts are representable".
    store.insert_scenario(_unexecutable_scenario("s1", "pkg.mod.foo"))
    store.insert_scenario(_executable_scenario("s1", "pkg.mod.foo"))

    history = store.get_scenario_history("s1", COMMIT)
    assert len(history) == 2
    assert history[0].executable is False
    assert history[1].executable is True
    assert store.get_latest_scenario("s1", COMMIT).executable is True
    # the current view only ever surfaces the latest row per scenario_id
    assert len(store.get_scenarios(COMMIT)) == 1


def test_get_latest_scenario_none_when_never_generated(store: VBGStore) -> None:
    assert store.get_latest_scenario("nonexistent", COMMIT) is None


def test_unexecutable_scenario_round_trips_reason_and_detail(store: VBGStore) -> None:
    store.insert_scenario(_unexecutable_scenario("s1", "pkg.mod.foo"))

    scenario = store.get_latest_scenario("s1", COMMIT)

    assert scenario.executable is False
    assert scenario.unexecutable_reason is ScenarioUnexecutableReason.MISSING_FIXTURE
    assert "x" in scenario.detail
    assert scenario.required_inputs == ("x",)
