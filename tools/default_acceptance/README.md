# Default source-only acceptance

From the framework project root, after installing the package:

```sh
python -m tools.default_acceptance \
  --project .verification/default-model-project \
  --evidence ../docs/implementation/acceptance/default-model
```

The project path must not exist. The tool generates the normal scaffold without
editing its App, handler, parser, embedding or store configuration. It exercises real
multilingual FastEmbed inference and default local SQLite vectors. No external vector
service or paid API key is required. The first inference downloads model weights;
`EMBEDDING_CACHE` can point to an existing model cache. Leave `EMBEDDING_MODEL` unset
when validating the default model.

The unchanged generated settings use public read/write fallback grants. Actual source
capabilities still apply: the generated source is read-only. No document owner is inferred.
The scenario first queries as anonymous, then creates UUID accounts, a group and opaque
MCP credentials in the real identity directory. It verifies explicit empty grants,
ordinary administrator isolation, explicit root document ACL bypass, and root token scope/app
limits. Group removal and root/ordinary token revocation are also injected immediately after
actual vector store IO to verify revalidation before any text is returned. Group changes
require no new embeddings; expired or revoked credentials remain denied after public access
is restored. Raw credentials and passwords are never written to evidence.

The JSON report also records resolved metadata, lexical versus semantic results, restart,
update/deletion intent fences, physical vector cleanup and release of private ingestion
checkpoint payloads. Generated sample input files are updated/deleted as part of the
isolated scenario. Keep evidence outside the repository; for the account/dashboard change:

```sh
python -m tools.default_acceptance \
  --project .verification/identity-default-model-project \
  --evidence ../docs/implementation/acceptance/identity-dashboard-2026-10-16/model
```

To run the same acceptance through pytest:

```sh
FRAMEWORK_LIVE_DEFAULTS=1 python -m pytest tests/integration/test_default_model_live.py -q
```

This test is skipped during ordinary offline regression runs.
