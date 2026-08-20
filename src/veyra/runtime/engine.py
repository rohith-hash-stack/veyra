"""
PLAN.md Milestone 3, Phase 3.5 -- Runtime Trace Engine.

Actually executes a Phase 3.4 Scenario inside the Phase 3.2 ExecutionBoundary
and turns what happened into real, persisted RUNTIME Evidence -- this is
where a Scenario stops being a plan and becomes an observation. Also closes
a deferral Phase 3.2 itself named: this module is the first to call
`store.insert_execution_environment()`, since `DockerExecutionBoundary`
deliberately stays storage-agnostic.

**Re-derives executability from live state** rather than trusting the
Scenario object's own cached `executable` flag -- the same discipline
Phase 2.6's `verify_question()` already established (re-derive, don't
replay a stale generation-time snapshot). The target node's source or its
safety classification may have changed since the scenario was planned; a
scenario that no longer qualifies becomes UNEXECUTABLE now, with a fresh
reason, never a silently forced run of stale intent.

**Argument synthesis is deliberately trivial**: every parameter Phase 3.4
already marked non-default + primitive-annotated gets a fixed zero-value
literal (0 / "" / 0.0 / False / b""), nothing more. This exists only to
prove the call can actually execute -- real input-space exploration is
Phase 3.3b's job (property-based synthesis, SAFE-classified targets only),
not attempted here.

Bound methods are never attempted here -- Phase 3.4 already refuses to mark
any bound method executable (AMBIGUOUS_INITIALIZATION), so this module
carries no constructor/fixture logic at all, not even a stub for it.

**"Failed execution still counts as evidence" (Phase 3.5 AC), interpreted
precisely**: an `EXCEPTION` outcome means the target genuinely ran inside
the sandbox and a real trace.json came back describing what happened --
that IS a runtime observation, and it is persisted as Evidence like any
other. A `CONTAINER_EXECUTION_FAILED`/`NO_TRACE_REPORTED` outcome (the
container itself never produced a usable trace at all -- crashed before
reaching the target, or timed out) is genuinely ambiguous about whether the
target was ever reached, so -- matching Phase 3.3a's harness manager
precedent -- it is treated as UNEXECUTABLE with no evidence, rather than
guessing.
"""

from __future__ import annotations

import base64
import enum
import json
import tempfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from veyra.execution import (
    ExecutionBoundary,
    ExecutionBoundaryError,
    ExecutionRequest,
    ExecutionStatus,
)
from veyra.scenarios import extract_signature
from veyra.vbg import Evidence, EvidenceType, Node, Provenance, SafetyClass, Scenario, VBGStore

from .tracer_script import TRACER_SOURCE

_RUNTIME_IMAGE = "python:3.11-alpine"
_PROVENANCE_PRODUCER = "veyra.runtime.engine"
_DEFAULT_TIMEOUT_SECONDS = 30.0


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class RuntimeUnexecutableReason(enum.Enum):
    BLOCKED_BY_SAFETY = "BLOCKED_BY_SAFETY"
    AMBIGUOUS_INITIALIZATION = "AMBIGUOUS_INITIALIZATION"
    MISSING_FIXTURE = "MISSING_FIXTURE"
    NO_SOURCE_AVAILABLE = "NO_SOURCE_AVAILABLE"
    CONTAINER_EXECUTION_FAILED = "CONTAINER_EXECUTION_FAILED"
    NO_TRACE_REPORTED = "NO_TRACE_REPORTED"


@dataclass(frozen=True)
class TraceEvent:
    kind: str  # "call" | "return" | "exception" | "external_interaction"
    entity_id: str | None
    qualname: str
    offset_seconds: float
    exception_type: str | None = None
    exception_message: str | None = None


@dataclass(frozen=True)
class ScenarioExecutionOutcome:
    scenario_id: str
    target_entity_id: str
    status: str  # "COMPLETED" | "EXCEPTION" | "UNEXECUTABLE"
    duration_seconds: float | None
    return_repr: str | None
    exception_type: str | None
    exception_message: str | None
    events: tuple[TraceEvent, ...]
    environment_id: str | None
    unexecutable_reason: RuntimeUnexecutableReason | None = None
    detail: str | None = None


def _unexecutable(
    scenario: Scenario,
    reason: RuntimeUnexecutableReason,
    detail: str,
    environment_id: str | None = None,
) -> ScenarioExecutionOutcome:
    return ScenarioExecutionOutcome(
        scenario_id=scenario.scenario_id,
        target_entity_id=scenario.target_entity_id,
        status="UNEXECUTABLE",
        duration_seconds=None,
        return_repr=None,
        exception_type=None,
        exception_message=None,
        events=(),
        environment_id=environment_id,
        unexecutable_reason=reason,
        detail=detail,
    )


def _encode_override(value: object) -> object:
    """JSON can't carry raw bytes -- encode as a marker dict the tracer
    script's `_decode_override()` recognizes and reverses."""
    if isinstance(value, bytes):
        return {"__bytes_b64__": base64.b64encode(value).decode("ascii")}
    return value


def _module_and_function(node: Node) -> tuple[str, str, str] | None:
    """Derives (module_id, module_path, function_name) from a module-level
    Function node's own entity_id/source_location -- no extra Node fields
    needed. Method nodes never reach here (see module docstring)."""
    if not node.source_location or "." not in node.entity_id:
        return None
    module_path = node.source_location.split(":", 1)[0]
    module_id, function_name = node.entity_id.rsplit(".", 1)
    return module_id, module_path, function_name


def _extract_observations(events: list[dict]) -> tuple[set[str], set[tuple[str, str]]]:
    """Reconstructs which entities were observed and which caller->callee
    edges were actually exercised, from the flat, time-ordered event list.
    Stack depth is tracked purely via call/return (1:1 per frame, including
    frames that exit via an exception -- CPython still fires a `return`
    event with arg=None in that case); `exception` events are informational
    only and never affect the stack."""
    entities: set[str] = set()
    edges: set[tuple[str, str]] = set()
    stack: list[str | None] = []
    for event in events:
        kind = event.get("kind")
        if kind == "call":
            entity_id = event.get("entity_id")
            if entity_id:
                entities.add(entity_id)
                if stack and stack[-1] is not None:
                    edges.add((stack[-1], entity_id))
            stack.append(entity_id)
        elif kind == "return" and stack:
            stack.pop()
    return entities, edges


def run_scenario(
    store: VBGStore,
    repository_root: Path,
    repository_version: str,
    scenario: Scenario,
    boundary: ExecutionBoundary,
    argument_overrides: dict[str, object] | None = None,
) -> ScenarioExecutionOutcome:
    """`argument_overrides` (name -> a JSON-safe value, or raw `bytes`) lets
    a caller supply real concrete values for some or all of the target's
    non-default parameters instead of the trivial zero-literal this module
    otherwise uses -- Phase 3.3b's novel-synthesis entry point is the only
    caller that does, feeding it Hypothesis-generated samples. Purely
    additive: omitting it (the default) reproduces Phase 3.5's original
    trivial-literal behavior exactly. Only names that are still independently
    re-derived as real, synthesizable, non-default parameters of the live
    signature are ever used -- an override for a stale/nonexistent/no-longer-
    synthesizable parameter name is silently ignored, never a way to bypass
    the synthesizability gate below."""
    node = store.get_latest_node(scenario.target_entity_id, repository_version)
    if node is None or node.type not in ("Function", "Method"):
        # Method is accepted here (not just Function) so a target that is
        # *currently* a bound method still gets the precise
        # AMBIGUOUS_INITIALIZATION verdict below, via signature.is_bound_method
        # -- the same invokable-type set Phase 3.4's generator itself uses.
        return _unexecutable(
            scenario, RuntimeUnexecutableReason.NO_SOURCE_AVAILABLE,
            "no current Function/Method node exists for this scenario's target",
        )

    signature = extract_signature(node)
    if signature is None:
        return _unexecutable(
            scenario, RuntimeUnexecutableReason.NO_SOURCE_AVAILABLE,
            "no lexical_representation currently available to introspect a call signature",
        )

    classification = store.get_latest_classification(scenario.target_entity_id, repository_version)
    if classification is None or classification.classification is SafetyClass.BLOCKED:
        return _unexecutable(
            scenario, RuntimeUnexecutableReason.BLOCKED_BY_SAFETY,
            "current classification is BLOCKED or missing -- re-checked at execution time, "
            "not just trusted from scenario generation",
        )

    if signature.is_bound_method:
        return _unexecutable(
            scenario, RuntimeUnexecutableReason.AMBIGUOUS_INITIALIZATION,
            "target is currently a bound method; no constructor/fixture strategy exists yet",
        )

    unsynthesizable = [p.name for p in signature.parameters if not p.synthesizable]
    if unsynthesizable:
        return _unexecutable(
            scenario, RuntimeUnexecutableReason.MISSING_FIXTURE,
            "no synthesizable value strategy for parameter(s): " + ", ".join(unsynthesizable),
        )

    located = _module_and_function(node)
    if located is None:
        return _unexecutable(
            scenario, RuntimeUnexecutableReason.NO_SOURCE_AVAILABLE,
            "could not derive a module path/function name for this target",
        )
    module_id, module_path, function_name = located
    kwargs_type_tags = {p.name: p.annotation for p in signature.parameters if not p.has_default}
    kwargs_literal_overrides = {
        name: _encode_override(value)
        for name, value in (argument_overrides or {}).items()
        if name in kwargs_type_tags
    }

    with tempfile.TemporaryDirectory(prefix="veyra-runtime-") as run_dir_raw:
        run_dir = Path(run_dir_raw)
        (run_dir / "run_scenario.py").write_text(TRACER_SOURCE, encoding="utf-8")
        spec = {
            "module_id": module_id,
            "module_path": module_path,
            "function_name": function_name,
            "kwargs_type_tags": kwargs_type_tags,
            "kwargs_literal_overrides": kwargs_literal_overrides,
        }
        (run_dir / "spec.json").write_text(json.dumps(spec), encoding="utf-8")

        request = ExecutionRequest(
            target=scenario.target_entity_id,
            command=("python3", "/output/run_scenario.py"),
            image=_RUNTIME_IMAGE,
            working_directory=repository_root,
            output_directory=run_dir,
            timeout_seconds=_DEFAULT_TIMEOUT_SECONDS,
        )

        try:
            handle = boundary.execute(request)
        except ExecutionBoundaryError as exc:
            return _unexecutable(
                scenario, RuntimeUnexecutableReason.CONTAINER_EXECUTION_FAILED,
                f"the execution boundary could not even start: {exc}",
            )

        try:
            outcome = boundary.collect_result(handle)
        finally:
            boundary.cleanup(handle)

        store.insert_execution_environment(handle.environment)
        environment_id = handle.environment.environment_id

        if outcome.status is not ExecutionStatus.COMPLETED:
            return _unexecutable(
                scenario, RuntimeUnexecutableReason.CONTAINER_EXECUTION_FAILED,
                f"execution container did not complete: {outcome.status.value} "
                f"(stderr: {outcome.stderr.strip()[:500]})",
                environment_id=environment_id,
            )

        trace_path = run_dir / "trace.json"
        if not trace_path.is_file():
            return _unexecutable(
                scenario, RuntimeUnexecutableReason.NO_TRACE_REPORTED,
                "execution container completed but produced no trace.json",
                environment_id=environment_id,
            )
        try:
            trace = json.loads(trace_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return _unexecutable(
                scenario, RuntimeUnexecutableReason.NO_TRACE_REPORTED,
                "trace.json was present but not valid JSON",
                environment_id=environment_id,
            )

    raw_events = trace.get("events", [])
    events = tuple(
        TraceEvent(
            kind=e.get("kind", ""),
            entity_id=e.get("entity_id"),
            qualname=e.get("qualname", ""),
            offset_seconds=e.get("offset_seconds", 0.0),
            exception_type=e.get("exception_type"),
            exception_message=e.get("exception_message"),
        )
        for e in raw_events
    )
    entities, edges = _extract_observations(raw_events)
    entities.add(scenario.target_entity_id)  # always observed, even if resolution somehow missed it

    result = ScenarioExecutionOutcome(
        scenario_id=scenario.scenario_id,
        target_entity_id=scenario.target_entity_id,
        status=trace.get("status", "EXCEPTION"),
        duration_seconds=trace.get("duration_seconds"),
        return_repr=trace.get("return_repr"),
        exception_type=trace.get("exception_type"),
        exception_message=trace.get("exception_message"),
        events=events,
        environment_id=environment_id,
    )

    _persist_runtime_evidence(store, repository_version, scenario, result, entities, edges)
    return result


def _edge_key(source_id: str, target_id: str) -> str:
    return f"{source_id}--CALLS-->{target_id}"


def _persist_runtime_evidence(
    store: VBGStore,
    repository_version: str,
    scenario: Scenario,
    result: ScenarioExecutionOutcome,
    entities: set[str],
    edges: set[tuple[str, str]],
) -> None:
    provenance = Provenance(
        producer=_PROVENANCE_PRODUCER,
        method="direct invocation traced via sys.settrace inside ExecutionBoundary (Phase 3.2)",
        recorded_at=_now(),
    )
    for entity_id in sorted(entities):
        detail = f"status={result.status}"
        if entity_id == result.target_entity_id:
            if result.exception_type:
                detail += f"; exception={result.exception_type}: {result.exception_message}"
            elif result.return_repr is not None:
                detail += f"; return={result.return_repr}"
        store.insert_evidence(
            Evidence(
                subject_id=entity_id,
                evidence_type=EvidenceType.RUNTIME,
                repository_version=repository_version,
                provenance=provenance,
                scenario_id=scenario.scenario_id,
                environment_id=result.environment_id,
                detail=detail,
            )
        )
    for source_id, target_id in sorted(edges):
        store.insert_evidence(
            Evidence(
                subject_id=_edge_key(source_id, target_id),
                evidence_type=EvidenceType.RUNTIME,
                repository_version=repository_version,
                provenance=provenance,
                scenario_id=scenario.scenario_id,
                environment_id=result.environment_id,
                detail=f"runtime-observed call: {source_id} -> {target_id}",
            )
        )
