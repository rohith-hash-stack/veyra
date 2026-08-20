"""
Tests for PLAN.md Phase 3.9 (Runtime Audit) and the Milestone 3 pipeline
orchestrator (`run_runtime_analysis()` in src/veyra/pipeline.py) that ties
Phases 3.3a/3.3b/3.4/3.5/3.6/3.7/3.8 together end to end. Uses a
FakeExecutionBoundary -- no Docker required, same pattern every other M3
test file in this project already established.
"""

from __future__ import annotations

import json
import time
from pathlib import Path

from veyra.execution import ExecutionHandle, ExecutionOutcome, ExecutionRequest, ExecutionStatus
from veyra.pipeline import run_runtime_analysis, run_static_analysis
from veyra.safety import PolicyConfig
from veyra.vbg import ExecutionEnvironment, VBGStore

COMMIT = "commit1"


class FakeExecutionBoundary:
    """Always COMPLETED, zero nested calls -- exercises the real
    orchestration and aggregation logic in run_runtime_analysis() without
    needing Docker. The sample repo below has no test_*.py files, so
    the Phase 3.3a harness path never calls execute() at all and this
    fake only ever needs to understand Phase 3.5's runtime spec shape."""

    def __init__(self) -> None:
        self.requests: list[ExecutionRequest] = []

    def execute(self, request: ExecutionRequest) -> ExecutionHandle:
        self.requests.append(request)
        env = ExecutionEnvironment(
            environment_id=f"fake-env-{len(self.requests)}", backend="fake", image=request.image,
            network_enabled=False, memory_limit_mb=request.memory_limit_mb, cpu_limit=request.cpu_limit,
            timeout_seconds=request.timeout_seconds, non_privileged=True, read_only_filesystem=True,
        )
        return ExecutionHandle(handle_id=f"fake-{len(self.requests)}", environment=env, started_at=time.time())

    def terminate(self, handle: ExecutionHandle) -> None:
        pass

    def collect_result(self, handle: ExecutionHandle, timeout_seconds: float | None = None) -> ExecutionOutcome:
        request = self.requests[-1]
        spec = json.loads((request.output_directory / "spec.json").read_text())
        target_entity_id = f"{spec['module_id']}.{spec['function_name']}"
        trace = {
            "status": "COMPLETED", "return_repr": "1", "exception_type": None,
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


def _write_sample_repo(repo_root: Path) -> None:
    repo_root.mkdir()
    (repo_root / "mod.py").write_text(
        "def helper():\n    return 1\n\n\ndef foo():\n    return helper()\n"
    )


def test_run_runtime_analysis_end_to_end(tmp_path: Path, store: VBGStore) -> None:
    repo_root = tmp_path / "repo"
    _write_sample_repo(repo_root)
    run_static_analysis(store, repo_root, COMMIT)
    boundary = FakeExecutionBoundary()

    report = run_runtime_analysis(store, repo_root, COMMIT, boundary, file_count=1)

    assert report.repository_version == COMMIT
    assert report.audit_duration_seconds >= 0
    assert report.existing_tests_discovered == 0  # no test_*.py files in the sample repo
    assert report.scenarios_generated > 0
    assert report.scenarios_executable > 0
    assert report.exploration_executions_attempted > 0
    assert report.exploration_executions_completed > 0
    assert "SANDBOXABLE" in report.classifications_by_class
    assert report.runtime_evidence_count > 0
    assert report.runtime_nodes_observed > 0
    assert sum(report.verification_state_counts.values()) > 0
    assert report.verified_count >= 1  # mod.foo/mod.helper both actually ran and completed


def test_run_runtime_analysis_persists_an_audit_record(tmp_path: Path, store: VBGStore) -> None:
    repo_root = tmp_path / "repo"
    _write_sample_repo(repo_root)
    run_static_analysis(store, repo_root, COMMIT)
    boundary = FakeExecutionBoundary()

    run_runtime_analysis(store, repo_root, COMMIT, boundary, file_count=1)

    history = store.get_audit_history("3.x_runtime_pipeline", COMMIT)
    assert len(history) == 1
    assert history[0].success is True


def test_default_policy_means_zero_novel_synthesis(tmp_path: Path, store: VBGStore) -> None:
    repo_root = tmp_path / "repo"
    _write_sample_repo(repo_root)
    run_static_analysis(store, repo_root, COMMIT)
    boundary = FakeExecutionBoundary()

    report = run_runtime_analysis(store, repo_root, COMMIT, boundary, file_count=1)

    # SAFE is only reachable via an explicit policy allowlist (D13) -- no
    # policy was passed, so 3.3b synthesizes nothing.
    assert report.synthesis_eligible_targets == 0
    assert report.synthesis_trials_run == 0


def test_allowlisted_policy_enables_synthesis(tmp_path: Path, store: VBGStore) -> None:
    repo_root = tmp_path / "repo"
    _write_sample_repo(repo_root)
    run_static_analysis(store, repo_root, COMMIT)
    boundary = FakeExecutionBoundary()
    default = PolicyConfig.default()
    policy = PolicyConfig(
        version=default.version, capability_classes=default.capability_classes,
        explicit_safe_targets=frozenset({"mod.helper"}),
    )

    # file_count=501 forces Tier 3, which performs zero eager exploration
    # (D10) -- otherwise Tier 1's "explore everything" would already have
    # given mod.helper RUNTIME coverage before synthesis ever ran, leaving
    # nothing zero-coverage left for it to pick up.
    report = run_runtime_analysis(store, repo_root, COMMIT, boundary, file_count=501, policy=policy)

    assert report.exploration_executions_attempted == 0
    assert report.synthesis_eligible_targets >= 1
    assert report.synthesis_trials_run > 0
