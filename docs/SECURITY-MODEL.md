# Security model

This page covers what SID Console protects, what it does not protect, and the evidence for each claim.
For how to report a vulnerability, see [SECURITY.md](../SECURITY.md).

## Assumptions

- **A single-user Mac.** SID Console runs as your user, and only you use the machine.
- You trust the coding agents' own CLIs, such as Claude Code, and their providers. SID Console limits what
  a *launched session* can change on disk. It does not protect you from the CLI vendor.

## The browser surface

| Threat | Mitigation |
|---|---|
| Another website reads your data | Read requests that carry `Sec-Fetch-Site` other than `same-origin` or `none` are rejected |
| Another website makes changes (CSRF) | Writes need the `X-SID-Console: 1` header and a same-origin `Origin` |
| DNS rebinding | The server binds to `127.0.0.1`, and the `Host` header must be a local address |
| Skill content injecting script | Strict CSP (`script-src 'self'`), `textContent` only, no `innerHTML` |
| Oversized or slow requests | Bodies over 64 KiB get 413; a body must arrive within 15 s |
| Secrets inside skill files | API keys, tokens and PEM blocks are masked in the index, previews and warnings |

`style-src` allows `'unsafe-inline'`, because xterm.js sets inline styles for 24-bit colour. No
user-controlled HTML or CSS reaches the page.

### Not protected: other local programs

The local API has **no authentication.** The header and Origin checks stop browsers, but they do not stop
other programs. Any program on the machine, under any user account, can connect to `127.0.0.1:7788`.
Such a program can open a terminal running any command as you (`POST /api/native/sessions`) and type
into existing terminals. Do not run SID Console on a machine shared with people or programs you do not trust.

The runtime socket (`~/.sid-console/runtime.sock`) is narrower: it accepts only connections from your own uid.

## Terminals

- Opening a terminal in the browser only **observes** it. Typing requires an explicit takeover, and only
  one tab holds control at a time.
- Output stays in memory and is never written to disk by SID Console. On connect, only the most recent
  output is replayed, up to 64 KiB.
- xterm.js runs with `linkHandler: null` and with window operations disabled. No clipboard (OSC 52) or link addon is loaded.

## Profile-managed Claude launches

These are the claims the launch preview makes, and their status:

| Claim | Status | Evidence |
|---|---|---|
| Bash cannot write outside the work directory and the session's scratch directory | Enforced by Claude Code's OS sandbox (Seatbelt) | The maintainer's boundary tests against the pinned version (not yet published as a reusable script); the shared `/tmp/claude-<uid>` is explicitly denied |
| No network from Bash | Enforced: `allowedDomains: []`, `strictAllowlist: true` | External connection refused with `EPERM` |
| Bash cannot reach SID Console itself | Enforced by the same sandbox | `127.0.0.1:<console port>` and `runtime.sock` both refused with `EPERM` (Claude Code 2.1.291 in headless mode, 2026-10-06) |
| Edit and Write tools are unavailable | `--tools Bash --disallowedTools Edit,Write`; those tools would not be covered by the Bash sandbox | Launch argv is built server-side from trusted values only |
| No MCP servers or project hooks from the work directory | `--safe-mode --strict-mcp-config` | |
| Commit is possible | **Not prevented.** `.git` is inside the writable work directory; you must acknowledge this before launch | |
| Deploy is denied | Only by the absence of network access | |
| Reads are isolated | **No.** A session can read anything your user account can read | |
| Commands you type with `!` are sandboxed | **No.** Claude Code runs `!` commands outside the sandbox; the preview says so | |

Other safeguards:
- **Fail closed.** The launch is refused if the installed Claude Code version is not the pinned one, if
  the sandbox is unavailable (`failIfUnavailable`), or if the profile, work directory or config changed
  since the preview.
- **No caller-supplied launch details.** The daemon's `open_managed` takes only a launch ID. It reads
  the manifest from its own state directory and re-validates the work directory. A launch ID is single-use.
- **Cleanup only when it is proven safe.** Files belonging to a launch are removed only after every
  descendant process is confirmed gone. Otherwise the launch is kept for manual review.

## Data handling

- No telemetry, analytics, crash reporting or update checks. The only HTTP client in the code talks to
  the local console itself.
- State lives in `~/.sid-console/`. The directory has mode `0700` and its files `0600`, written atomically.
- If `config.json` is corrupt, it is never overwritten. It is backed up, scanning is turned off, and a
  warning is shown.
