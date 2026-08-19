from __future__ import annotations

from veyra.scenarios import generate_scenarios
from veyra.vbg import Node, SafetyClass, ScenarioUnexecutableReason, VBGStore

COMMIT = "commit1"


def make_node(entity_id: str, source: str, node_type: str = "Function") -> Node:
    """See test_introspection.py's identical helper for why this is defined
    locally rather than imported from a shared conftest.py."""
    return Node(
        entity_id=entity_id,
        type=node_type,
        name=entity_id.rsplit(".", 1)[-1],
        repository_version=COMMIT,
        language="Python",
        lexical_representation=source,
    )


def _outcome(store: VBGStore, target: str):
    scenarios = generate_scenarios(store, COMMIT)
    return next(s for s in scenarios if s.target_entity_id == target)


def test_zero_arg_function_is_executable(store: VBGStore) -> None:
    store.insert_node(make_node("mod.foo", "def foo():\n    return 1\n"))
    scenario = _outcome(store, "mod.foo")
    assert scenario.executable is True
    assert scenario.unexecutable_reason is None
    assert scenario.safety_class is SafetyClass.SANDBOXABLE  # no capability detected, D13/D14
    assert scenario.required_inputs == ()


def test_primitive_annotated_args_are_executable(store: VBGStore) -> None:
    store.insert_node(make_node("mod.foo", "def foo(x: int, y: str) -> None:\n    pass\n"))
    scenario = _outcome(store, "mod.foo")
    assert scenario.executable is True
    assert scenario.required_inputs == ("x", "y")


def test_unsynthesizable_parameter_is_missing_fixture(store: VBGStore) -> None:
    store.insert_node(make_node("mod.foo", "def foo(x):\n    pass\n"))
    scenario = _outcome(store, "mod.foo")
    assert scenario.executable is False
    assert scenario.unexecutable_reason is ScenarioUnexecutableReason.MISSING_FIXTURE
    assert "x" in scenario.detail


def test_bound_method_is_ambiguous_initialization(store: VBGStore) -> None:
    store.insert_node(make_node("mod.Cls.foo", "def foo(self):\n    pass\n", node_type="Method"))
    scenario = _outcome(store, "mod.Cls.foo")
    assert scenario.executable is False
    assert scenario.unexecutable_reason is ScenarioUnexecutableReason.AMBIGUOUS_INITIALIZATION


def test_blocked_capability_is_blocked_by_safety(store: VBGStore) -> None:
    store.insert_node(
        make_node("mod.danger", "import subprocess\n\ndef danger():\n    subprocess.run(['ls'])\n")
    )
    scenario = _outcome(store, "mod.danger")
    assert scenario.executable is False
    assert scenario.unexecutable_reason is ScenarioUnexecutableReason.BLOCKED_BY_SAFETY
    assert scenario.safety_class is SafetyClass.BLOCKED


def test_node_with_no_lexical_representation_is_no_source_available(store: VBGStore) -> None:
    store.insert_node(make_node("mod.foo", ""))
    scenario = _outcome(store, "mod.foo")
    assert scenario.executable is False
    assert scenario.unexecutable_reason is ScenarioUnexecutableReason.NO_SOURCE_AVAILABLE


def test_non_invokable_node_types_are_skipped(store: VBGStore) -> None:
    store.insert_node(make_node("mod", "", node_type="Module"))
    store.insert_node(make_node("mod.Cls", "class Cls:\n    pass\n", node_type="Class"))
    store.insert_node(make_node("mod.Cls.x", "x = 1", node_type="Variable"))

    scenarios = generate_scenarios(store, COMMIT)

    assert scenarios == []


def test_generation_persists_a_real_classification(store: VBGStore) -> None:
    store.insert_node(make_node("mod.foo", "def foo():\n    return 1\n"))
    generate_scenarios(store, COMMIT)

    history = store.get_classification_history("mod.foo", COMMIT)
    assert len(history) == 1
    assert history[0].classification is SafetyClass.SANDBOXABLE


def test_generation_is_deterministic(store: VBGStore) -> None:
    store.insert_node(make_node("mod.foo", "def foo(x: int):\n    return x\n"))
    first = generate_scenarios(store, COMMIT)
    second = generate_scenarios(store, COMMIT)
    assert [s.scenario_id for s in first] == [s.scenario_id for s in second]
    assert first[0].scenario_id == second[0].scenario_id


def test_every_scenario_references_a_real_target_entity_id(store: VBGStore) -> None:
    store.insert_node(make_node("mod.foo", "def foo():\n    return 1\n"))
    store.insert_node(make_node("mod.bar", "def bar(x):\n    pass\n"))

    scenarios = generate_scenarios(store, COMMIT)
    known_entity_ids = {n.entity_id for n in store.get_all_nodes(COMMIT)}

    assert all(s.target_entity_id in known_entity_ids for s in scenarios)
