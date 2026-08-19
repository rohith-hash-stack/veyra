from __future__ import annotations

import json
import subprocess

import pytest

from veyra.execution import DockerExecutionBoundary

TEST_IMAGE = "python:3.11-alpine"


def _docker_available() -> bool:
    try:
        result = subprocess.run(["docker", "version"], capture_output=True, timeout=5)
        return result.returncode == 0
    except (FileNotFoundError, OSError, subprocess.TimeoutExpired):
        return False


DOCKER_AVAILABLE = _docker_available()

requires_docker = pytest.mark.skipif(
    not DOCKER_AVAILABLE,
    reason="Docker is not available in this environment -- see PLAN.md D16/D17",
)


@pytest.fixture
def boundary() -> DockerExecutionBoundary:
    return DockerExecutionBoundary()


def docker_inspect(container_id: str) -> dict:
    result = subprocess.run(["docker", "inspect", container_id], capture_output=True, text=True, timeout=15)
    return json.loads(result.stdout)[0]


def container_exists(container_id: str) -> bool:
    result = subprocess.run(["docker", "inspect", container_id], capture_output=True, timeout=15)
    return result.returncode == 0
