"""
Phase 3.6 orchestration tests using a FakeExecutionBoundary -- no Docker
required, same pattern as tests/runtime/test_engine.py. Real Nodes/Edges
come from the actual Phase 2.1 extractor (not hand-built) so CALLS edges
--needed for centrality ranking and call-graph neighborhood traversal--
are genuine.
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Callable

from veyra.exploration import ExplorationTier, explore, explore_at_ingest, explore_neighborhood
import veyra.exploration.engine as engine_module
from veyra.execution import ExecutionHandle, ExecutionOutcome, ExecutionRequest, ExecutionStatus
from veyra.static_analysis import extract_repository, persist_extraction
from veyra.vbg import Evidence, EvidenceType, ExecutionEnvironment, Provenance, VBGStore

COMMIT = "commit1"


class FakeExecutionBoundary:
    """Always COMPLETED, zero nested calls, records the order targets were
    executed in -- enough to test candidate selection/ordering/budgeting
    without depending on real trace mechanics (those are Phase 3.5's own
    tests)."""

    def __init__(self) -> None:
        self.executed_order: list[str] = []
        self.requests: list[ExecutionRequest] = []

    def execute(self, request: ExecutionRequest) -> ExecutionHandle:
        self.requests.append(request)
        env = ExecutionEnvironment(
            environment_id="fake-env", backend="fake", image=request.image, network_enabled=False,
            memory_limit_mb=request.memory_limit_mb, cpu_limit=request.cpu_limit,
            timeout_seconds=request.timeout_seconds, non_privileged=True, read_only_filesystem=True,
        )
        return ExecutionHandle(handle_id=f"fake-{len(self.requests)}", environment=env, started_at=time.time())

    def terminate(self, handle: ExecutionHandle) -> None:
        pass

    def collect_result(self, handle: ExecutionHandle, timeout_seconds: float | None = None) -> ExecutionOutcome:
        request = self.requests[-1]
        spec = json.loads((request.output_directory / "spec.json").read_text())
        target_entity_id = f"{spec['module_id']}.{spec['function_name']}"
        self.executed_order.append(target_entity_id)
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


_THREE_INDEPENDENT_FUNCS = "def a():\n    return 1\n\n\ndef b():\n    return 2\n\n\ndef c():\n    return 3\n"

_CALL_CHAIN = (
    "def leaf():\n    return 0\n\n\n"
    "def mid():\n    return leaf() + 1\n\n\n"
    "def root():\n    return mid() + 1\n"
)


def test_explore_persists_every_generated_scenario(
    write_file: Callable[[str, str], Path], repo_root: Path, store: VBGStore
) -> None:
    _build_repo(write_file, repo_root, store, _THREE_INDEPENDENT_FUNCS)
    boundary = FakeExecutionBoundary()

    explore(store, repo_root, COMMIT, boundary)

    persisted = store.get_scenarios(COMMIT)
    assert {s.target_entity_id for s in persisted} == {"mod.a", "mod.b", "mod.c"}


def test_explore_with_no_candidates_returns_empty_report(repo_root: Path, store: VBGStore) -> None:
    boundary = FakeExecutionBoundary()
    report = explore(store, repo_root, COMMIT, boundary, candidate_entity_ids=set())
    assert report.candidates_considered == 0
    assert report.attempted == 0
    assert report.outcomes == ()


def test_explore_attempts_every_executable_candidate_by_default(
    write_file: Callable[[str, str], Path], repo_root: Path, store: VBGStore
) -> None:
    _build_repo(write_file, repo_root, store, _THREE_INDEPENDENT_FUNCS)
    boundary = FakeExecutionBoundary()

    report = explore(store, repo_root, COMMIT, boundary)

    assert report.candidates_considered == 3
    assert report.attempted == 3
    assert report.completed == 3
    assert report.budget_exhausted is False
    assert set(boundary.executed_order) == {"mod.a", "mod.b", "mod.c"}


def test_candidate_entity_ids_restricts_the_set(
    write_file: Callable[[str, str], Path], repo_root: Path, store: VBGStore
) -> None:
    _build_repo(write_file, repo_root, store, _THREE_INDEPENDENT_FUNCS)
    boundary = FakeExecutionBoundary()

    report = explore(store, repo_root, COMMIT, boundary, candidate_entity_ids={"mod.a"})

    assert report.candidates_considered == 1
    assert boundary.executed_order == ["mod.a"]


def test_already_explored_target_is_skipped_not_reattempted(
    write_file: Callable[[str, str], Path], repo_root: Path, store: VBGStore
) -> None:
    _build_repo(write_file, repo_root, store, _THREE_INDEPENDENT_FUNCS)
    store.insert_evidence(
        Evidence(
            subject_id="mod.a", evidence_type=EvidenceType.RUNTIME, repository_version=COMMIT,
            provenance=Provenance(producer="test", method="pre-seeded", recorded_at="2026-08-20T00:00:00+00:00"),
            scenario_id="prior-scenario", environment_id="prior-env",
        )
    )
    boundary = FakeExecutionBoundary()

    report = explore(store, repo_root, COMMIT, boundary)

    assert report.already_explored_skipped == 1
    assert report.attempted == 2
    assert "mod.a" not in boundary.executed_order


def test_max_executions_budget_stops_early(
    write_file: Callable[[str, str], Path], repo_root: Path, store: VBGStore
) -> None:
    _build_repo(write_file, repo_root, store, _THREE_INDEPENDENT_FUNCS)
    boundary = FakeExecutionBoundary()

    report = explore(store, repo_root, COMMIT, boundary, max_executions=1)

    assert report.attempted == 1
    assert report.budget_exhausted is True


def test_zero_wall_clock_budget_attempts_nothing(
    write_file: Callable[[str, str], Path], repo_root: Path, store: VBGStore
) -> None:
    _build_repo(write_file, repo_root, store, _THREE_INDEPENDENT_FUNCS)
    boundary = FakeExecutionBoundary()

    report = explore(store, repo_root, COMMIT, boundary, max_wall_clock_seconds=0.0)

    assert report.attempted == 0
    assert report.budget_exhausted is True


def test_higher_centrality_target_is_attempted_first(
    write_file: Callable[[str, str], Path], repo_root: Path, store: VBGStore
) -> None:
    _build_repo(write_file, repo_root, store, _CALL_CHAIN)
    boundary = FakeExecutionBoundary()

    explore(store, repo_root, COMMIT, boundary)

    # `mid` has both an incoming CALLS edge (from root) and an outgoing one
    # (to leaf) -- strictly higher degree than `root` (outgoing only) or
    # `leaf` (incoming only) -- so it must be attempted first.
    assert boundary.executed_order[0] == "mod.mid"


def test_explore_at_ingest_tier1_explores_everything(
    write_file: Callable[[str, str], Path], repo_root: Path, store: VBGStore
) -> None:
    _build_repo(write_file, repo_root, store, _THREE_INDEPENDENT_FUNCS)
    boundary = FakeExecutionBoundary()

    report = explore_at_ingest(store, repo_root, COMMIT, boundary, file_count=3)

    assert report.tier is ExplorationTier.TIER_1
    assert report.attempted == 3


def test_explore_at_ingest_tier3_performs_no_eager_execution(
    write_file: Callable[[str, str], Path], repo_root: Path, store: VBGStore
) -> None:
    _build_repo(write_file, repo_root, store, _THREE_INDEPENDENT_FUNCS)
    boundary = FakeExecutionBoundary()

    report = explore_at_ingest(store, repo_root, COMMIT, boundary, file_count=501)

    assert report.tier is ExplorationTier.TIER_3
    assert report.attempted == 0
    assert report.candidates_considered == 0
    assert boundary.executed_order == []


def test_explore_at_ingest_tier2_restricts_to_top_n_centrality(
    write_file: Callable[[str, str], Path], repo_root: Path, store: VBGStore, monkeypatch
) -> None:
    monkeypatch.setattr(engine_module, "_TIER_2_TOP_N", 2)
    _build_repo(write_file, repo_root, store, _CALL_CHAIN)
    boundary = FakeExecutionBoundary()

    report = explore_at_ingest(store, repo_root, COMMIT, boundary, file_count=100)

    assert report.tier is ExplorationTier.TIER_2
    assert report.candidates_considered == 2
    # `mid` (degree 2) always makes the cut; `leaf` and `root` tie at
    # degree 1, so the entity_id-sorted tie-break deterministically picks
    # `leaf` ("mod.leaf" < "mod.root") for the second slot.
    assert set(boundary.executed_order) == {"mod.mid", "mod.leaf"}


def test_explore_neighborhood_follows_calls_edges_only(
    write_file: Callable[[str, str], Path], repo_root: Path, store: VBGStore
) -> None:
    write_file(
        "mod.py",
        "class Cls:\n    pass\n\n\n"
        "def leaf():\n    return 0\n\n\n"
        "def mid():\n    return leaf() + 1\n\n\n"
        "def root():\n    return mid() + 1\n",
    )
    extraction = extract_repository(repo_root, COMMIT)
    persist_extraction(store, extraction)
    boundary = FakeExecutionBoundary()

    report = explore_neighborhood(store, repo_root, COMMIT, boundary, "mod.root", max_depth=2)

    assert report.candidates_considered == 3  # root, mid, leaf
    assert set(boundary.executed_order) == {"mod.root", "mod.mid", "mod.leaf"}
    assert "mod.Cls" not in boundary.executed_order  # CONTAINS, not CALLS -- not part of this graph


def test_explore_neighborhood_respects_max_depth(
    write_file: Callable[[str, str], Path], repo_root: Path, store: VBGStore
) -> None:
    _build_repo(write_file, repo_root, store, _CALL_CHAIN)
    boundary = FakeExecutionBoundary()

    report = explore_neighborhood(store, repo_root, COMMIT, boundary, "mod.root", max_depth=1)

    assert report.candidates_considered == 2  # root, mid -- leaf is depth 2
    assert "mod.leaf" not in boundary.executed_order


def test_explore_neighborhood_default_budget_matches_tier3_query_cap() -> None:
    from veyra.exploration.engine import _TIER_3_QUERY_MAX_EXECUTIONS, _TIER_3_QUERY_WALL_CLOCK_SECONDS
    import inspect

    sig = inspect.signature(explore_neighborhood)
    assert sig.parameters["max_executions"].default == _TIER_3_QUERY_MAX_EXECUTIONS
    assert sig.parameters["max_wall_clock_seconds"].default == _TIER_3_QUERY_WALL_CLOCK_SECONDS
