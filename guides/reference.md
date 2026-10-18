# Configuration and operations reference

[Back to the overview](../README.md)

This English reference covers configuration, lifecycle guarantees and operations.
Shell paths are relative to the framework checkout or generated project as stated
in each section. The sibling duru checkout is `../access` relative to
the framework checkout.

For account-enabled projects, management service calls require a verified account.
After creating a root account, run `python manage.py login root --token-file
.runtime/operator.token`, then prefix management calls with
`FRAMEWORK_TOKEN_FILE=.runtime/operator.token`. Commands such as sync and index-status
already use the local OS operator path; ordinary `call search` may be anonymous for
public documents.

The framework provides source apps, ordinary Python ingestion handlers, durable lifecycle
management, and interchangeable exposure adapters. An app owns its discovery, schedule,
workflow and retry policy. The runtime executes that policy; it does not hardcode a
source-specific ingestion pipeline.

## Start a project

Python 3.12 or newer is required. Linux is the deployment target. No executable binaries
or platform-specific launchers are generated.

```sh
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -e ../access -e '.[mcp,grpc,dev]'
python -m galmuri new ./example
cd example
python manage.py sync
python manage.py call search --app sample --query welcome
python manage.py serve http
```

Open `http://127.0.0.1:8000/dashboard` to explore published documents. Create the first
authenticated root account with `python manage.py createsuperuser root`; it prompts for
a password. There is no default account or password. The dashboard manages accounts,
groups, document permissions and personal MCP tokens. Ordinary administrators manage
permissions without bypassing document ACLs. Explicit root accounts can bypass document
ACLs; token scopes, app restrictions, source capabilities and write-version guards still apply.

The default sample connects a read-only `duru.ReadOnlyLocalProvider` directly
to `App(name="sample", source=source)`. No read function, handler, parser or vector service
configuration is required. App defaults select parsing, character chunking, a real local
multilingual FastEmbed model and SQLite vectors. Weights download on first inference;
`EMBEDDING_CACHE` can select an existing cache. The sample welcome and clinic documents
use `DEFAULT_PERMISSIONS = {"read": ["*"], "write": ["*"]}`. Explicit policies override
these fallbacks, including empty lists that deny access. Source write capability is still
required. Source credentials and file names never establish an authenticated document owner.

`serve` runs the scheduler and one local worker by default. Use `--workers 0` for a
coordinator with remote document workers. The App owns discovery and scheduling choices.
The resource library owns provider IO, addresses, names and vendor APIs. The framework
normalizes its resource contract at `galmuri.ingestion.sources`, without source-specific
API implementations. A provider with `root_uri` can be passed straight to App; otherwise
use `Resources(provider, root_uri)` explicitly.

## Customize one step

```python
from galmuri import App, DatabaseConfig, IngestConfig, ParsingConfig, RetrievalConfig

app = App(
    name="knowledge",
    source=source,
    parser=ParsingConfig(process=my_parser, identity="company:manual", revision="2"),
    ingestion=IngestConfig(readers=(f"group:{dev_group_id}",)),
    retrieval=RetrievalConfig(mode="hybrid", batch_size=16),
    database=DatabaseConfig(alias="default", namespace="knowledge"),
)
```

Each related set of options has its own immutable configuration object. Configure only
what you need: `App(name="knowledge", source=source)` remains sufficient. Empty
`ParsingConfig()`, `IngestConfig()`, `RetrievalConfig()` and `DatabaseConfig()` select
the same built-in defaults as omitting those fields. `namespace` in this example requires
a PostgreSQL connection; leave it out for SQLite. Collection schedules and retry/workflow
policy remain in `policy=SyncPolicy(...)`, owned by the App.

Ordinary named parser functions work directly as `parser=my_parser`; explicit identity
and revision make deployed custom implementations reproducible. The App normalizes a
parser callable into `ParsingConfig`, so both forms use the same lifecycle. Parsers return Documents;
ingestion assigns grants and prepares publication. `readers=()` explicitly denies access,
and omitted grants inherit settings defaults. `dev_group_id` is the actual immutable group
ID from the account directory; membership changes take effect without reindexing.
Source credentials do not imply document grants.
Set `retrieval=None` for lexical-only access. Existing explicit handlers keep lexical
behavior unless retrieval is explicitly configured. `prepare_documents` is the canonical
ingestion preparation function; the old `index_default` name remains an import alias.

Retrieval settings can be partial. `RetrievalConfig(embedding=my_embedding)` keeps the
default chunker and selects the App database's vector store;
`RetrievalConfig(store=my_store)` keeps the default local embedding model. Omitted
providers are filled when the App is resolved, without loading model weights or running
inference. An explicit store bypasses default-store construction. Empty or partial
retrieval configuration defaults to hybrid search; the existing fully specified
`RetrievalConfig(embedding=my_embedding, store=my_store)` retains vector mode unless
`mode` is supplied. Use `dataclasses.replace(config, ...)` to customize a shared frozen
configuration. Moving a resolved App to another database rebinds inherited providers;
explicit providers remain selected. Configuration alone does not migrate existing data.

`describe` includes selected defaults, parser/model/store, actual source capabilities and
bound operation input schemas for LLM consumers. Credentials and private source locations
are excluded. `status` reports the separate read/parse/prepare stages; `index-status`
reports vector publication. Built-in ingestion under the standard SyncPolicy persists
accepted bytes and parsed documents so retries resume the failing stage. Private retry
payloads are released after confirmed publication, cancellation or supersession. Custom
workflows/handlers and remote workers keep their existing execution contract; remote
workers do not share the coordinator's read/parse checkpoints.

Changing parser or ingestion identity/revision changes the effective App revision and
requires explicit `activate`. A storage-only retrieval change leaves body ingestion
intact; compatible exact-text/chunker/model artifacts reuse embeddings, with fresh point
IDs for each vector generation. Model/chunker revisions invalidate their own artifacts.
Artifacts are retained in the private coordinator database; no retention/TTL policy is
implied. Current document grants still govern every query.

The resource bridge reports `snapshot_scan`: it scans through the library and compares
observed versions. A missing list entry is checked with provider stat before deletion;
access denial propagates as a failure. Resources moved outside a collection but still
stat-readable remain tracked until an authoritative removal is observed. No vendor
incremental change feed is inferred from that fallback.

Use `new PATH --lexical` for the explicit-handler public/developer tutorial, or
`new PATH --retrieval` for the explicit Qdrant tutorial. The plain `new PATH` preset is
the source-only local setup described above.

## Connect processing functions

`python -m galmuri new ./example --process` generates an executable example with
separate normalization and metadata functions under `apps/sample/views/`. Its App binds
the following callable by reference as `process=process`:

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

The default steps parse a File and prepare document grants. Each added step above takes
and returns document tuples. Declaration order determines execution order; `.then()`
returns a new pipeline. For complete control, use `Pipeline(Step(...), Step(...))` with
explicit `accepts` and `returns` boundaries: `file`, `documents`, or terminal `result`
(`IngestResult`). A pipeline ending in documents receives automatic preparation. A
pipeline returning an IngestResult owns its document grants. File transforms preserve
the accepted file identity and version. No function runs while connecting configuration.

A plain `App(process=my_function)` remains supported; its function receives File and
returns IngestResult. `process_default` selects built-in processing. The earlier `handler`
name remains compatible. App policy still controls when work runs; functions implement
how their individual step works. No Request wrapper is required.

Under the standard local Runtime worker, accepted pipeline outputs are persisted per
step. A process restart resumes after accepted steps; a callback interrupted before
acceptance can run again, so external effects must be idempotent. Publication rechecks
the live lease, source version, permissions and active configuration. Terminal success,
cancellation and supersession release private checkpoint payloads. Failures retain them
for retry. Custom workflows and HTTP remote workers retain whole-process retry semantics.
Pipeline processing and the separately persisted vector-index lifecycle have distinct
recovery boundaries. This API supports linear composition, without branching or DAG scheduling.

Use a stable named function, or supply explicit `identity` for callable instances/lambdas.
Increment `revision` when implementation behavior changes in place, then explicitly
activate the configuration. The framework does not hash function source code.
Existing state created before portable parser binding identities may require
`python manage.py activate` once before the next sync; activation fences prior work.

Individual indexing components can also wrap ordinary functions:

```python
from galmuri import ChunkingConfig, EmbeddingConfig, RetrievalConfig

retrieval = RetrievalConfig(
    chunker=ChunkingConfig(process=my_chunker, revision="2"),
    embedding=EmbeddingConfig(
        process=embed_documents, query_process=embed_query, spec=my_embedding_spec,
    ),
)
```

Chunkers receive published text and return Chunks with offsets into that text. Document embedding functions receive
a tuple of texts and return a vector batch; query functions receive one text and return
one vector. The paired embedding functions share a declared model and dimension contract.
Their binding identity is included in artifact compatibility. Existing Chunker,
EmbeddingProvider and VectorStore implementations also work directly, so source access,
parsing, chunking, embedding and storage can each be replaced independently.

## Embeddings and vector retrieval

An app selects its embedding provider, chunker, vector store and default search mode.
The framework runs their durable lifecycle. The default scaffold already includes local
semantic retrieval. The explicit retrieval scaffold selects external Qdrant:

```sh
python -m pip install -e '.[embeddings,mcp,grpc]'
python -m galmuri new ./knowledge --retrieval
cd knowledge
docker compose up -d
python manage.py sync
python manage.py index-status
python manage.py call search --app sample --mode vector --query "몸이 아프면 누구에게 가나요?"
python manage.py serve mcp
```

The first model operation downloads weights into `.runtime/models`. The generated
`apps/sample/retrieval/configuration.py` selects a 384-dimensional multilingual model,
Qdrant URL and a character chunker. Credentials come from the deployment environment.
For a small local app, select `SQLiteVectorStore(path)` for durable exact cosine search.
`PostgresVectorStore(dsn, schema="public")` provides shared exact cosine storage without
requiring a PostgreSQL extension. It reads authorized candidates and ranks them in the
framework process; it is a reference implementation, not an ANN index.
`OpenAIEmbedding(api_key=...)` is also provided. Custom implementations inherit
`EmbeddingProvider`, `Chunker` or `VectorStore`; source IO and ingestion handlers stay
independent of these contracts.

`App(retrieval=RetrievalConfig(embedding=..., store=..., mode="hybrid"), ...)` enables
lexical, vector and hybrid search through the same HTTP, MCP, gRPC and CLI service.
`describe` reports model, modes and chunking; `index-status` reports build progress.
Vector results include document
identity, immutable build ID, model fingerprint and matching chunks whose Unicode character
offsets reference the published text. Hybrid uses reciprocal rank fusion with k=60 over
equally bounded candidate lists (`min(1000, max(64, limit * 4))`). Scores are rankings,
not answer confidence.

Document publication and vector publication have separate durable states. Indexing
persists prepared vectors before upload; a store retry reuses them. Source updates and
deletions withdraw old semantic results as soon as the framework accepts their change.
Current grants filter candidates before the store's top-k operation and are checked again
after external IO. Ordinary administrator status does not bypass document grants; the
separate root role does, only while its credential remains valid. Old physical
vectors are deleted by retryable exact-ID cleanup jobs.

```sh
python manage.py index                  # dedicated indexing worker
python manage.py index --drain         # process currently eligible work and exit
python manage.py reindex --app sample  # queue fresh generations
python manage.py reindex --app sample --request-id maintenance-2026-10-16
python manage.py index-status --app sample
python manage.py index-retry FAILED_BUILD_ID
```

Normal workers and `sync` also process indexing. Inspect `index-status`: successful body
ingestion does not guarantee vector publication, and drain can finish with future retries
or failed jobs. Attempts are budgeted per build claim; completed preparation survives
store retries. Changed model/store/chunker identities require `activate`, which atomically
activates app and retrieval configuration; old workers cannot reactivate retired settings.
`EmbeddingSpec.revision` is an operator-managed version label, not verification that
upstream model downloads are immutable.

Dedicated index processes share the selected coordinator database: SQLite on one host,
or PostgreSQL across hosts. Existing HTTP document workers do not claim embedding jobs.
An optional `request_id` replays the originally accepted build IDs for the same app
selection and configuration; changed configuration under that identity is a conflict.
Omitting it deliberately creates new generations. Receipts are retained without an
automatic TTL. Across separate app databases, acceptance is atomic within each database;
a multi-app request has no cross-database transaction and may partially complete.
Document-level vector top-k uses a bounded search window and raises an explicit error if
10,000 chunk candidates cannot determine it. Exact cosine and per-query authorized-ID
lists suit smaller deployments; ANN quality and large-corpus performance need separate
evaluation.

After switching or disabling a store, cleanup may show `WAITING_STORE`. Supply its
original adapter in `config/settings.py` as `RETRIEVAL_CLEANUP_STORES = (old_store,)`,
then run an index worker. This restores the deletion route without reactivating retired
retrieval configuration. Retain that route for periodic repair as well as initial cleanup.
Direct Python hosts can use `Runtime(..., cleanup_stores=(old_store,))`.

Retired generations keep exact point-ID tombstones. `RetrievalConfig.cleanup_interval`
(default 300 seconds) controls repeated deletion after a successful cleanup; retained
superseded tombstones may transition `SUCCEEDED -> RUNNING` when due. This repairs a
late upload even if its uploader crashed before recording completion. Current generations
use fresh point IDs, so replay deletes only the retired generation. Tombstones have no
automatic garbage collection; repair requires an index worker and the original store.
Ordinary workers alternate eligible ingest and indexing work; index workers alternate
builds and due cleanup, while routed backends rotate claim opportunities across databases.
This bounds local scheduling starvation; external IO still needs its own finite timeouts.

Build the Linux image with optional model support:

```sh
docker build --build-context duru=../access \
  --build-arg FRAMEWORK_EXTRAS=mcp,grpc,embeddings -t galmuri-local .
```

Mount a generated project at `/workspace`, a persistent model cache at `/models`, and
set `EMBEDDING_CACHE=/models` and a reachable `QDRANT_URL` when running that image.
The generated Compose file runs Qdrant; it does not install the Python framework.
A separate RAG application or MCP client consumes the document/search contract to
generate answers.

## User code

Source IO is implemented in the separately packaged `duru` library
under `../access`. It owns abstract resource interfaces and local/Google Drive/Slack
implementations. App code supplies credentials and target IDs; the library never
imports framework settings. `galmuri.sources.resources.Resources(provider, root_uri)`
adapts a provider for an App. See the library README for provider configuration.
`LocalFiles` uses the same library internally while preserving existing source keys,
identities and checkpoints. Discovery timing, snapshots, processing and document grants
remain framework responsibilities.

Generic providers use app-owned full scans and do not infer deletions from list absence.
They must supply verifiable content revisions. The bridge includes display names and
metadata in ingestion versions so a rename is reprocessed even if content is unchanged.
Provider URI strings are opaque to the bridge. Source write exposure requires a
`ConditionalWritable` provider; readonly service providers have no framework write tool.

For example, an app source module constructs the library provider from its own settings:

```python
from duru import GoogleDriveProvider, SlackProvider
from galmuri.sources.resources import Resources
from config import settings

drive = GoogleDriveProvider(
    access_token=settings.DRIVE_ACCESS_TOKEN,
    account_id=settings.DRIVE_ACCOUNT_ID,
    folder_id=settings.DRIVE_FOLDER_ID,
    export_formats={"application/vnd.google-apps.document": "text/plain"},
)
drive_source = Resources(drive, drive.root_uri)

slack = SlackProvider(
    token=settings.SLACK_TOKEN,
    workspace_id=settings.SLACK_WORKSPACE_ID,
    channel_ids=(settings.SLACK_CHANNEL_ID,),
)
slack_source = Resources(slack, slack.uri(settings.SLACK_CHANNEL_ID))
```

These settings names are example user-defined fields; tokens are never generated or
loaded by the library. Pass either source into `App(source=..., handler=...)` and choose
its `SyncPolicy(mode="scan", interval=...)`. Slack messages are JSON byte resources;
the app handler can parse their text/blocks according to the application's needs.
The built-in service providers currently implement read/stat/list only; token refresh
is controlled by the calling application. Native Drive documents require an explicit
export representation. Read the library limitations before using large collections.

```python
from galmuri.parsing import parse_auto
from galmuri.ingestion import prepare_documents


def prepare(file):
    documents = parse_auto(file)
    readers = (f"group:{dev_group_id}",) if ".dev." in file.name else ("*",)
    return prepare_documents(documents, readers=readers, writers=(f"group:{dev_group_id}",))
```

`app.py` explicitly connects this callable to source access and policy. Its name is not
prescribed; callable classes work too. Parsing and preparation run as ordinary Python.
Handlers return `IngestResult(documents=(...), messages=(...))`, available from
`framework`; `prepare_documents` constructs this result for ordinary parser output.
`Processed` remains an identity alias for existing imports and handlers, with no removal
deadline. New code should use `IngestResult`. This name change does not alter worker
payloads: results still contain only `documents` and `messages`.
Prepared results become visible only after the publication boundary validates the current
source/app revision and execution lease. Custom object types use `DocumentContract.project`.

Custom `Document`/`prepare_documents` grants are explicit; their empty defaults deny access.
The built-in ingestion path instead resolves omitted `IngestConfig` grants from settings.
Source access has
no `access` method. `ReadOnlyFiles` has no write capability, so its app has no source-write
MCP tool. Whole-file writes require permission for every affected derived document.

## Exposure adapters

```sh
python manage.py serve http
python manage.py serve grpc
python manage.py serve mcp
python manage.py serve cli --workers 0
python manage.py call describe --app sample
```

- HTTP: JSON API at `/api/call` and read endpoints under `/api/`; dashboard at `/dashboard`
  (`/admin` alias).
- MCP: official SDK stdio server; source-specific read/search/describe and optional write tools.
- gRPC: protobuf service `framework.v1.Exposure`, schema shipped in
  `galmuri/exposure/grpc/exposure.proto`.
- CLI: one-shot calls or JSON commands read from standard input.

Every adapter calls the same `Service` with a host-authenticated `Principal`. Request bodies
cannot assert account identity, groups, administrator or root privileges. Add factories in `EXPOSURE_ADAPTERS`
and configure options in `EXPOSURES`; custom adapters implement `run()` and receive only
their explicit options. Authentication providers implement the `Authenticator` contract.

Create an account-bound credential file for CLI/stdio MCP:

```sh
python manage.py createuser reader
python manage.py creategroup developers
python manage.py group-add developers reader
python manage.py mcp-token reader --scope read --app sample --token-file .runtime/reader.token
FRAMEWORK_TOKEN_FILE=.runtime/reader.token python manage.py serve mcp
```

The MCP token is issued to the actual account; its secret is stored only in the private
0600 file and shown once in the dashboard. Never put account names or group assertions
in LLM tool parameters. Public documents allow anonymous access; an invalid, expired or
revoked credential is rejected rather than downgraded to anonymous. Group membership,
disable, password changes and token revocation are checked against current directory state.
Use `login USER --token-file PATH` for a session file and `logout --token-file PATH` to
revoke it. `createsuperuser` creates root; `createuser --administrator` creates an ordinary
administrator. Local account commands require trusted OS access to the project.

HTTP accepts Bearer credentials or password-authenticated browser sessions. Cookie sessions
use HttpOnly/SameSite Strict, CSRF and origin checks. Generated settings explicitly permit
loopback HTTP development; deployed dashboard hosting requires `public_origin="https://..."`
behind a TLS proxy and no insecure-loopback exception. Account-enabled gRPC must use loopback
or an explicitly configured TLS-terminating proxy (`tls_terminated=True`). Stdio MCP uses
host environment/file credentials; this is not an OAuth-enabled remote MCP HTTP server.
Legacy `--lexical`/`--retrieval` tutorials use explicitly configured trusted host identities
when `IDENTITY_DATABASE` is absent; this mode does not authenticate human users.

Example Bearer HTTP request:

```sh
curl -H "Authorization: Bearer $(cat .runtime/reader.token)" \
  -H 'Content-Type: application/json' \
  -d '{"operation":"search","params":{"app":"sample","query":"welcome"}}' \
  http://127.0.0.1:8000/api/call
```

## Workers and recovery

### Shared databases and app selection

The same project can run as several ordinary Python processes or containers. Operators
provide process managers, hosts and load balancing. Configure shared persistence rather
than copying per-host SQLite files or placing SQLite on NFS:

```sh
python -m pip install -e '.[postgres,mcp,grpc]'
```

```python
# config/settings.py
import os

DATABASES = {
    "default": {
        "ENGINE": "postgresql",
        "DSN": os.environ["DATABASE_URL"],
        "NAMESPACE": "documents",
        "OPTIONS": {"connect_timeout": 10, "lock_timeout": 15, "statement_timeout": 30},
    },
    "archive": {
        "ENGINE": "postgresql",
        "DSN": os.environ["ARCHIVE_DATABASE_URL"],
        "NAMESPACE": "archive",
    },
}
IDENTITY_DATABASE = "default"  # shared accounts, groups, revocation and login limits
RUNTIME_DIRECTORY = ROOT / ".runtime"  # local artifacts/model-cache location
```

```python
# apps/manuals/app.py
from galmuri import App, DatabaseConfig

manuals = App(name="manuals", source=manuals_source)
archive = App(
    name="archive", source=archive_source, database=DatabaseConfig(alias="archive")
)
engineering = App(
    name="engineering",
    source=engineering_source,
    database=DatabaseConfig(alias="default", namespace="engineering"),
)
```

Omitted `App.database` uses `DatabaseConfig()`, selecting the `default` connection.
Omitted `DatabaseConfig.namespace` inherits that connection's namespace. The alias names
a `DATABASES` entry, not a database engine. An explicit namespace selects a PostgreSQL schema within the
chosen database. `SCHEMA` is an alias for `NAMESPACE`; specify only one. SQLite uses
`{"ENGINE": "sqlite", "NAME": path}` and rejects namespaces; select another connection
alias for a separate SQLite database. Existing `DATABASE = path` settings remain supported
as the default connection when `DATABASES` is absent.

Related options belong to their own immutable configuration objects. Database selection
uses `DatabaseConfig`; parsing, ingestion and retrieval use `ParsingConfig`, `IngestConfig`
and `RetrievalConfig`, all imported from `framework`, while `policy` owns collection/workflow settings. There is no flat
App namespace parameter. Use `database=DatabaseConfig(alias="archive", namespace="team")`;
dictionaries and database strings are not accepted. Selecting another alias or namespace
does not migrate data.

Source-only apps also inherit their default vector store from this selection: shared
PostgreSQL exact vectors use the app's database/schema, while SQLite selects local vectors
beside its state file. The global SQLite default preserves `vectors.sqlite3`; other physical
SQLite targets use `<full-state-filename>.vectors.sqlite3` so aliases in one directory stay
isolated. Explicit `RetrievalConfig` stores, including remote Qdrant, override
that default. `RUNTIME_DIRECTORY` and `EMBEDDING_CACHE` remain local paths; they do not
select authoritative metadata or vector persistence. All instances must share compatible
code, source identity, app revision, retrieval configuration and account storage.

PostgreSQL owns authoritative lease and expiry time. Timeout options above are seconds.
Reads use operation-scoped snapshots;
short metadata writes serialize under a database/schema advisory transaction lock.
Parsing, inference and external provider/vector IO execute outside metadata transactions.
This preserves correctness across ordinary processes without a cluster controller.
The current backend opens a connection per operation, with finite timeouts; it does not
claim pooled throughput or row-level write scaling. Moving an app to another DB alias or
schema selects another store; it does not migrate existing documents, grants or history.
Back up and move data explicitly. No transaction spans independent app databases.

```sh
python manage.py scheduler
python manage.py worker
python manage.py worker --remote http://coordinator:8000 --token-file /run/secrets/worker_token
```

Remote workers load the same app code and source credentials in their own environment.
They exchange serializable references, lease tokens and prepared document results with
the coordinator; they do not share SQLite or live file streams. Worker claims advertise
supported app revisions. Source changes enqueue durable jobs before advancing the cursor.

Execution records distinguish READY, RUNNING, RETRY_WAIT, RECONCILING and terminal states.
Expired or uncertain external effects require reconciliation rather than blind retries.
Admin controls and Service commands use the same transitions. Writes persist authorization
and intent before external I/O; revocation after accepted intent denies new requests but
does not retroactively undo an in-flight source operation.

Changing app revision requires explicit activation:

```sh
python manage.py activate
python manage.py sync
```

Custom sources should expose stable resource `identity`; changing source identity requires
an app revision change. Without a declared identity, explicit revision replacement resets
permission overrides conservatively. Custom runtime backends implement `RuntimeBackend`
and return coordinated `RuntimeComponents`; the default backend is SQLite, with PostgreSQL
available through database settings. App routing composes coherent backend bundles rather
than mixing a queue from one database with publication state from another.

## Built-in scope

Included: local files, text/Markdown/Python parsers, custom document projections, lexical
search, local multilingual embeddings, SQLite vectors, Qdrant, account/group ACLs, dashboard,
SQLite/PostgreSQL coordinators, shared PostgreSQL exact vectors, HTTP remote workers, and
four exposure adapters. The required
resource library includes readonly Google Drive and Slack providers. Other service connectors,
PDF/OCR parsers and additional retrieval engines are extension implementations.
Arbitrary user functions do not resume at an internal code line.
Local source CAS coordinates framework writers; unrelated external writers must cooperate
with the source's mutation discipline.

## Verify

```sh
python -m pytest -q
python -m ruff check .
python -m ruff format --check .
python -m build --wheel
```

Build the framework image with the sibling library as an explicit named build context:

```sh
docker build --build-context duru=../access -t galmuri-local .
```

To install local wheels, build both packages and supply their directories with
`pip install --find-links ../access/dist --find-links dist galmuri`.
This still downloads missing runtime dependencies from the configured package index.
An offline installation requires those dependency wheels as well as the two product
wheels and `--no-index`. The dependency declaration uses a version range, not a
machine-specific path.

Tests cover lifecycle races, publication/ACL fences, update/delete, remote workers, real HTTP,
protobuf gRPC channels, official MCP SDK stdio sessions, generated projects and custom data.

The generated-project acceptance tests run the public creation/hosting CLI and a real
MCP client, including automatic scheduled ingestion without a manual sync:

```sh
python -m pytest tests/acceptance tests/configuration -q
```

For an actual LLM query, install/authenticate Codex CLI on the host and run the repository
acceptance tool (Docker must be available to that host). It uses the configured default
model and existing authentication; no model API keys are copied into the container.

```sh
docker build --build-context duru=../access -t galmuri-access:acceptance .
python -m tools.acceptance --output .verification/llm-001
```

Use a new output directory for each run. The tool generates a skeleton with random test
facts, syncs it, then starts isolated real LLM sessions for public retrieval, private-data
denial, developer retrieval, updated content and deleted content. Only the three readonly
MCP tools are enabled; shell, apps and web tools are disabled. Expected facts are excluded
from prompts. A passing result requires observed successful MCP calls and cited document
contents, or a successful relevant empty search for negative cases. Events, prompts,
answers and a machine-readable summary are retained in the ignored output directory.
This optional live tool is development code and is not included in the framework wheel.

For the source-only default scaffold with actual account/group tokens and root attenuation:

```sh
python -m tools.acceptance.defaults --container YOUR_RUNNING_CONTAINER --output .verification/accounts-001
python -m tools.acceptance.defaults --postgres --container YOUR_RUNNING_CONTAINER --output .verification/postgres-001
```

The container must have the installed current packages and a persistent model cache. This
scenario verifies member retrieval, ordinary administrator denial, explicit root access,
and membership removal through actual isolated LLM/MCP calls.
The `--postgres` variant also requires `FRAMEWORK_POSTGRES_DSN` in that container and the
PostgreSQL optional dependency. It creates an isolated schema and uses shared account,
document and default exact-vector storage; the DSN is not copied into generated settings
or acceptance evidence.

## Container

```sh
docker build --build-context duru=../access -t galmuri-local .
docker run --rm galmuri-local --help
```

The image uses Python 3.13 and includes the optional MCP/gRPC dependencies. Mount a project
directory at `/workspace` to keep its app code and runtime state outside the container.
