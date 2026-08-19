"""
Phase 3.2 storage tests for ExecutionEnvironment -- "container configuration
is auditable." No Docker required.
"""

from __future__ import annotations

from veyra.vbg import ExecutionEnvironment, VBGStore


def _env(environment_id: str = "env1") -> ExecutionEnvironment:
    return ExecutionEnvironment(
        environment_id=environment_id,
        backend="docker",
        image="python:3.11-alpine",
        network_enabled=False,
        memory_limit_mb=256,
        cpu_limit=1.0,
        timeout_seconds=30.0,
        non_privileged=True,
        read_only_filesystem=True,
    )


def test_insert_and_retrieve_execution_environment(store: VBGStore) -> None:
    store.insert_execution_environment(_env())

    latest = store.get_latest_execution_environment("env1")

    assert latest is not None
    assert latest.backend == "docker"
    assert latest.network_enabled is False


def test_execution_environment_history_preserved(store: VBGStore) -> None:
    store.insert_execution_environment(_env())
    store.insert_execution_environment(_env())  # re-recording the same config is a legitimate repeat

    history = store.get_execution_environment_history("env1")

    assert len(history) == 2


def test_unknown_environment_id_returns_none(store: VBGStore) -> None:
    assert store.get_latest_execution_environment("nonexistent") is None
    assert store.get_execution_environment_history("nonexistent") == []


def test_store_exposes_no_update_or_delete_for_execution_environments(store: VBGStore) -> None:
    assert not hasattr(store, "update_execution_environment")
    assert not hasattr(store, "delete_execution_environment")


def test_invalid_execution_environment_rejected() -> None:
    import pytest

    with pytest.raises(ValueError):
        ExecutionEnvironment(
            environment_id="e", backend="docker", image="x", network_enabled=False,
            memory_limit_mb=0, cpu_limit=1.0, timeout_seconds=30.0,
            non_privileged=True, read_only_filesystem=True,
        )
