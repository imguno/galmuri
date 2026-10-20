# Release procedure

English · [한국어](RELEASE.ko.md)

## Before a release

1. Update package versions and the dependency range, and prepare GitHub Release notes.
2. Run local checks and inspect the staged/public files for private material.
3. Run distribution verification from a clean source snapshot. Validate both the
   wheel and sdist, the installed CLI/API, packaged assets and agent skill.
4. Confirm the current commit's CI results, dependency audit and independent review.
5. Configure the protected GitHub environment `pypi` and the corresponding PyPI
   Trusted Publisher. Do not put a PyPI API token in repository secrets.

A main-branch push runs CI only. Publishing starts on a **published GitHub Release**.
Use an exact version tag, for example `v0.1.0` for package version `0.1.0`.
The release workflow checks the tag/version, runs CI, rebuilds and validates distributions,
then the separate `pypi` environment job publishes using GitHub OIDC.
Previously published versions are not overwritten.

## Initial registry setup

In PyPI, configure a pending/trusted publisher using the actual GitHub owner,
repository, workflow `publish.yml`, and environment `pypi`.
For these repositories the owner is `imguno`, and the repositories are
`duru` and `galmuri`. Account verification and any required 2FA are managed on PyPI.

Release **Duru first**, confirm `pip install duru==VERSION` from PyPI in a clean
environment, then release Galmuri against that available dependency.
Registry publication requires PyPI-side setup; committing a workflow is not a publish.

## Installation verification and rollback

Use a fresh virtual environment to install the exact published version. Run
`python -m pip check` and the README examples, including Galmuri project creation.
Verify the package comes from the intended project, not an older local checkout.

If a release is broken, stop further releases and investigate. Publish a new version
rather than trying to overwrite files. PyPI yanking is a separate maintainer action.
For deployed apps, back up state before activation; older code must not run concurrently
with incompatible schema/configuration. There is no automatic database rollback.

See [CI setup](../guides/ci.md) for the Galmuri companion repository variables and checks.
