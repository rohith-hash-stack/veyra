"""Writes an ExtractionResult into the canonical VBGStore. Kept separate from
python_extractor.py so extraction itself has no storage dependency and can be
tested (and reused by a future non-Python extractor) without a database."""

from __future__ import annotations

from veyra.vbg import VBGStore

from .python_extractor import ExtractionResult


def persist_extraction(store: VBGStore, result: ExtractionResult) -> None:
    for node in result.nodes:
        store.insert_node(node)
    for edge in result.edges:
        store.insert_edge(edge)
