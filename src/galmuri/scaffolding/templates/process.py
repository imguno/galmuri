"""Runnable stage functions and a small linear process declaration."""

BINDING = '''"""Select function references; the framework invokes and checkpoints them."""
from galmuri import Pipeline, Step
from .views.normalization import normalize
from .views.metadata import label

process = (
    Pipeline.default()
    .then(Step("normalize", process=normalize, accepts="documents", returns="documents"))
    .then(Step("label", process=label, accepts="documents", returns="documents"))
)
'''

NORMALIZATION = '''"""One replaceable documents-to-documents implementation."""
from dataclasses import replace


def normalize(documents):
    return tuple(replace(document, text=document.text.strip() + "\\n") for document in documents)
'''

METADATA = '''"""Enrich accepted document values without modifying their input."""
from dataclasses import replace


def label(documents):
    return tuple(
        replace(document, metadata={**document.metadata, "pipeline": "sample"})
        for document in documents
    )
'''

README = """# Your document service with custom processing

This is your application built with Galmuri. Connect your sources, edit the processing
functions, and choose an interface for other applications to use the results.
An App connects one source with its processing, retrieval and execution policy.
Register more Apps in config/settings.py as needed. Your LLM application obtains
evidence through search/read; prompts, conversation and answer generation stay there.
EXPOSURE_ADAPTERS registers custom exporters and EXPOSURES configures their options.

Run `python manage.py sync`, then inspect the result:

```sh
python manage.py index-status --app sample
python manage.py call describe --app sample
python manage.py call search --app sample --mode vector --query "몸이 아프면 누구에게 가나요?"
python manage.py serve mcp
```

The default multilingual model is real and downloads weights on first inference.
Set EMBEDDING_CACHE for a persistent cache. Use config/settings.py for deployment,
DB aliases, identity and permission defaults. Source IO belongs to the resource library.

apps/sample/process.py connects named functions in views/ by reference. The default
parser produces documents, normalize and label transform them in the declared order,
and automatic preparation applies settings permission defaults before publication.
Use .then(Step(...)) to add another document stage; change declaration order to change
execution order. File-to-document and final result steps have explicit contracts.
No Request class, custom base class, graph scheduler or manual DB write is required.

The framework stores each validated stage output. A failed stage resumes from the
last accepted output under the standard Runtime worker; earlier accepted steps are
not rerun. HTTP remote workers and custom workflows retry the whole process.
Callbacks must be pure or
idempotent: a crash before checkpoint can invoke a callback again. Change an explicit
stage revision when changing behavior without changing its function name, then activate
the changed configuration. Status exposes progress, never private checkpoint data.

Vector indexing has its own publication/retry lifecycle. Replace its Chunker,
EmbeddingProvider or VectorStore, or connect functions with ChunkingConfig and
EmbeddingConfig. The framework controls vector writes, current ACL checks and generation
publication; document callbacks do not acquire framework DB connections.

See `python manage.py --help` for processing/index workers, activation and transports.
"""
