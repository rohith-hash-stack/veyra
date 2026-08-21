"""
Phase E -- builds a semantic index for one repository, for one model, using
representation C (the winner of compare_representations.py -- see that
script's real, measured recall numbers on Flask: 13/25 vs 8/25 at
Recall@10). Saves embeddings + entity_id order to disk so downstream
scripts (recall, negative-query, hybrid) don't refit per experiment.

`SemanticCandidate` fields carried through every downstream result: not
just `entity_id`/`semantic_score`/`rank` but `retrieval_source` (this
model's name), `representation_version` ("C"), and `entity_id` doubling
as the real source-location lookup -- Phase E's own auditability
requirement (Section 12): every semantic candidate must be traceable back
to why it entered the candidate set.
"""
from __future__ import annotations

import json
import pickle
import sys
import time
from dataclasses import asdict, dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from veyra.retrieval import build_retrieval_index  # noqa: E402
from veyra.vbg import VBGStore  # noqa: E402

from models import GloveMeanPool, TfidfLsa  # noqa: E402
from representations import representation_c  # noqa: E402

BENCH = Path(__file__).resolve().parents[2] / "benchmarks" / "real_world_python"
INDEX_DIR = BENCH / "results" / "semantic_index"


@dataclass(frozen=True)
class SemanticCandidate:
    entity_id: str
    semantic_score: float
    rank: int
    retrieval_source: str  # model name
    representation_version: str
    source_location: str | None


def build_for_repo(repo_name: str, model_name: str, glove_kv=None) -> dict:
    repos_meta = json.loads((BENCH / "repos.json").read_text())
    entry = next(r for r in repos_meta["repositories"] if r["name"] == repo_name)
    commit = entry["commit_sha"]
    store = VBGStore(str(BENCH / "results" / f"{repo_name}_vbg.db"))

    t0 = time.time()
    index = build_retrieval_index(store, commit)
    index_build_s = time.time() - t0
    entities = index.all_entities()

    t0 = time.time()
    texts = [representation_c(e, index, repo_name) for e in entities]
    represent_s = time.time() - t0

    t0 = time.time()
    if model_name == "tfidf-lsa":
        model = TfidfLsa(n_components=200)
        corpus_vecs = model.fit_corpus(texts)
    elif model_name == "glove":
        model = GloveMeanPool(glove_kv)
        corpus_vecs = model.embed(texts)
    else:
        raise ValueError(model_name)
    embed_s = time.time() - t0

    INDEX_DIR.mkdir(parents=True, exist_ok=True)
    entity_ids = [e.entity_id for e in entities]
    source_locations = {e.entity_id: e.source_location for e in entities}
    out_path = INDEX_DIR / f"{repo_name}_{model_name}.pkl"
    with open(out_path, "wb") as f:
        pickle.dump(
            {
                "entity_ids": entity_ids,
                "corpus_vecs": corpus_vecs,
                "model": model,
                "model_name": model_name,
                "representation_version": "C",
                "source_locations": source_locations,
                "commit": commit,
            },
            f,
        )
    storage_bytes = out_path.stat().st_size

    timing = {
        "index_build_s": index_build_s,
        "represent_s": represent_s,
        "embed_s": embed_s,
        "total_s": index_build_s + represent_s + embed_s,
        "n_entities": len(entities),
        "storage_bytes": storage_bytes,
    }
    print(f"[{repo_name}/{model_name}] {timing}")
    return timing


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("repo")
    parser.add_argument("model", choices=["tfidf-lsa", "glove"])
    args = parser.parse_args()

    glove_kv = None
    if args.model == "glove":
        import gensim.downloader as api

        glove_kv = api.load("glove-wiki-gigaword-300")

    timing = build_for_repo(args.repo, args.model, glove_kv)
    timing_path = BENCH / "results" / "semantic_index" / f"{args.repo}_{args.model}_timing.json"
    timing_path.write_text(json.dumps(timing, indent=2))


if __name__ == "__main__":
    main()
