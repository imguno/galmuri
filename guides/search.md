# Configure and evaluate search

English · [한국어](search.ko.md) · [README](../README.md)

This guide covers **Galmuri 0.2.0**. Version 0.1.0 used substring search and
character-window defaults; see [upgrade steps](#upgrade-an-existing-project)
before upgrading an existing deployment.

## Defaults

An App with only a source still works. Keyword search uses an inverted postings
index and BM25 in either SQLite or PostgreSQL. Publication, updates and withdrawal
update that index in the same metadata transaction. Queries rank matching postings
and load authorized candidate bodies, rather than copying every document into Python.

Text uses Unicode NFKC normalization and case folding. Word identifiers such as
`user_id` stay whole. Word terms are required; Korean matching uses Hangul bigrams
across whitespace and requires at least half the query's distinct bigrams.
This tolerates some particles and spacing changes but is **not morphological
analysis**. Partial matches and false positives remain possible. Blank or
punctuation-only queries return no results. Query limits are 4,096 characters and
128 distinct analyzed terms.

Short words with longer particles can still be missed: a document containing
`문서` alone need not match `문서에서`. Evaluate domain-specific queries; this default
does not claim Korean morphological recall.

BM25 scores use statistics from the App's active corpus, including inaccessible
documents. Results contain only currently authorized documents; scores are
relative rankings, not probabilities or confidence. Vector mode keeps its own
generation and permission checks.

## Change the query policy

```python
from galmuri import App
from galmuri.retrieval import RetrievalConfig, SearchConfig, ReciprocalRankFusion
from .source.local import source

sample = App(
    name="sample",
    source=source,
    retrieval=RetrievalConfig(
        mode="hybrid",
        search=SearchConfig(
            fusion=ReciprocalRankFusion(k=20, lexical_weight=2, vector_weight=1),
            candidate_limit=200,
        ),
    ),
)
```

The default is equal-weight RRF with `k=60`. Hybrid uses up to
`min(candidate_limit, max(64, 4 * limit))` candidates per ranking. The cap is
1–1,000; it can limit the number of returned documents. Changing this query policy
does not regenerate embeddings.

A lexical function can query another index without replacing the framework search
service:

```python
from galmuri.retrieval import SearchCandidate, SearchConfig

def lookup(query, *, app, limit):
    hits = external_index.search(app=app, query=query, limit=limit)
    return tuple(SearchCandidate(hit.document_key, hit.score) for hit in hits)

search = SearchConfig(lexical=lookup)
```

`external_index` is your configured client. Return unique IDs and finite scores
in descending order, at most `limit` candidates. IDs refer to documents already
published in that App. Unknown or unauthorized IDs do not expose content. Your
external index's ingestion/update/deletion is your adapter's responsibility.
Inaccessible results can use up its candidate window; tune its scope accordingly.
Candidates carry IDs and scores, not an external index generation. Galmuri loads
current authorized contents but cannot prove an external score matched that exact
content version. Keep the external index current; body/ACL checks do not repair
stale rankings.

Pass a function to `fusion=` to use another method. It receives a read-only mapping
with `lexical` and `vector` tuples of `SearchCandidate`, and returns an ordered
iterable of unique candidates drawn from those inputs. It receives no document
bodies. The framework checks current permissions, source intent and generation
again after consuming the function or generator. Invalid results fail explicitly.
`describe` exposes the selected query policy and built-in lexical analyzer.

## Chunks and models

Default chunks respect Markdown headings, paragraphs and fenced code. A document
stays one document; chunk offsets still point into the exact published text.
Large blocks are split. This is a block scanner, not a complete CommonMark AST.

When FastEmbed and the default chunker are used, a copy of the model's tokenizer
further splits chunks to fit its actual input limit, including special tokens.
The tokenizer/model load occurs during indexing, not App configuration.
Custom `Chunker`/`ChunkingConfig` remains supported; `CharacterChunker` is explicit.
For a custom tokenizer use `TokenBudgetChunker(base, count_tokens, max_tokens,
identity="your-tokenizer-v1")`. Your counter must include prefixes/special tokens
and count the complete input without truncation.

FastEmbed rejects oversized explicit chunks and queries rather than silently
dropping their suffix. Inspect failed indexing work, change the chunking policy,
activate, and reindex. Other embedding adapters own their input-limit behavior.

The lightweight default remains multilingual MiniLM-L12 (384 dimensions,
128-token input). That limit is why character count alone is insufficient.
[Official model card](https://huggingface.co/sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2).
Choose another model using `RetrievalConfig(embedding=...)`; evaluate it on your
own documents before paying its memory/latency cost. For E5-large, explicitly
include its required prefixes:

```python
from galmuri.retrieval import FastEmbedEmbedding, RetrievalConfig

retrieval = RetrievalConfig(
    embedding=FastEmbedEmbedding(
        "intfloat/multilingual-e5-large",
        passage_prefix="passage: ",
        query_prefix="query: ",
    ),
)
```

Those prefixes participate in the embedding identity. E5-large requires
substantially more memory than MiniLM; dimension count is not a quality guarantee.
[E5 usage requirements](https://huggingface.co/intfloat/multilingual-e5-large).

## Upgrade an existing project

Stop its servers and workers together; mixed old/new writers are unsupported.
Back up its state as for any schema upgrade. The first upgraded Runtime backfills
the lexical index under the metadata writer lock, so large existing corpora delay
startup. The built-in parser and default chunker identities changed:

```sh
python manage.py activate
python manage.py sync
python manage.py index-status
```

Wait for ingestion and vector jobs to finish before restoring traffic. Resume
workers if more jobs remain. Explicitly configured chunkers keep their identities;
search-policy changes alone do not require embedding rebuilds.

## Measure your workload

From a source checkout:

```sh
python -m tools.search_quality \
  --output .verification/search-quality.json \
  --documents 100 1000 3000
```

This publishes a frozen synthetic bilingual corpus through Runtime, adds the
requested number of distractors, and compares indexed search with the exact former
substring algorithm. It reports individual rankings, positive-query Top1/MRR@3,
negative-query false positives and warmed median timings. Small corpora may be
slower with an index. This fixture is a regression aid, not a Korean benchmark
or evidence that one model wins. Add domain relevance judgments separately.
