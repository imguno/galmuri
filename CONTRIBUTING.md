# Contributing

English · [한국어](CONTRIBUTING.ko.md)

Start with the README and reproduce the behavior you want to change.
For a bug, include the package/Python versions, the command or minimal code, expected
behavior, and a redacted error. For an extension, describe the supported operations
and a small working example.

## Local checks

Run the development commands in the README. Use focused tests while working, then
run the relevant integration suite before sharing a change. Keep English and Korean
user documentation aligned. CI checks style, tests, dependency advisories, and
distribution installation; a green local test does not imply CI has run.

Source providers must keep credentials injected. Processing callbacks should return
the documented values; changes to durable transitions, retries, permissions or
publication need race/recovery coverage and independent review.

## Pull requests

Describe the user-visible problem and result. Include validation and any migration
requirements. Avoid unrelated rewrites. Never attach real tokens, private documents,
account databases, environment files, or local execution logs containing credentials.

Report vulnerabilities through the private route in [SECURITY.md](SECURITY.md).
Contributions are distributed under the [BSD 3-Clause license](LICENSE).
