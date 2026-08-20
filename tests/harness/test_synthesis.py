"""
Phase 3.3b orchestration tests using a FakeExecutionBoundary -- no Docker
required, same pattern as tests/runtime/test_engine.py. Real Nodes come
from the actual Phase 2.1 extractor.
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Callable

from veyra.execution import ExecutionHandle, ExecutionOutcome, ExecutionRequest, ExecutionStatus
from veyra.harness import synthesize_novel_scenarios
from veyra.safety import PolicyConfig
from veyra.static_analysis import extract_repository, persist_extraction
from veyra.vbg import Evidence, EvidenceType, ExecutionEnvironment, Provenance, VBGStore

COMMIT = "commit1"


class FakeExecutionBoundary:
    """Always COMPLETED, records every request's full spec.json (including
    kwargs_literal_overrides) so tests can inspect exactly what values were
    actually dispatched into the (fake) sandbox."""

    def __init__(self) -> None:
        self.specs: list[dict] = []
        self.requests: list[ExecutionRequest] = []

    def execute(self, request: ExecutionRequest) -> ExecutionHandle:
        self.requests.append(request)
        spec = json.loads((request.output_directory / "spec.json").read_text())
        self.specs.append(spec)
        env = ExecutionEnvironment(
            environment_id="fake-env", backend="fake", image=request.image, network_enabled=False,
            memory_limit_mb=request.memory_limit_mb, cpu_limit=request.cpu_limit,
            timeout_seconds=request.timeout_seconds, non_privileged=True, read_only_filesystem=True,
        )
        return ExecutionHandle(handle_id=f"fake-{len(self.requests)}", environment=env, started_at=time.time())

    def terminate(self, handle: ExecutionHandle) -> None:
        pass

    def collect_result(self, handle: ExecutionHandle, timeout_seconds: float | None = None) -> ExecutionOutcome:
        spec = self.specs[-1]
        target_entity_id = f"{spec['module_id']}.{spec['function_name']}"
        request = self.requests[-1]
        trace = {
            "status": "COMPLETED", "return_repr": "None", "exception_type": None,
            "exception_message": None, "duration_seconds": 0.001,
            "events": [
                {"kind": "call", "entity_id": target_entity_id, "qualname": spec["function_name"], "offset_seconds": 0.0},
                {"kind": "return", "entity_id": target_entity_id, "qualname": spec["function_name"], "offset_seconds": 0.001},
            ],
        }
        (request.output_directory / "trace.json").write_text(json.dumps(trace))
        return ExecutionOutcome(
            status=ExecutionStatus.COMPLETED, exit_code=0, stdout="", stderr="",
            duration_seconds=0.01, environment=handle.environment,
        )

    def cleanup(self, handle: ExecutionHandle) -> None:
        pass


def _build_repo(write_file: Callable[[str, str], Path], repo_root: Path, store: VBGStore, source: str) -> None:
    write_file("mod.py", source)
    extraction = extract_repository(repo_root, COMMIT)
    persist_extraction(store, extraction)


def _allowlisting(*entity_ids: str) -> PolicyConfig:
    default = PolicyConfig.default()
    return PolicyConfig(
        version=default.version, capability_classes=default.capability_classes,
        explicit_safe_targets=frozenset(entity_ids),
    )


def test_default_policy_synthesizes_nothing(
    write_file: Callable[[str, str], Path], repo_root: Path, store: VBGStore
) -> None:
    _build_repo(write_file, repo_root, store, "def foo():\n    return 1\n")
    boundary = FakeExecutionBoundary()

    report = synthesize_novel_scenarios(store, repo_root, COMMIT, boundary)

    # SAFE is only reachable via an explicit allowlist (D13) -- the default
    # policy has none, so nothing is ever eligible, by design.
    assert report.eligible_targets == 0
    assert report.trials_run == 0
    assert report.not_safe_classified == report.candidates_considered
    assert boundary.requests == []


def test_allowlisted_zero_arg_function_is_synthesized(
    write_file: Callable[[str, str], Path], repo_root: Path, store: VBGStore
) -> None:
    _build_repo(write_file, repo_root, store, "def foo():\n    return 1\n")
    boundary = FakeExecutionBoundary()
    policy = _allowlisting("mod.foo")

    report = synthesize_novel_scenarios(store, repo_root, COMMIT, boundary, policy=policy, samples_per_parameter=3)

    assert report.eligible_targets == 1
    assert report.trials_run == 3
    assert all(o.status == "COMPLETED" for o in report.outcomes)
    # Each trial's evidence is independently persisted (distinct scenario_id).
    evidence = store.get_evidence_for_subject("mod.foo", COMMIT)
    assert len(evidence) == 3
    assert len({e.scenario_id for e in evidence}) == 3


def test_already_covered_by_test_evidence_is_skipped(
    write_file: Callable[[str, str], Path], repo_root: Path, store: VBGStore
) -> None:
    _build_repo(write_file, repo_root, store, "def foo():\n    return 1\n")
    store.insert_evidence(
        Evidence(
            subject_id="mod.foo", evidence_type=EvidenceType.TEST, repository_version=COMMIT,
            provenance=Provenance(producer="test", method="pre-seeded", recorded_at="2026-08-20T00:00:00+00:00"),
        )
    )
    boundary = FakeExecutionBoundary()
    policy = _allowlisting("mod.foo")

    report = synthesize_novel_scenarios(store, repo_root, COMMIT, boundary, policy=policy)

    assert report.already_covered == 1
    assert report.eligible_targets == 0
    assert boundary.requests == []


def test_already_covered_by_runtime_evidence_is_skipped(
    write_file: Callable[[str, str], Path], repo_root: Path, store: VBGStore
) -> None:
    _build_repo(write_file, repo_root, store, "def foo():\n    return 1\n")
    store.insert_evidence(
        Evidence(
            subject_id="mod.foo", evidence_type=EvidenceType.RUNTIME, repository_version=COMMIT,
            provenance=Provenance(producer="test", method="pre-seeded", recorded_at="2026-08-20T00:00:00+00:00"),
            scenario_id="prior", environment_id="prior-env",
        )
    )
    boundary = FakeExecutionBoundary()
    policy = _allowlisting("mod.foo")

    report = synthesize_novel_scenarios(store, repo_root, COMMIT, boundary, policy=policy)

    assert report.already_covered == 1
    assert boundary.requests == []


def test_unannotated_required_parameter_is_unsynthesizable(
    write_file: Callable[[str, str], Path], repo_root: Path, store: VBGStore
) -> None:
    _build_repo(write_file, repo_root, store, "def foo(x):\n    return x\n")
    boundary = FakeExecutionBoundary()
    policy = _allowlisting("mod.foo")

    report = synthesize_novel_scenarios(store, repo_root, COMMIT, boundary, policy=policy)

    assert report.unsynthesizable == 1
    assert report.eligible_targets == 0
    assert boundary.requests == []


def test_bound_methods_are_never_even_considered(
    write_file: Callable[[str, str], Path], repo_root: Path, store: VBGStore
) -> None:
    _build_repo(
        write_file, repo_root, store,
        "class Cls:\n    def foo(self):\n        return 1\n",
    )
    boundary = FakeExecutionBoundary()
    policy = _allowlisting("mod.Cls.foo")

    report = synthesize_novel_scenarios(store, repo_root, COMMIT, boundary, policy=policy)

    assert report.candidates_considered == 0  # only Function-typed nodes are considered, Cls.foo is a Method
    assert boundary.requests == []


def test_primitive_annotated_parameter_gets_diverse_synthesized_values(
    write_file: Callable[[str, str], Path], repo_root: Path, store: VBGStore
) -> None:
    _build_repo(write_file, repo_root, store, "def foo(x: int):\n    return x\n")
    boundary = FakeExecutionBoundary()
    policy = _allowlisting("mod.foo")

    report = synthesize_novel_scenarios(store, repo_root, COMMIT, boundary, policy=policy, samples_per_parameter=5)

    assert report.trials_run == 5
    observed_values = [spec["kwargs_literal_overrides"]["x"] for spec in boundary.specs]
    assert all(isinstance(v, int) for v in observed_values)
    # Real property-based generation should not collapse every trial onto
    # the same value across a range of 2,000,001 possible integers and 5
    # independent draws -- vanishingly small (not zero) flake probability.
    assert len(set(observed_values)) > 1


def test_default_valued_parameter_is_never_overridden(
    write_file: Callable[[str, str], Path], repo_root: Path, store: VBGStore
) -> None:
    _build_repo(write_file, repo_root, store, "def foo(x: int = 7):\n    return x\n")
    boundary = FakeExecutionBoundary()
    policy = _allowlisting("mod.foo")

    report = synthesize_novel_scenarios(store, repo_root, COMMIT, boundary, policy=policy, samples_per_parameter=2)

    assert report.eligible_targets == 1
    assert report.trials_run == 2
    for spec in boundary.specs:
        assert "x" not in spec["kwargs_type_tags"]
        assert "x" not in spec["kwargs_literal_overrides"]


def test_bytes_parameter_round_trips_through_json(
    write_file: Callable[[str, str], Path], repo_root: Path, store: VBGStore
) -> None:
    _build_repo(write_file, repo_root, store, "def foo(x: bytes):\n    return x\n")
    boundary = FakeExecutionBoundary()
    policy = _allowlisting("mod.foo")

    report = synthesize_novel_scenarios(store, repo_root, COMMIT, boundary, policy=policy, samples_per_parameter=2)

    assert report.trials_run == 2
    for spec in boundary.specs:
        override = spec["kwargs_literal_overrides"]["x"]
        assert isinstance(override, dict) and "__bytes_b64__" in override
