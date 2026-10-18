"""Source-only defaults; optional Config objects customize individual App concerns."""

APP = """from pathlib import Path
from galmuri import App
from .source.local import source

sample = App(
    name="sample",
    source=source,
    description="Sample knowledge with automatic ingestion and configurable access policies",
    guides=(Path(__file__).parent / "skills" / "usage.md",),
)
"""

SOURCE = """from pathlib import Path
from duru import ReadOnlyLocalProvider

# Resource access, URI mapping and file IO belong to the independent library.
source = ReadOnlyLocalProvider(Path(__file__).resolve().parents[1] / "fixtures")
"""

GUIDE = """# Sample knowledge

Use describe to inspect the resolved ingestion/parsing and search capabilities.
This app uses a real local multilingual embedding model and local vector storage.
Use vector or hybrid search for paraphrases; lexical requires literal matching terms.
Read the returned document key to ground an answer. Keys are opaque resource URIs;
display names and addresses are independent. Use the exact key returned by search.
Omitted document permissions use settings defaults, initially allowing reads and writes.
Explicit document policies override those defaults. Use a server-issued account token
for restricted documents. Ordinary administrators do not bypass document grants; explicit
root accounts do, while credential scopes/apps still limit operations. The source is
read-only, so writing is not exposed even when a permission default allows it.
"""

README = """# Source-only knowledge app

The source in apps/sample/source/local.py uses the independent resource-access
library. App connects it; default ingestion, parsing, chunking, multilingual embedding
and local SQLite vector storage need no extra service or custom read/parser function.

```sh
python manage.py sync
python manage.py call describe --app sample
python manage.py call search --app sample --mode vector --query "몸이 아프면 누구에게 가나요?"
python manage.py serve mcp
```

The first embedding operation downloads model weights into .runtime/models. Set
EMBEDDING_CACHE to an existing cache directory if needed. DEFAULT_PERMISSIONS in
config/settings.py defines read/write fallbacks; explicit App/document grants override
them. Source credentials and external target IDs belong in your app/settings.

Create a real root account and open the dashboard:

```sh
python manage.py createsuperuser admin
python manage.py serve http
```

Visit http://127.0.0.1:8000/dashboard. The local operator command asks for a password;
there is no default account or password. Create users and groups, assign document access,
and issue/revoke account-bound MCP tokens there. Anonymous visitors see only public
documents. A token reduces account rights by scopes/apps and stops working after expiry
or revocation. Ordinary administrators manage permissions; root can access documents
despite their ACLs. Root still needs the right token scope/app and source write capability.
Use createuser --administrator for an administrator without root document access.
For stdio MCP set FRAMEWORK_TOKEN_FILE to a private credential file
created with manage.py login or manage.py mcp-token. Never put identities in tool args.

Customize only the App fields you need: parser, ingestion grants, collection policy or
retrieval provider/store. No extra configuration files are required. For example, add
these imports to apps/sample/app.py and configure only the needed fields:

```python
from galmuri import DatabaseConfig, IngestConfig, ParsingConfig, RetrievalConfig

# Optional App keyword arguments; empty Config objects preserve built-in defaults.
# parser=ParsingConfig(my_parser, identity="company:parser", revision="1")
# ingestion=IngestConfig(readers=("*",), writers=())
# retrieval=RetrievalConfig(batch_size=16, mode="hybrid")
# database=DatabaseConfig(alias="default")
```

Partial RetrievalConfig settings inherit missing embedding/store providers. The default
store follows the App database selection; an explicit store overrides it. Constructors
do not load model weights. Explicit retrieval=None chooses lexical-only search.
Ordinary named parser functions also work directly as parser=my_parser and normalize to
ParsingConfig. Use dataclasses.replace to customize shared immutable Config objects.
Changed parser/ingestion revision requires explicit activate. Inspect describe to see
which defaults were selected, and status/index-status for stage failures and retry state.
Source-library IO and framework ingestion have separate ownership; no vendor API client
belongs in the ingestion function. Ordinary explicit handlers remain supported.
For a generated pipeline with separate normalization and metadata functions, use
python -m galmuri new OTHER_PATH --process. App(process=...) connects a callable;
Pipeline.default().then(Step("normalize", process=normalize)) adds a document step.
"""
