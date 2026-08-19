"""
Phase 3.2 real Docker backend / security tests (spec items 2-9: Docker
backend, network isolation, filesystem isolation, resource limits, timeout,
cleanup). Every test here spins up a real disposable container -- nothing
is mocked, per the explicit instruction not to fake Docker behavior with
string-matching. Skipped automatically when Docker isn't available
(`requires_docker`), never weakened.
"""

from __future__ import annotations

import time
from pathlib import Path

import pytest

from veyra.execution import DockerExecutionBoundary, ExecutionRequest, ExecutionStatus

from conftest import TEST_IMAGE, container_exists, docker_inspect, requires_docker

pytestmark = requires_docker


def _req(**overrides) -> ExecutionRequest:
    defaults = dict(target="test", command=("python3", "-c", "print('ok')"), image=TEST_IMAGE, timeout_seconds=15)
    defaults.update(overrides)
    return ExecutionRequest(**defaults)


# -- Docker backend basics ---------------------------------------------------


def test_successful_execution(boundary: DockerExecutionBoundary) -> None:
    handle = boundary.execute(_req(command=("python3", "-c", "print('hello')")))
    try:
        outcome = boundary.collect_result(handle)
        assert outcome.status is ExecutionStatus.COMPLETED
        assert outcome.exit_code == 0
        assert "hello" in outcome.stdout
    finally:
        boundary.cleanup(handle)


def test_nonzero_exit_is_reported_not_raised(boundary: DockerExecutionBoundary) -> None:
    handle = boundary.execute(_req(command=("python3", "-c", "import sys; sys.exit(7)")))
    try:
        outcome = boundary.collect_result(handle)
        assert outcome.status is ExecutionStatus.COMPLETED  # the boundary ran fine; the TARGET failed
        assert outcome.exit_code == 7
    finally:
        boundary.cleanup(handle)


def test_stderr_is_captured(boundary: DockerExecutionBoundary) -> None:
    handle = boundary.execute(_req(command=("python3", "-c", "import sys; sys.stderr.write('boom')")))
    try:
        outcome = boundary.collect_result(handle)
        assert "boom" in outcome.stderr
    finally:
        boundary.cleanup(handle)


# -- Non-privileged execution -------------------------------------------------


def test_container_runs_as_non_root_user(boundary: DockerExecutionBoundary) -> None:
    handle = boundary.execute(_req(command=("id", "-u")))
    try:
        outcome = boundary.collect_result(handle)
        assert outcome.stdout.strip() == "65534"  # never root (0)
    finally:
        boundary.cleanup(handle)


def test_container_is_not_privileged(boundary: DockerExecutionBoundary) -> None:
    handle = boundary.execute(_req())
    try:
        boundary.collect_result(handle)
        config = docker_inspect(handle.handle_id)["HostConfig"]
        assert config["Privileged"] is False
        assert config.get("CapDrop") == ["ALL"]
    finally:
        boundary.cleanup(handle)


# -- Network isolation ---------------------------------------------------


def test_network_disabled_by_default(boundary: DockerExecutionBoundary) -> None:
    handle = boundary.execute(
        _req(command=("python3", "-c", "import socket; socket.create_connection(('8.8.8.8', 53), timeout=3)"))
    )
    try:
        outcome = boundary.collect_result(handle)
        assert outcome.exit_code != 0  # network access must fail
    finally:
        boundary.cleanup(handle)


def test_network_mode_is_none_in_container_config(boundary: DockerExecutionBoundary) -> None:
    handle = boundary.execute(_req())
    try:
        boundary.collect_result(handle)
        config = docker_inspect(handle.handle_id)["HostConfig"]
        assert config["NetworkMode"] == "none"
    finally:
        boundary.cleanup(handle)


# -- Filesystem isolation -----------------------------------------------


def test_root_filesystem_is_read_only(boundary: DockerExecutionBoundary) -> None:
    handle = boundary.execute(_req(command=("python3", "-c", "open('/etc/should_not_write', 'w')")))
    try:
        outcome = boundary.collect_result(handle)
        assert outcome.exit_code != 0  # writing outside /tmp must fail
    finally:
        boundary.cleanup(handle)


def test_tmp_is_writable_scratch_space(boundary: DockerExecutionBoundary) -> None:
    handle = boundary.execute(
        _req(command=("python3", "-c", "open('/tmp/scratch', 'w').write('ok'); print('wrote-ok')"))
    )
    try:
        outcome = boundary.collect_result(handle)
        assert outcome.exit_code == 0
        assert "wrote-ok" in outcome.stdout
    finally:
        boundary.cleanup(handle)


def test_working_directory_is_mounted_read_only(boundary: DockerExecutionBoundary, tmp_path: Path) -> None:
    (tmp_path / "input.txt").write_text("repository content")
    handle = boundary.execute(
        _req(
            command=("python3", "-c", "print(open('/workspace/input.txt').read()); open('/workspace/new.txt','w')"),
            working_directory=tmp_path,
        )
    )
    try:
        outcome = boundary.collect_result(handle)
        assert "repository content" in outcome.stdout
        assert outcome.exit_code != 0  # the write attempt into the ro mount must fail
    finally:
        boundary.cleanup(handle)


def test_output_directory_is_mounted_read_write(boundary: DockerExecutionBoundary, tmp_path: Path) -> None:
    output_dir = tmp_path / "out"
    output_dir.mkdir()
    handle = boundary.execute(
        _req(
            command=("python3", "-c", "open('/output/result.txt', 'w').write('done')"),
            output_directory=output_dir,
        )
    )
    try:
        outcome = boundary.collect_result(handle)
        assert outcome.exit_code == 0
        assert (output_dir / "result.txt").read_text() == "done"
    finally:
        boundary.cleanup(handle)


# -- Resource limits -----------------------------------------------------


def test_memory_limit_is_enforced(boundary: DockerExecutionBoundary) -> None:
    handle = boundary.execute(
        _req(
            command=("python3", "-c", "bytearray(400 * 1024 * 1024)"),  # allocate 400MB
            memory_limit_mb=64,
        )
    )
    try:
        outcome = boundary.collect_result(handle)
        assert outcome.exit_code != 0  # OOM-killed, must not silently succeed
    finally:
        boundary.cleanup(handle)


def test_cpu_limit_is_applied_to_container_config(boundary: DockerExecutionBoundary) -> None:
    handle = boundary.execute(_req(cpu_limit=0.5))
    try:
        boundary.collect_result(handle)
        config = docker_inspect(handle.handle_id)["HostConfig"]
        assert config["NanoCpus"] == int(0.5 * 1_000_000_000)
    finally:
        boundary.cleanup(handle)


def test_pids_limit_is_applied_to_container_config(boundary: DockerExecutionBoundary) -> None:
    handle = boundary.execute(_req(pids_limit=32))
    try:
        boundary.collect_result(handle)
        config = docker_inspect(handle.handle_id)["HostConfig"]
        assert config["PidsLimit"] == 32
    finally:
        boundary.cleanup(handle)


# -- Timeout ---------------------------------------------------------------


def test_timeout_is_enforced_and_container_is_terminated(boundary: DockerExecutionBoundary) -> None:
    handle = boundary.execute(_req(command=("sleep", "30")))
    start = time.time()
    outcome = boundary.collect_result(handle, timeout_seconds=2)
    elapsed = time.time() - start

    try:
        assert outcome.status is ExecutionStatus.TIMED_OUT
        assert elapsed < 10  # nowhere near the full 30s sleep
        inspected = docker_inspect(handle.handle_id)
        assert inspected["State"]["Running"] is False  # actually terminated, not just abandoned
    finally:
        boundary.cleanup(handle)


# -- Cleanup -----------------------------------------------------------------


def test_cleanup_removes_the_container(boundary: DockerExecutionBoundary) -> None:
    handle = boundary.execute(_req())
    boundary.collect_result(handle)
    assert container_exists(handle.handle_id)

    boundary.cleanup(handle)

    assert not container_exists(handle.handle_id)


def test_cleanup_occurs_after_timeout(boundary: DockerExecutionBoundary) -> None:
    handle = boundary.execute(_req(command=("sleep", "30")))
    boundary.collect_result(handle, timeout_seconds=2)

    boundary.cleanup(handle)

    assert not container_exists(handle.handle_id)


def test_terminate_then_cleanup_does_not_error(boundary: DockerExecutionBoundary) -> None:
    handle = boundary.execute(_req(command=("sleep", "30")))
    boundary.terminate(handle)
    boundary.cleanup(handle)  # must not raise even though terminate already stopped it
    assert not container_exists(handle.handle_id)


# -- Environment / credential isolation --------------------------------------


def test_host_environment_is_not_inherited(boundary: DockerExecutionBoundary, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HOST_SECRET_TOKEN", "should-never-appear-in-container")
    handle = boundary.execute(
        _req(command=("python3", "-c", "import os; print(os.environ.get('HOST_SECRET_TOKEN', 'MISSING'))"))
    )
    try:
        outcome = boundary.collect_result(handle)
        assert outcome.stdout.strip() == "MISSING"
    finally:
        boundary.cleanup(handle)


def test_only_explicitly_passed_environment_variables_are_visible(boundary: DockerExecutionBoundary) -> None:
    handle = boundary.execute(
        _req(
            command=("python3", "-c", "import os; print(os.environ.get('EXPLICIT_VAR', 'MISSING'))"),
            environment={"EXPLICIT_VAR": "explicit-value"},
        )
    )
    try:
        outcome = boundary.collect_result(handle)
        assert outcome.stdout.strip() == "explicit-value"
    finally:
        boundary.cleanup(handle)


# -- Execution environment is captured as provenance -------------------------


def test_execution_environment_is_captured(boundary: DockerExecutionBoundary) -> None:
    handle = boundary.execute(_req(memory_limit_mb=128, cpu_limit=0.5, timeout_seconds=10))
    try:
        outcome = boundary.collect_result(handle)
        assert outcome.environment.backend == "docker"
        assert outcome.environment.image == TEST_IMAGE
        assert outcome.environment.memory_limit_mb == 128
        assert outcome.environment.cpu_limit == 0.5
        assert outcome.environment.network_enabled is False
        assert outcome.environment.non_privileged is True
        assert outcome.environment.read_only_filesystem is True
    finally:
        boundary.cleanup(handle)
