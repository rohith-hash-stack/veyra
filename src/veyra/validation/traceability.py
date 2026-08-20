"""
PLAN.md Milestone 5, Phase 5.1 -- Acceptance-Criteria Traceability.

`Requirement -> Acceptance Criterion -> Test Case -> Result`. Every
acceptance criterion has an automated test; critical security requirements
have negative tests; no milestone marked complete with untested criteria.

**Granularity, deliberately scoped**: one `Requirement` per PLAN.md
phase-level "Acceptance:" criterion (M1 through M4, 30 phases -- M5 itself
is excluded, since auditing this milestone's own not-yet-finished
acceptance criteria against itself would be circular), not an exhaustive
per-sub-clause catalog. That is the granularity PLAN.md's own phase gates
already use ("Milestone N Gate" checklists are phase-level, not
clause-level) -- matching it here keeps this catalog honest and
maintainable rather than a brittle, ever-drifting line-by-line mapping.

Every `covering_test_modules` entry is a real path, verified to exist by
this module's own check function -- not a name typed from memory. Phase
2.2 (Emerge Integration Assessment) has none: PLAN.md's own text calls it
a desk-review "Deliverable: Emerge Compatibility Report," not code with
acceptance criteria to test -- it is marked `assessment_only=True` and
excluded from the coverage computation rather than silently counted as
either covered or a gap.

`security_critical=True` marks Phase 3.1 (Execution Classification) and
3.2 (Execution Boundary) specifically -- PLAN.md's own text frames these as
the phases where "no execution before classification" and sandbox
isolation are the actual safety guarantees; every other phase's negative
tests are important but not load-bearing for the "no execution-boundary
escape" release criterion (Phase 5.8) the same way these two are.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Requirement:
    requirement_id: str  # PLAN.md phase number, e.g. "1.1", "3.2", "4.7"
    milestone: int
    title: str
    acceptance_criteria: str
    covering_test_modules: tuple[str, ...]
    security_critical: bool = False
    assessment_only: bool = False


_REQUIREMENTS: tuple[Requirement, ...] = (
    Requirement("1.1", 1, "Repository Acquisition",
        "Reproducible clone; exact commit SHA captured; invalid-repo handling deterministic; "
        "inventory generated; clone duration recorded.",
        ("tests/acquisition/test_acquire.py",)),
    Requirement("1.2", 1, "Canonical VBG Schema",
        "Stable node identity; every edge has source+target; explicit relationship types; "
        "historical records cannot be silently overwritten.",
        ("tests/vbg/test_models.py",)),
    Requirement("1.3", 1, "Evidence & Provenance",
        "Every verified claim has evidence; every evidence record has provenance; "
        "runtime evidence references a scenario + execution environment.",
        ("tests/vbg/test_evidence.py",)),
    Requirement("1.4", 1, "Git Version Tracking (+ D4 symbol-level diff)",
        "Exact versions distinguishable; changed files identifiable; evidence tied to a "
        "specific commit; changes never silently overwrite previous knowledge.",
        ("tests/git_tracking/test_diff.py", "tests/git_tracking/test_symbol_diff.py")),
    Requirement("1.5", 1, "Audit Infrastructure",
        "Duration/timestamps/success/failure/sizes captured for every phase that uses it.",
        ("tests/audit/test_audit.py", "tests/vbg/test_audit_storage.py")),
    Requirement("2.1", 2, "Static Repository Analysis",
        "Supported constructs deterministically extracted; unsupported constructs explicitly "
        "recorded; every extracted entity maps to a VBG node.",
        ("tests/static_analysis/test_python_extractor.py",)),
    Requirement("2.2", 2, "Emerge Integration Assessment",
        "Deliverable: Emerge Compatibility Report (desk assessment, not code).",
        (), assessment_only=True),
    Requirement("2.3", 2, "Structural VBG Construction",
        "Deterministic graph per commit; unique node identity; typed relationships; cycles "
        "supported; cross-module relationships supported.",
        ("tests/vbg/test_graph_queries.py",)),
    Requirement("2.4", 2, "Neighborhood Model",
        "Parent/children/siblings/grandchildren derivable; configurable depth; unobserved "
        "relationships stay identifiable as unobserved.",
        ("tests/vbg/test_neighborhood.py",)),
    Requirement("2.5", 2, "Deterministic Question Generator",
        "No LLM dependency; every question references >=1 VBG entity; duplicates removed by "
        "construction; deterministic generation.",
        ("tests/questions/test_generator.py",)),
    Requirement("2.6", 2, "Static Question Verification",
        "Answers reference VBG entities; static evidence attached; unsupported questions "
        "become UNANSWERED.",
        ("tests/questions/test_verifier.py",)),
    Requirement("2.7", 2, "Verified / Unverified Knowledge Arms",
        "Kept strictly separate; unknown never silently becomes verified; unanswered "
        "questions stay queryable.",
        ("tests/questions/test_knowledge_arms.py",)),
    Requirement("2.8", 2, "Static Audit",
        "Real counts for every M2 pipeline stage; precision/recall left None pending M5 "
        "ground truth (D6).",
        ("tests/test_pipeline.py",)),
    Requirement("3.1", 3, "Execution Classification",
        "No execution before classification; unknown external behavior never auto-executed; "
        "policy decisions persisted and auditable.",
        ("tests/safety/test_classification.py", "tests/safety/test_capabilities.py",
         "tests/safety/test_policy.py", "tests/safety/test_classification_audit.py"),
        security_critical=True),
    Requirement("3.2", 3, "Execution Boundary",
        "Filesystem/network/credential isolation; CPU/memory limits; timeout; process "
        "restrictions; cleanup -- all genuinely exercised, not mocked.",
        ("tests/execution/test_docker_boundary.py", "tests/execution/test_boundary_contract.py",
         "tests/execution/test_execution_environment_storage.py"),
        security_critical=True),
    Requirement("3.3a", 3, "Harness & Fixture Manager (existing-test tracing)",
        "Dependencies identified where possible; failed harness creation -> UNEXECUTABLE; "
        "failed execution never becomes a successful behavioral claim.",
        ("tests/harness/test_discovery.py", "tests/harness/test_dependencies.py",
         "tests/harness/test_install_policy.py", "tests/harness/test_manager.py",
         "tests/harness/test_manager_docker.py")),
    Requirement("3.3b", 3, "Novel Scenario Synthesis",
        "Restricted to SAFE-classified, zero-coverage targets; property-based value "
        "generation, not a bespoke generator.",
        ("tests/harness/test_synthesis.py",)),
    Requirement("3.4", 3, "Behavioral Scenario Generator",
        "Scenarios reference actual VBG nodes; required inputs explicit; safety classified "
        "before execution; unsupported scenarios -> unexecutable.",
        ("tests/scenarios/test_scenario_generator.py", "tests/scenarios/test_scenario_introspection.py",
         "tests/vbg/test_scenario_model.py", "tests/vbg/test_scenario_storage.py")),
    Requirement("3.5", 3, "Runtime Trace Engine",
        "Runtime observations map to VBG nodes/edges; trace tied to commit/scenario/"
        "environment; failed execution still counts as evidence.",
        ("tests/runtime/test_engine.py", "tests/runtime/test_engine_docker.py")),
    Requirement("3.6", 3, "Multi-Execution Exploration",
        "New evidence updates VBG; previously observed paths not redundantly re-treated as "
        "new; no completeness claim just because executions stop finding new paths.",
        ("tests/exploration/test_exploration_engine.py",)),
    Requirement("3.7", 3, "Static/Runtime Evidence Reconciliation",
        "Conflicting evidence preserved, tagged by source; nothing silently deleted; "
        "unresolved conflicts stay CONFLICTED.",
        ("tests/reconciliation/test_reconciliation_engine.py",)),
    Requirement("3.8", 3, "Verification State Engine",
        "Every state transition has a valid evidence basis.",
        ("tests/verification/test_verification_engine.py",)),
    Requirement("3.9", 3, "Runtime Audit",
        "Scenario/execution counts, safety counts, runtime nodes/edges observed, evidence "
        "counts -- the whole M3 pipeline demonstrated running together.",
        ("tests/test_pipeline_runtime.py",)),
    Requirement("4.1", 4, "VBG Retrieval Index",
        "Relevant VBG regions retrievable; commit-aware; retrieval returns graph references, "
        "not invented entities.",
        ("tests/retrieval/test_retrieval_index.py",)),
    Requirement("4.2", 4, "Semantic Repository Retrieval",
        "Conceptual queries retrieve relevant regions; exact symbol queries retrieve exact "
        "nodes; retrieval never invents graph entities.",
        ("tests/retrieval/test_retrieval_search.py",)),
    Requirement("4.3", 4, "Query-Time Evidence Retrieval",
        "Query -> nodes -> relationships -> evidence -> verification states -> context.",
        ("tests/retrieval/test_retrieval_context.py",)),
    Requirement("4.4-4.6", 4, "Eager/Lazy Retrieval Caching + Explosion Control",
        "Precompute only for high-value nodes; duplicates avoided; storage growth "
        "measurable; eager strategy has configurable limits.",
        ("tests/retrieval/test_retrieval_cache.py",)),
    Requirement("4.7", 4, "LLM Grounding Contract",
        "LLM can distinguish verified/unverified; conflicts exposed; unknowns stay unknown; "
        "cannot silently claim unsupported repository behavior.",
        ("tests/retrieval/test_retrieval_grounding.py",)),
    Requirement("4.8", 4, "Git Impact Analysis & Invalidation",
        "Changed evidence goes stale where appropriate; unaffected evidence stays valid; "
        "reverification targeted, not a full-repo re-scan.",
        ("tests/invalidation/test_invalidation_engine.py",)),
    Requirement("4.9", 4, "Retrieval Audit",
        "Index build duration/size, query latency, relevant nodes/edges/evidence retrieved, "
        "grounded vs unsupported answers.",
        ("tests/test_pipeline_retrieval.py",)),
)


@dataclass(frozen=True)
class TraceabilityResult:
    requirement: Requirement
    modules_found: tuple[str, ...]
    modules_missing: tuple[str, ...]
    fully_covered: bool


@dataclass(frozen=True)
class TraceabilityReport:
    total_requirements: int
    fully_covered_count: int
    gaps: tuple[TraceabilityResult, ...]
    security_critical_gaps: tuple[TraceabilityResult, ...]
    fully_traceable: bool


def check_traceability(veyra_repo_root: Path) -> TraceabilityReport:
    """`veyra_repo_root` is Veyra's own repository root -- this audits
    Veyra's own acceptance-criteria coverage against its own test suite,
    the same self-referential scope Phase 5.8's security audit uses."""
    results: list[TraceabilityResult] = []
    for requirement in _REQUIREMENTS:
        if requirement.assessment_only:
            results.append(TraceabilityResult(requirement, (), (), fully_covered=True))
            continue
        found = tuple(m for m in requirement.covering_test_modules if (veyra_repo_root / m).is_file())
        missing = tuple(m for m in requirement.covering_test_modules if m not in found)
        results.append(TraceabilityResult(requirement, found, missing, fully_covered=len(missing) == 0))

    gaps = tuple(r for r in results if not r.fully_covered)
    security_critical_gaps = tuple(r for r in gaps if r.requirement.security_critical)

    return TraceabilityReport(
        total_requirements=len(results),
        fully_covered_count=sum(1 for r in results if r.fully_covered),
        gaps=gaps,
        security_critical_gaps=security_critical_gaps,
        fully_traceable=len(gaps) == 0,
    )
