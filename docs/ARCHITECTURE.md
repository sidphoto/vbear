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
  `open`, `open_managed`, `list`, `close`, `attach`, `shutdown` (terminals); `open_stream`,
  `dispatch_prepare`, `stream_send`, `stream_status`, `stream_close`, `pipeline_hold`, `pipeline_release`
  (the managed stream executor); `review_start`, `review_status`, `review_cancel` (Codex review jobs);
  `flow_delete` (a flow's data). Each request is validated against a per-operation field list.
- **Three kinds of work, one daemon.** *Terminals* (`open`, `open_managed`) are PTY children. *Stream
  sessions* (`claude-stream`, `daemon_stream.py`, `stream_session.py`, `stream_journal.py`) are pipe-based, with
  no terminal and no typing: a dispatch is a sanitized line written to stdin and the answer is a stream of
  events, attributed, ordered and journalled. *Review jobs* (`daemon_review.py`, `review_*.py`) run Codex once,
  in a separate clone with a dedicated `CODEX_HOME` and a temporary `HOME`, and are judged afterwards from their
  events and rollout. Stream and review state lives in files only the daemon writes: `sessions/<launch>/`,
  `reviews/<job>/`, `pipelines/<task>/` and `holds/<flow>`; the console only reads them.
- **Quota ledger (`quota.py`).** The three directories together may not pass 4 GiB. A writer reserves its
  maximum first and returns what it did not use; the ledger lives in the daemon's memory and is rebuilt from a
  scan on start and after a deletion (any error counts as over the limit). Files a launch's preparation wrote
  count as used when the daemon opens the launch.
- **Sessions.** Each terminal session is a PTY child with a 1 MiB scrollback ring. At most 16 sessions run at
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
  before the prompt, the spinner after it, the idle mark after the turn, and the spinner cadence (at least one gap
  over 0 s between working frames, none over `SPINNER_STALE_S`). The judge is `vbear/title_check.py`; readers of a
  report (`cli_versions`, `claude_verify`) run it again on the report's events. Numbers from reports, records and
  evidence go through `vbear/numbers.finite_real` (finite reals only, never raises).
- **Working freshness.** A working title counts while `-CLOCK_SKEW_S <= now - last_seen <= SPINNER_STALE_S`, so
  "working" can still show for up to `SPINNER_STALE_S + CLOCK_SKEW_S` (about 7 s) after the spinner stops.
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

## Flows — `vbear/flows.py`

Phase 1 of multi-agent support is a board; its recording routes add no way to dispatch work, send input, run
`git` or start an agent. Phase 2 (below, "Managed executor and review") adds those through separate, gated
routes.

- **Record.** One flow per task card in `flows.json`: `roles` (planner, executor, 1–4 reviewers, each with a model
  family from a fixed list; the executor may name a runtime session id and a work directory) and an append-only
  `events` list. The server sets each event's `seq`, `at` (never earlier than the previous event, so a clock that
  steps back cannot break the log's ordering) and `source` (`manual`, the only value in this stage). A review
  event also stores the reviewer's and the executor's family as they were when it was recorded, so changing roles
  later cannot turn an old review into a pass. Commits must be full 40- or 64-character lowercase hashes.
- **Storage.** `vbear/jsonstore.py` holds the rules `tasks.json` established — 0600 atomic writes, one `flock` per
  read-modify-write, refusal of non-regular files, symlinks and extra hard links, and a blocked state (marker
  first, then quarantine) when the file does not parse or holds an entry `flows.py` could not have written. Every
  entry is re-validated on load and again before save: event order, times (finite, in range, not going back),
  field sets per kind, enums and lengths.
- **Derivation.** `derive()` runs on every read and stores nothing: the phase from the events; review rounds
  (one per executor report, holding the reviews of that commit; a review of another commit is listed apart and
  never counts); whether a PASS counts (both families known, not `other`, and different); and, for a counted pass,
  the executor directory's HEAD read now by `git_head`, giving `awaiting_merge` (same commit), `review_stale`
  (moved) or `review_unverified` (no directory, or HEAD unreadable). A merge or push recorded without a counted
  pass shows a warning. Once a merge is recorded the round's commit is closed: later reviews of it, or a report of
  it again, are listed but never move the phase back (a late objection is a warning); only a report of a different
  commit opens a new round. The executor's live state comes from `Store.live_cached()`, the last live view built:
  it never builds one, because a build calls the runtime and the native runtime starts its daemon when none is
  running. The flows pages load `/api/live` first (as the home page always has), which fills that cache; they wait
  at most 10 s for it and then show flows without live state. The cached view's age travels with every flow
  (`executor_live.freshness`): its `generated_at` must be finite, in range and not ahead of now by more than the
  2 s clock-skew allowance. A session state is shown as current only from a view at most 30 s old, judged on the
  exact age (`flows.LIVE_STALE_S`: the pages refresh the 3 s cache just before reading, so older means the refresh
  failed). Otherwise the executor reads:
  - 「即時狀態未載入」: no view built yet, or this page's own `/api/live` load failed or timed out;
  - 「即時狀態時間不明」: the view's `generated_at` is missing, invalid or ahead of now beyond the allowance;
  - 「即時狀態已過期」: older than 30 s, with the old state as history;
  - 「runtime 未連線」: the view says the runtime did not answer (`runtime.available` is `false`), rather than
    reporting the session as missing;
  - 「runtime 狀態不明」: the view does not say whether the runtime answered.
- **API** (behind the access token): `GET /api/flows`, `GET /api/flows/<id>`, `POST /api/flows`
  (`task_id`, `roles`), `POST /api/flows/<id>/events`, `POST /api/flows/<id>/roles`. Unknown fields are rejected
  per event kind; `roles_changed` is written only by the roles route. Bad input → 400, unknown flow → 404, a
  blocked store → 503.

### Managed executor and review (Phase 2, S2c)

The console is a thin, validating layer over the daemon's RPCs. The two things that carry content, the risk
acceptance and each dispatch, are previewed first (a one-use server-held record) and approved with only the
preview's id. Starting the executor and starting a review are empty-bodied POSTs: they have no preview record, and
rest on the valid acceptance and the daemon's own re-verification of everything it binds.

```
UI ── POST …/acceptance-preview ──▶ preview file (<state>/previews/, 300 s, single use)
UI ── POST …/acceptance {preview_id} ──▶ consume ──▶ risk_acknowledged event (server's values, never the browser's)
UI ── POST …/executor ──▶ FlowExecutor.start ──▶ prepare launch ──▶ daemon open_stream
UI ── POST …/dispatch-preview {launch_id, text} ──▶ preview ──▶ daemon dispatch_prepare … POST …/dispatch {preview_id} ──▶ stream_send
UI ── POST …/review ──▶ FlowReview.start ──▶ daemon review_start ──▶ Codex in a clone ──▶ validated result
UI ── GET  …/reports | reviews | merge-gate ──▶ read models from the files (nothing is run)
UI ── POST …/delete {flow_id} ──▶ FlowStorage.delete ──▶ daemon flow_delete ──▶ flows.delete_flow
```

- **Modules.** `previews.py` (the one-use preview files), `risk_text.py` (the three residual-risk texts, versioned),
  `risk_acceptance.py` (preview/confirm/status; the acceptance is compared with the live Claude/Codex versions
  and accounts, cached ≤ 10 s), `flow_executor.py` (start, close, dispatch preview/approve, hold/continue,
  status with accounting against the nine limits), `flow_review.py` (reports with the executor's statement and
  VBear's file checks apart, review start/cancel, reviews, opinion draft, merge gate), `flow_storage.py`
  (sizes, reasons, deletion), `daemon_client.py` (the RPC client), `api_error.py` (one error type: status, code,
  message, safe extras). Server routes only parse and dispatch to them; a flows POST body that is not exactly one
  JSON object is 400.
- **Order of sessions.** "Newest" is decided from the `created` time in each daemon-written manifest, never from
  a launch id (random); an order that cannot be told is reported and nothing is called the newest.
- **Reading a review in flight.** The daemon records a review's outcome in its manifest first and `result.json`
  after it. The console's readers give a review not yet "cleaned" a short grace (`stream_flow.settling`, 2 s)
  before calling its record missing; the daemon's own reads never wait, and the refusal after the grace is the
  same as before.
- **Deleting.** `runtime/flow_data.py`. `plan()` proves what is the flow's (session directory = the inode its
  manifest recorded; review job = manifest *and* the flow-side `job.json` of its round; task directory = start
  record naming the flow, or only empty scaffolding), `blockers()` lists why not (running, launching, manual
  review, not cleaned, an unproven process group, a stop marker, an unreleased failure, anything unprovable).
  `remove()` first renames the proven directories into `<state>/deleting/<flow>/` (counted by the quota scan,
  read by no flow's accounting) and then purges that tomb with
  every directory pinned (`O_NOFOLLOW|O_DIRECTORY`, owner, device, inode, re-checked before `rmdir`). While the
  tomb exists `pipeline_store.is_held` is true, so nothing new starts; asking again re-plans what is left and
  purges, with no dependence on a record already removed. The (empty) tomb is kept until the console has
  removed the flow's record and says so (`flow_delete_done`, refused while the record exists): that is what keeps
  a not-yet-locked approval out in between. A marker left behind (the console died after the record) is finished
  when the storage list is read, when a delete names the flow, when the console starts and when the daemon starts
  (`flow_data.sweep_orphans`, which also removes an `automation/<flow>/` holding only the approval lock of a flow
  that is gone); a marker that is not empty is left for a person. The table in the security model lists every
  interruption and its way out. It runs on the daemon's single thread, so a very large flow delays other requests
  while it goes; the ledger is rebuilt after.
- **The page.** `web/app.js` builds the panels with `el()`/`textContent` only (no `innerHTML`; review text is
  plain text), refreshes the data panels every 5 s one round at a time (a tick that finds a round running is
  dropped, each read has a 15 s limit and is aborted when the page is left, only the newest answer is applied),
  never refreshes under an open dialog and never rebuilds the dispatch box.
- **API** (behind the access token). GET: `/api/flows/<id>/executor`, `.../reports`, `.../reviews`,
  `.../reviews/<job>/draft`, `.../merge-gate`, `/api/flows/storage`. POST: `.../acceptance-preview`,
  `.../acceptance`, `.../executor`, `.../executor/close`, `.../dispatch-preview`, `.../dispatch`, `.../hold`,
  `.../continue`, `.../review`, `.../review/cancel`, `.../delete`. Errors carry `code` and, where safe, extra
  fields (for example the exact `codex login` command when a login is missing).

### Automatic mode (Phase 3, S3)

- **Mode.** `<state>/modes/<flow>` (0600, atomic) holds `{mode: auto, approval_id: "auto-<seq>"}`; no file is
  manual. RPC `pipeline_mode_set {pipeline, mode, approval}`. `dispatch_prepare` and `review_start` (which gained an
  optional `approval`) go through one gate in the daemon: manual refuses an automation approval; auto accepts only
  the approval the mode was switched on with, and re-verifies on every call that it is still the newest valid
  acceptance and that `plan.txt` is the hash it names. At daemon start every flow with a mode record is
  persistently held ("daemon 重啟") before any request is answered; a mode record that cannot be read is auto with
  no approval that can match.
- **Approval.** `automation.py`: preview (plan text from the task card, the acceptance facts, one record of kind
  `automation`), confirm (under `<state>/automation/<flow>/.lock`: stage `plan.txt`, append the acceptance event
  naming its hash, rename it into place, `pipeline_mode_set`, `automation_mode` event), `disable`, `read_plan`.
  Texts: `risk_text.render_auto` (version `AUTO_RISK_TEXT_VERSION`).
- **Events** (flows.json, strict fields): `automation_mode` (console); `auto_dispatch_intent`, `auto_dispatch_sent`,
  `auto_report`, `auto_review_intent`, `auto_review_started`, `auto_review_result`, `auto_review_aborted`,
  `auto_stopped` (automation).
- **Runner** (`runner.py`). `derive(events)` gives the step from the events since the mode was last switched on
  (`auto_stopped` is a barrier, not a step); `step()` performs at most one action per flow per tick under the
  flow's lock: it checks not-held, a trustworthy mode record, a valid acceptance, the approval event and its
  `automation_mode` event; then dispatch / await turn / start review / await review / forward / gate as described
  in the security model. The reads are the manual screens' own (`FlowReview.reports`, `reviews`, `plan_start`,
  `merge_gate`, `FlowExecutor.status`), so the runner and the person see the same facts. `stream_flow.check_limits`
  gives it the daemon's own numbers, worst case included.
- **Continue** (`FlowExecutor.release`) on an automatic flow checks the premises first (`_continue_problems`);
  the runner has no call to `pipeline_release`.
- **Deletion.** An automatic flow is a blocker; `modes/<flow>` and `automation/<flow>/` (which holds `plan.txt`,
  `.lock` and a temp name) go through the deletion area like the rest; the deleting side takes the approval lock
  without waiting.
- **Routes.** GET `/api/flows/<id>/automation`; POST `.../automation-preview`, `.../automation`,
  `.../automation/disable`. The flow view carries `automation` (mode, step, held, awaiting_merge) and an
  `attention_reason` the home list shows.
- **Tests.** `test_automation_daemon` (mode, gate, restart, schema), `_api` (approval, locks, screens' data),
  `_runner` (the cycle, the stops, derive), `_recovery` (every action boundary, aborted review, continue,
  restart), `_e2e` (second console, stop during a turn, restarts, ledger); `tests/qa_s3.py` for a person or a
  browser tool.

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
