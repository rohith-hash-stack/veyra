"""
PLAN.md Milestone 4, Phase 4.2 -- Semantic Repository Retrieval.

**A real, stated scope decision**: "semantic" here means lightweight
lexical token-overlap scoring, computed in pure Python over each
`IndexedEntity`'s name/docstring/lexical text -- NOT embedding-based
semantic search. A true embedding model is a materially heavier dependency
(a real ML library, likely GPU-friendly infra, a much bigger footprint than
anything else this project has added) that nothing has reviewed or
approved; a stdlib-only lexical technique gives real, useful conceptual-
query relevance ranking without that cost -- the same "start with the
minimum real thing, not the maximum possible thing" discipline as
Hypothesis's use in Phase 3.3b (there: a genuine new dependency was
justified and added; here: a stdlib-only technique is judged sufficient
for this slice). This is a real, honest limitation, not hidden:
token-overlap scoring will miss true paraphrases with no shared
vocabulary (e.g. "how does auth work" won't score `check_credentials`
without a shared token). Revisit if this proves insufficient once run
against real repositories and an embedding dependency is explicitly
approved.

"exact symbol queries retrieve exact nodes" is `RetrievalIndex.find_by_name()`
(Phase 4.1) directly -- not re-implemented here. "lexical + semantic
retrieval combinable" is `search()`: exact/substring name matches (always
ranked first, since a query that literally names a symbol should always
surface it) unioned with lexical-scored matches, deduplicated by entity_id.
"retrieval never invents graph entities" holds structurally -- every
`ScoredEntity` wraps a real `IndexedEntity`, itself always built from a
real Node (Phase 4.1). "evidence accompanies retrieved entities" is
already true since `IndexedEntity` carries `verification_state`/
`evidence_counts` on every result.

**Retrieval-quality remediation, Phase D -- document-length bias
correction.** The real-world benchmark (benchmarks/real_world_python/
REPORT.md, root cause 1) found that raw cosine-similarity over TF-IDF
vectors systematically ranks near-empty documents (a `Variable` node
whose entire indexed text is its own one-word name) above large, genuinely
correct documents (a `Method`/`Class` whose `lexical_representation` is
hundreds of tokens of real source). This was root-caused with real
numbers before any fix was written
(benchmarks/real_world_python/scripts/instrument_tfidf_ranking.py):
for the query "What happens when app.run() is called with debug=True?",
`Flask.run` (1026 raw tokens, 228 unique terms) matched 6 of the query's
terms but scored *lower* than a `called` variable (2 tokens total, the
whole "document" is one repeated word) that matched exactly one term.
The mechanism, confirmed directly: cosine similarity normalizes every
document to a unit vector regardless of how much real content it has --
a document that is *entirely* about one word will always look "100%
relevant" to any query touching that word, no matter how irrelevant the
word actually is to the query's intent, while a document about hundreds
of things gets that one relevant word diluted across everything else
it's about.

**The fix: Okapi BM25** in place of raw cosine similarity for the
lexical-tier score -- the standard, decades-established information-
retrieval technique built specifically for this pathology (term-frequency
saturation + tunable document-length normalization), not a speculative
swap. It keeps the same bag-of-words token model (`_tokenize`/
`_entity_text` unchanged -- stopword filtering is Phase C's job, not
touched here) and the same three-tier `search()` structure (exact ->
substring -> lexical); only the scoring math inside the lexical tier
changed. Unlike cosine similarity, BM25 sums independent, saturating
per-matched-term contributions rather than normalizing by the full
document vector's norm across every term (matched or not) -- so a
document's score no longer gets penalized merely for containing many
*other*, query-irrelevant concepts, while `_BM25_B`'s length
normalization still prevents unboundedly long documents from winning
purely on raw token volume.
"""

from __future__ import annotations

import math
import re
from collections import Counter
from dataclasses import dataclass

from .index import IndexedEntity, RetrievalIndex

_TOKEN_RE = re.compile(r"[A-Za-z0-9]+")

# Standard BM25 defaults (Robertson/Sparck Jones); not tuned against this
# benchmark's pass rate (the remediation plan explicitly forbids that) --
# these are the field-standard starting values, kept because nothing here
# has evidence they should move.
_BM25_K1 = 1.5  # term-frequency saturation: higher = repeated terms keep mattering longer
_BM25_B = 0.75  # length normalization: 0 = ignore document length, 1 = fully normalize by it


# ARCF Fix 4 -- stopword policy.
#
# A small, fixed set of closed-class English function words: articles,
# pronouns, prepositions, conjunctions, and a handful of common auxiliary/
# question verbs ("does", "is", "how", "where", ...). These are the words
# the directive's own examples ("I", "a") point at -- terms that carry
# almost no discriminative signal on their own and mostly show up as
# natural-language query filler ("how does X work") or as single-letter
# loop/parameter names in code (`for i in range(...)`, `def f(a, b)`).
#
# Deliberately excluded from this list: short but domain-meaningful words
# that happen to also be common English words -- "end" (the directive's own
# example of the hard case) is a real, frequent, meaningful token in this
# codebase's domain (request/session/range boundaries, "end_to_end", etc.),
# not a closed-class function word, so it is NOT stopped. The same
# reasoning keeps "start"/"before"/"after"/"between" out of the list. When
# in doubt, a word stays -- BM25's own IDF term already suppresses truly
# uninformative high-document-frequency tokens mathematically; this list
# only removes words informative enough to slightly skew scores but never
# informative enough to be a real answer signal.
#
# Applied identically to query tokens and to indexed-entity document
# tokens (the same _tokenize() call both go through) -- filtering only one
# side would silently break BM25's IDF math, which assumes both operate on
# the same vocabulary.
#
# This never touches exact_name/substring_name matching (search.py's
# `search()` calls `RetrievalIndex.find_by_name()` directly against the
# untokenized `entity.name`) -- a real identifier is always findable by
# its literal name regardless of this policy.
_STOPWORDS = frozenset(
    {
        "a", "an", "the",
        "i", "you", "he", "she", "it", "we", "they",
        "this", "that", "these", "those",
        "is", "are", "was", "were", "be", "been", "being",
        "do", "does", "did", "doing",
        "have", "has", "had", "having",
        "to", "of", "in", "on", "at", "by", "for", "with", "as", "from",
        "and", "or", "but", "not", "no",
        "how", "what", "where", "when", "why", "which", "who", "whom",
        "so", "if", "than", "then", "there", "here",
        "its", "their", "his", "her", "my", "your", "our",
    }
)


def _tokenize(text: str) -> list[str]:
    """Splits on non-alphanumeric boundaries AND camelCase/snake_case word
    boundaries (lowercased), so `processOrder`/`process_order`/"process
    order" all tokenize to the same {"process", "order"} -- a small,
    deliberate concession that materially improves symbol-name matching
    without needing any real NLP dependency. ARCF Fix 4: closed-class
    English function words (`_STOPWORDS`) are dropped *after* that
    camelCase/snake_case split, so a compound identifier like `is_valid`
    keeps its meaningful part (`valid`) and only loses the low-information
    fragment (`is`) -- the identifier itself remains fully searchable via
    exact/substring name matching either way, since those never call this
    function at all."""
    tokens: list[str] = []
    for raw in _TOKEN_RE.findall(text):
        # split camelCase: "processOrder" -> "process", "Order"
        parts = re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", raw).split()
        tokens.extend(p.lower() for p in parts if p.lower() not in _STOPWORDS)
    return tokens


def _entity_text(entity: IndexedEntity) -> str:
    parts = [entity.name]
    if entity.docstring:
        parts.append(entity.docstring)
    if entity.lexical_representation:
        parts.append(entity.lexical_representation)
    return " ".join(parts)


@dataclass(frozen=True)
class ScoredEntity:
    entity: IndexedEntity
    score: float
    matched_by: str  # "exact_name" | "substring_name" | "tfidf"


def _build_bm25_index(
    index: RetrievalIndex,
) -> tuple[dict[str, Counter], dict[str, int], dict[str, float], dict[str, float]]:
    """Precomputes BM25's per-document term counts, document lengths, and
    inverse document frequencies once per index build, reused across every
    query issued against it (same "build once, query many times" contract
    `RetrievalIndex` itself already documents).

    **Performance finding, actually made true here, not just claimed:**
    `search_semantic()` and (since Fix 3) `retrieve_context()` each used
    to call this function independently -- a full O(corpus size)
    tokenize-every-entity pass repeated on *every single query*, despite
    depending only on `index`, never the query text. `index._bm25_cache`
    (a generic slot `RetrievalIndex` itself owns) makes this genuinely
    "once per index build": computed on the first call against a given
    `index` instance, reused by every call after, regardless of which
    function asked.

    **Length normalization is computed per `node_type`, not one corpus-wide
    average.** Measured directly against Flask's real index (Phase D):
    `Method` documents average 103 tokens, `Class` documents average 282,
    while `Variable` documents average 8 and `Module` documents average 4 --
    a single global average (52, dragged down by the ~37% of entities that
    are near-empty `Variable` nodes) would still length-normalize every
    substantial `Method`/`Class` body as "abnormally long" relative to a
    corpus average that mostly describes one-line variables, re-introducing
    the same bias BM25 was chosen to fix. Normalizing each entity against
    its own type's typical length is the standard field/category-length-
    normalization technique for exactly this kind of heterogeneous corpus."""
    if index._bm25_cache is not None:
        return index._bm25_cache  # type: ignore[return-value]
    entities = index.all_entities()
    doc_tokens: dict[str, Counter] = {e.entity_id: Counter(_tokenize(_entity_text(e))) for e in entities}
    doc_lengths = {entity_id: sum(tokens.values()) for entity_id, tokens in doc_tokens.items()}

    document_frequency: Counter = Counter()
    for tokens in doc_tokens.values():
        document_frequency.update(tokens.keys())

    n = max(len(entities), 1)
    # The "+1.0 inside the log" (Lucene-style) BM25 IDF variant -- stays
    # positive even for a term appearing in most documents, unlike the
    # classic Robertson-Sparck-Jones IDF, which can go negative and
    # therefore *penalize* a match on a very common term.
    idf = {term: math.log((n - df + 0.5) / (df + 0.5) + 1.0) for term, df in document_frequency.items()}

    lengths_by_type: dict[str, list[int]] = {}
    for entity in entities:
        lengths_by_type.setdefault(entity.node_type, []).append(doc_lengths[entity.entity_id])
    avg_doc_length_by_type = {t: sum(lengths) / len(lengths) for t, lengths in lengths_by_type.items()}

    result = (doc_tokens, doc_lengths, idf, avg_doc_length_by_type)
    index._bm25_cache = result
    return result


def _bm25_score(
    query_terms: set[str],
    doc_tokens: Counter,
    doc_length: int,
    idf: dict[str, float],
    avg_doc_length_for_type: float,
) -> float:
    """Okapi BM25 -- sums a saturating, length-normalized contribution per
    matched query term, rather than cosine similarity's whole-vector
    normalization (see module docstring, Phase D, for why that distinction
    is exactly what fixes the confirmed document-length bias). Length is
    normalized against `avg_doc_length_for_type` -- the calling entity's
    own `node_type` average, not one corpus-wide figure (see
    `_build_bm25_index`)."""
    if avg_doc_length_for_type <= 0:
        return 0.0
    score = 0.0
    length_norm = 1 - _BM25_B + _BM25_B * (doc_length / avg_doc_length_for_type)
    for term in query_terms:
        f = doc_tokens.get(term)
        if not f:
            continue
        score += idf.get(term, 0.0) * (f * (_BM25_K1 + 1)) / (f + _BM25_K1 * length_norm)
    return score


# ARCF Fix 5 -- source-category weighting.
#
# A deterministic, path-structure classification of every entity's
# `source_location` into a small fixed set of categories -- no repository
# name, no benchmark-specific directory, nothing here names Flask, FastAPI,
# SQLAlchemy, or Django. Every rule is a generic path-segment convention
# real Python projects widely share (a "tests/" directory, a "docs"-
# prefixed directory, an "examples/" directory, a "scripts/" directory) --
# the same conventions this benchmark's own 4 real repositories all
# happen to follow, which is exactly why this generalizes rather than
# being tuned to any one of them.
_TEST_PATH_SEGMENTS = frozenset({"test", "tests"})
_DOC_PATH_PREFIX = "doc"  # catches "docs", "doc", "docs_src", "documentation"
_EXAMPLE_PATH_SEGMENTS = frozenset({"examples", "example", "samples", "sample", "demo", "demos"})
_SCRIPT_PATH_SEGMENTS = frozenset({"scripts", "script", "tools", "bin"})
_CONFIG_FILENAMES = frozenset({"setup.py", "conftest.py", "pyproject.toml", "tox.ini"})
_CONFIG_EXTENSIONS = frozenset({".cfg", ".ini", ".toml", ".yaml", ".yml"})


def _classify_source_category(source_location: str | None) -> str:
    """One of "test" | "documentation" | "examples" | "scripts" |
    "configuration" | "production" | "unknown", derived purely from
    `source_location`'s path structure -- deterministic, auditable (call
    it directly on any entity to see exactly why it was classified a
    given way), and identical logic regardless of which repository the
    path came from."""
    if not source_location:
        return "unknown"
    path = source_location.split(":")[0]  # strip ":line" or ":line-line" suffix
    segments = [s.lower() for s in re.split(r"[/\\]", path) if s]
    if not segments:
        return "unknown"
    filename = segments[-1]
    filename_stem, _, ext = filename.rpartition(".")
    ext = f".{ext}" if ext else ""

    if filename in _CONFIG_FILENAMES and filename != "conftest.py":
        return "configuration"
    if ext in _CONFIG_EXTENSIONS:
        return "configuration"
    if any(seg in _TEST_PATH_SEGMENTS for seg in segments) or filename_stem == "conftest" or filename_stem.startswith(
        "test_"
    ) or filename_stem.endswith("_test"):
        return "test"
    if any(seg.startswith(_DOC_PATH_PREFIX) for seg in segments[:-1]):
        return "documentation"
    if any(seg in _EXAMPLE_PATH_SEGMENTS for seg in segments):
        return "examples"
    if any(seg in _SCRIPT_PATH_SEGMENTS for seg in segments):
        return "scripts"
    return "production"


_TEST_INTENT_TERMS = frozenset({"test", "tests", "testing"})
_DOC_INTENT_TERMS = frozenset({"doc", "docs", "documentation", "tutorial", "tutorials", "example", "examples"})


def _detect_query_intent(query_terms: set[str]) -> str:
    """Deterministic, keyword-based (not repository- or benchmark-
    specific) query-intent classification: "test" | "documentation" |
    "default". A query mentioning test/testing prefers test sources; one
    mentioning docs/tutorial/example prefers documentation/example
    sources; everything else defaults to preferring production
    implementation -- the common case for "where is X implemented"-shaped
    questions."""
    if query_terms & _TEST_INTENT_TERMS:
        return "test"
    if query_terms & _DOC_INTENT_TERMS:
        return "documentation"
    return "default"


# Bounded multipliers, not filters -- every value stays within roughly
# +/-25% of 1.0, so even a query's least-preferred category is still
# reachable when its lexical match is strong enough; nothing is ever
# excluded outright. Chosen as a modest, symmetric nudge (not tuned to
# any individual query's outcome) -- the same order of magnitude as
# `_structural_weight`'s bound below, so neither signal alone can dominate
# a strong BM25 score.
_CATEGORY_WEIGHT_BY_INTENT: dict[str, dict[str, float]] = {
    "default": {
        "production": 1.15,
        "unknown": 1.0,
        "scripts": 0.95,
        "configuration": 0.95,
        "examples": 0.9,
        "documentation": 0.9,
        "test": 0.8,
    },
    "test": {
        "test": 1.25,
        "unknown": 1.0,
        "scripts": 0.95,
        "production": 0.9,
        "configuration": 0.9,
        "examples": 0.85,
        "documentation": 0.85,
    },
    "documentation": {
        "documentation": 1.25,
        "examples": 1.2,
        "production": 1.0,
        "unknown": 1.0,
        "scripts": 0.9,
        "configuration": 0.9,
        "test": 0.8,
    },
}


def _source_category_weight(entity: IndexedEntity, intent: str) -> float:
    """The actual per-entity multiplier -- a pure function of the
    entity's own classified category and the query's classified intent,
    both independently inspectable/auditable via
    `_classify_source_category`/`_detect_query_intent`."""
    category = _classify_source_category(entity.source_location)
    return _CATEGORY_WEIGHT_BY_INTENT[intent].get(category, 1.0)


# ARCF Fix 6 -- structural graph ranking signal.
#
# Uses only relationships `IndexedEntity` already carries -- real, verified
# CONTAINS-derived edges computed once at index-build time (`index.py`),
# never re-queried or inferred here. No CALLS-based signal: the ARCF
# inspection measured real CALLS resolution rates of 7.7-12% across all 4
# benchmark repositories (`python_extractor.py`'s self/cls-and-bare-name-
# only resolution model), so a CALLS-based structural signal would be
# built on data that's ~90% missing -- not a "verified relationship," an
# absent one for the large majority of real call sites. CONTAINS, by
# contrast, is structural (derived directly from the AST, not from call
# resolution) and is essentially fully populated (~97-99% of nodes have a
# real CONTAINS parent in the measured repositories).
#
# The signal: an entity with many real children (a class containing many
# methods) is more likely to be a genuine "hub" answer than an entity with
# none; an entity with many siblings (one of many methods on the same
# parent) is, on its own, less individually distinctive than one with few
# -- directly targeting the discovered mechanism where several near-
# identical sibling methods (FastAPI's near-duplicate HTTP-verb
# convenience methods) collectively crowd out their own parent class or an
# unrelated, more specific function. This is a general shape (many
# similar siblings sharing a parent), not anything FastAPI-specific.
_STRUCTURAL_CHILD_BONUS_PER_CHILD = 0.02
_STRUCTURAL_CHILD_BONUS_CAP = 0.3
_STRUCTURAL_SIBLING_PENALTY_PER_SIBLING = 0.01
_STRUCTURAL_SIBLING_PENALTY_CAP = 0.15


def _structural_weight(entity: IndexedEntity) -> float:
    """Bounded multiplier in [1 - cap, 1 + cap] derived only from
    `entity.children`/`entity.siblings` -- real, already-resolved CONTAINS
    edges (`index.py`'s `_build_entity`), zero additional storage queries.
    Never negative, never zero -- a structural disadvantage can dampen a
    match, never remove it: a signal, not an exclusion."""
    child_bonus = min(_STRUCTURAL_CHILD_BONUS_CAP, _STRUCTURAL_CHILD_BONUS_PER_CHILD * len(entity.children))
    sibling_penalty = min(
        _STRUCTURAL_SIBLING_PENALTY_CAP, _STRUCTURAL_SIBLING_PENALTY_PER_SIBLING * len(entity.siblings)
    )
    return 1.0 + child_bonus - sibling_penalty


def search_semantic(
    index: RetrievalIndex, query: str, top_k: int = 10, candidate_pool_size: int | None = None
) -> list[ScoredEntity]:
    """BM25 lexical ranking -- see module docstring for exactly what
    "semantic" does and doesn't mean here, and for Phase D's document-
    length-bias fix this function embodies.

    **ARCF Fix 1 -- candidate pool separate from final top_k.** Every
    entity in `index` is already fully scored and sorted below (an O(N)
    pass this function always did, regardless of `top_k` -- truncating
    later costs nothing extra). `candidate_pool_size`, when given,
    overrides `top_k` for that truncation -- letting a caller (`search()`,
    `retrieve_context()`) consider a wider slice of the real ranking than
    it ultimately returns, so a correctly-scored entity a fixed small
    `top_k` used to cut before anything downstream ever saw it (the
    original benchmark's `fastapi-01`/`fastapi-03`/`flask-08` failure
    mechanism -- see PHASE_D_RESULTS.md) can still reach later ranking/
    confidence stages. `top_k` alone (no `candidate_pool_size`) keeps this
    function's old, single-parameter behavior for direct callers.

    **ARCF Fixes 5 & 6.** After the raw BM25 score, two independent,
    bounded, explainable multiplicative adjustments are applied (see
    `_source_category_weight`/`_structural_weight` docstrings for what
    each does and why) -- both are ranking *signals*, not filters:
    nothing is ever excluded for its category or its graph position,
    every adjustment stays within a bounded range so a genuinely strong
    lexical match can never be fully overridden by either."""
    doc_tokens, doc_lengths, idf, avg_doc_length_by_type = _build_bm25_index(index)
    query_terms = set(_tokenize(query))
    if not query_terms:
        return []
    intent = _detect_query_intent(query_terms)

    scored = [
        ScoredEntity(
            entity=entity,
            score=(
                _bm25_score(
                    query_terms,
                    doc_tokens[entity.entity_id],
                    doc_lengths[entity.entity_id],
                    idf,
                    avg_doc_length_by_type.get(entity.node_type, 0.0),
                )
                * _source_category_weight(entity, intent)
                * _structural_weight(entity)
            ),
            matched_by="tfidf",
        )
        for entity in index.all_entities()
    ]
    scored = [s for s in scored if s.score > 0.0]
    scored.sort(key=lambda s: (-s.score, s.entity.entity_id))
    limit = candidate_pool_size if candidate_pool_size is not None else top_k
    return scored[:limit]


def search(
    index: RetrievalIndex, query: str, top_k: int = 10, candidate_pool_size: int | None = None
) -> list[ScoredEntity]:
    """Combines exact-name, substring-name, and TF-IDF results, deduplicated
    by entity_id -- exact matches always rank first (score 2.0), substring
    matches next (score 1.0), TF-IDF results fill the rest.

    With no `candidate_pool_size` (the default, and every pre-Fix-1
    caller/test), behaves exactly as before: returns at most `top_k`
    entities total. When a caller explicitly passes `candidate_pool_size`
    wider than `top_k` -- `retrieve_context()` does exactly this -- this
    function returns up to `candidate_pool_size` entities *without*
    re-truncating to `top_k` itself; the caller is expected to apply its
    own downstream filtering (confidence, in `retrieve_context()`'s case)
    across that wider pool and only *then* cut to its own final `top_k`.
    `search()` still guarantees "no more than the requested pool size" --
    it just isn't the one deciding what the *final* returned size is once
    a caller has explicitly asked for a wider pool to filter from. A query
    that is itself a real symbol name always surfaces that symbol,
    regardless of what TF-IDF alone would have ranked it."""
    seen: set[str] = set()
    results: list[ScoredEntity] = []

    for entity in index.find_by_name(query, exact=True):
        if entity.entity_id not in seen:
            seen.add(entity.entity_id)
            results.append(ScoredEntity(entity=entity, score=2.0, matched_by="exact_name"))

    for entity in index.find_by_name(query, exact=False):
        if entity.entity_id not in seen:
            seen.add(entity.entity_id)
            results.append(ScoredEntity(entity=entity, score=1.0, matched_by="substring_name"))

    limit = candidate_pool_size if candidate_pool_size is not None else top_k
    for scored in search_semantic(index, query, top_k=top_k, candidate_pool_size=limit):
        if scored.entity.entity_id not in seen:
            seen.add(scored.entity.entity_id)
            results.append(scored)

    return results[:limit]

    results.sort(key=lambda s: (-s.score, s.entity.entity_id))
    return results[:top_k]
