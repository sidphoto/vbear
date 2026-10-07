# Security model

This page covers what VBear protects, what it does not protect, and the evidence for each claim.
For how to report a vulnerability, see [SECURITY.md](../SECURITY.md).

## Assumptions

- **A single-user Mac.** VBear runs as your user, and only you use the machine.
- You trust the coding agents' own CLIs, such as Claude Code, and their providers. VBear limits what
  a *launched session* can change on disk. It does not protect you from the CLI vendor.

## The browser surface

| Threat | Mitigation |
|---|---|
| Another website reads your data | Read requests that carry `Sec-Fetch-Site` other than `same-origin` or `none` are rejected |
| Another website makes changes (CSRF) | Writes need the `X-VBear: 1` header and a same-origin `Origin` |
| DNS rebinding | The server binds to `127.0.0.1`, and the `Host` header must be a local address |
| Skill content injecting script | Strict CSP (`script-src 'self'`), `textContent` only, no `innerHTML` |
| Oversized or slow requests | Bodies over 64 KiB get 413; a body must arrive within 15 s |
| Secrets inside skill files | API keys, tokens and PEM blocks are masked in the index, previews and warnings |

`style-src` allows `'unsafe-inline'`, because xterm.js sets inline styles for 24-bit colour. No
user-controlled HTML or CSS reaches the page.

### Other local programs: the access token

Since v0.2, every `/api/` request needs a **random token that is new for each server start**
(`secrets.token_urlsafe(32)`). Requests without it get `401`. Static files (`/`, `app.js`, CSS) need no token
and contain no data.

- The token is written only to `~/.vbear/server.token` (mode `0600`, inside the `0700` state directory),
  and to `~/.vbear/open.html`, the page the launcher opens. Both are removed when the server stops.
- A browser exchanges it once (`POST /api/auth`) for an `HttpOnly; SameSite=Strict` cookie named after the
  port. The token reaches the browser only as a URL fragment written by that local file, and the page removes
  it from the address bar at once. It never appears in a command line.
- Local tools send `Authorization: Bearer <token>`.

The result is that **other user accounts on the Mac can no longer drive VBear**, because they cannot read your
state directory. **Programs running as your own user still can,** because they can read the token file, just as
they can read anything else you own. Sandboxed Agent sessions can read the file too (reads are not isolated),
but their network access to `127.0.0.1` is refused by the sandbox (see the table below).

The runtime socket (`~/.vbear/runtime.sock`) is narrower: it accepts only connections from your own uid.

## Terminals

- **Built-in terminals** (`POST /api/native/terminals`) run your login shell (`/etc/shells`-listed
  account shell, else `/bin/zsh`) with `-l` in a folder under your home directory. The server picks the
  command; the request accepts only `cwd`, `cols` and `rows`. They are **not sandboxed**: they are
  exactly as powerful as Terminal.app, and the UI labels them so. They take input control as soon as
  they connect, without the takeover dialog Agent terminals use.
- Opening a terminal in the browser only **observes** it. Typing requires an explicit takeover, and only
  one tab holds control at a time.
- Output stays in memory and is never written to disk by VBear. On connect, only the most recent
  output is replayed, up to 64 KiB.
- xterm.js runs with `linkHandler: null` and with window operations disabled. No clipboard (OSC 52) or link addon is loaded.

## Profile-managed Claude launches

These are the claims the launch preview makes, and their status:

| Claim | Status | Evidence |
|---|---|---|
| Bash cannot write outside the work directory and the session's scratch directory | Enforced by Claude Code's OS sandbox (Seatbelt) | Evidence for [2.1.292](evidence/claude-code-2.1.292.md#writes), [2.1.291](evidence/claude-code-2.1.291.md#writes) and [2.1.286](evidence/claude-code-2.1.286.md#writes); the shared `/tmp/claude-<uid>` is explicitly denied |
| No network from Bash | Enforced: `allowedDomains: []`, `strictAllowlist: true` | Evidence for [2.1.292](evidence/claude-code-2.1.292.md#network), [2.1.291](evidence/claude-code-2.1.291.md#network) and [2.1.286](evidence/claude-code-2.1.286.md#network): external connection refused with `EPERM` |
| Bash cannot reach VBear itself | Enforced by the same sandbox | `127.0.0.1` listener and unix socket both refused with `EPERM`, headless and interactive, on [2.1.291](evidence/claude-code-2.1.291.md#network); headless-only spot check on 2.1.291 for the 2.1.286 page; **not re-run on 2.1.286 itself** |
| Edit and Write tools are unavailable | `--tools Bash --disallowedTools Edit,Write`; those tools would not be covered by the Bash sandbox | Launch argv is built server-side from trusted values only |
| No MCP servers or project hooks from the work directory | `--safe-mode --strict-mcp-config` | |
| Commit is possible | **Not prevented.** `.git` is inside the writable work directory; you must acknowledge this before launch | |
| Deploy is denied | Only by the absence of network access | |
| Reads are isolated | **No.** A session can read anything your user account can read | |
| Commands you type with `!` are sandboxed | **No.** Claude Code runs `!` commands outside the sandbox; the preview says so | |

Other safeguards:
- **Unverified Claude Code versions are labelled, not hidden.** A genuine Claude Code release that is not on the
  verified list (built-in, or verified on this Mac and recorded in `~/.vbear/claude-verified.json`) still gets the
  same sandbox settings, but Write, Network and Filesystem are labelled **unverified** with no evidence, and the
  launch is refused unless the request carries `accept_unverified_cli: true` (the dialog's checkbox). The internal
  one-shot launch path never starts an unverified version. Output that is not a Claude Code version is still refused.
  When a verified version is installed, it is used in preference to a newer unverified one.
- **The version is what the program says it is.** The gate reads `claude --version`; it is not binary
  authentication. VBear prefers Claude Code's own versioned install (`~/.local/share/claude/versions/<version>`),
  pins the file's identity between preview and launch, and shows the path in the preview. A program that can put
  itself first on your `PATH` already runs as you, so this is not treated as a boundary.
- **Verifying on this Mac.** 「驗證這個版本」 runs `vbear/boundary_check.py` headless and interactive against
  the binary a launch would use. The version is recorded as verified only if both runs pass every check; a
  refusal only counts if it is the sandbox's (`EPERM`/`EACCES`, or the proxy's 403). The record file is
  owner-only. Any program running as you could edit it, as it could edit anything else you own.
- **Fail closed** otherwise: the launch is refused if the sandbox is unavailable (`failIfUnavailable`), or if the
  profile, work directory, Claude Code binary or config changed since the preview.
- **No caller-supplied launch details.** The daemon's `open_managed` takes only a launch ID. It reads
  the manifest from its own state directory and re-validates the work directory. A launch ID is single-use.
- **Cleanup only when it is proven safe.** Files belonging to a launch are removed only after every
  descendant process is confirmed gone. Otherwise the launch is kept for manual review.

## Data handling

- No telemetry, analytics, crash reporting or update checks. The only HTTP client in the code talks to
  the local console itself.
- State lives in `~/.vbear/`. The directory has mode `0700` and its files `0600`, written atomically.
- If `config.json` is corrupt, it is never overwritten. It is backed up, scanning is turned off, and a
  warning is shown.
