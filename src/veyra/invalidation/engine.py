"""
PLAN.md Milestone 4, Phase 4.8 -- Git Impact Analysis & Invalidation.

```
Git change -> Changed symbols -> Impact analysis -> Tier 0 -> Tier 1 -> Tier 2 -> Tier 3 if required
```
- Tier 0: changed symbol/body.
- Tier 1: direct callers/callees/references/inheritance.
- Tier 2: questions/evidence directly dependent on affected nodes.
- Tier 3: wider behavioral dependencies.

**Consumes Phase 1.4/D4's `diff_symbols()` directly, per PLAN's own note** ("this phase now consumes the
symbol-level diff built in M1.4/M2, rather than building diffing from scratch here") -- `analyze_impact()`'s
entire Tier 0 is that function's `ADDED`/`REMOVED`/`MODIFIED_SIGNATURE`/`MODIFIED_BODY` output, unfiltered.
**"Unchanged signatures do not prove unchanged behavior" is therefore automatic, not a separate rule this
module has to enforce**: `MODIFIED_BODY` (a signature-preserving change) lands in Tier 0 exactly like
`MODIFIED_SIGNATURE` does -- `diff_symbols()` already classifies both as real changes, and nothing here
treats them differently.

Tier 1 walks CALLS/INHERITS/REFERENCES edges (not CONTAINS -- structural containment isn't a behavioral
dependency; not IMPORTS -- a module-level import doesn't by itself mean the imported symbol's *behavior*
matters to the importer) incoming and outgoing from every Tier 0 entity, in BOTH the old and new commit's
graphs (unioned) -- a REMOVED entity only exists in the old graph, an ADDED one only in the new, so checking
both is the only way to find its real neighbors either way.

Tier 2 is Questions (Phase 2.5) whose own `entity_ids` intersect Tier 0 | Tier 1, in either commit.

Tier 3 -- "wider behavioral dependencies" -- is deliberately scoped to what Phase 3.5's RUNTIME evidence
actually observed: targets of a RUNTIME-observed CALLS edge sourced from Tier 0 | Tier 1 in the new commit.
This is real behavioral reach static analysis alone (Tier 1) could miss entirely (dynamic dispatch, anything
the extractor's own documented resolution limits leave unresolved) -- it is not a broader static walk, which
would just be Tier 1 again at a different depth.

**"Changed evidence goes stale where appropriate" is implemented by feeding this report's
`stale_entity_ids` (Tier 0 | Tier 1 | Tier 3) into Phase 3.8's `derive_verification_states(...,
stale_entity_ids=...)`** -- STALE is computed on read, per D15's discipline, never by mutating a stored
Node/Edge/Evidence row. "Unaffected evidence stays valid" and "historical evidence stays accessible" hold
for free: this module never writes to `VBGStore` at all, so nothing outside `stale_entity_ids`'s
*derivation* is touched, and every prior Evidence row -- affected or not -- remains exactly where Phase 1.3's
append-only storage already put it. "Reverification targeted, not a full-repo re-scan by default" is what
`stale_entity_ids` itself IS: a targeted, precise set, not "everything."
"""

from __future__ import annotations

from dataclasses import dataclass

from veyra.git_tracking import SymbolChangeType, diff_symbols
from veyra.vbg import EvidenceType, RelationshipType, VBGStore, parse_edge_evidence_key

_TIER_1_RELATIONSHIPS = frozenset({RelationshipType.CALLS, RelationshipType.INHERITS, RelationshipType.REFERENCES})


@dataclass(frozen=True)
class ImpactAnalysisReport:
    old_repository_version: str
    new_repository_version: str
    tier_0: frozenset[str]
    tier_1: frozenset[str]
    tier_2_question_ids: frozenset[str]
    tier_3: frozenset[str]

    @property
    def stale_entity_ids(self) -> frozenset[str]:
        """Ready to feed directly into
        `veyra.verification.derive_verification_states(..., stale_entity_ids=...)`.
        Tier 2 (question_ids) is deliberately excluded -- it identifies
        affected *Questions*, not VBG entities; a Question's own staleness
        is a re-verification concern (re-run `verify_question()` against
        it), not a `VerificationState` a Node/Edge can carry."""
        return self.tier_0 | self.tier_1 | self.tier_3


def _relationship_neighbors(store: VBGStore, entity_id: str, repository_version: str) -> set[str]:
    neighbors: set[str] = set()
    for edge in store.get_incoming_edges(entity_id, repository_version):
        if edge.relationship_type in _TIER_1_RELATIONSHIPS:
            neighbors.add(edge.source_id)
    for edge in store.get_outgoing_edges(entity_id, repository_version):
        if edge.relationship_type in _TIER_1_RELATIONSHIPS:
            neighbors.add(edge.target_id)
    return neighbors


def _tier_1(store: VBGStore, tier_0: frozenset[str], old_repository_version: str, new_repository_version: str) -> frozenset[str]:
    neighbors: set[str] = set()
    for entity_id in tier_0:
        neighbors |= _relationship_neighbors(store, entity_id, old_repository_version)
        neighbors |= _relationship_neighbors(store, entity_id, new_repository_version)
    return frozenset(neighbors - tier_0)


def _tier_2_question_ids(
    store: VBGStore, affected: frozenset[str], old_repository_version: str, new_repository_version: str
) -> frozenset[str]:
    question_ids: set[str] = set()
    for repository_version in (old_repository_version, new_repository_version):
        for question in store.get_questions(repository_version):
            if affected & set(question.entity_ids):
                question_ids.add(question.question_id)
    return frozenset(question_ids)


def _tier_3(store: VBGStore, affected: frozenset[str], new_repository_version: str) -> frozenset[str]:
    dependents: set[str] = set()
    for evidence in store.get_all_evidence(new_repository_version, EvidenceType.RUNTIME):
        parsed = parse_edge_evidence_key(evidence.subject_id)
        if parsed is None:
            continue
        source_id, target_id, relationship_type = parsed
        if relationship_type is RelationshipType.CALLS and source_id in affected:
            dependents.add(target_id)
    return frozenset(dependents - affected)


def analyze_impact(
    store: VBGStore, old_repository_version: str, new_repository_version: str
) -> ImpactAnalysisReport:
    """Both commits must already have been run through static analysis
    (`veyra.pipeline.run_static_analysis`) against the same store -- this
    reads Nodes/Edges/Questions/Evidence already persisted per commit, it
    never checks out or re-extracts anything itself."""
    old_nodes = store.get_all_nodes(old_repository_version)
    new_nodes = store.get_all_nodes(new_repository_version)
    changes = diff_symbols(old_nodes, new_nodes)

    tier_0 = frozenset(c.entity_id for c in changes if c.change_type is not SymbolChangeType.UNCHANGED)
    tier_1 = _tier_1(store, tier_0, old_repository_version, new_repository_version)
    tier_0_and_1 = tier_0 | tier_1
    tier_2_question_ids = _tier_2_question_ids(store, tier_0_and_1, old_repository_version, new_repository_version)
    tier_3 = _tier_3(store, tier_0_and_1, new_repository_version)

    return ImpactAnalysisReport(
        old_repository_version=old_repository_version,
        new_repository_version=new_repository_version,
        tier_0=tier_0,
        tier_1=tier_1,
        tier_2_question_ids=tier_2_question_ids,
        tier_3=tier_3,
    )
