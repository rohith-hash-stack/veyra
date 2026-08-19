"""
Phase 3.5 real end-to-end proof: DockerExecutionBoundary (Phase 3.2, real
containers) actually invoking a target function inside the sandbox with
sys.settrace active, and genuine observed events -- including a real
external_interaction event when the traced code reaches outside
/workspace -- landing as real RUNTIME evidence in VBGStore.
"""

from __future__ import annotations

from pathlib import Path
from typing import Callable

from conftest import requires_docker

from veyra.execution import DockerExecutionBoundary
from veyra.runtime import run_scenario
from veyra.safety import classify_and_audit
from veyra.scenarios import generate_scenarios
from veyra.static_analysis import extract_repository, persist_extraction
from veyra.vbg import EvidenceType, VBGStore

COMMIT = "commit1"


@requires_docker
def test_real_docker_run_traces_a_nested_call(
    write_file: Callable[[str, str], Path], repo_root: Path, store: VBGStore
) -> None:
    write_file(
        "mod.py",
        "def helper():\n    return 41\n\n\ndef foo():\n    return helper() + 1\n",
    )
    extraction = extract_repository(repo_root, COMMIT)
    persist_extraction(store, extraction)

    scenarios = generate_scenarios(store, COMMIT)
    scenario = next(s for s in scenarios if s.target_entity_id == "mod.foo")
    assert scenario.executable is True

    boundary = DockerExecutionBoundary()
    outcome = run_scenario(store, repo_root, COMMIT, scenario, boundary)

    assert outcome.status == "COMPLETED"
    assert outcome.return_repr == "42"

    target_evidence = store.get_evidence_for_subject("mod.foo", COMMIT)
    assert len(target_evidence) == 1
    assert target_evidence[0].evidence_type is EvidenceType.RUNTIME

    helper_evidence = store.get_evidence_for_subject("mod.helper", COMMIT)
    assert len(helper_evidence) == 1

    edge_evidence = store.get_evidence_for_subject("mod.foo--CALLS-->mod.helper", COMMIT)
    assert len(edge_evidence) == 1


@requires_docker
def test_real_docker_run_captures_exception(
    write_file: Callable[[str, str], Path], repo_root: Path, store: VBGStore
) -> None:
    write_file("mod.py", "def foo():\n    raise ValueError('boom')\n")
    extraction = extract_repository(repo_root, COMMIT)
    persist_extraction(store, extraction)

    scenario = next(s for s in generate_scenarios(store, COMMIT) if s.target_entity_id == "mod.foo")
    boundary = DockerExecutionBoundary()
    outcome = run_scenario(store, repo_root, COMMIT, scenario, boundary)

    assert outcome.status == "EXCEPTION"
    assert outcome.exception_type == "ValueError"
    evidence = store.get_evidence_for_subject("mod.foo", COMMIT)
    assert "ValueError" in evidence[0].detail


@requires_docker
def test_real_docker_run_observes_external_interaction_not_network_access(
    write_file: Callable[[str, str], Path], repo_root: Path, store: VBGStore
) -> None:
    # urllib is stdlib, outside /workspace -- the tracer should observe one
    # external_interaction event and then genuinely fail the network call
    # (real --network none from Phase 3.2, unmodified) rather than hang.
    write_file(
        "mod.py",
        "import urllib.request\n\ndef foo():\n    urllib.request.urlopen('http://example.com', timeout=2)\n",
    )
    extraction = extract_repository(repo_root, COMMIT)
    persist_extraction(store, extraction)

    scenario = next(s for s in generate_scenarios(store, COMMIT) if s.target_entity_id == "mod.foo")
    boundary = DockerExecutionBoundary()
    outcome = run_scenario(store, repo_root, COMMIT, scenario, boundary)

    assert outcome.status == "EXCEPTION"
    assert any(e.kind == "external_interaction" for e in outcome.events)
