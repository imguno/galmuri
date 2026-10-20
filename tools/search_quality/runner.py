"""Publish a synthetic corpus through Runtime, then compare measured searches."""

import json
import platform
import sqlite3
import statistics
from pathlib import Path
from tempfile import TemporaryDirectory
from time import perf_counter

from galmuri import App, Change, ChangeSet, Document, File, FileRef, IngestResult, Principal
from galmuri.runtime import Runtime
from tools.search_quality.baseline import substring_search
from tools.search_quality.fixtures import QUERIES, corpus


class CorpusSource:
    """A versioned catalog whose ordinary processing emits multiple documents."""

    identity = "search-quality:synthetic-catalog:v1"

    def __init__(self, documents):
        self.content = json.dumps(documents, ensure_ascii=False).encode("utf-8")

    def changes(self, checkpoint):
        ref = self.current("catalog")
        return ChangeSet(() if checkpoint == "1" else (Change(ref),), "1")

    def current(self, key):
        if key != "catalog":
            raise FileNotFoundError(key)
        return FileRef(key, "1")

    def read(self, ref):
        return File(ref, self.content)


def prepare_catalog(file):
    return IngestResult(
        tuple(Document(key, text, readers=("*",)) for key, text in json.loads(file.text).items())
    )


def _measure(searches, query, repeats):
    samples = {name: [] for name in searches}
    results = {name: search(query) for name, search in searches.items()}
    # Alternate ordering after a warmup to reduce systematic cache/order bias.
    for repetition in range(repeats):
        ordered = list(searches.items())
        if repetition % 2:
            ordered.reverse()
        for name, search in ordered:
            start = perf_counter()
            current = search(query)
            samples[name].append((perf_counter() - start) * 1000)
            if current != results[name]:
                raise RuntimeError(f"Search results changed while timing {name}")
    return results, {name: statistics.median(values) for name, values in samples.items()}


def _judgment(query, matches, duration):
    keys = [match["key"] for match in matches]
    relevant = set(query.relevant)
    rank = next((rank for rank, key in enumerate(keys, 1) if key in relevant), None)
    return {
        "keys": keys,
        "relevant_hits": [key for key in keys if key in relevant],
        "false_positives": [key for key in keys if key not in relevant],
        "top1": bool(keys and keys[0] in relevant) if relevant else None,
        "reciprocal_rank_at_3": 1 / rank if rank else (0 if relevant else None),
        "median_ms": round(duration, 4),
    }


def _summary(rows, engine):
    positive = [row[engine] for row in rows if row["relevant"]]
    negative = [row[engine] for row in rows if not row["relevant"]]
    return {
        "positive_queries": len(positive),
        "top1": statistics.mean(item["top1"] for item in positive),
        "mrr_at_3": statistics.mean(item["reciprocal_rank_at_3"] for item in positive),
        "negative_queries": len(negative),
        "negative_query_false_positive_rate": statistics.mean(
            bool(item["keys"]) for item in negative
        ),
        "returned_false_positives_at_3": sum(len(row[engine]["false_positives"]) for row in rows),
        "median_of_query_medians_ms": statistics.median(row[engine]["median_ms"] for row in rows),
    }


def evaluate(distractors, repeats):
    documents = corpus(distractors)
    with TemporaryDirectory(prefix="galmuri-search-quality-") as temporary:
        runtime = Runtime(
            Path(temporary) / "state.sqlite",
            [App("corpus", CorpusSource(documents), prepare_catalog, retrieval=None)],
        )
        started = perf_counter()
        sync = runtime.sync()
        if sync["processed"] != 1:
            raise RuntimeError(f"Expected one ordinary catalog publication, got {sync}")
        with runtime.database.connection() as connection:
            published = connection.execute(
                "SELECT COUNT(*) FROM documents WHERE state='ACTIVE'"
            ).fetchone()[0]
        if published != len(documents):
            raise RuntimeError(f"Expected {len(documents)} active documents, got {published}")
        publication_ms = (perf_counter() - started) * 1000
        principal = Principal()
        searches = {
            "indexed": lambda query: runtime.search("corpus", query, principal, limit=3),
            "substring": lambda query: substring_search(
                runtime.database, "corpus", query, principal, limit=3
            ),
        }
        rows = []
        for query in QUERIES:
            results, durations = _measure(searches, query.text, repeats)
            rows.append(
                {
                    "name": query.name,
                    "query": query.text,
                    "behavior": query.behavior,
                    "relevant": list(query.relevant),
                    **{
                        engine: _judgment(query, results[engine], durations[engine])
                        for engine in searches
                    },
                }
            )
        # Selectivity affects indexed retrieval. Report a deliberately common
        # term separately rather than folding it into a favorable average.
        _, common_durations = _measure(searches, "ordinary", repeats)
        return {
            "distractors": distractors,
            "documents": published,
            "publication_ms": round(publication_ms, 3),
            "queries": rows,
            "summary": {engine: _summary(rows, engine) for engine in searches},
            "common_term_query": {
                "query": "ordinary",
                "median_ms": {
                    engine: round(duration, 4) for engine, duration in common_durations.items()
                },
            },
            "indexed_search_metadata": runtime.queries.describe("corpus", principal),
        }


def environment():
    return {
        "python": platform.python_version(),
        "sqlite": sqlite3.sqlite_version,
        "system": platform.system(),
        "machine": platform.machine(),
    }
