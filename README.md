# Galmuri

English · [한국어](README.ko.md)

**A Python framework for building services that collect, process, and serve documents.**

Connect files, Google Drive documents, Slack messages, or your own data source.
Choose how to transform and index the content, then make it available to other
applications through MCP, HTTP, gRPC, CLI, or an interface you implement.

You develop your service in a generated project. Source connectors, processing
functions, and output adapters are replaceable parts of that project. Galmuri
executes the policies you configure and manages checkpoints, document updates,
permissions, and retries.

## Create your first project

Requires **Python 3.12+**. Install Galmuri from PyPI:

```sh
python3 -m venv .venv
. .venv/bin/activate
python -m pip install 'galmuri[mcp,grpc]==0.2.0'
```

Create a project, then create its first app:

```sh
python -m galmuri startproject example
cd example
python manage.py startapp sample
```

`startproject` creates the project settings and `manage.py`. `startapp` creates
an app with its own source connection and sample documents. Register that app
by editing `config/settings.py`:

```python
APPS = ["apps.sample.app:sample"]
```

The generated app uses a local folder, the default parsers, local multilingual
embeddings, and SQLite. Its first sync downloads model weights; no LLM API key
is needed. Set `EMBEDDING_CACHE` before syncing to reuse an existing model cache.

```sh
python manage.py sync --app sample
python manage.py index-status --app sample
python manage.py call search --app sample --mode lexical --query welcome
python manage.py serve http
```

The search command returns the generated `welcome.md` document. Open
<http://127.0.0.1:8000/dashboard> to browse the documents, then stop the server
with Ctrl+C. Document processing and vector indexing finish separately; check
index status for pending or failed work before using vector search.

For an example that does not download a model, follow
[Build your first document service](guides/build-an-integration.md).

## Develop your app

The main files created by those two commands are:

```text
example/
├── manage.py
├── config/
│   └── settings.py
└── apps/
    └── sample/
        ├── app.py
        ├── source/
        │   └── local.py
        ├── fixtures/
        │   ├── welcome.md
        │   └── clinic.md
        └── skills/
            └── usage.md
```

| File or directory | What you develop there |
| --- | --- |
| `config/settings.py` | Register apps; configure databases, access defaults, and interfaces |
| `apps/sample/app.py` | Connect the source, processing functions, and execution policy |
| `apps/sample/source/` | Configure a supplied source provider or implement your own connector |
| `apps/sample/fixtures/` | Local example documents; add or edit one, then sync |
| `apps/sample/skills/usage.md` | Instructions made available to consumers through app metadata |
| `manage.py` | Run this project's commands |

To connect your own folder, edit the path in `apps/sample/source/local.py`.
To use another service, configure a provider from [Duru](https://github.com/imguno/duru)
or implement its source contract. Reading, writing, and service-specific API calls
belong in the source provider.

`apps/sample/app.py` binds that source to the framework. Its minimal form is:

```python
from galmuri import App
from .source.local import source

sample = App(name="sample", source=source)
```

Use the default processing to get started. When you need your own parser,
transformation, or indexing method, write that implementation in the app and
connect it here. The [step-by-step tutorial](guides/build-an-integration.md)
shows the files to create and how to verify their output.

Each App owns one source connection and its processing, retrieval, and execution
policies. To add another source, run `python manage.py startapp manuals`, configure
its source, and add `"apps.manuals.app:manuals"` to `APPS`. Apps can use different
processing, schedules, and stores within the same project.

## What you can build

| Goal | What to implement or configure |
| --- | --- |
| Connect an internal API | A Duru provider, bound to your App |
| Normalize documents or add metadata | Parsing and transformation functions in the app |
| Supply documents to an LLM client | The MCP interface and your app's usage instructions |
| Provide an API or custom output format | A supplied interface or your own output adapter |
| Change embeddings or vector storage | The app's `RetrievalConfig` |
| Restrict documents to a team | Accounts, groups, and document permissions |

An output adapter—called an **exporter** in the integration guide—uses the shared
`Service` to expose accepted documents and operations. Built-in adapters provide
MCP, HTTP, gRPC, and CLI. A custom adapter implements `run()` and is registered
in `EXPOSURE_ADAPTERS`. Automatic delivery and retries to arbitrary external
destinations are outside that adapter contract.

For RAG, use Galmuri to develop the document and retrieval side of your system.
Your existing LLM application consumes those results and owns prompts,
answer generation, and conversation logic.

The older `python -m galmuri new PATH` command remains available as a shortcut
that creates a project with a registered sample app. Its `--process`, `--lexical`,
and `--retrieval` presets remain supported. The lexical and Qdrant presets use
trusted host identities instead of the default account-enabled setup.

## Customize processing

Inside your project, generate an app with editable processing functions:

```sh
python manage.py startapp articles --process
```

Register `"apps.articles.app:articles"` in `APPS`. The app includes:

```text
apps/articles/
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
`App(name="articles", source=source, process=process)`.
Functions run when processing work executes. Add `.then(Step(...))` for another
step, or change declaration order to change the sequence.

Run the app and inspect its output:

```sh
python manage.py sync --app articles
python manage.py call search --app articles --mode lexical --query welcome
```

The returned document includes `"pipeline": "articles"` in its metadata.

These added steps receive and return document tuples. Default parsing runs
first; document permission preparation follows your transformations.
For a fully custom sequence, use `Pipeline(*steps)` with explicit `file`,
`documents`, and terminal `result` boundaries.
A plain `App(process=my_function)` accepts File and returns IngestResult.
Default processing and `Pipeline` retain automatic retrieval when `retrieval` is
omitted. A plain custom `process`/`handler` instead defaults to lexical-only;
set `retrieval=RetrievalConfig()` explicitly to enable its embeddings and vector
index. A plain function returning `IngestResult` also owns the returned grants;
settings defaults are not added to that result.

Configure only the parts you need:

| App option | Use it to… |
| --- | --- |
| `parser=ParsingConfig(process=my_parser)` | Select a parsing function |
| `ingestion=IngestConfig(...)` | Set fallback document grants |
| `retrieval=RetrievalConfig(...)` | Select chunking, embedding, store, and search mode |
| `database=DatabaseConfig(...)` | Select a DB alias and optional PostgreSQL namespace |
| `policy=SyncPolicy(...)` | Set discovery mode, interval, and retries |

Config classes above are imported from `galmuri`, except `SyncPolicy`, which
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
| Chunking | Structure-aware default with FastEmbed token budgets; explicit character/custom chunkers |
| Vector storage | SQLite, PostgreSQL exact cosine, Qdrant |
| Search | Indexed BM25, vector, configurable hybrid fusion |
| Metadata/account storage | SQLite, PostgreSQL |

Version 0.2.0 introduces indexed keyword search and structure-aware chunking.
See [search configuration, evaluation, and upgrade steps](guides/search.md)
for Korean matching limits, `SearchConfig`, model input budgets, and migration.

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

Built-in ingestion and pipelines ending in document tuples resolve omitted
`IngestConfig` grants from `DEFAULT_PERMISSIONS` in `config/settings.py`.
Generated defaults allow reads and writes; explicit empty grants deny access.
A custom process or terminal pipeline step returning `IngestResult` supplies its
own document grants. `Document`'s empty default grants do not become public by themselves.
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
The [integration tutorial](guides/build-an-integration.md#connect-your-rag-client)
includes stdio client configuration and a complete Python MCP client.
HTTP deployment needs a public HTTPS origin and TLS proxy; generated loopback
HTTP settings are for local use.

Build the supplied image from the framework checkout, with the sibling `duru/`
checkout present:

```sh
docker build --build-context duru=../duru -t galmuri-local .
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

Clone the repositories next to each other for source development:

```sh
git clone https://github.com/imguno/duru.git duru
git clone https://github.com/imguno/galmuri.git galmuri
cd galmuri
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -e ../duru -e '.[mcp,grpc,postgres,dev]'
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

See [contributing](docs/CONTRIBUTING.md), [security reporting](docs/SECURITY.md),
and the [release procedure](docs/RELEASE.md).

## License

Distributed under the [BSD 3-Clause license](LICENSE).
