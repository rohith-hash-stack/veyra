"""Mirrors veyra.static_analysis.persist / veyra.questions.persist:
generate_scenarios() returns plain in-memory Scenario objects; persisting
them is an explicit, separate step."""

from __future__ import annotations

from veyra.vbg import Scenario, VBGStore


def persist_scenarios(store: VBGStore, scenarios: list[Scenario]) -> None:
    for scenario in scenarios:
        store.insert_scenario(scenario)
