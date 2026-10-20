"""Opt-in app composition for real neural embeddings and an external vector store."""

CONFIGURATION = '''"""App-owned retrieval choices; credentials are injected by deployment."""
import os
from pathlib import Path
from galmuri.retrieval import (
    FastEmbedEmbedding, QdrantVectorStore, RetrievalConfig,
)

ROOT = Path(__file__).resolve().parents[3]
retrieval = RetrievalConfig(
    embedding=FastEmbedEmbedding(
        model=os.environ.get(
            "EMBEDDING_MODEL", "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
        ),
        cache_dir=os.environ.get("EMBEDDING_CACHE", str(ROOT / ".runtime" / "models")),
    ),
    store=QdrantVectorStore(
        os.environ.get("QDRANT_URL", "http://127.0.0.1:6333"),
        api_key=os.environ.get("QDRANT_API_KEY"),
    ),
    mode=os.environ.get("SEARCH_MODE", "hybrid"),
)
'''

QDRANT_IMAGE = (
    "qdrant/qdrant:v1.19.2@sha256:b7b0444c4c351c970b98e90a6f89c2ee4287c65b44e52b4cb503fa5b2aa927ad"
)

COMPOSE = f"""services:
  qdrant:
    image: {QDRANT_IMAGE}
    ports:
      - "127.0.0.1:6333:6333"
    volumes:
      - vectors:/qdrant/storage
volumes:
  vectors:
"""

GUIDE = """# Semantic sample

This app supports lexical, vector, and hybrid retrieval. Use describe to inspect
the active embedding model, chunking and search modes. Operators inspect indexing
progress with index-status.
For paraphrases and Korean natural-language questions use vector or hybrid.
Lexical search ranks analyzed terms with BM25; Hangul subwords tolerate spacing
and particles approximately. It can return partial matches; inspect the document.
Results include matching chunks with character offsets into the original text.
Read the cited document to ground an answer. Current document grants are enforced
for every mode, including administrator callers. Developer operations requires dev.
Source writes require the current version and enqueue normal reprocessing.
"""

CLINIC = """# 진료 안내

아픈 사람은 병원의 의사에게 진료를 받습니다.
예약 확인 번호는 CLINIC-42입니다.
"""

README = """# Source project with semantic retrieval

Install galmuri with the embeddings and desired transport extras first.
For a source checkout, install `../duru` and `.[embeddings,mcp,grpc]` from the
framework directory. Then start Qdrant and collect the included sample documents:

```sh
docker compose up -d
python manage.py sync
python manage.py index-status
python manage.py call search --app sample --mode vector --query "몸이 아프면 누구에게 가나요?"
python manage.py serve mcp
```

The first embedding operation downloads a real multilingual model into
`.runtime/models`. Query/provider configuration belongs to
`apps/sample/retrieval/configuration.py`; ingestion and permission assignment stay
in `apps/sample/ingestion/documents.py`. Set QDRANT_URL/QDRANT_API_KEY or
EMBEDDING_MODEL/EMBEDDING_CACHE in the host environment to override these app choices.
When running the framework itself in Docker, use a reachable QDRANT_URL rather
than the container's localhost and mount the model cache persistently.

Normal workers run both ingestion and indexing. To dedicate processes to embedding
and vector storage, run `python manage.py index`. `reindex` queues new generations;
`index --drain` processes currently eligible work. Failed builds appear in
`index-status` and can be requeued with `index-retry JOB_ID`.
Inspect status for retries/failures; a body ingestion success is not a vector-index
completion claim. Changed model/store/chunker identities require explicit `activate`
before rebuilding; queries never mix embedding generations.
"""
