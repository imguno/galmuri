# Galmuri continuous integration and release verification

[Back to the overview](../README.md)

The CI workflow checks pull requests, pushes and manual runs. It verifies code and
builds; it does not publish packages, deploy services or push commits. GitHub-hosted
execution starts only after the repository is pushed and the companion source is
configured. Local test results or workflow syntax checks are not evidence that a
GitHub Actions run has passed.

## Configure the companion repository first

The framework and duru library are separate repositories. The library
is not yet published, so CI must use its reviewed source rather than resolve a
similarly named package from a public index.

In the framework repository, open **Settings → Secrets and variables → Actions →
Variables** and configure these repository variables:

| Variable | Required value |
| --- | --- |
| `RESOURCE_ACCESS_REPOSITORY` | The actual public companion repository, in `owner/repository` form. |
| `RESOURCE_ACCESS_REF` | A reviewed, complete 40-character Git commit SHA from that repository. |

No repository name or remote URL is assumed. A branch name, tag or abbreviated SHA
is rejected before dependent jobs start. The companion must be public: the
workflow uses the ordinary read-only repository token and does not require a
personal token or a fork-only secret.

CI checks out the two sources next to each other:

```text
workspace/
├── framework/    # The framework revision under test
└── access/       # The configured companion repository and trusted commit
```

Both are explicit local install inputs. Updating the companion means reviewing a
new commit and deliberately changing `RESOURCE_ACCESS_REF`; CI does not follow an
unreviewed moving branch. A matching public-index package is not a substitute for
a missing companion checkout.

## Verification jobs

| Job | Coverage |
| --- | --- |
| Validate companion source | Required repository variables and immutable commit syntax. |
| Linux Python 3.12, 3.13 and 3.14 | Full test suite, PostgreSQL contracts and integration, source ingestion, transports and dashboard lifecycle tests. |
| Windows Python 3.13 | Full cross-platform suite, including the dashboard lifecycle harness. |
| Formatting and lint | Ruff checks on Python 3.13 Linux. |
| Verify built distributions | Build and verify fresh installations using `python -m tools.release`. |
| Audit installed dependencies | Check public dependencies against vulnerability advisories, without suppressing advisory IDs. |
| Required checks | Fail unless every preceding required job succeeds. |

Node.js 22 is installed explicitly so the dashboard JavaScript lifecycle test does
not disappear behind an optional-runtime skip. The Linux jobs start a disposable
PostgreSQL 17 service and provide `FRAMEWORK_POSTGRES_DSN`, enabling the actual
database tests, including process isolation and pipeline recovery. PostgreSQL is
bound to runner loopback only. Its trust authentication is restricted to this
disposable CI service; it is not a deployment configuration and uses no production
credentials. Each database fixture creates its own schema and removes it afterward.

The Windows job has no PostgreSQL service, so tests requiring a configured remote
DSN skip there; the Linux matrix supplies that coverage. Tests explicitly requiring
downloaded neural model weights or an external Qdrant service remain opt-in. CI does
not claim live LLM acceptance and receives no model-provider API keys. Run those
acceptance scenarios separately when the required services are available.

## Local commands

Run from the framework checkout with the companion at `../access`:

```sh
python -m pip install -e ../access -e '.[dev,release,mcp,grpc,postgres]'
python -m ruff check src tests tools
python -m ruff format --check src tests tools
python -m pytest -q --junitxml=.verification/reports/pytest.xml
python -m tools.release --resource-access ../access --output .verification/release
```

Set `FRAMEWORK_POSTGRES_DSN` to a disposable local PostgreSQL service before running
the tests to include remote database coverage. Do not point the test suite at a
production database. Node.js 22 should be on `PATH` for the dashboard lifecycle
harness.

The dependency audit runs against installed versions. Only the two unpublished
local distributions, `galmuri` and `duru`, are excluded from
public-index lookup; their public dependencies remain in scope. A failed audit is
a failing check. A temporary registry outage is not treated as a passing audit.

## Reports and dependency updates

JUnit test reports, built wheels/source distributions, package verification JSON
and the dependency audit JSON are uploaded using explicit paths even when their job fails. Artifacts are retained
for 14 days. No workspace-wide upload, generated `.runtime` directory, token,
environment file or credential cache is included. A job that fails before producing
a report may have no artifact; its step log remains the source of the failure.

All third-party actions are pinned to complete commit SHAs. Dependabot proposes
weekly GitHub Actions and Python dependency updates. Its Python configuration
excludes updates to the unpublished `duru` distribution because its
source is selected by the trusted companion commit, not by the public package
index. This exclusion does not suppress security advisories for other packages.

Before enabling branch protection, configure the companion and obtain a successful
GitHub run. Then require the stable **Required checks** check and an independent
review on the protected branch. Review dependency and action-pin changes before
merging. The workflow does not configure repository rules or merge automatically.
