APP = """from pathlib import Path
from galmuri import App
from .source.local import source
from .ingestion.documents import prepare
from .policies.collection import policy

sample = App(
    name="sample",
    source=source,
    handler=prepare,
    policy=policy,
    description="Sample knowledge: welcome guide and developer operations",
    guides=(Path(__file__).parent / "skills" / "usage.md",),
)
"""

SOURCE = """from pathlib import Path
from galmuri.sources.local import LocalFiles

source = LocalFiles(Path(__file__).resolve().parents[1] / "fixtures")
"""

INGESTION = """from galmuri.ingestion.parsers import parse_auto
from galmuri.ingestion.indexing import index_default

def prepare(file):
    readers = ("group:dev",) if ".dev." in file.name else ("*",)
    documents = parse_auto(file)
    return index_default(documents, readers=readers, writers=("group:dev",))
"""

POLICY = """from galmuri.collection.policies import SyncPolicy

# This app owns the discovery method, schedule and retry policy.
policy = SyncPolicy(mode="changes", interval=60, max_attempts=3, retry_delay=1)
"""

GUIDE = """# Sample source

Search for onboarding, framework, deployment or developer operations.
The welcome document is readable by everyone. Developer operations requires
the dev group. Writers in the dev group can update the source with its current
version; the normal collection and publication contracts then update search.
Search is lexical by default. Returned documents include source and version.
"""

WELCOME = """# Welcome

This sample demonstrates source apps, ordinary Python handlers and lifecycle
management. Connect a source in app.py, select its collection policy, and use
the same search and read contracts through CLI, HTTP API, MCP or gRPC.
"""

DEVELOPMENT = """# Developer operations

Deployment operations are restricted to the dev group. Retry failed work from
the admin page. Multiple worker processes can claim independent documents.
Remote workers use authenticated coordinator operations instead of sharing
open streams or database connections.
"""
