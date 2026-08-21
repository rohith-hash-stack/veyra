# Veyra Phase E — Semantic Retrieval Feasibility & Hybrid Retrieval Evaluation

This is a feasibility experiment, not an implementation commitment. Deterministic
retrieval (`src/veyra/retrieval/`) was not modified anywhere in this phase — every
measurement below comes from an isolated prototype under `experiments/semantic_retrieval/`
that can be deleted without changing deterministic behavior at all.

## 1. Objective

Determine whether semantic retrieval provides a genuinely new retrieval capability —
one that bridges the natural-language-to-code-vocabulary gap the frozen deterministic
layer cannot close (`FINAL_RETRIEVAL_HARDENING_REPORT.md`'s architectural-boundary
conclusion) — while preserving Veyra's auditability, negative-query safety,
reproducibility, and practical performance. This is explicitly a measurement exercise:
the question is whether the evidence supports building a hybrid architecture next, not
whether embeddings are aesthetically the right answer.

## 2. Frozen Deterministic Baseline

Verified at the start of this phase, reproduced exactly, and never touched during it:

```
DETERMINISTIC_BASELINE
Commit:        91cf85e (experiment/real-world-python-benchmark)
Fully correct: 14/48 (29.2%)
Partial:       11/48 (22.9%)
False:         23/48 (47.9%)
Negative:       6/8  (75.0%)
Gate:          39/48 -- NOT MET
Test suite:    485 passed, 0 failed, 26 skipped
```

The working tree was clean at the start of this phase (no uncommitted deterministic
changes to identify or clean up). All Phase E work landed on top of this commit as new,
additive commits — `src/veyra/` was never staged in any Phase E commit.

## 3. Models Evaluated

**A real network constraint was hit and is disclosed here, not routed around.**
`huggingface.co` — the host for essentially every modern sentence-transformer,
cross-encoder, and reranker model — is blocked by this environment's organization
egress policy (verified: `curl` to it returns a 403 on the CONNECT tunnel, and the
proxy's own status endpoint logs it as `connect_rejected` / "policy or upstream
denial"). Per the proxy's own operating instructions, a policy denial is reported, not
retried or worked around. **No modern neural sentence-embedding model could be
evaluated in this environment.** This is a real, material limitation on what this
report's evidence can support — see Section 14.

Two models obtainable from allowed hosts (verified reachable: `github.com`,
`raw.githubusercontent.com`, `objects.githubusercontent.com`; PyPI was already
reachable) were evaluated instead:

| Model | Source | Dimensionality | Nature |
|---|---|---:|---|
| GloVe (`glove-wiki-gigaword-300`) | `gensim-data`, served from GitHub release assets — not HuggingFace | 300 | Real pretrained general-English word vectors (Wikipedia + Gigaword), mean-pooled per document. Static, not contextual, not code-aware. |
| TF-IDF + Truncated SVD (LSA) | Computed entirely locally from each repository's own corpus, zero external download | 200 | Classic latent-semantic-analysis technique — captures co-occurrence structure beyond literal term overlap, automatically vocabulary-matched to the actual codebase (unlike GloVe's generic English training data). |

Neither is a modern sentence-transformer. Both were selected because they were the
*best real, reproducible* options available given the network constraint above, not
because they were assumed to be sufficient — Section 15's recommendation accounts for
this directly.

**Not evaluated, and why**: a self-hosted transformer (e.g., a HuggingFace model)
was ruled out by the network block; a paid external API (OpenAI/Cohere/etc.
embeddings) was ruled out by the directive's own constraint against a mandatory paid
architecture dependency; ONNX-exported static embedding models distributed via PyPI
wheels were investigated briefly but not found to be meaningfully different from the
GloVe approach already covered (both are non-contextual static word/sentence vectors)
and were not pursued further given the time budget for a feasibility pass.

## 4. Repository Representation Evaluated

Two representations were built and compared with real data (TF-IDF+LSA, the real
persisted Flask store, 2,607 entities) before committing to one for the full sweep —
per the directive's explicit instruction not to assume a richer representation helps:

- **Representation A**: `name + docstring + full source` — the exact same shape as
  production's `_entity_text()`, included as the natural baseline every deterministic
  decision in this project was measured against. Uncapped.
- **Representation C**: structured, repository-aware text (`Repository: / Module: /
  Parent: / Entity: / Kind: / Purpose: / Relevant source:`), with the source excerpt
  deliberately capped at 500 characters to directly test the directive's own concern
  that blindly including huge source bodies could dilute the embedding.

| | Representation A | Representation C |
|---|---:|---:|
| Avg. text length | 388 chars | 348 chars |
| Fit time (Flask, 2,607 entities) | 2.2s | 0.8s |
| Recall@10 (real, 25 ground-truth symbols) | 8/25 | **13/25** |
| Recall@50 | 15/25 | **21/25** |

Representation C won measurably, not marginally — the structural context (module,
parent, kind) and the capped source both appear to help, not hurt. **Representation C
was used for the entire remaining experiment** (all 4 repos, both models).

## 5. Semantic Retrieval Methodology

For each repository: build the real `RetrievalIndex` from the already-persisted
`VBGStore` (same data deterministic retrieval uses — no separate re-extraction), render
every entity through representation C, fit the model (TF-IDF+LSA: fit vectorizer + SVD
on the whole corpus; GloVe: no fitting, pure lookup+mean), producing one dense vector
per entity. A query is embedded through the same fitted pipeline (LSA: transform
through the already-fitted vectorizer+SVD; GloVe: mean-pool the query's own tokens) and
ranked against the corpus by cosine similarity. `SemanticCandidate` carries
`entity_id`/`semantic_score`/`rank`/`retrieval_source` (model name)/
`representation_version`/`source_location` — see Section 12.

Semantic candidate generation was measured **entirely independently** of deterministic
retrieval first (Sections 6–9); the two were only combined via simple set union
(Section 10/`run_hybrid.py`) after that, per the directive's explicit ordering — no
weighted-score combination was built or tested this phase.

## 6. Recall@K Results

Aggregated across all 4 repositories, all 48 answerable queries, 88 total
ground-truth symbols:

| K | TF-IDF+LSA | GloVe |
|---:|---:|---:|
| 1 | 2/88 (2.3%) | 6/88 (6.8%) |
| 5 | 11/88 (12.5%) | 15/88 (17.0%) |
| 10 | 18/88 (20.5%) | 17/88 (19.3%) |
| 20 | 22/88 (25.0%) | 28/88 (31.8%) |
| 50 | 32/88 (36.4%) | 35/88 (39.8%) |
| 100 | 38/88 (43.2%) | 47/88 (53.4%) |

**Per-repository breakdown reveals a real, important pattern the aggregate hides**:

| Repo (entities) | TF-IDF+LSA R@10 | GloVe R@10 |
|---|---:|---:|
| Flask (2,607) | 13/25 (52%) | 11/25 (44%) |
| FastAPI (13,891) | 1/22 (4.5%) | 1/22 (4.5%) |
| SQLAlchemy (87,782) | 4/21 (19%) | 2/21 (9.5%) |
| Django (92,679) | 0/20 (0%) | 3/20 (15%) |

**Both models work reasonably on the smallest corpus and degrade sharply on the
larger, more heterogeneous real codebases** — this is not a corpus-size coincidence
confined to one repo; it recurs for both models, in the same direction, across all 3
larger repos. Neither model demonstrates that its semantic signal scales the way
production-grade retrieval would need it to.

## 7. Deterministic vs. Semantic Comparison

| Metric | Deterministic | TF-IDF+LSA | GloVe |
|---|---:|---:|---:|
| Recall@10 (raw candidate presence, all 88 symbols) | not measured this way (deterministic uses accept/reject, not raw rank recall) | 20.5% | 19.3% |
| Fully correct (final, confidence-accepted) | **14/48 (29.2%)** | not applicable — no confidence mechanism built this phase (Section 9) | not applicable |
| Partial | 11/48 | — | — |
| Negative correct | **6/8 (75%)** | not applicable (Section 9) | not applicable |
| Index build time (largest repo, Django) | ~37s | 63.6s | 50.9s |
| Query latency (largest repo, Django) | ~3.1s (`retrieve_context`) | 82.9ms | 170.0ms |

**This is not an apples-to-apples "fully correct" comparison, deliberately.** The
directive's Section 7 explicitly says not to claim semantic improvement merely because
it retrieves more candidates — candidate retrieval and final answer correctness are
different metrics, and no confidence/acceptance mechanism was built for the semantic
signal this phase (Section 9 explains why). The honest comparison this phase can make
is: deterministic retrieval has a real, audited, confidence-gated end-to-end pipeline
producing 14/48 fully-correct answers; semantic retrieval, evaluated as a raw
candidate-recall system with no such gate, would need a comparable gate built and
validated (a whole additional project, not attempted this phase) before its own
"fully correct" number could be honestly measured. What Section 6/8 *can* say is
whether the raw candidates it generates are worth gating at all.

**Query latency is a genuine, real semantic advantage**, worth stating plainly:
82–170ms vs. ~3.1s on the largest repo — semantic search over a pre-built dense index
is fundamentally cheaper per query than deterministic's `retrieve_context()` pipeline
(which includes real-repository edge reconciliation and per-candidate structural
scoring, not just ranking).

## 8. Complementarity Analysis

For every one of the 88 real ground-truth symbols, classified by presence in
deterministic's real top-50 candidate pool (`search()`, `candidate_pool_size=50`) vs.
each semantic model's real top-50:

| Classification | TF-IDF+LSA | GloVe |
|---|---:|---:|
| Both (D ∩ S) | 27/88 (30.7%) | 27/88 (30.7%) |
| Deterministic-only | 30/88 (34.1%) | 30/88 (34.1%) |
| **Semantic-only** | **5/88 (5.7%)** | **8/88 (9.1%)** |
| Neither | 26/88 (29.5%) | 23/88 (26.1%) |

**Semantic-only recovery is real and non-zero — this is not merely reproducing BM25**
— but it is small, and asymmetric: deterministic-only recovery (30/88) is roughly
4–6x larger than semantic-only recovery (5–8/88) for both models. Union recall
(`run_hybrid.py`, derived from the same matrix): TF-IDF+LSA brings deterministic's own
57/88 (64.8%) up to 62/88 (70.5%); GloVe brings it up to 65/88 (73.9%). A real, modest
gain (+6 to +9 percentage points), not a transformative one.

**Deterministic-failure recovery** (the 34 queries whose deterministic grade is not
TRUE, 66 ground-truth symbols): TF-IDF+LSA surfaces at least one needed symbol in its
top-50 for 14/34 queries (41.2%); GloVe for 16/34 (47.1%). At the tighter top-10
window (closer to what a real acceptance mechanism would actually use), this drops to
8/34 (23.5%) for both models. **The information is present in the corpus for a
meaningful fraction of deterministic's failures — but "present somewhere in a top-50
raw ranking" is a different, weaker claim than "would be accepted as a correct
answer,"** exactly the same reachable-vs.-accepted distinction the deterministic phase
itself repeatedly had to hold apart (candidate pool size, Fix 9's rejected relative
mechanisms).

## 9. Negative-Query Analysis (mandatory)

All 8 negative queries, both models, no aggregate-hiding:

| Query | Repo | TF-IDF+LSA top-1 score | GloVe top-1 score |
|---|---|---:|---:|
| `flask-13` | Flask | 0.686 | 0.850 |
| `flask-14` | Flask | 0.456 | 0.820 |
| `fastapi-13` | FastAPI | 0.614 | 0.830 |
| `fastapi-14` | FastAPI | 0.710 | 0.860 |
| `sqla-13` | SQLAlchemy | 0.766 | 0.849 |
| `sqla-14` | SQLAlchemy | 0.721 | 0.830 |
| `django-13` | Django | 0.674 | 0.875 |
| `django-14` | Django | 0.738 | 0.783 |

**Every single negative query produces a substantial top-1 semantic similarity score
under both models — none is anywhere near zero.** Compared directly against the
positive-query top-1 score distribution measured the same way (48 answerable queries,
same models, same representation):

| | Negative-query top-1 range | Positive-query top-1 range (median) |
|---|---|---|
| TF-IDF+LSA | 0.456 – 0.766 | 0.468 – 0.878 (median 0.675) |
| GloVe | 0.783 – 0.875 | 0.788 – 0.942 (median 0.898) |

**The negative-query range sits almost entirely inside the positive-query range for
both models. There is no similarity value that would separate "genuinely answerable"
from "genuinely unanswerable" queries in either model.** This is not a threshold-tuning
gap — it is the exact same structural failure the deterministic phase already found and
rejected for purely relative signals (Fix 3's original z-score-alone design, and Fix
9's percentile/z-score/margin coverage mechanisms): **every candidate pool has a "most
similar" entity, whether or not anything in the pool is actually a correct answer.** A
raw cosine-similarity threshold, however tuned, could not reliably separate Veyra's own
8 negative queries from its 48 positive ones.

Per Section 9's mandatory constraint, `semantic_score` was never treated as
`confidence` anywhere in this experiment — no threshold was applied to accept or reject
any candidate. This finding is reported as risk evidence for *any future* threshold-
based mechanism, not as a live leak in a system that doesn't have an acceptance gate.

## 10. Performance Measurements

| Repo | Model | Index build (embed+represent) | Query latency (embed+search) |
|---|---|---:|---:|
| Flask (2,607) | TF-IDF+LSA | 2.5s | 3.6ms |
| Flask | GloVe | 1.8s | 1.4ms |
| FastAPI (13,891) | TF-IDF+LSA | 12.2s | 9.7ms |
| FastAPI | GloVe | 8.9s | 9.0ms |
| SQLAlchemy (87,782) | TF-IDF+LSA | 99.6s | 179.2ms |
| SQLAlchemy | GloVe | 67.6s | 208.6ms |
| Django (92,679) | TF-IDF+LSA | 90.9s | 82.9ms |
| Django | GloVe | 71.8s | 170.0ms |

Index build time is comparable to (LSA) or somewhat faster than (GloVe) deterministic's
own index build (~37s for Django); query latency is markedly faster (tens–hundreds of
milliseconds vs. ~3.1s for `retrieve_context()`) — a genuine advantage, already noted in
Section 7.

## 11. Resource Requirements

| | TF-IDF+LSA | GloVe (mean-pool) |
|---|---|---|
| Dimensionality | 200 (fit per-corpus via SVD) | 300 (fixed, pretrained) |
| Model weights, one-time | None — fit from the corpus itself | ~376MB download (`glove-wiki-gigaword-300.gz`), ~480MB loaded in memory (400k-word vocabulary) |
| Per-repo index storage (real, deduplicated — see note) | Flask 2.1MB, FastAPI 11.1MB, SQLAlchemy 70.2MB, Django 74.1MB | Flask 3.1MB, FastAPI 16.7MB, SQLAlchemy 105.3MB, Django 111.2MB |
| CPU/GPU | CPU only, both models | CPU only, both models |
| Memory (largest repo, Django, peak build) | ~500MB–1GB (TF-IDF sparse matrix + SVD) | ~500MB–1GB (embedding pass) + the one-time 480MB vocabulary |
| Licensing | scikit-learn (BSD), no model license | GloVe vectors: Public Domain Dedication and License (PDDL) |
| Operational complexity | Low — pure Python/scikit-learn, no external service | Low — one-time vocabulary download, then pure lookup |

**Note on the storage figures**: this experiment's own harness (`build_index.py`)
pickles the *shared* GloVe vocabulary object into every single repo's index file, so
the raw `.pkl` file sizes on disk (Flask 495MB, FastAPI 510MB, SQLAlchemy 607MB, Django
614MB — all real, all measured) grossly overstate GloVe's actual per-repo marginal
storage cost. The deduplicated numbers in the table above (`corpus_vecs` array size
alone: `n_entities × dimensionality × 4 bytes`) are the real, apples-to-apples
per-repo cost; the 480MB vocabulary is a one-time, shared cost regardless of how many
repositories are indexed. This is a real inefficiency in this experiment's own
prototype code, disclosed here rather than silently left to mislead the storage
comparison, and would need to be fixed (load the vocabulary once, reference it from
every repo's index) before any production use.

## 12. Auditability/Provenance Design

Every `SemanticCandidate` this experiment produced carries: `entity_id`,
`semantic_score` (the real cosine similarity, never fabricated or rounded away),
`rank`, `retrieval_source` (the exact model name — `tfidf-lsa` or `glove`),
`representation_version` (`"C"`, so a future representation change is distinguishable
from a model change), and `source_location` (the same real, extracted file:line
location deterministic retrieval already uses). For any semantic candidate, the system
can answer "why did this enter the candidate set" with a real, specific, reproducible
number and model identifier — never a fabricated explanation. This mirrors
`ConfidenceDecision`'s own discipline (a real `reason` string for every decision) even
though no acceptance/confidence layer was built this phase (Section 9).

## 13. Failure Analysis

The intended target case — natural-language/code-vocabulary mismatch, e.g.
`authenticate()` for "Where does authenticate check a user's credentials?" — was
checked directly against both models' real output. Neither model reliably surfaces
this class of case in a useful top-K either: the underlying problem (a correct
entity's own text, and now its *semantic* representation, still needs to be
distinctive enough in a large corpus to rank highly against everything else) is not
automatically solved by moving from lexical to a *weak* semantic signal — it recurs
in a different form. This is the central, sobering finding of this phase: **a weak
semantic signal does not by itself close the gap a weak lexical signal left open** —
recall degrades with corpus size for exactly the queries this phase set out to help.
The strongest evidence that a *stronger* semantic signal (a modern sentence-transformer)
might behave differently is exactly what this environment's network policy prevented
testing — see Section 14.

## 14. Risks

- **The evaluated models are not representative of the state of the art.** Every
  finding in this report is scoped to GloVe mean-pooling and TF-IDF+LSA — genuinely
  weaker techniques than a modern sentence-transformer, which was categorically
  unavailable in this environment (Section 3). A NO-GO read of this report's evidence
  cannot be extrapolated to "semantic retrieval in general doesn't work for Veyra" —
  only to "these two specific, real, reproducible techniques don't clear the bar in
  this environment."
- **Corpus-size degradation is unexplained, not just unfixed.** Recall dropping from
  ~50% (Flask) to single digits (FastAPI/Django) was measured, not diagnosed to a root
  cause this phase — a legitimate open question for whoever picks this up next.
- **No acceptance/confidence mechanism exists for either model** — Section 9's
  negative-query finding means building one is a real, nontrivial problem, not a
  formality, and the deterministic phase's own multi-pass history (Fix 3, Fix 9)
  shows this kind of mechanism design is exactly where the hard, iterative work lives.
- **Harness inefficiency** (Section 11's duplicated-vocabulary storage bug) means the
  performance numbers here are a lower bound on what a properly engineered
  implementation would cost, not an upper bound — real production engineering would
  likely be cheaper than what's reported, not more expensive.

## 15. Recommendation

```
NO-GO (for these two specific models, in this environment, as evaluated)
CONDITIONAL GO on re-evaluation with a modern sentence-transformer model,
if and when that becomes reachable.
```

Neither GloVe mean-pooling nor TF-IDF+LSA clears the bar the directive itself set:

- **Candidate recall**: real and non-trivial (Recall@50 36–40% aggregate) but degrades
  sharply exactly where it would matter most — the larger, more realistic repositories
  (FastAPI/SQLAlchemy/Django all under 20% Recall@10).
- **Complementarity**: real and non-zero (5–9% semantic-only recovery) but small and
  asymmetric — deterministic-only recovery is 4–6x larger. This is evidence semantic
  retrieval *can* find things deterministic structurally cannot, which is the right
  kind of evidence to have — just not evidence of a capability strong enough on its own
  to justify the engineering cost of a hybrid architecture with these two models.
- **Negative safety**: the clearest NO on its own — no threshold on either model's raw
  similarity score would reliably distinguish Veyra's real negative queries from its
  real positive ones. Any hybrid design combining these signals with confidence
  would need to solve this from scratch, with no existing signal to lean on.
- **Performance**: the one clear win (query latency), not by itself sufficient
  justification for an architecture change.

This NO-GO is scoped honestly, not treated as closing the semantic-retrieval question
generally: **the single largest unresolved variable is that this environment's network
policy blocked evaluation of the class of model (modern sentence-transformers) most
likely to behave differently** — particularly on the corpus-size degradation (Section
6/13) and the negative-query separability (Section 9), both of which a contextual,
much richer embedding could plausibly handle better than a static, non-contextual one.
**Recommendation for whoever picks this up next**: re-run this exact experiment
harness (`experiments/semantic_retrieval/`) against a real sentence-transformer model
in an environment where `huggingface.co` (or an equivalent model host) is reachable,
before concluding semantic retrieval cannot help Veyra at all. The harness, the
representation (C), the recall/negative-query/complementarity measurement scripts, and
the real 48-query/8-negative-query benchmark are all already built and reusable —
only the model itself needs to change.
