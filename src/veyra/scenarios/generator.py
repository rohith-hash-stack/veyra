"""
PLAN.md Milestone 3, Phase 3.4 -- Behavioral Scenario Generator.

For every Function/Method node at a commit, plans exactly one candidate
scenario: "directly invoke this with zero/default/synthesizable-primitive
arguments." This is deliberately the simplest possible scenario shape for a
first slice -- multi-call sequences, exception-injection scenarios, or
scenarios requiring constructed fixtures are not attempted here (a stated
scope boundary, not an oversight; see introspection.py).

Reuses Phase 3.1's `classify_and_audit()` exactly as-is (same as Phase
3.3a's harness manager) -- this module is therefore NOT storage-free the
way Phase 2.5's pure `generate_questions()` was: every call persists a real,
auditable classification record. That tradeoff is deliberate, matching the
most recent precedent (3.3a) rather than the older one: a scenario without
a persisted classification decision behind its safety_class would be an
unearned safety claim.

"unsupported scenarios -> unexecutable" (Phase 3.4 AC) is structural, not a
convention: Scenario.__post_init__ (vbg/scenarios.py) refuses to construct a
non-executable Scenario without an unexecutable_reason and a detail
explaining it -- there is no code path here that can silently produce a
Scenario that looks executable but isn't, or vice versa.

Determinism ("scenarios reproducible"): scenario_id is a stable hash of
(target_entity_id, repository_version) only, matching Phase 2.5's Question
identity discipline -- running this twice against the same commit and
policy produces byte-identical scenario_ids (though re-running under a
*different* policy can legitimately change a scenario's own
executable/safety_class content at that same id, which Phase 1.2's
"conflicts are representable" append-only storage already handles, see
VBGStore.insert_scenario).

**Not populated in this slice**: `Scenario.dependencies`. The natural
source would be the target's own outgoing CALLS/IMPORTS edges, but nothing
here yet consumes that field -- populating it before an actual planner/
executor needs it would be exactly the kind of premature scaffolding this
project avoids elsewhere. Left as an empty tuple, not guessed at.
"""

from __future__ import annotations

import hashlib

from veyra.safety import PolicyConfig, classify_and_audit
from veyra.vbg import Node, SafetyClass, Scenario, ScenarioUnexecutableReason, VBGStore

from .introspection import extract_signature

_INVOKABLE_TYPES = ("Function", "Method")


def _scenario_id(target_entity_id: str, repository_version: str) -> str:
    raw = f"direct_invocation|{target_entity_id}|{repository_version}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


def _unexecutable(
    node: Node,
    repository_version: str,
    safety_class: SafetyClass,
    reason: ScenarioUnexecutableReason,
    detail: str,
    required_inputs: tuple[str, ...],
) -> Scenario:
    return Scenario(
        scenario_id=_scenario_id(node.entity_id, repository_version),
        target_entity_id=node.entity_id,
        description=f"Directly invoke `{node.name}` with synthesized/default arguments.",
        required_inputs=required_inputs,
        dependencies=(),
        expected_observable_points=(),
        safety_class=safety_class,
        executable=False,
        repository_version=repository_version,
        unexecutable_reason=reason,
        detail=detail,
    )


def generate_scenarios(
    store: VBGStore, repository_version: str, policy: PolicyConfig | None = None
) -> list[Scenario]:
    nodes = [n for n in store.get_all_nodes(repository_version) if n.type in _INVOKABLE_TYPES]

    scenarios: list[Scenario] = []
    for node in sorted(nodes, key=lambda n: n.entity_id):
        signature = extract_signature(node)
        classification = classify_and_audit(store, node, repository_version, policy)

        if signature is None:
            scenarios.append(
                _unexecutable(
                    node, repository_version, classification.classification,
                    ScenarioUnexecutableReason.NO_SOURCE_AVAILABLE,
                    "no lexical_representation was available to introspect a call signature from",
                    (),
                )
            )
            continue

        required_inputs = tuple(p.name for p in signature.parameters)

        if classification.classification is SafetyClass.BLOCKED:
            scenarios.append(
                _unexecutable(
                    node, repository_version, classification.classification,
                    ScenarioUnexecutableReason.BLOCKED_BY_SAFETY,
                    classification.reason, required_inputs,
                )
            )
            continue

        if signature.is_bound_method:
            scenarios.append(
                _unexecutable(
                    node, repository_version, classification.classification,
                    ScenarioUnexecutableReason.AMBIGUOUS_INITIALIZATION,
                    "this is a bound method; no constructor/fixture strategy exists yet "
                    "to obtain an instance to call it on",
                    required_inputs,
                )
            )
            continue

        unsynthesizable = [p.name for p in signature.parameters if not p.synthesizable]
        if unsynthesizable:
            scenarios.append(
                _unexecutable(
                    node, repository_version, classification.classification,
                    ScenarioUnexecutableReason.MISSING_FIXTURE,
                    "no synthesizable value strategy for parameter(s): " + ", ".join(unsynthesizable),
                    required_inputs,
                )
            )
            continue

        scenarios.append(
            Scenario(
                scenario_id=_scenario_id(node.entity_id, repository_version),
                target_entity_id=node.entity_id,
                description=f"Directly invoke `{node.name}` with synthesized/default arguments.",
                required_inputs=required_inputs,
                dependencies=(),
                expected_observable_points=("return_value", "raised_exception"),
                safety_class=classification.classification,
                executable=True,
                repository_version=repository_version,
            )
        )

    return scenarios
