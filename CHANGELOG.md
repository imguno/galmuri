# Changelog

English · [한국어](CHANGELOG.ko.md)

## 0.1.0 — 2026-10-18

- Galmuri: generated apps, replaceable parsing/processing and linear step pipelines.
- Duru: independent local, Google Drive and Slack resource access.
- Lexical/vector/hybrid search with replaceable chunking, embeddings and stores.
- Account/group document permissions, root accounts and personal MCP tokens.
- Dashboard document explorer and MCP, HTTP, gRPC and CLI interfaces.
- SQLite/PostgreSQL state, app-specific database selection and durable recovery.
- Separate document/vector publication and cleanup of retired vector generations.
- English/Korean onboarding and a bundled Galmuri usage skill.

Python imports are `galmuri` and `duru`. Code using earlier local placeholder imports
must update them before activating the new app configuration.
Large-corpus performance and long-running production operation are not release claims.
