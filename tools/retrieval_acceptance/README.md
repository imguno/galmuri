# Real semantic acceptance

This opt-in check uses a newly generated `--retrieval` project, actual ONNX neural
embeddings, and an existing Qdrant server. It does not replace either provider
with a deterministic collaborator. The default test suite skips the network check.

Install the framework's `embeddings` extra first. Start the Qdrant service from a
generated retrieval project's `compose.yaml`, or supply an isolated test server.
From this repository's root:

```sh
python -m tools.retrieval_acceptance \
  --project .verification/semantic-run-001 \
  --evidence ../docs/implementation/acceptance/semantic-run-001 \
  --qdrant-url http://127.0.0.1:6333 \
  --cache .verification/models
```

The project directory must not exist. The model is
`sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2`, with 384 dimensions;
the first run downloads its weights. `QDRANT_API_KEY` is optional and is never
written into the evidence. `QDRANT_URL` and `EMBEDDING_CACHE` can replace the
corresponding arguments. The pytest entry point runs the same scenario in a
separate process, with a ten-minute timeout:

```sh
FRAMEWORK_LIVE_QDRANT=1 \
QDRANT_URL=http://127.0.0.1:6333 \
EMBEDDING_CACHE=.verification/models \
python -m pytest tests/retrieval/integration/test_real_qdrant_model.py
```

`summary.json` records actual vector/hybrid results, matching chunk anchors,
embedding descriptors, build identifiers, remote point observations, and the
final lifecycle state. Checks include:

- Korean paraphrase with no lexical match, ranked first by vector and hybrid search.
- Current public/developer permissions and revocation without re-embedding.
- A fresh Qdrant adapter after runtime restart.
- Update and delete intent withdrawal before ingestion processes the change.
- Physical cleanup of retired points, independently observed through Qdrant REST.
- Explicit reindex producing new generations.
- Explicit configuration activation and retirement of the old namespace.

Each run uses its own random collection prefix. It leaves generated projects,
evidence, and those isolated collections available for inspection. It never drops
collections or removes existing directories. A dedicated disposable Qdrant
instance is recommended for repeated runs. This validates a small fixture's
correctness; it does not measure retrieval quality across a benchmark corpus or
provide an ANN performance result. Actual LLM/MCP acceptance is a separate check.
