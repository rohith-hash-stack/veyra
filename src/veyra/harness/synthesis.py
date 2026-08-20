"""
PLAN.md Milestone 3, Phase 3.3b -- Novel Scenario Synthesis.

Per Design Decision D2, this is the second, higher-risk half of the Harness
& Fixture Manager: synthesize *novel* scenarios for functions with zero
test coverage, restricted to the SAFE-classified subset, using an
established property-based library (Hypothesis) rather than a bespoke
input/fixture generator.

**How "restricted to SAFE" actually plays out**: `SafetyClass.SAFE` is only
ever reachable through an explicit per-target policy allowlist entry (D13)
-- never derived from an empty capability set. Under `PolicyConfig.default()`
(no allowlist configured), this module therefore does nothing at all, by
design -- the same conservative "ambiguity resolves toward not proceeding"
posture as everything else in `veyra.safety`. A caller must deliberately
configure a `PolicyConfig` with specific allowlisted targets before this
module will ever synthesize anything for them.

**"Zero test coverage" is defined directly off evidence this project
already produces**: a target is eligible only if it carries no
`EvidenceType.TEST` (Phase 3.3a) and no `EvidenceType.RUNTIME` (Phase 3.5/
3.6) evidence yet at this commit -- i.e. nothing has ever actually
exercised it, neither an existing test nor a prior scenario execution.

**Where the property-based generation actually happens, and where it
deliberately does not**: Hypothesis's own `strategies` module generates
diverse concrete values for a parameter's already-synthesizable primitive
type (str/int/float/bool/bytes -- the exact same 5-type boundary Phase 3.4/
3.5 already use, not a wider one) entirely on the HOST, using
`@given`/`@settings(max_examples=..., database=None)` to collect a bounded
sample set without needing a live test runner. Those concrete values are
then handed, unmodified, to Phase 3.5's `run_scenario(..., argument_overrides=...)`
-- so the actual invocation of repository code always happens exactly where
D1 requires it: inside the unmodified Phase 3.2 sandbox, via the exact same
tracer Phase 3.5 already uses. Hypothesis's own execution/shrinking engine
is deliberately NOT run inside the container (that would need installing a
third-party package into the sandboxed image over a network connection this
project's `DockerExecutionBoundary` deliberately never opens -- see D17 and
`veyra.harness.install_policy`'s own docstring for why installing anything
into the sandbox at request time is out of scope). Hypothesis here is
Veyra's own trusted, pinned tooling dependency (like `pytest` already is
for Veyra's own test suite), not a repository dependency -- a categorically
different case from the arbitrary-repo-dependency installation
`install_policy.py` declines to solve.

Each Hypothesis-generated value combination becomes its own scenario
(distinct `scenario_id`, so its evidence is never confused with another
trial's), and each trial is dispatched through `run_scenario()`
independently -- one real, sandboxed execution per trial, exactly as
disciplined as every other execution in this project.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path

from hypothesis import given, settings
from hypothesis import strategies as st

from veyra.execution import ExecutionBoundary
from veyra.runtime import ScenarioExecutionOutcome, run_scenario
from veyra.safety import PolicyConfig, classify_and_audit
from veyra.scenarios import extract_signature
from veyra.vbg import EvidenceType, SafetyClass, Scenario, VBGStore

_DEFAULT_SAMPLES_PER_PARAMETER = 5
_PROVENANCE_TARGET_TYPE = "Function"

_STRATEGIES = {
    "str": st.text(max_size=50),
    "int": st.integers(min_value=-1_000_000, max_value=1_000_000),
    "float": st.floats(allow_nan=False, allow_infinity=False, width=32),
    "bool": st.booleans(),
    "bytes": st.binary(max_size=50),
}


@dataclass(frozen=True)
class SynthesisReport:
    repository_version: str
    candidates_considered: int
    not_safe_classified: int
    already_covered: int
    unsynthesizable: int
    eligible_targets: int
    trials_run: int
    outcomes: tuple[ScenarioExecutionOutcome, ...]


def _collect_samples(strategy: st.SearchStrategy, count: int) -> list:
    """Collects up to `count` example values from a Hypothesis strategy
    without needing a real pytest-style test body -- the idiomatic way to
    get bounded example batches programmatically (bare repeated
    `.example()` calls are explicitly discouraged by Hypothesis and emit
    warnings; this uses the same `@given`/`@settings` machinery a real
    test would, just with a no-op body that only records the value)."""
    samples: list = []

    @given(strategy)
    @settings(max_examples=count, database=None, deadline=None)
    def _inner(value: object) -> None:
        samples.append(value)

    _inner()
    return samples


def _has_test_or_runtime_coverage(store: VBGStore, entity_id: str, repository_version: str) -> bool:
    return any(
        e.evidence_type in (EvidenceType.TEST, EvidenceType.RUNTIME)
        for e in store.get_evidence_for_subject(entity_id, repository_version)
    )


def _scenario_id(target_entity_id: str, repository_version: str, trial: int) -> str:
    raw = f"novel_synthesis|{target_entity_id}|{repository_version}|{trial}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


def synthesize_novel_scenarios(
    store: VBGStore,
    repository_root: Path,
    repository_version: str,
    boundary: ExecutionBoundary,
    policy: PolicyConfig | None = None,
    samples_per_parameter: int = _DEFAULT_SAMPLES_PER_PARAMETER,
) -> SynthesisReport:
    nodes = [n for n in store.get_all_nodes(repository_version) if n.type == _PROVENANCE_TARGET_TYPE]

    not_safe_classified = 0
    already_covered = 0
    unsynthesizable_count = 0
    eligible_targets = 0
    outcomes: list[ScenarioExecutionOutcome] = []

    for node in sorted(nodes, key=lambda n: n.entity_id):
        classification = classify_and_audit(store, node, repository_version, policy)
        if classification.classification is not SafetyClass.SAFE:
            not_safe_classified += 1
            continue

        if _has_test_or_runtime_coverage(store, node.entity_id, repository_version):
            already_covered += 1
            continue

        signature = extract_signature(node)
        if signature is None or signature.is_bound_method:
            unsynthesizable_count += 1
            continue

        needs_value = [p for p in signature.parameters if not p.has_default]
        if any(not p.synthesizable for p in needs_value):
            unsynthesizable_count += 1
            continue

        eligible_targets += 1
        per_param_samples = {
            p.name: _collect_samples(_STRATEGIES[p.annotation], samples_per_parameter) for p in needs_value
        }

        for trial in range(samples_per_parameter):
            argument_overrides = {
                name: samples[trial] for name, samples in per_param_samples.items() if trial < len(samples)
            }
            scenario = Scenario(
                scenario_id=_scenario_id(node.entity_id, repository_version, trial),
                target_entity_id=node.entity_id,
                description=f"Novel synthesized invocation #{trial} of `{node.name}` "
                "(Hypothesis-generated arguments).",
                required_inputs=tuple(p.name for p in needs_value),
                dependencies=(),
                expected_observable_points=("return_value", "raised_exception"),
                safety_class=classification.classification,
                executable=True,
                repository_version=repository_version,
            )
            store.insert_scenario(scenario)
            outcomes.append(
                run_scenario(
                    store, repository_root, repository_version, scenario, boundary,
                    argument_overrides=argument_overrides,
                )
            )

    return SynthesisReport(
        repository_version=repository_version,
        candidates_considered=len(nodes),
        not_safe_classified=not_safe_classified,
        already_covered=already_covered,
        unsynthesizable=unsynthesizable_count,
        eligible_targets=eligible_targets,
        trials_run=len(outcomes),
        outcomes=tuple(outcomes),
    )
