"""Builds all 4 repos x 2 models (8 indices total), loading GloVe once."""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from build_index import BENCH, build_for_repo  # noqa: E402

REPOS = ["flask", "fastapi", "sqlalchemy", "django"]


def main() -> None:
    import gensim.downloader as api

    print("loading glove-wiki-gigaword-300 ...", flush=True)
    glove_kv = api.load("glove-wiki-gigaword-300")
    print("loaded", flush=True)

    all_timing = {}
    for repo in REPOS:
        all_timing.setdefault(repo, {})
        timing = build_for_repo(repo, "tfidf-lsa")
        all_timing[repo]["tfidf-lsa"] = timing
        (BENCH / "results" / "semantic_index" / f"{repo}_tfidf-lsa_timing.json").write_text(json.dumps(timing, indent=2))

        timing = build_for_repo(repo, "glove", glove_kv)
        all_timing[repo]["glove"] = timing
        (BENCH / "results" / "semantic_index" / f"{repo}_glove_timing.json").write_text(json.dumps(timing, indent=2))

    (BENCH / "results" / "semantic_index" / "all_timing.json").write_text(json.dumps(all_timing, indent=2))
    print("DONE")


if __name__ == "__main__":
    main()
