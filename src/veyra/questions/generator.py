"""
PLAN.md Milestone 2, Phase 2.5 -- Deterministic Question Generator.

No LLM involved: every question is produced by a fixed template applied to
real VBG structure (nodes + edges as of one commit), fetched via
VBGStore.get_all_nodes()/get_all_edges() (the "current view" -- latest row
per entity, consistent with every other bulk read in this project).

Template coverage, one per (category, direction):
    SYMBOL        "What kind of symbol is `X`?"              -- every node
    STRUCTURAL    "What does `X` contain?"                    -- Module/Class/Function/Method nodes
    LEXICAL       "What is the exact source text of `X`?"     -- nodes with a lexical_representation
    RELATIONSHIP  "What does `X` import?"                     -- nodes with outgoing IMPORTS
    DEPENDENCY    "Which modules import `X`?"                 -- nodes with incoming IMPORTS
    CALL_FLOW     "What does `X` call?" / "Who calls `X`?"     -- outgoing/incoming CALLS
    INHERITANCE   "What does `X` inherit from?" /
                  "What inherits from `X`?"                    -- outgoing/incoming INHERITS
    REFERENCE     "What references `X`?"                       -- incoming REFERENCES
    NEIGHBORHOOD  "What are the neighboring nodes of `X`?"     -- any incoming or outgoing edge

Every template is guarded by "is there at least one real edge/attribute to
ask about" -- a node with zero outgoing CALLS never gets a "what does X
call?" question fabricated. That is what satisfies "unsupported constructs
do not generate false questions" here.

OCCURRENCE is intentionally NOT generated in this slice: Node.occurrence_count
is never populated by the Phase 2.1 extractor (a previously-documented gap),
so every OCCURRENCE question would currently have the same trivial "0"
answer for every node -- generating a real-looking question with a
structurally meaningless answer would be worse than not generating it.
Revisit once occurrence tracking actually exists.

Determinism + dedup: each (category, template_key, primary_entity_id) is
emitted at most once, and nodes are processed in sorted entity_id order --
running this twice against the same commit produces byte-identical output.
question_id is a stable hash of that same key plus the repository_version,
so a question's identity survives being regenerated later, e.g. after a
git-triggered reverification.
"""

from __future__ import annotations

import hashlib
from collections import defaultdict

from veyra.vbg import Edge, Question, QuestionCategory, RelationshipType, VBGStore

_CONTAINER_TYPES = ("Module", "Class", "Function", "Method")


def _question_id(category: QuestionCategory, template_key: str, primary_id: str, repository_version: str) -> str:
    raw = f"{category.value}|{template_key}|{primary_id}|{repository_version}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


def generate_questions(store: VBGStore, repository_version: str) -> list[Question]:
    nodes = store.get_all_nodes(repository_version)
    edges = store.get_all_edges(repository_version)

    outgoing: dict[str, list[Edge]] = defaultdict(list)
    incoming: dict[str, list[Edge]] = defaultdict(list)
    for edge in edges:
        outgoing[edge.source_id].append(edge)
        incoming[edge.target_id].append(edge)

    seen: set[tuple[str, str, str]] = set()
    questions: list[Question] = []

    def emit(category: QuestionCategory, template_key: str, primary_id: str, entity_ids: list[str], text: str, provenance: str) -> None:
        key = (category.value, template_key, primary_id)
        if key in seen:
            return
        seen.add(key)
        questions.append(
            Question(
                question_id=_question_id(category, template_key, primary_id, repository_version),
                category=category,
                template_key=template_key,
                text=text,
                entity_ids=tuple(entity_ids),
                repository_version=repository_version,
                provenance=provenance,
            )
        )

    for node in sorted(nodes, key=lambda n: n.entity_id):
        eid = node.entity_id
        name = node.name
        out_edges = outgoing.get(eid, [])
        in_edges = incoming.get(eid, [])

        emit(
            QuestionCategory.SYMBOL, "kind_of_symbol", eid, [eid],
            f"What kind of symbol is `{name}`?", f"type of node {eid}",
        )

        if node.type in _CONTAINER_TYPES:
            children = [e.target_id for e in out_edges if e.relationship_type is RelationshipType.CONTAINS]
            if children:
                emit(
                    QuestionCategory.STRUCTURAL, "contains", eid, [eid, *children],
                    f"What does `{name}` contain?", f"CONTAINS edges from {eid}",
                )

        if node.lexical_representation:
            emit(
                QuestionCategory.LEXICAL, "source_text", eid, [eid],
                f"What is the exact source text of `{name}`?", f"lexical_representation of {eid}",
            )

        imports_out = [e.target_id for e in out_edges if e.relationship_type is RelationshipType.IMPORTS]
        if imports_out:
            emit(
                QuestionCategory.RELATIONSHIP, "imports", eid, [eid, *imports_out],
                f"What does `{name}` import?", f"IMPORTS edges from {eid}",
            )

        imports_in = [e.source_id for e in in_edges if e.relationship_type is RelationshipType.IMPORTS]
        if imports_in:
            emit(
                QuestionCategory.DEPENDENCY, "imported_by", eid, [eid, *imports_in],
                f"Which modules import `{name}`?", f"IMPORTS edges into {eid}",
            )

        calls_out = [e.target_id for e in out_edges if e.relationship_type is RelationshipType.CALLS]
        if calls_out:
            emit(
                QuestionCategory.CALL_FLOW, "calls_from", eid, [eid, *calls_out],
                f"What does `{name}` call?", f"CALLS edges from {eid}",
            )

        calls_in = [e.source_id for e in in_edges if e.relationship_type is RelationshipType.CALLS]
        if calls_in:
            emit(
                QuestionCategory.CALL_FLOW, "calls_to", eid, [eid, *calls_in],
                f"Who calls `{name}`?", f"CALLS edges into {eid}",
            )

        inherits_out = [e.target_id for e in out_edges if e.relationship_type is RelationshipType.INHERITS]
        if inherits_out:
            emit(
                QuestionCategory.INHERITANCE, "inherits_from", eid, [eid, *inherits_out],
                f"What does `{name}` inherit from?", f"INHERITS edges from {eid}",
            )

        inherits_in = [e.source_id for e in in_edges if e.relationship_type is RelationshipType.INHERITS]
        if inherits_in:
            emit(
                QuestionCategory.INHERITANCE, "inherited_by", eid, [eid, *inherits_in],
                f"What inherits from `{name}`?", f"INHERITS edges into {eid}",
            )

        references_in = [e.source_id for e in in_edges if e.relationship_type is RelationshipType.REFERENCES]
        if references_in:
            emit(
                QuestionCategory.REFERENCE, "referenced_by", eid, [eid, *references_in],
                f"What references `{name}`?", f"REFERENCES edges into {eid}",
            )

        all_neighbors = sorted({e.target_id for e in out_edges} | {e.source_id for e in in_edges})
        if all_neighbors:
            emit(
                QuestionCategory.NEIGHBORHOOD, "neighbors", eid, [eid, *all_neighbors],
                f"What are the neighboring nodes of `{name}`?", f"incoming and outgoing edges of {eid}",
            )

    return questions
