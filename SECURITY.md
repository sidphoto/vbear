# Security policy

SID Console launches and controls coding agents on your machine, so we take vulnerabilities seriously.

## Reporting a vulnerability

Please **do not open a public issue.** Report it privately through GitHub:
**Security → Report a vulnerability** on this repository, or use
[this link](https://github.com/sidphoto/sid-console/security/advisories/new).

Please include:
- the version or commit;
- your macOS and Python versions, and the Claude Code or Codex versions if relevant;
- steps to reproduce, and what an attacker gains.

You will get an acknowledgement within 7 days. This is a one-person project, so fixes are best-effort.
You will be credited in the advisory unless you prefer not to be.

English or Traditional Chinese is fine. 中文或英文皆可。

## Scope

The following are in scope:
- escaping the managed launch boundary, or making the launch preview claim something that is not true;
- bypassing the browser protections (CSRF, DNS rebinding, cross-site reads);
- reading or writing files outside what the docs describe;
- leaking secrets from skill files through the UI.

The following are **known and documented**, so they are not vulnerabilities on their own (see
[docs/SECURITY-MODEL.md](docs/SECURITY-MODEL.md)):
- local programs calling the unauthenticated API on `127.0.0.1`;
- reads that are not isolated;
- `!` commands that bypass the sandbox;
- commits that cannot be prevented.

## Supported versions

Only the latest release on `main` receives fixes.
