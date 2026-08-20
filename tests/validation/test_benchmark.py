from __future__ import annotations

import json
import time
from pathlib import Path

from veyra.execution import ExecutionHandle, ExecutionOutcome, ExecutionRequest, ExecutionStatus
from veyra.validation.benchmark import BenchmarkTier, run_benchmark
from veyra.validation.structural_accuracy import GroundTruthSet
from veyra.vbg import ExecutionEnvironment, VBGStore

COMMIT = "commit1"


class FakeExecutionBoundary:
    def __init__(self) -> None:
        self.requests: list[ExecutionRequest] = []

    def execute(self, request: ExecutionRequest) -> ExecutionHandle:
        self.requests.append(request)
        env = ExecutionEnvironment(
            environment_id="fake-env", backend="fake", image=request.image, network_enabled=False,
            memory_limit_mb=request.memory_limit_mb, cpu_limit=request.cpu_limit,
            timeout_seconds=request.timeout_seconds, non_privileged=True, read_only_filesystem=True,
        )
        return ExecutionHandle(handle_id="fake", environment=env, started_at=time.time())

    def terminate(self, handle: ExecutionHandle) -> None:
        pass

    def collect_result(self, handle: ExecutionHandle, timeout_seconds: float | None = None) -> ExecutionOutcome:
        request = self.requests[-1]
        spec = json.loads((request.output_directory / "spec.json").read_text())
        target = f"{spec['module_id']}.{spec['function_name']}"
        trace = {
            "status": "COMPLETED", "return_repr": "1", "exception_type": None, "exception_message": None,
            "duration_seconds": 0.001,
            "events": [
                {"kind": "call", "entity_id": target, "qualname": spec["function_name"], "offset_seconds": 0.0},
                {"kind": "return", "entity_id": target, "qualname": spec["function_name"], "offset_seconds": 0.001},
            ],
        }
        (request.output_directory / "trace.json").write_text(json.dumps(trace))
        return ExecutionOutcome(
            status=ExecutionStatus.COMPLETED, exit_code=0, stdout="", stderr="",
            duration_seconds=0.01, environment=handle.environment,
        )

    def cleanup(self, handle: ExecutionHandle) -> None:
        pass


def _write_repo(root: Path) -> None:
    root.mkdir()
    (root / "mod.py").write_text("def foo():\n    return 1\n")


def test_benchmark_run_produces_every_report(tmp_path: Path, store: VBGStore) -> None:
    repo_root = tmp_path / "repo"
    _write_repo(repo_root)

    result = run_benchmark(
        store, repo_root, COMMIT, BenchmarkTier.TIER_1_CONTROLLED, FakeExecutionBoundary(),
        file_count=1, sample_queries=["foo"],
    )

    assert result.tier is BenchmarkTier.TIER_1_CONTROLLED
    assert result.static_report.node_count > 0
    assert result.runtime_report.repository_version == COMMIT
    assert result.retrieval_report.queries_run == 1
    assert result.structural_accuracy is None  # no ground truth supplied


def test_benchmark_run_with_ground_truth_computes_real_accuracy(tmp_path: Path, store: VBGStore) -> None:
    repo_root = tmp_path / "repo"
    _write_repo(repo_root)
    ground_truth = GroundTruthSet(COMMIT, frozenset({"mod", "mod.foo"}), frozenset())

    result = run_benchmark(
        store, repo_root, COMMIT, BenchmarkTier.TIER_1_CONTROLLED, FakeExecutionBoundary(),
        file_count=1, sample_queries=[], ground_truth=ground_truth,
    )

    assert result.structural_accuracy is not None
    assert result.structural_accuracy.node_accuracy.precision == 1.0
    assert result.structural_accuracy.node_accuracy.recall == 1.0


def test_benchmark_tiers_are_distinct_from_exploration_tiers() -> None:
    from veyra.exploration import ExplorationTier

    benchmark_names = {t.name for t in BenchmarkTier}
    exploration_names = {t.name for t in ExplorationTier}
    assert benchmark_names.isdisjoint(exploration_names)
