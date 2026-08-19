"""
Phase 3.3a real end-to-end proof: DockerExecutionBoundary (Phase 3.2, real
containers) actually executing the stdlib-only runner script against a real
on-disk repository, with genuine PASS/FAIL/ERROR outcomes coming back from
inside the sandbox and landing as real TEST evidence in VBGStore. No part of
this file mocks Docker or string-matches a command -- it is the same kind of
proof PROGRESS.md's Phase 3.2 entry describes for the boundary itself.
"""

from __future__ import annotations

from pathlib import Path
from typing import Callable

from veyra.execution import DockerExecutionBoundary
from veyra.harness import TestStatus, run_existing_test_harness
from veyra.vbg import EvidenceType, Node, VBGStore

from conftest import requires_docker

COMMIT = "commit1"

_TEST_SOURCE = (
    "import unittest\n\n"
    "def test_pass():\n"
    "    assert 1 + 1 == 2\n\n"
    "def test_fail():\n"
    "    assert 1 + 1 == 3\n\n"
    "def test_error():\n"
    "    raise ValueError('boom')\n\n"
    "class TestSuite(unittest.TestCase):\n"
    "    def test_class_pass(self):\n"
    "        self.assertEqual(2 + 2, 4)\n"
)


def _persist_node(store: VBGStore, entity_id: str) -> None:
    store.insert_node(
        Node(
            entity_id=entity_id, type="Function", name=entity_id.rsplit(".", 1)[-1],
            repository_version=COMMIT, language="Python", lexical_representation=_TEST_SOURCE,
        )
    )


@requires_docker
def test_real_docker_harness_run_reports_genuine_pass_fail_error(
    write_file: Callable[[str, str], Path], repo_root: Path, store: VBGStore
) -> None:
    write_file("test_suite.py", _TEST_SOURCE)
    for entity_id in (
        "test_suite.test_pass",
        "test_suite.test_fail",
        "test_suite.test_error",
        "test_suite.TestSuite.test_class_pass",
    ):
        _persist_node(store, entity_id)

    boundary = DockerExecutionBoundary()
    report = run_existing_test_harness(store, repo_root, COMMIT, boundary)

    outcomes = {o.entity_id: o for o in report.outcomes}
    assert outcomes["test_suite.test_pass"].status is TestStatus.PASS
    assert outcomes["test_suite.test_fail"].status is TestStatus.FAIL
    assert outcomes["test_suite.test_error"].status is TestStatus.ERROR
    assert outcomes["test_suite.TestSuite.test_class_pass"].status is TestStatus.PASS

    pass_evidence = store.get_evidence_for_subject("test_suite.test_pass", COMMIT)
    assert len(pass_evidence) == 1
    assert pass_evidence[0].evidence_type is EvidenceType.TEST

    fail_evidence = store.get_evidence_for_subject("test_suite.test_fail", COMMIT)
    assert "FAIL" in fail_evidence[0].detail


@requires_docker
def test_real_docker_harness_run_has_no_network_access(
    write_file: Callable[[str, str], Path], repo_root: Path, store: VBGStore
) -> None:
    source = (
        "import urllib.request\n\n"
        "def test_network():\n"
        "    urllib.request.urlopen('http://example.com', timeout=2)\n"
    )
    write_file("test_net.py", source)
    store.insert_node(
        Node(
            entity_id="test_net.test_network", type="Function", name="test_network",
            repository_version=COMMIT, language="Python", lexical_representation=source,
        )
    )

    boundary = DockerExecutionBoundary()
    report = run_existing_test_harness(store, repo_root, COMMIT, boundary)

    outcome = report.outcomes[0]
    # urllib.request is not in the capability table's recognized network
    # patterns (only requests/httpx are), so this reaches ERROR from a real
    # network failure inside the sandbox rather than being BLOCKED/MOCKABLE
    # by the safety gate -- proving the boundary's `--network none` (Phase
    # 3.2) is what actually stopped it, not classification.
    assert outcome.status is TestStatus.ERROR
