# Contributing with coding agents

- Read README.md and CONTRIBUTING.md; user documentation describes current behavior.
- The product is Galmuri (갈무리), package/import/CLI `galmuri`. Source access uses Duru.
- Keep modules cohesive and hierarchical. Source IO belongs in Duru; processing and publication belong here.
- App owns workflow, discovery, scheduling and retry policy; the runtime executes it.
- Each stateful capability owns its transitions, effects, invariants and recovery.
- Preserve callback contracts and check current lease, source version, permissions and active configuration before accepting results.
- Keep parsing, inference and external IO outside metadata transactions.
- Exposure adapters call the shared service; tool arguments never establish account identity.
- Add meaningful contract/recovery/race tests for behavior changes; use the README's checks.
- Request independent code/structure and lifecycle/contract review for nontrivial changes.
- Keep README.md and README.ko.md aligned; do not publish local credentials, state, private documents or work logs.
