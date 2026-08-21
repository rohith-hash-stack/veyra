"""
Phase E, Section 5 -- semantic embedding backends.

Modern sentence-transformer models (SBERT, E5, BGE, MiniLM, etc.) are
almost universally hosted on huggingface.co, which this environment's
organization egress policy blocks (verified 403, logged as a policy
denial by the proxy -- not retried or routed around, per the proxy's own
operating instructions). See ../README.md. Two real, reproducible
alternatives obtainable from allowed hosts are evaluated instead:

- GloVe (`glove-wiki-gigaword-300`): real pretrained general-English word
  vectors (gensim-data, served from GitHub-hosted release assets, which
  this environment *can* reach), mean-pooled per document. Not code-aware,
  not contextual -- a real but weak semantic signal, disclosed as such.
- TF-IDF + Truncated SVD (LSA): a classic, fully local, zero-external-
  download "semantic" technique -- captures latent co-occurrence structure
  a document's literal words don't directly show, computed entirely from
  each repository's own corpus (so it's automatically code/repo-vocabulary
  aware, unlike GloVe's generic English training data).

Neither is a modern neural sentence embedding model. This is a real,
disclosed constraint on what this experiment's evidence can support,
not a claim that semantic retrieval in general has been fully evaluated.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

import numpy as np

_TOKEN_RE = re.compile(r"[A-Za-z0-9]+")


def _tokenize(text: str) -> list[str]:
    """Same camelCase/snake_case-aware splitting as production's
    `search._tokenize`, reimplemented here (not imported) to keep this
    experiment fully isolated from `src/veyra/retrieval/` -- see
    ../README.md. Deliberately does NOT drop stopwords: word-vector mean-
    pooling benefits from function words contributing to the average far
    less than production's discrete term-matching did, and removing this
    experiment's ability to independently verify that isn't worth the
    coupling to production's stopword list."""
    tokens: list[str] = []
    for raw in _TOKEN_RE.findall(text):
        parts = re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", raw).split()
        for part in parts:
            tokens.append(part.lower())
    return tokens


@dataclass(frozen=True)
class EmbeddingModel:
    name: str
    dimensionality: int
    embed_corpus_fn: object  # Callable[[list[str]], np.ndarray] -- fit + transform in one call
    embed_query_fn: object  # Callable[[str], np.ndarray] -- uses the fitted model


class GloveMeanPool:
    """Mean of each document's real GloVe word vectors -- the classic
    pre-transformer "semantic" document representation. Words absent from
    GloVe's vocabulary (very common for code identifiers: `wsgi_app`,
    `dispatch_request`) are simply skipped, not zero-padded or guessed --
    a document with zero recognized words gets an explicit all-zero
    vector, not a fabricated one."""

    name = "glove-wiki-gigaword-300"

    def __init__(self, keyed_vectors) -> None:
        self._kv = keyed_vectors
        self.dimensionality = keyed_vectors.vector_size

    def embed(self, texts: list[str]) -> np.ndarray:
        vectors = np.zeros((len(texts), self.dimensionality), dtype=np.float32)
        for i, text in enumerate(texts):
            tokens = _tokenize(text)
            word_vecs = [self._kv[t] for t in tokens if t in self._kv]
            if word_vecs:
                vectors[i] = np.mean(word_vecs, axis=0)
        return vectors

    def embed_query(self, text: str) -> np.ndarray:
        """Same mean-pooling as `embed()`, for a single query string --
        given the uniform `embed_query(text) -> np.ndarray` interface
        `TfidfLsa` also exposes, so downstream scripts don't need to know
        which model they're calling."""
        return self.embed([text])[0]


class TfidfLsa:
    """TF-IDF followed by truncated SVD (latent semantic analysis) --
    fit once on a repository's own corpus (`fit_corpus`), then every
    query is projected into that same fitted latent space (`embed_query`)
    -- never refit per query, exactly mirroring how a real embedding
    index is built once and queried many times."""

    name = "tfidf-lsa"

    def __init__(self, n_components: int = 200) -> None:
        from sklearn.decomposition import TruncatedSVD
        from sklearn.feature_extraction.text import TfidfVectorizer

        self.dimensionality = n_components
        self._vectorizer = TfidfVectorizer(tokenizer=_tokenize, token_pattern=None, min_df=1)
        self._svd = TruncatedSVD(n_components=n_components, random_state=0)
        self._fitted = False

    def fit_corpus(self, texts: list[str]) -> np.ndarray:
        tfidf = self._vectorizer.fit_transform(texts)
        # n_components must stay below min(n_samples, n_features) for TruncatedSVD.
        actual_components = min(self.dimensionality, tfidf.shape[1] - 1, tfidf.shape[0] - 1)
        if actual_components < self.dimensionality:
            from sklearn.decomposition import TruncatedSVD

            self._svd = TruncatedSVD(n_components=max(actual_components, 1), random_state=0)
        vectors = self._svd.fit_transform(tfidf)
        self._fitted = True
        return vectors.astype(np.float32)

    def embed_query(self, text: str) -> np.ndarray:
        if not self._fitted:
            raise RuntimeError("fit_corpus() must be called before embed_query()")
        tfidf = self._vectorizer.transform([text])
        return self._svd.transform(tfidf)[0].astype(np.float32)


def cosine_similarities(query_vec: np.ndarray, corpus_vecs: np.ndarray) -> np.ndarray:
    """Real cosine similarity -- a zero-norm vector (a document/query with
    no recognized words) gets similarity 0.0 against everything, not NaN
    or a fabricated non-zero score."""
    query_norm = np.linalg.norm(query_vec)
    corpus_norms = np.linalg.norm(corpus_vecs, axis=1)
    denom = corpus_norms * query_norm
    with np.errstate(divide="ignore", invalid="ignore"):
        sims = np.where(denom > 0, (corpus_vecs @ query_vec) / denom, 0.0)
    return sims
