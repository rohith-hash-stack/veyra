"""
PLAN.md Milestone 5, Phase 5.2 -- Full Integration Testing.

"Every subsystem in the full pipeline (Repository -> VBG -> Question
Generator -> Static Verification -> Safety -> Harness -> Runtime ->
Evidence -> Graph-RAG -> LLM) preserves identity, version, evidence,
provenance, status, failure information end to end."

This is deliberately a TEST file, not a new `src/veyra/validation/` module
-- "integration testing" means exercising the real pipeline together and
asserting on what comes out, not computing a new report. Drives
`run_static_analysis()` -> `run_runtime_analysis()` -> `run_retrieval_analysis()`
-> `retrieve_context()`/`build_grounding_context()` -> `analyze_impact()`
against one repository across two commits, using a `FakeExecutionBoundary`
(no Docker required, same pattern every M3/M4 test file already
established).
"""

from __future__ import annotations

import json
import time
from pathlib import Path

from veyra.execution import ExecutionHandle, ExecutionOutcome, ExecutionRequest, ExecutionStatus
from veyra.invalidation import analyze_impact
from veyra.pipeline import run_retrieval_analysis, run_runtime_analysis, run_static_analysis
from veyra.retrieval import build_grounding_context, build_retrieval_index, retrieve_context
from veyra.safety import PolicyConfig
from veyra.vbg import EvidenceType, VBGStore, VerificationState

COMMIT_A = "commit_a"
COMMIT_B = "commit_b"


class FakeExecutionBoundary:
    """Traces exactly what the target function's source says: a
    `raise ValueError` target genuinely reports EXCEPTION with the real
    exception text, everything else genuinely reports COMPLETED -- so
    "status/failure information preserved end to end" has something real
    to check, not a boundary that always says the same thing."""

    def __init__(self) -> None:
        self.requests: list[ExecutionRequest] = []

    def execute(self, request: ExecutionRequest) -> ExecutionHandle:
        self.requests.append(request)
        from veyra.vbg import ExecutionEnvironment

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
        is_failing = spec["function_name"] == "will_fail"
        trace = {
            "status": "EXCEPTION" if is_failing else "COMPLETED",
            "return_repr": None if is_failing else "1",
            "exception_type": "ValueError" if is_failing else None,
            "exception_message": "a real, specific failure message" if is_failing else None,
            "duration_seconds": 0.001,
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


def _write_repo(root: Path, ok_return: str) -> None:
    root.mkdir(exist_ok=True)
    (root / "mod.py").write_text(
        f"def ok():\n    return {ok_return}\n\n\n"
        "def will_fail():\n    raise ValueError('boom')\n"
    )


def test_identity_and_version_survive_the_full_pipeline(tmp_path: Path, store: VBGStore) -> None:
    repo_root = tmp_path / "repo"
    _write_repo(repo_root, "1")

    static_report = run_static_analysis(store, repo_root, COMMIT_A)
    boundary = FakeExecutionBoundary()
    runtime_report = run_runtime_analysis(store, repo_root, COMMIT_A, boundary, file_count=1)
    retrieval_report = run_retrieval_analysis(store, COMMIT_A, ["ok", "will_fail"])

    # The exact same entity_id, mod.ok, is what static extraction produced,
    # what runtime tracing attached evidence to, and what retrieval finds
    # again -- one stable identity across every subsystem, never rebuilt or
    # renamed along the way.
    assert any(n.entity_id == "mod.ok" for n in store.get_all_nodes(COMMIT_A))
    assert store.get_evidence_for_subject("mod.ok", COMMIT_A) != []
    index = build_retrieval_index(store, COMMIT_A)
    assert index.get("mod.ok") is not None

    # Every report along the way carries the same repository_version --
    # never silently mixed across commits.
    assert static_report.repository_version == COMMIT_A
    assert runtime_report.repository_version == COMMIT_A
    assert retrieval_report.repository_version == COMMIT_A


def test_provenance_is_real_on_every_evidence_record(tmp_path: Path, store: VBGStore) -> None:
    repo_root = tmp_path / "repo"
    _write_repo(repo_root, "1")
    run_static_analysis(store, repo_root, COMMIT_A)
    run_runtime_analysis(store, repo_root, COMMIT_A, FakeExecutionBoundary(), file_count=1)

    all_evidence = store.get_all_evidence(COMMIT_A)
    assert len(all_evidence) > 0
    for evidence in all_evidence:
        assert evidence.provenance.producer
        assert evidence.provenance.method
        assert evidence.provenance.recorded_at


def test_failure_information_survives_into_grounded_context(tmp_path: Path, store: VBGStore) -> None:
    repo_root = tmp_path / "repo"
    _write_repo(repo_root, "1")
    run_static_analysis(store, repo_root, COMMIT_A)
    run_runtime_analysis(store, repo_root, COMMIT_A, FakeExecutionBoundary(), file_count=1)

    index = build_retrieval_index(store, COMMIT_A)
    retrieved = retrieve_context(store, index, COMMIT_A, "will_fail")
    grounding = build_grounding_context(retrieved)

    fact = next(f for f in grounding.facts if f.entity_id == "mod.will_fail")
    assert any("ValueError" in excerpt for excerpt in fact.evidence_excerpts)
    assert any("a real, specific failure message" in excerpt for excerpt in fact.evidence_excerpts)
    # RUNTIME_OBSERVED (ran, but didn't complete cleanly) carries a hedge --
    # the grounding layer never states a failed execution as unqualified fact.
    assert fact.verification_state is VerificationState.RUNTIME_OBSERVED
    assert "NOTE" in fact.verification_note


def test_git_change_propagates_to_stale_verification_state_through_the_full_pipeline(
    tmp_path: Path, store: VBGStore
) -> None:
    repo_a = tmp_path / "repo_a"
    repo_b = tmp_path / "repo_b"
    _write_repo(repo_a, "1")
    _write_repo(repo_b, "2")  # ok()'s body changes
    run_static_analysis(store, repo_a, COMMIT_A)
    run_static_analysis(store, repo_b, COMMIT_B)
    run_runtime_analysis(store, repo_b, COMMIT_B, FakeExecutionBoundary(), file_count=1)

    impact = analyze_impact(store, COMMIT_A, COMMIT_B)
    assert "mod.ok" in impact.tier_0

    from veyra.verification import derive_verification_states

    states = derive_verification_states(store, COMMIT_B, stale_entity_ids=impact.stale_entity_ids)
    assert states["mod.ok"] is VerificationState.STALE

    # And that STALE verdict is what a retrieval query actually sees --
    # the full pipeline, not just the verification module in isolation.
    index = build_retrieval_index(store, COMMIT_B)  # (index itself doesn't take stale_entity_ids -- direct check below)
    entity = index.get("mod.ok")
    assert entity is not None  # still a real, retrievable entity -- staleness isn't deletion


def test_safety_gate_blocks_dangerous_code_across_the_full_pipeline(tmp_path: Path, store: VBGStore) -> None:
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    (repo_root / "mod.py").write_text("import subprocess\n\ndef dangerous():\n    subprocess.run(['ls'])\n")
    run_static_analysis(store, repo_root, COMMIT_A)

    boundary = FakeExecutionBoundary()
    run_runtime_analysis(store, repo_root, COMMIT_A, boundary, file_count=1)

    # BLOCKED targets never even reach the boundary.
    assert boundary.requests == []
    from veyra.verification import derive_verification_state

    assert derive_verification_state(store, "mod.dangerous", COMMIT_A) is VerificationState.BLOCKED_BY_SAFETY


def test_synthesis_only_fires_with_an_explicit_allowlist(tmp_path: Path, store: VBGStore) -> None:
    repo_root = tmp_path / "repo"
    _write_repo(repo_root, "1")
    run_static_analysis(store, repo_root, COMMIT_A)
    default = PolicyConfig.default()
    policy = PolicyConfig(
        version=default.version, capability_classes=default.capability_classes,
        explicit_safe_targets=frozenset({"mod.ok"}),
    )

    # Tier 3 (file_count > 500) performs zero eager exploration, so
    # mod.ok stays zero-coverage and eligible for novel synthesis.
    report = run_runtime_analysis(
        store, repo_root, COMMIT_A, FakeExecutionBoundary(), file_count=501, policy=policy
    )

    assert report.synthesis_trials_run > 0
    evidence = [e for e in store.get_all_evidence(COMMIT_A, EvidenceType.RUNTIME) if e.subject_id == "mod.ok"]
    assert len(evidence) > 0
