# Build your first document service

English · [한국어](build-an-integration.ko.md) · [Overview](../README.md)

Build a service that reads article files, turns them into searchable documents,
and provides them to other applications. Start by generating a project and its
first app, then write a JSON parser and an output adapter in that app's project.
Galmuri runs the connected implementations and manages document updates, access
checks, and recovery.

This tutorial starts with one **Galmuri App**: one source connection together with
its processing, retrieval and execution policies. A project can register several
Apps. Exporters expose these Apps through the shared service. A RAG application
can consume those documents while keeping its own LLM and answer logic.

This guide uses **Galmuri 0.2.0**. The first example disables vector indexing, so it needs
no model download, model API key, or external service. See
[search configuration](search.md) for search options and existing-state upgrades.
Use Python 3.12 or newer. Shell examples below use Linux/macOS syntax.
Duru is installed as a dependency; no separate Duru checkout is required.

## 1. Generate your project

Install Galmuri, then create a project and its first app:

```sh
python3 -m venv .venv
. .venv/bin/activate
python -m pip install 'galmuri[mcp]==0.2.0'
python -m galmuri startproject catalog
cd catalog
python manage.py startapp sample
mkdir -p apps/sample/views
touch apps/sample/views/__init__.py
```

In the generated `config/settings.py`, register the app:

```python
APPS = ["apps.sample.app:sample"]
```

The remaining changes are to your project files. Make them **before your first sync**.

The generated `apps/sample/source/local.py` connects a Duru read-only local provider
to `apps/sample/fixtures/`. Keep it for this example. Duru handles file IO; your parser
receives an already-read `File`. For your own API connector, implement the
[Duru provider contract](https://github.com/imguno/duru#extend-the-contract) and
connect that provider through the same `App.source` field.

## 2. Add a document and a parser

Create `apps/sample/fixtures/article.json`:

```json
{
  "title": "Observatory handbook",
  "body": "A quasar is the bright active nucleus of a distant galaxy."
}
```

Create `apps/sample/views/articles.py`:

```python
import json

from galmuri import Document, File
from galmuri.parsing import parse_auto


def parse_article(file: File) -> tuple[Document, ...]:
    name = str(file.ref.metadata.get("name", ""))
    if not name.lower().endswith(".json"):
        return parse_auto(file)

    record = json.loads(file.text)
    if not isinstance(record, dict):
        raise ValueError("An article must be a JSON object")
    title, body = record["title"], record["body"]
    if not isinstance(title, str) or not isinstance(body, str):
        raise ValueError("Article title and body must be strings")

    return (
        Document(
            key=file.ref.key,
            text=f"{title}\n\n{body}",
            metadata={**file.ref.metadata, "title": title, "format": "article"},
        ),
    )
```

The input contains byte `content`, decoded `text` and a `ref` with the source key,
version and metadata. The output is a tuple of `Document` values: each has a stable
`key`, searchable `text` and JSON-serializable `metadata`. This parser keeps one
document per file and uses the source key as its document key. Existing sample
Markdown files continue through `parse_auto`.

Your parser may call a library such as an HTML or PDF parser instead of `json.loads`.
Translate that library's result to the same `Document` contract. Parsing runs during
processing; registering the function does not execute it.

## 3. Connect the parser to the App

Replace `apps/sample/app.py` with:

```python
from galmuri import App, IngestConfig, ParsingConfig

from .source.local import source
from .views.articles import parse_article

sample = App(
    name="sample",
    source=source,
    parser=ParsingConfig(process=parse_article, revision="1"),
    ingestion=IngestConfig(readers=("*",), writers=()),
    retrieval=None,
)
```

Pass the function reference `parse_article`, not `parse_article(...)`. The default
processing path calls it and prepares the returned documents for publication.
Here `IngestConfig` explicitly makes the documents readable and denies document
writes. The local source is also read-only.

Keep the App registration you added to `config/settings.py` in step 1:

```python
APPS = ["apps.sample.app:sample"]
```

Keep the rest of that file. A second source can have its own `apps/manuals/app.py`
and App object; add its import path to `APPS` when you create it. Each App can choose
its own source, parser, schedule and database/vector-store configuration.

## 4. Publish and verify what your parser produced

Run from `catalog/`:

```sh
python manage.py sync
python manage.py call describe --app sample
python manage.py call search --app sample --mode lexical --query quasar
```

The search response's result list should include your article, with `text` beginning
`Observatory handbook` and `metadata.format` equal to `article`. Its `key` is an
opaque source-derived identifier; use the returned value rather than reconstructing
it from the file name.

To read that document, replace `KEY_FROM_SEARCH` with the returned key:

```sh
python manage.py call read --app sample --params '{"document_key":"KEY_FROM_SEARCH"}'
```

Edit the JSON body, then run `sync` again to process the new source version. If you
change the parser's behavior, increment `ParsingConfig.revision` in `app.py`, then run:

```sh
python manage.py activate
python manage.py sync
```

Activation accepts the changed processing contract and fences old work; function
source code is not automatically hashed. Deleting a source file is also detected
through the local provider on a later sync.

## Connect your RAG client

Keep your LLM and answer construction in your existing application. With this
project synced, an MCP client can call `sample_describe`, `sample_search` and
`sample_read`. The source is read-only, so `sample_write` is not registered.

For clients using an `mcpServers` configuration, replace both absolute paths:

```json
{
  "mcpServers": {
    "catalog": {
      "command": "/absolute/path/to/.venv/bin/python",
      "args": [
        "/absolute/path/to/catalog/manage.py",
        "serve",
        "mcp",
        "--workers",
        "0"
      ]
    }
  }
}
```

This uses the documents already synced in the tutorial. Run workers separately or
omit `--workers 0` if this server should process new changes. The project root is
resolved from `manage.py`, so the client need not choose a working directory.
Client-specific configuration locations differ; the process command and arguments
are the same.

Still inside `catalog/`, create `mcp_client.py` beside `manage.py`:

```python
import asyncio
import sys
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


async def main() -> None:
    project = Path(__file__).resolve().parent
    server = StdioServerParameters(
        command=sys.executable,
        args=[str(project / "manage.py"), "serve", "mcp", "--workers", "0"],
    )
    async with stdio_client(server) as (reader, writer):
        async with ClientSession(reader, writer) as session:
            await session.initialize()
            result = await session.call_tool(
                "sample_search", {"query": "quasar", "mode": "lexical"}
            )
            print(result.structuredContent)


if __name__ == "__main__":
    asyncio.run(main())
```

Run `python mcp_client.py` in the same environment. This retrieves public documents
without an LLM. Your RAG application can feed the returned content and source keys to
its chosen model.

For restricted documents, create an account-bound token with the account commands
and set `FRAMEWORK_TOKEN_FILE` in the server's environment to its private absolute
file path. Account names in tool arguments do not authenticate a user. HTTP, gRPC
and CLI expose the same service; see [accounts and exposure](reference.md#exposure-adapters).

## 5. Enable embeddings (optional)

Add this import to your existing `apps/sample/app.py`:

```python
from galmuri import RetrievalConfig
```

In the existing App declaration, change only `retrieval=None` to
`retrieval=RetrievalConfig(mode="hybrid")`. Keep your source, parser revision,
and document permissions.

Omitted providers now select local multilingual FastEmbed and the App database's
default vector store. The first inference downloads model weights; `EMBEDDING_CACHE`
can point to an existing cache. Then run:

```sh
python manage.py activate
python manage.py sync
python manage.py index-status --app sample
python manage.py call search --app sample --mode vector --query "What shines at a galaxy's center?"
```

Check that the relevant vector builds are `PUBLISHED` before judging semantic
search. Document publication and vector publication are separate; a completed sync
can leave a failed build or a retry scheduled for later. Use `index --drain` to
process currently eligible builds, and inspect failures with `index-status`.

To choose a different model and store, create `apps/sample/retrieval.py`:

```python
import os

from galmuri import RetrievalConfig
from galmuri.retrieval import FastEmbedEmbedding, QdrantVectorStore

retrieval = RetrievalConfig(
    embedding=FastEmbedEmbedding(
        model="sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2",
        cache_dir=os.environ.get("EMBEDDING_CACHE"),
    ),
    store=QdrantVectorStore(
        url=os.environ["QDRANT_URL"],
        api_key=os.environ.get("QDRANT_API_KEY"),
    ),
    mode="hybrid",
)
```

This alternative requires a reachable Qdrant service and `QDRANT_URL`. Import its
object into `app.py` with `from .retrieval import retrieval` and replace the
`retrieval=RetrievalConfig(...)` argument with `retrieval=retrieval`. Activate the
change and check index status again. No parser or RAG answer code needs to change.

Existing `Chunker`, `EmbeddingProvider` and `VectorStore` implementations can be
passed directly. Function-based adapters use `ChunkingConfig` and `EmbeddingConfig`.
See the [input/output contracts](reference.md#retrieval-input-and-output-contracts).
[SearchConfig](search.md) also connects a lexical search function
or a fusion strategy without replacing the repository service.

## Processing and permission defaults

Changing one parser keeps the default preparation and publication path. For several
document transformations, `python manage.py startapp articles --process` creates
`views/` functions connected through `Pipeline.default().then(Step(...))`.
Register the new app in `APPS` before running it.

| Declaration | When `retrieval` is omitted | Who prepares document grants |
| --- | --- | --- |
| Default processing, optionally `parser=...` | Local embeddings/vector store | Built-in preparation uses `IngestConfig` and settings fallbacks |
| `process=Pipeline(...)` | Local embeddings/vector store | A document-ending pipeline prepares grants; a terminal `IngestResult` supplies its own |
| `process=my_function` or legacy `handler=my_function` | Lexical-only | Your function returns `IngestResult` with explicit grants |

A plain custom process can opt into indexing with `retrieval=RetrievalConfig()`.
Its input is `File`; its output is `IngestResult`, not a database write or a log line.
Do not combine a plain process with App `parser`/`ingestion` options: that function
already owns those steps.

`DEFAULT_PERMISSIONS` supplies omitted `IngestConfig` grants in the built-in and
document-ending pipeline preparation paths. It does not rewrite a custom terminal
`IngestResult`. A `Document` created with no grant arguments has empty grants.
Document grants always remain subject to source capabilities and verified account
credentials.

## 6. Implement an exporter (optional)

The built-in exporters are exposure adapters for MCP, HTTP, gRPC and CLI. Your own
adapter receives `Service` and implements `run()`. It obtains authorized results
through that service, rather than opening the framework's database.

Create `exporters/__init__.py` as an empty file and `exporters/articles.py`:

```python
import json

from galmuri import Principal


class ArticleExporter:
    def __init__(self, service, *, app="sample", query="quasar", limit=100):
        self.service = service
        self.app, self.query, self.limit = app, query, limit

    def run(self):
        response = self.service.call(
            "search",
            {"app": self.app, "query": self.query, "mode": "lexical", "limit": self.limit},
            Principal(),
        )
        if not response["ok"]:
            raise RuntimeError(response["error"]["code"])
        for document in response["result"]:
            print(json.dumps(document, ensure_ascii=False, allow_nan=False))
```

In `config/settings.py`, import the class and replace `EXPOSURE_ADAPTERS = {}`:

```python
from ..exporters.articles import ArticleExporter

EXPOSURE_ADAPTERS = {"articles": ArticleExporter}
EXPOSURES["articles"] = {"app": "sample", "query": "quasar", "limit": 100}
```

Keep the existing HTTP/gRPC/MCP settings. Run the exporter after sync:

```sh
python manage.py serve articles --workers 0
```

It emits up to 100 public matching documents as JSON Lines and exits. The example
deliberately uses an anonymous `Principal()`: it cannot read restricted documents.
A network exporter needs a verified credential from an authenticator before calling
the service; request parameters must never establish user identity. The example
is a bounded search export, not a complete backup or an atomic corpus snapshot.
If an exporter sends data to another system, it owns that delivery, idempotency and
retry behavior. The exposure adapter interface does not supply a durable outbox.

## 7. Add a connector you implement yourself

Create a second app:

```sh
python manage.py startapp manuals
```

Instead of its generated local-folder connection, implement a source that serves
one immutable document through Duru's `Provider` interface.
Create `apps/manuals/source/manual.py`:

```python
import hashlib
import io

from duru import Conflict, NotFound, Provider, ResourceInfo


class GuideProvider(Provider):
    identity = "example-guide:v1"
    root_uri = "guide://manual"
    content = b"The quasar operations guide is supplied by a custom connector."

    def stat(self, uri):
        if uri != self.root_uri:
            raise NotFound("Unknown guide")
        snapshot = self.content
        return ResourceInfo(
            uri,
            "manual.txt",
            revision=hashlib.sha256(snapshot).hexdigest(),
            size=len(snapshot),
        )

    def open(self, uri, *, expected_revision=None):
        if uri != self.root_uri:
            raise NotFound("Unknown guide")
        snapshot = self.content
        revision = hashlib.sha256(snapshot).hexdigest()
        if expected_revision is not None and expected_revision != revision:
            raise Conflict("Guide revision changed")
        return io.BufferedReader(io.BytesIO(snapshot))
```

Replace `apps/manuals/app.py` with:

```python
from galmuri import App

from .source.manual import GuideProvider

manuals = App(name="manuals", source=GuideProvider(), retrieval=None)
```

Append to `config/settings.py`:

```python
APPS.append("apps.manuals.app:manuals")
```

Both Apps now run in one project:

```sh
python manage.py sync
python manage.py call search --app sample --query quasar
python manage.py call search --app manuals --query quasar
```

`sample` uses local files and a custom parser; `manuals` uses your connector and the
default parser. The same exporters can serve both. Each search explicitly selects
an App; consumers or custom exporters combine results across Apps when needed.
Multi-source support means several independently configured source Apps in one
project, not implicit cross-App ranking.
To reuse the earlier `articles` exporter for `manuals`, set
`EXPOSURES["articles"]["app"] = "manuals"` in settings before running it.

A connector for a real API replaces the example's byte source with its client
library. Preserve the contract: `stat` reports identity, display name and revision;
`open` returns a caller-owned binary snapshot that matches the requested revision
or raises `Conflict`. Never validate a version and then return unchecked mutable
bytes. Add `Listable` for collections; only advertise mutation interfaces the
underlying source can actually guarantee. Inject credentials through constructor
arguments from your deployment settings. Keep vendor IO in the connector and
document conversion in the parser.
