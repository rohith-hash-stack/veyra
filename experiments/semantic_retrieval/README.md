# Semantic Retrieval Feasibility Experiment (Phase E)

Isolated experiment code. Nothing in this directory is imported by
`src/veyra/`, and nothing in `src/veyra/` was modified to build this
experiment. It can be deleted entirely without changing deterministic
retrieval behavior.

See `../../benchmarks/real_world_python/SEMANTIC_RETRIEVAL_FEASIBILITY_REPORT.md`
for the full methodology, results, and GO/NO-GO recommendation.

## Network constraint (real, not routed around)

`huggingface.co` is blocked by this environment's organization egress
policy (verified: 403 on CONNECT, logged as a policy denial, not a
transient failure). Per the proxy's own operating instructions, a policy
denial is reported, not retried or routed around. This ruled out every
modern sentence-transformer / cross-encoder model (all hosted on
HuggingFace), which is a real, disclosed limitation on what this
experiment could evaluate — see the report's Risks section.

Two models were evaluated instead, both obtainable from allowed hosts:

- **GloVe** (`glove-wiki-gigaword-300`, gensim-data, GitHub-hosted release
  assets) — real pretrained general-English word vectors, mean-pooled per
  document. Not code-aware, not contextual, not a sentence-transformer.
- **TF-IDF + Truncated SVD (LSA)** — corpus-derived, zero external
  download, computed entirely from each repository's own text.

## Files

- `representations.py` — the 2 representations compared (A: name+docstring+
  source; C: structured repo-aware text with a capped source excerpt).
- `models.py` — the 2 embedding backends (GloVe mean-pool, TF-IDF+LSA).
- `build_index.py` — builds a semantic index for one repo from its real,
  already-persisted `VBGStore`.
- `run_recall.py` — measures Recall@K against the real ground-truth queries.
- `run_negative.py` — the mandatory negative-query check.
- `run_hybrid.py` — deterministic ∪ semantic candidate union.
