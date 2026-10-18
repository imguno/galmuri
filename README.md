# Galmuri

English · [한국어](README.ko.md)

Connect document sources, prepare searchable documents, and serve them to RAG
applications through MCP, HTTP, gRPC, or CLI.

Start with a local folder and the generated sample app. Replace parsing, document
transformations, embeddings, or vector storage as needed. Your RAG application
uses the document and search APIs to build answers.

**Status:** development preview. Install and import `galmuri`; the command is `galmuri`
or `python -m galmuri`. Source access is provided by the independent `duru` library.

## Contents

- [Use cases](#use-cases)
- [Quick start](#quick-start)
- [Your generated project](#your-generated-project)
- [Customize processing](#customize-processing)
- [Agent skill](#agent-skill)
- [Sources, models, and storage](#sources-models-and-storage)
- [Accounts and document access](#accounts-and-document-access)
- [Serve your app](#serve-your-app)
- [Commands and recovery](#commands-and-recovery)
- [Current limits](#current-limits)
- [Development](#development)

## Use cases

| You want to… | Start with… |
| --- | --- |
| Search a local folder from an MCP client | Default sample app, then `serve mcp` |
| Clean documents or add metadata before search | `new PATH --process`, then edit `views/` |
| Read Google Drive or Slack content | duru providers with your credentials and target IDs |
| Use a different model or vector store | `RetrievalConfig` on your App |
| Control document access by team | Dashboard accounts, groups, and document permissions |
| Run several processes with shared state | PostgreSQL and compatible app/account settings |

Included parsers handle text, Markdown, and Python source. Local multilingual
embeddings and SQLite vectors work with the default sample.

## Quick start

Requires **Python 3.12+**. Linux is the deployment target; the Dockerfile uses
Python 3.13. Install from local checkouts arranged as follows:

```text
workspace/
├── access/     # duru checkout
└── project/    # framework checkout
```

From `workspace/`:

```sh
cd project
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -e ../access -e '.[mcp,grpc]'

python -m galmuri new ./example
cd example
python manage.py sync
python manage.py call search --app sample --mode lexical --query welcome
python manage.py serve http
```

The sample includes `welcome.md` and `clinic.md`. Sync publishes their documents;
the search command returns matching document data. Browse them at
<http://127.0.0.1:8000/dashboard>. Stop the server with Ctrl+C.

The first embedding operation downloads model weights. Set `EMBEDDING_CACHE`
before sync to reuse a populated cache or keep it in a persistent location.
The default local model needs no LLM API key.

To try semantic search from the generated project:

```sh
python manage.py call search --app sample --mode vector --query "Where should I go when I feel unwell?"
```

## Your generated project

The default App connects a source without a custom read or parser function:

```python
# apps/sample/app.py
from galmuri import App
from .source.local import source

sample = App(name="sample", source=source)
```

| File or directory | What you change there |
| --- | --- |
| `config/settings.py` | Enabled apps, DB connections, access defaults, and server options |
| `apps/sample/app.py` | Source and optional processing/search settings |
| `apps/sample/source/local.py` | Folder or provider used as the source |
| `apps/sample/fixtures/` | Sample files; add/edit a file here, then sync |
| `apps/sample/skills/usage.md` | Usage instructions exposed in app metadata |
| `manage.py` | Project command entry point |

To use another folder, change the `ReadOnlyLocalProvider` path in
`apps/sample/source/local.py`. The sample is read-only; client updates require
a source with conditional-write support.

Choose a preset when creating a new directory:

| Command | Generated example |
| --- | --- |
| `python -m galmuri new PATH` | Local source, default processing, accounts, local embeddings/vectors |
| `python -m galmuri new PATH --process` | Default setup plus runnable transformation functions |
| `python -m galmuri new PATH --lexical` | Explicit-handler keyword-search tutorial |
| `python -m galmuri new PATH --retrieval` | Explicit Qdrant settings and a Compose file |

Presets are mutually exclusive. The lexical and Qdrant tutorials use trusted host
identities rather than the default account-enabled setup.

## Customize processing

From the framework checkout, generate the runnable processing example:

```sh
python -m galmuri new ./custom-example --process
```

It adds these files to the sample app:

```text
apps/sample/
├── app.py
├── process.py
└── views/
    ├── __init__.py
    ├── normalization.py
    └── metadata.py
```

Edit `views/normalization.py` to change document text:

```python
from dataclasses import replace

def normalize(documents):
    return tuple(
        replace(document, text=document.text.strip() + "\n")
        for document in documents
    )
```

In `process.py`, connect the function and the supplied metadata function:

```python
from galmuri import Pipeline, Step
from .views.normalization import normalize
from .views.metadata import label

process = (
    Pipeline.default()
    .then(Step("normalize", process=normalize))
    .then(Step("label", process=label))
)
```

The generated `app.py` selects it with
`App(name="sample", source=source, process=process)`.
Functions run when processing work executes. Add `.then(Step(...))` for another
step, or change declaration order to change the sequence.

These added steps receive and return document tuples. Default parsing runs
first; document permission preparation follows your transformations.
For a fully custom sequence, use `Pipeline(*steps)` with explicit `file`,
`documents`, and terminal `result` boundaries.
A plain `App(process=my_function)` accepts File and returns IngestResult.

Configure only the parts you need:

| App option | Use it to… |
| --- | --- |
| `parser=ParsingConfig(process=my_parser)` | Select a parsing function |
| `ingestion=IngestConfig(...)` | Set fallback document grants |
| `retrieval=RetrievalConfig(...)` | Select chunking, embedding, store, and search mode |
| `database=DatabaseConfig(...)` | Select a DB alias and optional PostgreSQL namespace |
| `policy=SyncPolicy(...)` | Set discovery mode, interval, and retries |

Config classes above are imported from `framework`, except `SyncPolicy`, which
is in `galmuri.collection.policies`.
For example, `SyncPolicy(mode="scan", interval=86400)` schedules a daily full scan.
Omitted settings retain defaults.

## Agent skill

The repository includes [using-galmuri](skills/using-galmuri/SKILL.md), an agent skill
for creating apps, changing processing steps and checking document access. From this
checkout, install it for Codex with:

```sh
mkdir -p "${CODEX_HOME:-$HOME/.codex}/skills"
cp -R skills/using-galmuri "${CODEX_HOME:-$HOME/.codex}/skills/"
```

Restart or reload skill discovery, then ask the agent to use `$using-galmuri`.
Other compatible agents can install the same skill folder. Wheels also include it
under `share/galmuri/skills/using-galmuri` in the Python installation's data directory.

## Sources, models, and storage

| Component | Included choices |
| --- | --- |
| Sources | Local files; read-only Google Drive and Slack through duru |
| Parsers | Text, Markdown, Python source |
| Embedding | Local FastEmbed; OpenAI embedding adapter |
| Chunking | Character chunker; custom Chunker or `ChunkingConfig(process=...)` |
| Vector storage | SQLite, PostgreSQL exact cosine, Qdrant |
| Search | Lexical, vector, hybrid |
| Metadata/account storage | SQLite, PostgreSQL |

Supply credentials and account/folder/channel IDs to the resource library.
A provider with `root_uri` can be passed directly as `App.source`; otherwise
use `galmuri.sources.resources.Resources(provider, root_uri)`.
Google-native documents require an explicit export format. Slack messages arrive
as JSON resources; customize parsing to select the fields you need.

The current provider bridge scans snapshots and compares versions. It does not
automatically subscribe to native Google Drive or Slack incremental feeds.

An App can set `retrieval=RetrievalConfig(embedding=my_embedding, store=my_store,
mode="hybrid")`. Missing embedding/store providers are filled from defaults.
The default vector store follows the App's selected database.
`EmbeddingConfig(process=..., query_process=..., spec=...)` connects paired
document-batch and query functions. Existing EmbeddingProvider, Chunker, and
VectorStore implementations can also be passed directly.

Set `retrieval=None` to disable vector indexing. Selecting lexical as the default
search mode alone does not disable vector builds.
For PostgreSQL aliases/namespaces, Qdrant setup, and provider configuration, see
the [configuration and operations reference](guides/reference.md).

## Accounts and document access

From a default or `--process` generated project:

```sh
python manage.py createsuperuser root
python manage.py serve http
```

The first command prompts for a password. Sign in at
<http://127.0.0.1:8000/dashboard> to manage accounts, groups, document permissions,
and personal MCP tokens. There is no default account or password.

Omitted grants inherit `DEFAULT_PERMISSIONS` in `config/settings.py`.
Generated defaults allow reads and writes; explicit empty grants deny access.
Source write support is still required, so the read-only sample exposes no write tool.

Group membership changes apply without reindexing. Ordinary administrators manage
permissions; root can also bypass document ACLs. Token scopes, app restrictions,
source capabilities, and version checks still apply to root.

For a read-only account token:

```sh
python manage.py createuser reader
python manage.py mcp-token reader --scope read --app sample --token-file .runtime/reader.token
FRAMEWORK_TOKEN_FILE=.runtime/reader.token python manage.py serve mcp
```

Local account commands require trusted OS access to the project.
Restricted documents require verified credentials; tool arguments cannot assert
a user/group. Invalid, expired, or revoked credentials are rejected.

## Serve your app

Run from the generated project:

| Command | Interface |
| --- | --- |
| `python manage.py serve http` | JSON API at `/api/call`; dashboard at `/dashboard` |
| `python manage.py serve mcp` | MCP over standard input/output |
| `python manage.py serve grpc` | Protobuf service; schema at `src/galmuri/exposure/grpc/exposure.proto` in the framework checkout |
| `python manage.py call describe --app sample` | One-shot CLI call with source/search metadata |
| `python manage.py serve cli --workers 0` | JSON commands over standard input/output |

`serve` normally starts the scheduler and one local worker. Use `--workers 0`
when running workers separately. The MCP adapter is a stdio server.
HTTP deployment needs a public HTTPS origin and TLS proxy; generated loopback
HTTP settings are for local use.

Build the supplied image from the framework checkout, with the sibling `access/`
checkout present:

```sh
docker build --build-context duru=../access -t galmuri-local .
docker run --rm galmuri-local --help
```

Mount a generated project at `/workspace` to retain its code and state.

## Commands and recovery

Run from a generated project. Replace `BUILD_ID` with a build ID from index status.
For management calls such as status, first create a root session after creating
your root account: `python manage.py login root --token-file .runtime/operator.token`.
It prompts for the password.

| Command | Purpose |
| --- | --- |
| `python manage.py sync` | Collect changes and process currently eligible work |
| `FRAMEWORK_TOKEN_FILE=.runtime/operator.token python manage.py call status` | Inspect document jobs and ingestion stages with the root session |
| `python manage.py index-status --app sample` | Inspect vector builds |
| `python manage.py index --drain` | Process currently eligible indexing work |
| `python manage.py reindex --app sample` | Queue new vector generations |
| `python manage.py index-retry BUILD_ID` | Retry a failed vector build |
| `python manage.py activate` | Activate changed app/parser/model settings |
| `python manage.py scheduler` | Run scheduling separately |
| `python manage.py worker` | Run a processing worker |
| `python manage.py --help` | Show all commands |

Standard Runtime workers persist accepted step outputs and resume after them.
HTTP remote workers and custom workflows retry the whole process.
Callbacks interrupted before their output is saved may run again: make external
side effects idempotent.

Document publication and vector publication finish separately. Check
`index-status` after sync; a drain can leave future retries or failed jobs.
Change an implementation's revision when changing its behavior in place, then
activate. State from older parser bindings may also require `activate`.
See the [reference](guides/reference.md) for detailed recovery and store-cleanup commands.

## Current limits

- Pipelines support linear steps; branches, loops, and DAG scheduling are not included.
- Google Drive/Slack providers currently support read/stat/list. Their account APIs
  are tested with local HTTP fixtures; live-account verification is separate.
- PDF/OCR parsers and OpenSearch require additional implementations.
- SQLite is for a single host. Use PostgreSQL to share metadata/account state across
  hosts, with compatible code and source settings in every process.
- SQLite/PostgreSQL vector stores use exact cosine search. Large-corpus throughput,
  ANN quality, and long-running production operation need separate evaluation.

## Development

From the framework checkout:

```sh
python -m pip install -e ../access -e '.[mcp,grpc,postgres,dev]'
python -m pytest -q
python -m ruff check src tests tools
python -m ruff format --check src tests tools
python -m build --wheel
```

Set `FRAMEWORK_POSTGRES_DSN` to a disposable PostgreSQL instance for remote DB tests.
Optional live-model/LLM checks are separate from the ordinary suite; commands are
in the [reference](guides/reference.md#verify).

Include a reproducible example and relevant checks with fixes or extensions.
Keep the English and Korean READMEs aligned for user-facing changes.

See [contributing](CONTRIBUTING.md), [security reporting](SECURITY.md),
[changes](CHANGELOG.md) and the [release procedure](RELEASE.md).

## License

Distributed under the [BSD 3-Clause license](LICENSE).
