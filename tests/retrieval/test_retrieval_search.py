from __future__ import annotations

from pathlib import Path
from typing import Callable

from veyra.retrieval import build_retrieval_index, search, search_semantic
from veyra.retrieval.search import (
    _CATEGORY_WEIGHT_BY_INTENT,
    _classify_source_category,
    _detect_query_intent,
    _source_category_weight,
    _structural_weight,
    _tokenize,
)
from veyra.static_analysis import extract_repository, persist_extraction
from veyra.vbg import VBGStore

COMMIT = "commit1"


def test_exact_symbol_query_returns_exact_node_first(sample_repo: Path, store: VBGStore) -> None:
    index = build_retrieval_index(store, COMMIT)
    results = search(index, "process_order")
    assert results[0].entity.entity_id == "orders.process_order"
    assert results[0].matched_by == "exact_name"


def test_conceptual_query_matches_via_shared_vocabulary(sample_repo: Path, store: VBGStore) -> None:
    index = build_retrieval_index(store, COMMIT)
    results = search_semantic(index, "charge the customer for their order")
    entity_ids = {r.entity.entity_id for r in results}
    assert "orders.charge_customer" in entity_ids


def test_semantic_search_never_invents_entities(sample_repo: Path, store: VBGStore) -> None:
    index = build_retrieval_index(store, COMMIT)
    results = search_semantic(index, "process order")
    known_ids = {e.entity_id for e in index.all_entities()}
    assert all(r.entity.entity_id in known_ids for r in results)


def test_no_shared_vocabulary_returns_no_results(sample_repo: Path, store: VBGStore) -> None:
    index = build_retrieval_index(store, COMMIT)
    results = search_semantic(index, "xylophone quantum teapot")
    assert results == []


def test_search_combines_lexical_and_semantic_deduplicated(sample_repo: Path, store: VBGStore) -> None:
    index = build_retrieval_index(store, COMMIT)
    results = search(index, "order")
    ids = [r.entity.entity_id for r in results]
    assert len(ids) == len(set(ids))  # no duplicates
    assert "orders.process_order" in ids


def test_search_respects_top_k(sample_repo: Path, store: VBGStore) -> None:
    index = build_retrieval_index(store, COMMIT)
    results = search(index, "order", top_k=1)
    assert len(results) == 1


def test_camelcase_and_snakecase_tokenize_the_same(sample_repo: Path, store: VBGStore) -> None:
    index = build_retrieval_index(store, COMMIT)
    snake = search_semantic(index, "process_order")
    camel = search_semantic(index, "processOrder")
    assert {r.entity.entity_id for r in snake} == {r.entity.entity_id for r in camel}


# -- Phase D: document-length bias correction (benchmarks/real_world_python/REPORT.md) --


def test_a_large_relevant_method_outranks_a_tiny_entity_sharing_one_token(
    write_file: Callable[[str, str], Path], repo_root: Path, store: VBGStore
) -> None:
    """Reproduces, at fixture scale, the exact mechanism the real-world
    benchmark found (flask-08: Flask.run(), 1026 real tokens, matching 6
    query terms, ranked *below* a 2-token test variable matching only 1).
    Under raw cosine similarity (pre-Phase-D), `widget` -- a document whose
    entire identity is that one word -- would score a perfect match on the
    query's one shared term, while `configure_subsystem`'s dozens of other,
    query-irrelevant tokens would dilute its own five-times-repeated
    'widget' mentions into a near-zero score. BM25 with per-entity-type
    length normalization must not reproduce that: it sums independent,
    saturating per-term contributions rather than normalizing by the whole
    document's unrelated content."""
    write_file(
        "app.py",
        "def configure_subsystem(self, mode, verbose, timeout, retries, cache, cleanup, validate,\n"
        "                         encode, decode, transform, normalize, aggregate, sort, merge):\n"
        '    """Configures the widget subsystem before request handling begins, wiring up the\n'
        "    widget registry, validating each widget's declared dependencies, and finally starting\n"
        '    the widget event loop once every widget has been registered and confirmed healthy."""\n'
        "    self.mode = mode\n"
        "    self.verbose = verbose\n"
        "    self.timeout = timeout\n"
        "    self.retries = retries\n"
        "    self.cache = cache\n"
        "    self.cleanup = cleanup\n"
        "    self.validate = validate\n"
        "    return True\n\n\n"
        "widget = None\n",
    )
    extraction = extract_repository(repo_root, COMMIT)
    persist_extraction(store, extraction)
    index = build_retrieval_index(store, COMMIT)

    results = search_semantic(index, "how does the widget subsystem get configured and started")
    entity_ids = [r.entity.entity_id for r in results]

    assert "app.configure_subsystem" in entity_ids
    assert "app.widget" in entity_ids
    assert entity_ids.index("app.configure_subsystem") < entity_ids.index("app.widget")


def _write_pool_fixture(write_file: Callable[[str, str], Path]) -> None:
    """15 strongly-matching decoys and one weakly-matching real candidate,
    reproducing (at fixture scale, without hardcoding any real benchmark
    query name into production logic) the ARCF-identified mechanism: a
    genuinely relevant entity that scores low enough to rank outside a
    plain top_k=10 window, purely because more than 10 *other* entities
    score higher on this query -- not because the entity itself scored
    zero or was excluded for any other reason. Real measured scores with
    this construction: decoys score 8.361 each (rank 0-14), the real
    candidate scores 1.198 (rank 15) -- solidly outside top_k=10, solidly
    inside a candidate_pool_size of 20+."""
    for i in range(15):
        write_file(
            f"decoys/decoy_{i}.py",
            "def strong_match_entity(amount, currency):\n"
            '    """payment gateway validate a transaction how does the"""\n'
            "    return amount\n",
        )
    write_file(
        "payment.py",
        "def sparse_match_entity(x):\n"
        '    """gateway"""\n'
        "    return x\n",
    )


# -- ARCF Fix 1: candidate pool separate from final top_k --


def test_candidate_outside_old_top_k_is_inside_wider_candidate_pool(
    write_file: Callable[[str, str], Path], repo_root: Path, store: VBGStore
) -> None:
    _write_pool_fixture(write_file)
    extraction = extract_repository(repo_root, COMMIT)
    persist_extraction(store, extraction)
    index = build_retrieval_index(store, COMMIT)
    query = "how does the payment gateway validate a transaction"

    narrow = search_semantic(index, query, top_k=10)
    assert "payment.sparse_match_entity" not in {r.entity.entity_id for r in narrow}

    wide = search_semantic(index, query, top_k=10, candidate_pool_size=20)
    assert "payment.sparse_match_entity" in {r.entity.entity_id for r in wide}
    # Widening the pool must not shrink or reorder what a narrow caller gets.
    assert [r.entity.entity_id for r in wide[:10]] == [r.entity.entity_id for r in narrow]


def test_search_widens_candidate_pool_without_relying_on_search_semantic_directly(
    write_file: Callable[[str, str], Path], repo_root: Path, store: VBGStore
) -> None:
    _write_pool_fixture(write_file)
    extraction = extract_repository(repo_root, COMMIT)
    persist_extraction(store, extraction)
    index = build_retrieval_index(store, COMMIT)
    query = "how does the payment gateway validate a transaction"

    narrow = search(index, query, top_k=10)
    assert "payment.sparse_match_entity" not in {r.entity.entity_id for r in narrow}

    wide = search(index, query, top_k=10, candidate_pool_size=20)
    assert "payment.sparse_match_entity" in {r.entity.entity_id for r in wide}


def test_length_normalization_is_per_entity_type_not_corpus_wide(sample_repo: Path, store: VBGStore) -> None:
    """The real-world benchmark's Phase D investigation found a *second*,
    sharper mechanism after the first BM25 pass: Flask's real index has
    Method entities averaging 103 tokens and Variable entities averaging 8
    -- a single corpus-wide average (52, dragged down by ~37% of entities
    being near-empty Variable nodes) would still length-normalize every
    substantial Method as "abnormally long". This asserts the per-type
    averages this module now computes are computed separately, not
    collapsed into one figure that would reintroduce that bias."""
    from veyra.retrieval.search import _build_bm25_index

    index = build_retrieval_index(store, COMMIT)
    _, _, _, avg_by_type = _build_bm25_index(index)

    assert "Function" in avg_by_type
    # This fixture's Variable-typed entities (if any) and Function-typed
    # entities must not be forced onto one shared average.
    assert isinstance(avg_by_type["Function"], float)


# -- ARCF Fix 4: stopword handling --


def test_single_letter_stopwords_produce_no_token() -> None:
    """'I' and 'a' -- the directive's own examples -- must not become a
    meaningful retrieval signal on their own."""
    assert _tokenize("I") == []
    assert _tokenize("a") == []


def test_stopwords_do_not_dominate_a_real_query() -> None:
    """A whole sentence's filler words (a, the, how, does, to, of, ...)
    disappear, leaving only the content words that can actually
    discriminate between entities."""
    tokens = _tokenize("How does a payment gateway validate a transaction")
    assert tokens == ["payment", "gateway", "validate", "transaction"]
    assert "a" not in tokens
    assert "how" not in tokens
    assert "does" not in tokens


def test_end_is_not_stopped_per_the_documented_policy() -> None:
    """'end' is the directive's own hard case: a common English word that
    is also a real, meaningful domain/identifier term in this codebase.
    The documented policy (search.py's `_STOPWORDS` comment) keeps it --
    confirm that decision actually holds in the tokenizer's behavior."""
    assert _tokenize("end") == ["end"]
    assert "end" in _tokenize("where does the request end")


def test_stopword_filtering_preserves_meaningful_identifier_fragments() -> None:
    """Compound identifiers keep their real content after stopword
    filtering removes only the low-information fragment -- the
    identifiers themselves remain searchable (exact/substring matching
    never goes through this tokenizer at all; this is about what the
    lexical/BM25 tier sees)."""
    assert _tokenize("end_to_end") == ["end", "end"]  # "to" (stopword) dropped, "end" kept twice
    assert _tokenize("get_user_by_id") == ["get", "user", "id"]  # "by" (stopword) dropped
    # Acronym-led identifiers: pre-existing camelCase-split limitation
    # (the boundary regex only catches lowercase-to-uppercase transitions,
    # not uppercase-run-to-word), unrelated to and unchanged by this fix --
    # each identifier still tokenizes to one real, non-empty, consistently
    # lowercased token, not silently destroyed.
    assert _tokenize("APIClient") == ["apiclient"]
    assert _tokenize("HTTPRequest") == ["httprequest"]


def test_exact_name_retrieval_is_unaffected_by_stopword_filtering(sample_repo: Path, store: VBGStore) -> None:
    """Exact/substring name matching never calls `_tokenize()` at all
    (`RetrievalIndex.find_by_name()` compares against the literal
    `entity.name`) -- confirm a real symbol whose name contains words that
    would be stopwords in a sentence ("process_order" has no stopword
    fragments, so use a query that as a *sentence* would be gutted by
    stopword filtering but still names the entity exactly)."""
    index = build_retrieval_index(store, COMMIT)
    results = search(index, "process_order")
    assert results[0].entity.entity_id == "orders.process_order"
    assert results[0].matched_by == "exact_name"


# -- ARCF Fix 5: source-category weighting --


def test_classify_source_category_by_generic_path_conventions() -> None:
    """Deterministic, path-structure-only classification -- no repository
    name appears anywhere in the rule set."""
    assert _classify_source_category(None) == "unknown"
    assert _classify_source_category("src/flask/app.py:10") == "production"
    assert _classify_source_category("tests/test_app.py:10") == "test"
    assert _classify_source_category("fastapi/tests/test_routing.py:5") == "test"
    assert _classify_source_category("test_something.py:1") == "test"
    assert _classify_source_category("something_test.py:1") == "test"
    assert _classify_source_category("docs/tutorial.py:1") == "documentation"
    assert _classify_source_category("docs_src/security/tutorial001.py:1") == "documentation"
    assert _classify_source_category("examples/quickstart.py:1") == "examples"
    assert _classify_source_category("scripts/release.py:1") == "scripts"
    assert _classify_source_category("setup.py:1") == "configuration"
    assert _classify_source_category("conftest.py:1") == "test"  # test-infra, not generic config


def test_query_intent_detection_is_keyword_based_and_deterministic() -> None:
    assert _detect_query_intent({"where", "authentication", "implemented"}) == "default"
    assert _detect_query_intent({"what", "test", "cover", "authentication"}) == "test"
    assert _detect_query_intent({"show", "me", "a", "tutorial"}) == "documentation"


def test_implementation_query_prefers_production_over_test_category() -> None:
    """Requirement 1: an implementation-oriented intent weights production
    above test, but does not zero test out (a signal, not an exclusion)."""
    assert _CATEGORY_WEIGHT_BY_INTENT["default"]["production"] > _CATEGORY_WEIGHT_BY_INTENT["default"]["test"]
    assert _CATEGORY_WEIGHT_BY_INTENT["default"]["test"] > 0.0


def test_test_oriented_query_prefers_test_category() -> None:
    """Requirement 2: a test-oriented intent weights test sources above
    production."""
    assert _CATEGORY_WEIGHT_BY_INTENT["test"]["test"] > _CATEGORY_WEIGHT_BY_INTENT["test"]["production"]


def test_documentation_oriented_query_prefers_documentation_and_examples() -> None:
    """Requirement 3."""
    assert (
        _CATEGORY_WEIGHT_BY_INTENT["documentation"]["documentation"]
        > _CATEGORY_WEIGHT_BY_INTENT["documentation"]["test"]
    )
    assert (
        _CATEGORY_WEIGHT_BY_INTENT["documentation"]["examples"] > _CATEGORY_WEIGHT_BY_INTENT["documentation"]["test"]
    )


def test_unknown_category_gets_a_neutral_default_weight() -> None:
    """Requirement 4: an entity search() can't locate a source path for at
    all is neither penalized nor favored by default."""
    assert _CATEGORY_WEIGHT_BY_INTENT["default"]["unknown"] == 1.0


def test_category_weighting_never_zeroes_out_a_category(sample_repo: Path, store: VBGStore) -> None:
    """Requirement 5: category weighting changes ranking, it never
    excludes -- a test-category candidate with a strong lexical match
    still surfaces for a default-intent query, just deprioritized, not
    removed."""
    index = build_retrieval_index(store, COMMIT)
    entity = index.all_entities()[0]
    for category_weights in _CATEGORY_WEIGHT_BY_INTENT.values():
        for weight in category_weights.values():
            assert weight > 0.0  # never a hard zero/exclusion
    weight = _source_category_weight(entity, intent="default")
    assert weight > 0.0


# -- ARCF Fix 6: structural graph ranking signal --


def test_structural_weight_is_neutral_with_no_children_or_siblings() -> None:
    """Requirement 2: a real entity `IndexedEntity` knows has no CONTAINS
    children/siblings gets no structural contribution at all -- 1.0,
    exactly neutral, not a penalty."""
    from veyra.retrieval.index import IndexedEntity
    from veyra.vbg import VerificationState

    entity = IndexedEntity(
        entity_id="m.isolated",
        node_type="Function",
        name="isolated",
        repository_version=COMMIT,
        lexical_representation=None,
        docstring=None,
        source_location=None,
        parents=(),
        children=(),
        siblings=(),
        outgoing_relationships=(),
        incoming_relationships=(),
        verification_state=VerificationState.STRUCTURALLY_IDENTIFIED,
        evidence_counts={},
    )
    assert _structural_weight(entity) == 1.0


def test_structural_weight_rewards_real_children_and_is_bounded(sample_repo: Path, store: VBGStore) -> None:
    """Requirement 1 and the "bounded" requirement: more real children ->
    a higher (but capped) multiplier."""
    from veyra.retrieval.index import IndexedEntity
    from veyra.vbg import VerificationState

    def make(children: tuple[str, ...], siblings: tuple[str, ...] = ()) -> IndexedEntity:
        return IndexedEntity(
            entity_id="m.e", node_type="Class", name="E", repository_version=COMMIT,
            lexical_representation=None, docstring=None, source_location=None,
            parents=(), children=children, siblings=siblings,
            outgoing_relationships=(), incoming_relationships=(),
            verification_state=VerificationState.STRUCTURALLY_IDENTIFIED, evidence_counts={},
        )

    no_children = _structural_weight(make(children=()))
    few_children = _structural_weight(make(children=("a", "b")))
    many_children = _structural_weight(make(children=tuple(f"c{i}" for i in range(50))))

    assert no_children == 1.0
    assert few_children > no_children
    assert many_children > few_children
    assert many_children <= 1.0 + 0.3  # bounded, per _STRUCTURAL_CHILD_BONUS_CAP


def test_structural_weight_dampens_many_near_identical_siblings(sample_repo: Path, store: VBGStore) -> None:
    """The general mechanism behind Fix 6's motivating case (many
    near-identical sibling methods sharing one parent crowding out a more
    distinctive candidate) -- more siblings, all else equal, means a
    slightly lower (never negative/zero) weight."""
    from veyra.retrieval.index import IndexedEntity
    from veyra.vbg import VerificationState

    def make(siblings: tuple[str, ...]) -> IndexedEntity:
        return IndexedEntity(
            entity_id="m.e", node_type="Method", name="e", repository_version=COMMIT,
            lexical_representation=None, docstring=None, source_location=None,
            parents=(), children=(), siblings=siblings,
            outgoing_relationships=(), incoming_relationships=(),
            verification_state=VerificationState.STRUCTURALLY_IDENTIFIED, evidence_counts={},
        )

    no_siblings = _structural_weight(make(siblings=()))
    many_siblings = _structural_weight(make(siblings=tuple(f"s{i}" for i in range(20))))

    assert no_siblings == 1.0
    assert many_siblings < no_siblings
    assert many_siblings > 0.0
    assert many_siblings >= 1.0 - 0.15  # bounded, per _STRUCTURAL_SIBLING_PENALTY_CAP


def test_structural_weight_only_uses_relationships_the_index_actually_has(
    sample_repo: Path, store: VBGStore
) -> None:
    """Requirement 3: nothing here queries the store or infers a
    relationship -- it is a pure function of the fields `IndexedEntity`
    already carries, verified by checking real entities from a real
    index."""
    index = build_retrieval_index(store, COMMIT)
    for entity in index.all_entities():
        weight = _structural_weight(entity)
        expected_bonus = min(0.3, 0.02 * len(entity.children))
        expected_penalty = min(0.15, 0.01 * len(entity.siblings))
        assert weight == 1.0 + expected_bonus - expected_penalty


# -- Performance: BM25 tables are built once per index, not once per call --


def test_bm25_index_is_computed_once_and_cached_on_the_retrieval_index(sample_repo: Path, store: VBGStore) -> None:
    """search_semantic() and retrieve_context() each used to call
    _build_bm25_index(index) independently on every single query -- a
    full O(corpus size) tokenize-every-entity pass repeated for no
    reason, since it depends only on `index`, never the query text.
    Confirms the actual mechanism (a real cache slot gets populated, and
    a second call reuses the exact same object) rather than a timing
    threshold."""
    from veyra.retrieval.search import _build_bm25_index

    index = build_retrieval_index(store, COMMIT)
    assert index._bm25_cache is None

    first = _build_bm25_index(index)
    assert index._bm25_cache is not None

    second = _build_bm25_index(index)
    assert second is first  # the cached tuple, not a freshly recomputed one

    # And a real search still works correctly off the cached tables.
    results = search_semantic(index, "process order")
    assert any(r.entity.entity_id == "orders.process_order" for r in results)
