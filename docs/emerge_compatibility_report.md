# Emerge Compatibility Report

PLAN.md Phase 2.2 deliverable. Status: **assessed from general knowledge only, not verified against a real
installation or real output** — see "How to actually finish this" below.

## What this assessment is based on

Nothing in this environment names, installs, or references a specific "Emerge" tool, and no such tool is
available to run or inspect here. The plan's own description ("dependency graph, clusters, relationships, git
information, TF-IDF information, architecture metrics") matches the open-source static-analysis tool `emerge`
(glato/emerge on GitHub) closely enough that this report assumes that's the intended tool — but that
identification itself is an inference, not a confirmed fact, and the assessment below is written from general
knowledge of that project rather than from running it against a real repository and inspecting real output.
**Treat every row below as a hypothesis to verify, not a settled fact.**

## Compatibility table (per PLAN.md Phase 2.2's deliverable format)

| Emerge output | VBG mapping | Status |
|---|---|---|
| Dependency graph (module/file-level edges) | Could seed `DEPENDS_ON` edges (currently unimplemented in `static_analysis`, see PROGRESS.md) — if Emerge's edges are file/module-granularity, they'd need to be reconciled against Veyra's own `IMPORTS`/`CALLS` edges, not just copied in | REQUIRES_SUPPLEMENTATION |
| Clusters (community detection on the dependency graph) | No corresponding VBG concept exists yet — would need a new Node type or a new relationship, not something the current schema absorbs directly | UNSUPPORTED (schema doesn't have a slot for this today) |
| TF-IDF term weighting | No corresponding VBG concept; the plan's own PMI/entropy-style lexical experiments (referenced in prior project memory, unrelated codebase) suggest this kind of signal is easy to compute but historically low-value on its own | UNSUPPORTED |
| Git information | Veyra already has its own git handling (`veyra.git_tracking`, Phase 1.4) that's deterministic and tested — an external tool's git output would be redundant at best, and risks disagreeing with Veyra's own git_tracking results at worst | UNSUPPORTED (Veyra's own mechanism takes precedence, per D9: "Emerge cannot overwrite stronger evidence") |
| Architecture metrics (coupling, cohesion, etc.) | Downstream/derived metrics — could theoretically be recomputed from Veyra's own CONTAINS/CALLS/IMPORTS graph once enough of the structural graph exists, without needing Emerge specifically | UNSUPPORTED (not needed as an external input) |

## Recommendation

Per Design Decision D9 (PLAN.md), Emerge integration is a strictly optional, non-blocking plug-in — nothing in
Milestones 1–2's implementation to date depends on it, and none of the acceptance criteria for the phases built
so far require it. Given the table above, the strongest candidate for real integration would be the dependency
graph (as a supplementary source for `DEPENDS_ON`, which `static_analysis` deliberately hasn't implemented yet
— see PROGRESS.md's Phase 2.1 entry), but only once there is real tool output to check the mapping against.

**How to actually finish this assessment**: if the user has (or can point to) the specific "Emerge" tool
they mean, provide its actual output on a sample repository. Until then, this report stays a hypothesis, and
Veyra's own extraction (Phase 2.1, plus the cross-module resolution added on top of it) remains fully
independent, per the acceptance criterion "Veyra remains independent of Emerge."
