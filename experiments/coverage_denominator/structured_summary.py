"""
Offline experiment: augment each entity's indexed text with a structured
Q&A summary block, built purely from real, already-persisted graph edges
(CONTAINS/CALLS/INHERITS -- the "structural core" per user's scoping
choice), reusing the same real relationship data veyra.questions.generator
draws from (never fabricated, guarded per-line by "is there a real edge").

Supplements (does not replace) the existing name+docstring+source text --
per user's scoping choice. Rendered with SHORT names (last dotted segment)
for neighbors, not full entity_ids -- avoids reintroducing the exact
dotted-qualified-path tokenization noise problem found in the stopword
experiment.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, "/home/user/veyra/src")

import importlib

search_mod = importlib.import_module("veyra.retrieval.search")
from veyra.retrieval.index import IndexedEntity  # noqa: E402

_ORIGINAL_ENTITY_TEXT = search_mod._entity_text


def _short_name(entity_id: str) -> str:
    return entity_id.rsplit(".", 1)[-1]


def _structured_summary(entity: IndexedEntity) -> str:
    lines: list[str] = []

    if entity.children:
        names = ", ".join(_short_name(c) for c in entity.children)
        lines.append(f"What does {entity.name} contain? {names}")

    calls_out = [_short_name(t) for r, t in entity.outgoing_relationships if r == "calls"]
    if calls_out:
        lines.append(f"What does {entity.name} call? {', '.join(calls_out)}")

    calls_in = [_short_name(s) for r, s in entity.incoming_relationships if r == "calls"]
    if calls_in:
        lines.append(f"Who calls {entity.name}? {', '.join(calls_in)}")

    inherits_out = [_short_name(t) for r, t in entity.outgoing_relationships if r == "inherits"]
    if inherits_out:
        lines.append(f"What does {entity.name} inherit from? {', '.join(inherits_out)}")

    inherits_in = [_short_name(s) for r, s in entity.incoming_relationships if r == "inherits"]
    if inherits_in:
        lines.append(f"What inherits from {entity.name}? {', '.join(inherits_in)}")

    return " ".join(lines)


def _augmented_entity_text(entity: IndexedEntity) -> str:
    base = _ORIGINAL_ENTITY_TEXT(entity)
    summary = _structured_summary(entity)
    return f"{base} {summary}" if summary else base


from veyra.vbg import VBGStore  # noqa: E402
from veyra.retrieval import build_retrieval_index, retrieve_context  # noqa: E402

BENCH = Path("/home/user/veyra/benchmarks/real_world_python")
REPOS = ["flask", "fastapi", "sqlalchemy", "django"]


def run_all(entity_text_fn, label: str) -> dict:
    search_mod._entity_text = entity_text_fn
    repos_meta = json.loads((BENCH / "repos.json").read_text())
    commit_by_repo = {r["name"]: r["commit_sha"] for r in repos_meta["repositories"]}

    all_results = {}
    for repo in REPOS:
        commit = commit_by_repo[repo]
        store = VBGStore(str(BENCH / "results" / f"{repo}_vbg.db"))
        index = build_retrieval_index(store, commit)  # fresh index -> fresh _bm25_cache
        gt = json.loads((BENCH / "ground_truth" / f"{repo}.json").read_text())

        repo_results = []
        for q in gt["queries"]:
            ctx = retrieve_context(store, index, commit, q["query"], top_k=10, candidate_pool_size=200)
            repo_results.append({
                "query_id": q["query_id"],
                "insufficient_evidence": ctx.insufficient_evidence,
                "accepted_entities": [e.entity_id for e in ctx.entities],
            })
        all_results[repo] = repo_results
        print(f"[{label}] {repo} done", flush=True)

    return all_results


def main() -> None:
    before = run_all(_ORIGINAL_ENTITY_TEXT, "BEFORE (current)")
    after = run_all(_augmented_entity_text, "AFTER (structured summary)")

    out = {"before": before, "after": after}
    out_path = BENCH / "results" / "structured_summary_experiment.json"
    out_path.write_text(json.dumps(out, indent=2))
    print("wrote", out_path)


if __name__ == "__main__":
    main()
