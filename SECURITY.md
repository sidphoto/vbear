# Security policy

VBear launches and controls coding agents on your machine, so we take vulnerabilities seriously.

## Reporting a vulnerability

Please **do not open a public issue.** Report it privately through GitHub:
**Security → Report a vulnerability** on this repository, or use
[this link](https://github.com/sidphoto/vbear/security/advisories/new).

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
- leaking secrets from skill files through the UI;
- a chat that runs a tool without the permission card being answered, that keeps what the initialize answer carries (the
  account, commands, models or extra folders), or that spends more than its turn cap without the ledger saying so;
- the start-up page sending a command that does not come only from the server's list (a tool and an action are all the page
  may name), keeping or serving what a status command or a try printed (a status command is read by its exit code only), or
  starting a try that is not isolated or is not booked against the daily limit.

The following are **known and documented**, so they are not vulnerabilities on their own (see
[docs/SECURITY-MODEL.md](docs/SECURITY-MODEL.md)):
- local programs calling the unauthenticated API on `127.0.0.1`;
- reads that are not isolated;
- `!` commands that bypass the sandbox;
- commits that cannot be prevented;
- a chat's Edit or Write checked before the write and not held after it (Claude Code writes the file itself), and Claude
  Code's own reads, which are not isolated (see "Chats with a role card").

## Supported versions

Only the latest release on `main` receives fixes.
