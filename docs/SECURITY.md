# Security policy

English · [한국어](SECURITY.ko.md)

## Reporting

Use this repository's **Security → Report a vulnerability** private reporting feature.
Include affected versions, prerequisites, a minimal reproduction using synthetic data,
impact, and any suggested mitigation. Do not open a public issue with exploit details
or send live credentials. If private reporting is unavailable, wait for a private
reporting route rather than posting sensitive material publicly.

## Support scope

This is a development preview. Fixes target current development and the latest preview;
there is no response-time or long-term-support commitment yet. Dependency audit results
describe the installed versions at the time of the check, not a security guarantee.

## Deployment

Keep credentials in environment variables or private credential files outside Git.
Use verified account credentials for restricted documents. Configure document permission
defaults before serving private content: generated default settings allow public access.
Root can bypass document ACLs; restrict root credentials and token scopes.

Use HTTPS and an explicit public origin for the dashboard. Keep databases, model caches,
source credentials, worker credentials, and private documents outside the application
image. Treat retrieved document text and source-provided guides as untrusted content,
not authorization or instructions to disclose secrets.

Before changing versions, back up authoritative state and review the release notes.
A rollback of code does not roll back an external write or a changed database.
