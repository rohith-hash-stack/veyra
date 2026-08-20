#!/usr/bin/env python3
"""
Phase D investigation: dumps per-candidate TF-IDF term contributions for a
fixed query, against real Flask data, to confirm (not assume) exactly why
a short, irrelevant entity outranks a long, correct one -- per the
remediation plan's explicit "instrument before you fix" requirement.
"""
from __future__ import annotations

import sys
from pathlib import Path

BENCH_ROOT = Path(__file__).resolve().parents[1]
VEYRA_ROOT = BENCH_ROOT.parents[1]
sys.path.insert(0, str(VEYRA_ROOT / "src"))

from veyra.retrieval.index import build_retrieval_index  # noqa: E402
from veyra.retrieval.search import _build_tfidf_vectors, _entity_text, _tokenize  # noqa: E402
from veyra.vbg import VBGStore  # noqa: E402

COMMIT = "d318b683471101618febed18996405ad26462110"


def dump(entity_id: str, index, vectors, idf, query_tokens) -> None:
    entity = index.get(entity_id)
    text = _entity_text(entity)
    tokens = _tokenize(text)
    total = len(tokens)
    vec = vectors[entity_id]
    print(f"--- {entity_id} ({entity.node_type}) ---")
    print(f"  total token count in this entity's document: {total}")
    print(f"  name={entity.name!r} docstring={(entity.docstring or '')[:40]!r}")
    for t in sorted(set(query_tokens)):
        raw_count = tokens.count(t)
        tf = raw_count / total if total else 0.0
        contribution = vec.get(t, 0.0)
        print(f"  token={t!r}: raw_count={raw_count} tf={tf:.4f} idf={idf.get(t, 0.0):.3f} "
              f"tf*idf={contribution:.4f}")
    norm = sum(v * v for v in vec.values()) ** 0.5
    print(f"  full vector L2 norm (all {len(vec)} terms): {norm:.4f}")


def main() -> None:
    store = VBGStore(str(BENCH_ROOT / "results" / "flask_vbg.db"))
    index = build_retrieval_index(store, COMMIT)
    vectors, idf = _build_tfidf_vectors(index)

    query = "What happens when app.run() is called with debug=True?"
    query_tokens = _tokenize(query)
    print(f"query tokens: {query_tokens}\n")

    dump("src.flask.app.Flask.run", index, vectors, idf, query_tokens)
    print()
    dump("tests.test_appctx.test_clean_pop.called", index, vectors, idf, query_tokens)


if __name__ == "__main__":
    main()
