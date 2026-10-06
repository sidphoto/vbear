# Contributing to VBear

Thanks for your interest. This is a small, early project maintained by one person, so please
**open an issue or a discussion before starting a large change**. Issues in English or Traditional
Chinese are both welcome.

## Before you start

- Keep each change scoped to one clear user-facing improvement, bug fix or refactor.
- macOS is the only supported platform for now. Code that is not macOS-specific should stay portable,
  and macOS-only paths must be explicit.
- No new dependencies: the backend uses the Python standard library only (3.13+), and the front end has no build step.
- User-facing text is Traditional Chinese (zh-TW). If you are not comfortable writing it, write
  English and the maintainer will translate it.
- Follow the ground rules in [AGENTS.md](../AGENTS.md). They apply to humans too: be truthful in the UI,
  fail closed, and never touch real user data in tests.

## Local setup

```sh
git clone https://github.com/sidphoto/vbear.git
cd vbear
VBEAR_HOME=$(mktemp -d) python3 -m vbear serve --port 7790 --open
```

Using a temporary `VBEAR_HOME` and another port keeps your development console separate from
your everyday one.

## Branch naming

Use a descriptive name, for example `fix/stream-reconnect-loop`, `feat/read-only-profile` or
`docs/security-model`. Avoid vague names like `test` or `changes`.

## Before opening a PR

Run what CI runs:

```sh
python3 -m unittest discover -s tests
for f in tests/frontend/*.cjs; do node "$f" || exit 1; done
```

Add tests that would catch a regression, not only the happy path.

## Pull requests

Follow the [PR template](pull_request_template.md):
- If you are an outside contributor, link the issue your PR addresses.
- Open with a plain-language summary; the title is the one-liner.
- Explain what changed and why, and keep to a single topic.
- Attach **before and after** screenshots for any UI change, or write `N/A`.
- If you used an AI coding agent, include its short review of the change: security impact on the
  launch boundary and browser surface, truthfulness of UI text, and test coverage.
- **Security-sensitive changes** to the launch boundary, the runtime socket or the HTTP protections must
  update [docs/SECURITY-MODEL.md](../docs/SECURITY-MODEL.md).

Contributions are accepted under the project's [MIT License](../LICENSE). There is no CLA.

## Releases

Version bumps, tags and releases are handled by the maintainer. Please do not change version numbers in a PR.

For maintainers:
1. Set `__version__` in `vbear/__init__.py` and move the CHANGELOG notes under `## vX.Y.Z`.
2. Build and check locally: `./macos/build.sh`, then `./macos/smoke_test.sh dist/VBear-X.Y.Z-arm64.dmg`.
3. Tag and push (`git tag -a vX.Y.Z && git push origin vX.Y.Z`). The **Release** workflow tests, builds the app
   and attaches the `.dmg` and its `.sha256` to the GitHub Release.
4. Update `version` and `sha256` in `Casks/vbear.rb` of [sidphoto/homebrew-tap](https://github.com/sidphoto/homebrew-tap)
   with the CI-built `.sha256`.
