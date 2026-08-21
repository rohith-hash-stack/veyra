# Coverage Denominator Experiments

Isolated, discussion-driven follow-ups to the root-cause finding that generic
framing verbs in a natural-language query (`call`, `actually`, `implement`,
`use`, ...) are not filtered by `_STOPWORDS`, and can consume 35-40% of a
query's coverage weight -- diluting the 0.5 floor for well-ranked, genuinely
correct candidates. Real cases traced end-to-end: `django-04`, `flask-04`,
`fastapi-04`'s `App.add_url_rule`/`FastAPI.add_api_route`.

Nothing here is imported by `src/veyra/`, and nothing in `src/veyra/` was
modified to run these. Each script monkeypatches the relevant production
function for the duration of its own process only, runs the real 4-repo/
56-query benchmark before and after, and writes its result JSON next to the
other benchmark results. **Neither experiment's change has been shipped.**

## `stopword_experiment.py` / `stopword_experiment_v2.py`

Tried extending `_STOPWORDS` (shared by both query and document tokenization)
with 14 candidate framing verbs.

- **v1** found a real negative-query regression: `django-13` flipped from
  correctly-rejected to leaking, because removing `implement` shrank the
  coverage denominator enough for unrelated `runserver`/production-warning
  test entities to newly clear the 0.5 floor.
- **v2** (12 words, `implement`/`implements` excluded) fixed that regression
  (0 negative-query changes) but surfaced a different, more fundamental
  problem: `_tokenize()` is shared between query and document text, so
  stripping a word to stop it diluting a *question's* denominator also
  strips it from ever counting as *matched evidence* when a document's own
  real text legitimately uses it. Confirmed directly: `fastapi.param_functions
  .Depends`'s own docstring says "Don't call it directly, FastAPI will call
  it for you" and describes being "used for dependency injection" --
  `call`/`called`/`use`/`used`/`handles` are real tokens in its own text, not
  query-only noise. Net result: 2 real gains (`django-04` recovers
  `authenticate()`, `sqla-08` recovers `Session.commit`) vs. 2 real losses
  (`fastapi-03` loses its sole correct answer `Depends` via a genuine
  coverage drop; `fastapi-04` loses its one recovered symbol via ranking
  crowding), 0 negative regressions.

**Conclusion: a blanket, shared-tokenizer stopword extension is the wrong
mechanism** -- these words are dual-purpose (framing noise in questions,
genuine content in some answers), not one-directional noise. A better-
targeted design (asymmetric treatment: exclude these words from coverage's
*denominator* while still crediting them in the *numerator* when genuinely
matched) was proposed but not yet built or tested.

## `structured_summary.py`

A different idea: instead of touching tokenization, append a small,
structured "fact sheet" to every entity's indexed text, built entirely from
real, already-persisted graph edges (CONTAINS/CALLS/INHERITS) -- "What does
X contain? What does X call? Who calls X? What does X inherit from?" --
rendered with short (last-segment) names to avoid reintroducing the dotted-
qualified-path noise the stopword experiment ran into. Supplements, does not
replace, the existing name+docstring+source text.

Result: 0 negative-query regressions (same clean safety property). 2 real
gains (`django-04` recovers `authenticate()` again -- a second, structurally
independent mechanism recovering the same case, a meaningfully reproducible
signal -- plus `flask-06` gains a third of its five needed symbols). 2 real
losses via two different mechanisms: `fastapi-05` loses `APIRoute` to
ranking crowding (still `accepted=True`, pushed outside `top_k=10`);
`fastapi-04` loses `FastAPI.add_api_route` to a *new* mechanism -- z-score
suppression, where uniformly-applied template phrasing across many corpus
entities appears to compress the query's candidate-pool score distribution,
making a genuinely good candidate stand out *less* in relative terms even
as its absolute coverage improved.

**Not shipped.** A promising, more encouraging trade-off than the stopword
experiment (no shared-tokenizer risk, the `authenticate()` recovery
reproduces via an independent mechanism), but still a real trade, not a
clean win -- would need the same negative-query and gain/loss validation
after any follow-up (e.g. down-weighting the structured block's contribution
to ranking while keeping its full contribution to coverage) before shipping.
