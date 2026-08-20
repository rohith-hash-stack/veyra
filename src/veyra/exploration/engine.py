"""
PLAN.md Milestone 3, Phase 3.6 -- Multi-Execution Exploration.

Orchestrates repeated Phase 3.5 `run_scenario()` calls across the Phase 3.4
candidate scenarios for a whole commit, bounded by Design Decision D10's
tiered numeric budgets (tied to the `file_count` Phase 1.1 already
captures):
    Tier 1 (<50 files):     unlimited executions, 5 min wall-clock cap.
    Tier 2 (50-500 files):  eager execution of only the top-50
                             centrality-ranked nodes, 30 min wall-clock cap.
    Tier 3 (>500 files):    NO eager execution at ingest at all -- purely
                             lazy/query-driven, 2 min / 20-execution cap
                             per individual query.

`explore_at_ingest()` implements the eager Tier 1/2 policy directly (Tier 3
returns an empty report immediately, by design -- see D10). `explore_neighborhood()`
is the general lazy/query-driven primitive Tier 3 needs: bounded exploration
of one entity's own *call-graph* neighborhood (outgoing CALLS edges, walked
breadth-first up to `max_depth`) -- deliberately NOT Phase 2.4's structural
CONTAINS-based children/grandchildren, which is a different relationship
entirely and is left completely untouched by this module. "Siblings/
children/grandchildren stay visible" (Phase 3.6 AC) is therefore a
non-regression guarantee inherited for free from Phase 2.4, not something
this module has to (re)implement.

Since no real caller for query-time exploration exists yet (that's
Milestone 4's Query-Time Evidence Retrieval, Phase 4.3, not built),
`explore_neighborhood()` is offered here as the general, reusable,
budget-capped primitive Phase 4.3 will eventually call -- not wired to a
fabricated query trigger, per the same discipline Phase 3.3a used for
deferring its own downstream wiring.

**"Previously observed paths not redundantly re-treated as new"**: a
candidate is skipped the moment it already carries any RUNTIME evidence at
this commit, regardless of whether that evidence came from a prior
`explore()` pass targeting it directly, or incidentally from Phase 3.5
tracing it as a *nested* call of some other scenario. This is what makes
repeated `explore()` calls against an unchanged commit converge toward zero
newly-attempted scenarios -- itself the "convergence measurable" signal --
without ever claiming that convergence means completeness (Phase 3.6 AC
explicitly forbids that claim; see `ExplorationReport`'s docstring).

**Centrality is plain degree centrality** (in-edges + out-edges via Phase
2.4's `get_incoming_edges`/`get_outgoing_edges`), a deliberately simple,
stated proxy for "high-value/public-API" -- not betweenness or eigenvector
centrality. Revisit once Phase 5.7 performance-audit data exists showing
this is a poor ranking in practice (same "starting default, not a measured
optimum" framing D10 itself uses).

**Per-node execution cap not implemented**: D10 also specifies "max 5
scenarios/executions per node" for Tier 2. Phase 3.4 generates exactly one
deterministic scenario per node today, so a per-node cap has nothing to
bound yet -- adding one now would be dead code. Revisit once 3.3b (or any
future multi-scenario generation) can produce more than one candidate
scenario for the same target.
"""

from __future__ import annotations

import enum
import time
from dataclasses import dataclass
from pathlib import Path

from veyra.execution import ExecutionBoundary
from veyra.runtime import ScenarioExecutionOutcome, run_scenario
from veyra.scenarios import generate_scenarios, persist_scenarios
from veyra.vbg import EvidenceType, RelationshipType, VBGStore

_TIER_1_MAX_FILES = 50
_TIER_2_MAX_FILES = 500
_TIER_1_WALL_CLOCK_SECONDS = 5 * 60.0
_TIER_2_TOP_N = 50
_TIER_2_WALL_CLOCK_SECONDS = 30 * 60.0
_TIER_3_QUERY_WALL_CLOCK_SECONDS = 2 * 60.0
_TIER_3_QUERY_MAX_EXECUTIONS = 20
_DEFAULT_NEIGHBORHOOD_DEPTH = 2


class ExplorationTier(enum.Enum):
    TIER_1 = "TIER_1"
    TIER_2 = "TIER_2"
    TIER_3 = "TIER_3"


def _tier_for(file_count: int) -> ExplorationTier:
    if file_count < _TIER_1_MAX_FILES:
        return ExplorationTier.TIER_1
    if file_count <= _TIER_2_MAX_FILES:
        return ExplorationTier.TIER_2
    return ExplorationTier.TIER_3


@dataclass(frozen=True)
class ExplorationReport:
    """`budget_exhausted=False` after a pass with `attempted < candidates_considered`
    means every remaining candidate was already explored, not that none
    existed -- and even `attempted == 0` with `budget_exhausted=False`
    across repeated passes is a *convergence* signal, never a completeness
    one (Phase 3.6 AC: "no completeness claim just because executions stop
    finding new paths"). Unreachable code, code behind a permanently-false
    condition, and code no scenario was ever planned for are not "explored
    and found safe" -- they are simply absent from this report."""

    repository_version: str
    tier: ExplorationTier | None  # None for explore_neighborhood() (tier-agnostic)
    candidates_considered: int
    already_explored_skipped: int
    attempted: int
    completed: int
    exceptioned: int
    unexecutable: int
    elapsed_seconds: float
    budget_exhausted: bool
    outcomes: tuple[ScenarioExecutionOutcome, ...]


def _centrality_score(store: VBGStore, entity_id: str, repository_version: str) -> int:
    return len(store.get_incoming_edges(entity_id, repository_version)) + len(
        store.get_outgoing_edges(entity_id, repository_version)
    )


def _already_has_runtime_evidence(store: VBGStore, entity_id: str, repository_version: str) -> bool:
    return any(
        e.evidence_type is EvidenceType.RUNTIME
        for e in store.get_evidence_for_subject(entity_id, repository_version)
    )


def _call_graph_neighborhood(
    store: VBGStore, entity_id: str, repository_version: str, max_depth: int
) -> set[str]:
    """Breadth-first walk of outgoing CALLS edges only, up to max_depth --
    the behaviorally meaningful graph for "what might this function's own
    execution reach next," deliberately distinct from Phase 2.4's
    structural CONTAINS children/grandchildren (see module docstring)."""
    visited = {entity_id}
    frontier = [entity_id]
    for _ in range(max_depth):
        next_frontier: list[str] = []
        for node_id in frontier:
            for edge in store.get_outgoing_edges(node_id, repository_version):
                if edge.relationship_type is RelationshipType.CALLS and edge.target_id not in visited:
                    visited.add(edge.target_id)
                    next_frontier.append(edge.target_id)
        if not next_frontier:
            break
        frontier = next_frontier
    return visited


def explore(
    store: VBGStore,
    repository_root: Path,
    repository_version: str,
    boundary: ExecutionBoundary,
    candidate_entity_ids: set[str] | None = None,
    max_executions: int | None = None,
    max_wall_clock_seconds: float = _TIER_1_WALL_CLOCK_SECONDS,
    tier: ExplorationTier | None = None,
) -> ExplorationReport:
    """Runs Phase 3.4's generator fresh (append-only + idempotent-safe --
    same reasoning `run_scenario()` already relies on for re-classification)
    to get today's live executable scenarios, restricts them to
    `candidate_entity_ids` when given (None = every executable target in
    the repository), ranks by descending centrality, and executes in that
    order until every candidate is either attempted or already-explored, or
    a budget is hit."""
    start = time.monotonic()

    scenarios = generate_scenarios(store, repository_version)
    persist_scenarios(store, scenarios)  # every candidate, not just executable ones -- Phase 3.9's audit needs the full picture
    scenario_by_target = {s.target_entity_id: s for s in scenarios if s.executable}

    if candidate_entity_ids is None:
        candidates = list(scenario_by_target.values())
    else:
        candidates = [scenario_by_target[eid] for eid in candidate_entity_ids if eid in scenario_by_target]

    ranked = sorted(
        candidates,
        key=lambda s: (-_centrality_score(store, s.target_entity_id, repository_version), s.target_entity_id),
    )

    already_explored_skipped = 0
    outcomes: list[ScenarioExecutionOutcome] = []
    budget_exhausted = False

    for scenario in ranked:
        if _already_has_runtime_evidence(store, scenario.target_entity_id, repository_version):
            already_explored_skipped += 1
            continue
        if time.monotonic() - start >= max_wall_clock_seconds:
            budget_exhausted = True
            break
        if max_executions is not None and len(outcomes) >= max_executions:
            budget_exhausted = True
            break
        outcomes.append(run_scenario(store, repository_root, repository_version, scenario, boundary))

    return ExplorationReport(
        repository_version=repository_version,
        tier=tier,
        candidates_considered=len(ranked),
        already_explored_skipped=already_explored_skipped,
        attempted=len(outcomes),
        completed=sum(1 for o in outcomes if o.status == "COMPLETED"),
        exceptioned=sum(1 for o in outcomes if o.status == "EXCEPTION"),
        unexecutable=sum(1 for o in outcomes if o.status == "UNEXECUTABLE"),
        elapsed_seconds=time.monotonic() - start,
        budget_exhausted=budget_exhausted,
        outcomes=tuple(outcomes),
    )


def explore_at_ingest(
    store: VBGStore,
    repository_root: Path,
    repository_version: str,
    boundary: ExecutionBoundary,
    file_count: int,
) -> ExplorationReport:
    """Implements D10's eager-exploration tier policy directly. Tier 3
    deliberately performs zero executions here -- per D10, it is
    purely lazy/query-driven via explore_neighborhood()."""
    tier = _tier_for(file_count)

    if tier is ExplorationTier.TIER_1:
        return explore(
            store, repository_root, repository_version, boundary,
            candidate_entity_ids=None, max_executions=None,
            max_wall_clock_seconds=_TIER_1_WALL_CLOCK_SECONDS, tier=tier,
        )

    if tier is ExplorationTier.TIER_2:
        all_targets = {n.entity_id for n in store.get_all_nodes(repository_version) if n.type == "Function"}
        top_n = sorted(
            all_targets,
            key=lambda eid: (-_centrality_score(store, eid, repository_version), eid),
        )[:_TIER_2_TOP_N]
        return explore(
            store, repository_root, repository_version, boundary,
            candidate_entity_ids=set(top_n), max_executions=None,
            max_wall_clock_seconds=_TIER_2_WALL_CLOCK_SECONDS, tier=tier,
        )

    return ExplorationReport(
        repository_version=repository_version, tier=ExplorationTier.TIER_3,
        candidates_considered=0, already_explored_skipped=0, attempted=0,
        completed=0, exceptioned=0, unexecutable=0, elapsed_seconds=0.0,
        budget_exhausted=False, outcomes=(),
    )


def explore_neighborhood(
    store: VBGStore,
    repository_root: Path,
    repository_version: str,
    boundary: ExecutionBoundary,
    entity_id: str,
    max_depth: int = _DEFAULT_NEIGHBORHOOD_DEPTH,
    max_executions: int = _TIER_3_QUERY_MAX_EXECUTIONS,
    max_wall_clock_seconds: float = _TIER_3_QUERY_WALL_CLOCK_SECONDS,
) -> ExplorationReport:
    """The lazy/query-driven primitive: bounded exploration of one entity's
    own call-graph neighborhood. Default budget matches D10's Tier 3
    per-query cap exactly (2 min / 20 executions); a caller exploring a
    smaller/larger neighborhood on purpose can override either."""
    candidates = _call_graph_neighborhood(store, entity_id, repository_version, max_depth)
    return explore(
        store, repository_root, repository_version, boundary,
        candidate_entity_ids=candidates, max_executions=max_executions,
        max_wall_clock_seconds=max_wall_clock_seconds, tier=None,
    )
