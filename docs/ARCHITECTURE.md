# Architecture

VBear has two local processes and a browser UI. It has no build step, it uses no third-party Python
packages, and it does not connect to anything outside your machine.

```
browser (web/)  ──HTTP 127.0.0.1:7788──▶  console server (vbear serve)
                                             │  scans ~/.claude, ~/.codex, ~/.agents (read-only)
                                             │  state in ~/.vbear/
                                             └──unix socket runtime.sock──▶  VBear runtime (vbear runtimed)
                                                                               owns the PTY sessions
                                                                               └── claude / codex / any command
```

## Console server — `vbear/server.py`

- A `ThreadingHTTPServer` bound to `127.0.0.1`. It serves `web/` and a JSON API under `/api/`.
- **Access token.** Each start creates a random token. `/api/` requires it as a cookie (from `POST /api/auth`)
  or a `Bearer` header; it is handed over through `~/.vbear/server.token` and `~/.vbear/open.html` (both `0600`),
  which `vbear launch` and the app use.
- **Index.** The `vbear/scan/` adapters read skills, plugins and agent roles from the Claude Code,
  Codex and shared skill directories. `vbear/index.py` combines them into a static index
  (`~/.vbear/index.json`) and a live view of running sessions from the runtime.
- **Usage evidence.** `scan/usage.py` reads agent session logs and keeps only skill names, model names,
  session IDs, working directories and timestamps.
- **Local data.** Notes (`annotations.py`), task cards (`tasks.py`) and Agent Profiles
  (`agent_profiles.py`) are JSON files in the state directory, written atomically with mode `0600`.
  How task cards bind results to commits and hand work on is described [below](#task-cards--vbeartaskspy).
- **Built-in terminals.** `POST /api/native/terminals` opens the account's login shell in a folder
  under `HOME`; the daemon labels the session `kind: "shell"` so the UI can tell it from Agent sessions.
- **Terminal streaming.** `GET /api/term/<id>/stream` relays runtime output to the browser as
  server-sent events. Input goes through `POST /api/term/<id>/input` only after an explicit takeover.

## VBear runtime — `vbear/runtime/daemon.py`

- A single daemon for each state directory, guarded by `runtimed.lock`. The console starts it on demand
  (set `VBEAR_RUNTIME_AUTOSTART=0` to turn that off). It keeps running after the console exits, so open
  terminals survive a console restart.
- **Protocol.** Newline-delimited JSON on `~/.vbear/runtime.sock`. Only connections from the same
  uid are accepted; the daemon reads the peer's credentials with `LOCAL_PEERCRED`. Operations: `hello`,
  `open`, `open_managed`, `list`, `close`, `attach`, `shutdown`.
- **Sessions.** Each session is a PTY child with a 1 MiB scrollback ring. At most 16 sessions run at
  once, with at most 4 attachments per session. An attachment that falls behind is resynchronised with
  one full frame of at most 64 KiB (a terminal reset followed by the recent output), so the full history
  is never replayed.
- **Input control.** An attachment is either `observe` or `control`. Only one controller exists per
  session; a new takeover moves the old controller back to observe.
- **Close.** Close escalates from SIGHUP to SIGTERM to SIGKILL against the session's process group.
  Managed sessions also signal the other process groups their descendants created.
- **Activity evidence.** Output of a managed Claude session also goes through `osc_title.TitleTracker`, an
  incremental OSC parser that keeps only the class of the latest terminal title (working spinner, idle mark,
  empty, other) and when it was seen. `list` returns that as `activity_evidence`, with the launch's
  `cli_version`. The title text is never stored.

The client side is `vbear/runtime/native.py` (`NativeRuntime`), which implements the protocol
in `runtime/base.py`. Tests can substitute a fake runtime.

## Agent activity — `vbear/activity.py`

What an Agent is doing is decided in one place, `activity.arbitrate()`, called by the runtime client for every
Agent session it lists. The vocabulary is adapted from OpenRig's agent state taxonomy
([docs/evidence/openrig-learnings.md](evidence/openrig-learnings.md)):

- Three separate axes: session (`present` / `exited`), activity (`working` / `waiting` / `unknown`) and
  resumability (not served, always `unknown`). Needs-input is a count plus a reason, never an activity value; no
  source can observe it yet.
- Evidence comes in rungs, each authoritative, trial (recorded and shown, never consulted) or absent. The only rung
  is `claude-title`, authoritative for the Claude Code versions in `activity.VERIFIED`, each backed by a record in
  `docs/evidence/` ([2.1.291](evidence/claude-code-2.1.291-activity.md), [2.1.292](evidence/claude-code-2.1.292-activity.md)),
  and for versions whose title check passed on this Mac (`cli_versions.local_title_verified_versions`, from
  「驗證這個版本」); trial for any other version.
- **Title check.** `boundary_check`'s interactive run feeds the PTY output to `TitleTracker` and checks the idle mark
  before the prompt, the spinner after it, the idle mark after the turn, and the spinner cadence. The result goes to
  the report's `title`, and `claude_verify` records it beside the boundary result.
- The result carries `decided_by`, a reason and every piece of evidence. The UI's status badges, the home page's
  「需要你處理」 list (only `waiting` / `needs-input`) and task-card pickup all read this one answer; without
  usable evidence it is `unknown`.

## Task cards — `vbear/tasks.py`

- **Exact candidate.** A card may name a `workdir`. When tests are set to passed or the card is approved, the server
  reads the commit that directory is on (`git_head.read_head`) and stores it with the result; the client cannot
  supply it. Every read compares those commits with the current one: `verification_asserted` holds only while both
  results refer to it, otherwise the status is `verification_stale`. `git_head` reads `HEAD`, refs and
  `packed-refs` as plain bounded files, including linked worktrees; it never runs `git`.
- **Closure.** Moving the agent field to `completed` or `blocked` requires a reason saying what follows
  (`no_follow_on`, `handed_off_to`, `superseded`, `canceled`, `denied`; `blocked_on`, `escalation`), with a target for
  the reasons that name someone. Older cards without one load and are flagged `closure_missing`. A raw
  `status` can no longer stand in for the agent field; cards an older version stored that way derive to `draft`
  and carry `legacy_status`, which the UI shows until the agent field is set.
- **Handoff.** `POST /api/tasks/<id>/handoff` closes the card as `handed_off_to` and creates its successor in one
  locked write. The successor copies the contract and workdir, starts with fresh provenance, and carries
  `handed_off_from` and `chain_of_record`, which nothing else can set.
- **Pickup.** Every task response includes `pickup` (`closed`, `blocked`, `unclaimed`, `working`, `parked`,
  `stalled`, `unknown`), derived on the spot from the card and the live view. It is never stored.

## Profile-managed Claude launch

```
UI ── POST /api/native/agent-previews ──▶ preview (stored 300 s, single use)
UI ── POST /api/native/agent-launches ──▶ re-check preview, profile and config (409 on any drift)
          │
          ├─ agent_sessions.prepare_claude_launch
          │     ~/.vbear/sessions/<launch-id>/{settings.json, manifest.json}
          │     private scratch dir /private/tmp/sc-<random>/
          └─ runtime  open_managed {launch_id}   (single use; the manifest is read from the
                                                  daemon's own state directory, never from the caller)
                 ├─ version gate: a genuine Claude Code version; unverified ones need the user's acknowledgement
                 ├─ trusted argv: --safe-mode --settings <file> --tools Bash
                 │                --disallowedTools Edit,Write --strict-mcp-config [--model <id>]
                 ├─ env: CLAUDE_CODE_TMPDIR=<scratch>, DISABLE_AUTOUPDATER=1, minimal allow-list
                 └─ proctrack.DescendantTracker follows every descendant (libproc via ctypes)
```

- The preview and launch endpoints accept only `profile_id`, `workdir`, `commit`, `network` and `tool`.
  They never take an argv, environment variables, settings or credentials.
- **Cleanup.** When the session ends, the scratch directory and the per-launch files are removed only after
  every tracked process is proven dead. Otherwise the launch is kept in a `manual_review` state for you
  to inspect. Launches that were prepared but never opened expire after 600 s. At startup the daemon
  recovers the launches left behind by a previous run.
- **Codex.** A launch path exists (`codex_settings`), but the preview always reports that Codex is
  not launchable. With the pinned version, Codex's interactive mode still loads global MCP servers,
  plugins and hooks, and cannot ignore your user config.

## macOS app — `macos/`

`macos/build.sh` builds `VBear.app`. The app is a small Swift program (`macos/VBear/main.swift`) with a WebKit window,
plus a standalone CPython 3.13 (python-build-standalone, pinned by version and SHA-256) and a copy of `vbear/` and
`web/`. On launch it reuses a VBear that accepts the token in `server.token`, or starts
`python3 -B -m vbear serve --port <free port>` with a fresh token in `VBEAR_ACCESS_TOKEN`. The server removes that
variable from its environment at once, so the runtime daemon and terminals never inherit it. The window then loads
`http://127.0.0.1:<port>/#auth=<token>`. The bundle is ad-hoc signed and is never written to at run time
(`-B`, byte-compiled at build).

## Front end — `web/`

Plain HTML, CSS and JavaScript with no framework. The only dependency is the bundled xterm.js 5.5.0 with
its fit addon. A unit test pins the SHA-256 of both files, and CSP `script-src 'self'` keeps CDNs out.
All dynamic text goes through `textContent`, and `innerHTML` is not used.

## Tests

- `tests/test_*.py` use a synthetic `HOME` and start real runtime daemons in temporary directories. They
  never touch your real state directory.
- `tests/frontend/*.cjs` run the UI logic in Node against a minimal synthetic DOM. They are not browser tests.
- Some runtime tests measure timing, such as stream latency and an 8 s version probe, and can fail
  occasionally on a heavily loaded machine.
