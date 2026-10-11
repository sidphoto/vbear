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

Attachment backpressure discards only queued `terminal.frame` lines (delta or full).
The handshake and protocol notices remain in their original order, with `out_bytes`
recomputed from the retained lines. A partially sent line is finished before one
capped full replay is built after the queue drains; overflow never splices a JSON line.

Client command processing and socket reads pause at 256 queued non-frame notices,
and resume after output drains. Each command generates at most one error. A takeover
can add one `control_lost` per attachment (it then remains observe-only), and session
closure can add one `closed`, so at most 258 notices can be queued, plus one current
partially sent line. These server-generated notices have bounded fields. Buffered input
is bounded by `MAX_LINE` plus one 65,536-byte read; paused reads cannot grow it.
The existing frame count/byte caps, 64 KiB replay cap and write-stall timeout still apply.


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

Terminal sessions and interactive boundary probes detect leader exits with
`waitid(WEXITED | WNOHANG | WNOWAIT)`, without reaping. Group signals are sent
only while the leader remains an unreaped child, keeping its PID/PGID from
being reused. The process table must prove that no non-zombie group member
remains before `waitpid` reaps the leader. On macOS, EPERM from signalling a
zombie-only group is tolerated; it does not prove cleanup. If the table is
unavailable or members survive, cleanup logs manual review and retains the
leader (and managed launch files). If ownership of the child is lost, no more
signals are sent, including to managed descendant groups. Spawn-setup failures
and daemon shutdown follow the same order. RPC/output/exit-code semantics and
the HUP → TERM → KILL close sequence are unchanged.

## Agent activity evidence

- For managed Claude sessions, the daemon classifies the terminal title Claude Code sets (evidence for
  [2.1.291](evidence/claude-code-2.1.291-activity.md) and [2.1.292](evidence/claude-code-2.1.292-activity.md)). The
  title comes from the Agent process itself: anything that can write to the session's terminal can set it. It is
  self-report, and it drives only what the UI shows (status badges, 「需要你處理」, task-card pickup). No launch,
  permission, cleanup or verification decision reads it.
- 「驗證這個版本」 checks the title in the same interactive run as the launch boundary and records the two results
  apart in `~/.vbear/claude-verified.json`. A title failure never undoes a boundary pass, and a title pass grants
  nothing beyond using the title for display. A title result counts only when the report's own events, judged again
  by `vbear/title_check.py`, pass all four checks (the summary written in the report never suffices). Records or
  reports of the wrong shape, non-finite or backward times, and missing results all count as title-unverified;
  reading them never raises. Like the rest of that file, it can be edited by programs running as you; the worst they
  can do with it is make a status badge wrong.
- Only the class of the title's first character and when it was seen are kept. The text, where Claude puts a
  summary of the current task, is discarded. OSC strings over 4 KiB are skipped, not buffered.
- Hooks are not used. `--safe-mode` stays in the launch argv, and it disables settings hooks.

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
  launch is refused unless the request carries `accept_unverified_cli: true` (the dialog's checkbox). Only then does
  the confirm step call `launch_prepared_agent_after_acknowledgement`, which records the acknowledgement in the
  launch's manifest in the state directory. The **runtime daemon**, which actually starts the process, decides on
  its own from the version whether it is verified and refuses an unverified one without that record. Every other
  launch method (`launch_prepared_agent`, the one-shot `create_managed_claude_session`) refuses unverified versions.
  Output that is not a Claude Code version is still refused.
  Code running as your user could call that method or write the record itself, just as it could start any program
  directly; as stated above, this model does not defend against programs running as you. What it does keep out:
  websites, other user accounts, sandboxed Agents, and a launch the UI did not show as unverified.
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

## Task cards

- **Commit binding never runs `git`.** Repository config (clean filters, fsmonitor and the like) can make git
  execute programs, and a managed Agent may write `.git` once commit is acknowledged; a git command run by the
  console would run that code outside every sandbox. `git_head` reads `HEAD`, refs and `packed-refs` as plain files
  instead: symlinked `.git`, `HEAD` and ref files are refused, files are opened non-blocking so a FIFO planted in
  `.git` is refused instead of hanging the request, sizes are capped, and every ref name and hash is validated. Nothing read is shown except a validated hash or ref name.
- **The binding notices change; it does not authenticate history.** Anyone who can write `.git` can point HEAD
  anywhere, including back to the approved commit. Uncommitted changes are not seen.
- Results, approvals, closure reasons and handoffs are still set through the same unauthenticated local UI/API, and
  `verified` stays false.

## Flows

- **No new execution capability.** The flows board records and shows. Its routes write only `flows.json`; nothing
  in `vbear/flows.py` starts a process, sends input to a terminal, runs `git` or contacts the network. The only
  outside reads are the executor directory's HEAD through `git_head` (plain bounded file reads, as for task cards)
  and the last live view already built (`Store.live_cached()`). The flows routes never build a live view, so they
  never reach the runtime and cannot start its daemon; a test holds them to that.
- **The pages still read live state the existing way.** The 「流程」 pages, like the home page, call `/api/live`. On
  the native runtime with autostart on (the default), that call starts VBear's own runtime daemon when it is not
  running (unchanged behaviour). It
  never starts an agent.
- **Manual means unverified.** Every event is entered through the UI/API by whoever can reach it with the access
  token, and is labelled 「手動記錄（未驗證）」. A recorded review result says someone typed it, not that a
  reviewer produced it.
- **What the board does enforce.** Phases cannot be set by a client; they are derived on each read. A review counts
  as a pass only for different, known model families, judged on the families stored with the event. A pass
  binds to the reviewed commit and is shown as out of date when HEAD moves; like task cards, this notices change
  and does not authenticate history or see uncommitted edits.
- **Malformed data fails closed.** Stored values that are non-finite, out of range, of the wrong type, out of order
  or unknown block the store instead of being shown or repaired; tests feed each entry point NaN, ±inf, huge
  integers, booleans, wrong containers and unknown fields.

## Data handling

- No telemetry, analytics, crash reporting or update checks. The only HTTP client in the code talks to
  the local console itself.
- State lives in `~/.vbear/`. The directory has mode `0700` and its files `0600`, written atomically.
- If `config.json` is corrupt, it is never overwritten. It is backed up, scanning is turned off, and a
  warning is shown.
