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
  (`~/.vbear/index.json`) and a live view of running sessions from the runtime. `scan/agy.py` works out which skills
  Antigravity reads from files only (`read_by` on a record, plus sources of tool `agy`); see the SECURITY-MODEL.
- **Usage evidence.** `scan/usage.py` reads agent session logs and keeps only skill names, model names,
  session IDs, working directories and timestamps.
- **Local data.** Notes (`annotations.py`), task cards (`tasks.py`) and Agent Profiles
  (`agent_profiles.py`) are JSON files in the state directory, written atomically with mode `0600`.
  How task cards bind results to commits and hand work on is described [below](#task-cards--vbeartaskspy).
- **Built-in terminals.** `POST /api/native/terminals` opens the account's login shell in a folder
  under `HOME`; the daemon labels the session `kind: "shell"` so the UI can tell it from Agent sessions.
- **Terminal streaming.** `GET /api/term/<id>/stream` relays runtime output to the browser as
  server-sent events. Input goes through `POST /api/term/<id>/input` only after an explicit takeover.

- **Chats.** `vbear/chat_service.py` is the console's side of a chat: it checks the card (enabled, Claude Code or Codex; the card's tool fixes the chat's engine, `claude-chat` or `codex-chat`, when it is opened, and a card whose tool changed afterwards gets `card_tool_changed`), asks the
  runtime to open, send, answer, stop and delete, retries a send once the process is replaced, and turns every
  refusal into a sentence (`explain`). `GET /api/chats/<id>/stream` relays the daemon's live view as server-sent events
  (`X-VBear` required, at most four open); the page falls back to polling. `claude_verify.py`'s `ChatVerifier` runs
  `vbear/chat_check.py` (through `python3 -m vbear.boundary_check --mode chat`) and trusts a version only when the
  0600 report it names reads back as a pass. The records and the day's spend are `runtime/chat_store.py`'s, written only by the daemon. A Codex chat's version check is `vbear/codex_chat_check.py` (`boundary_check --mode codex-chat`), which records `codex-chat-verified.json` the same way; `vbear/codex_verify.py`'s `CodexChatVerifier` is the console's button for it (`POST /api/chat-support/verify {"engine": "codex"}`), built on `ChatVerifier`. `GET /api/chat-support` carries Claude Code's keys and a `codex` object (`runtime/codex_chat_env.py`'s `status`). The Codex process, protocol and cards are `runtime/codex_chat_session.py`, `runtime/codex_chat_protocol.py` and the Codex branches of `daemon_chat.py`. Which AI tools chat, and everything that differs by engine (chat.json fields, the launch manifest checked, the daemon's send method, the support block, the verifier, the check mode), is one row each of `runtime/chat_engines.py`'s `TABLE` (P39-1); a new engine is a new row plus the methods it names.

## VBear runtime — `vbear/runtime/daemon.py`

- A single daemon for each state directory, guarded by `runtimed.lock`. The console starts it on demand
  (set `VBEAR_RUNTIME_AUTOSTART=0` to turn that off). It keeps running after the console exits, so open
  terminals survive a console restart.
- **Protocol.** Newline-delimited JSON on `~/.vbear/runtime.sock`. Only connections from the same
  uid are accepted; the daemon reads the peer's credentials with `LOCAL_PEERCRED`. Operations: `hello`,
  `open`, `open_managed`, `list`, `close`, `attach`, `shutdown` (terminals); `open_stream`,
  `dispatch_prepare`, `stream_send`, `stream_status`, `stream_close`, `pipeline_hold`, `pipeline_release`
  (the managed stream executor); `review_start`, `review_status`, `review_cancel` (Codex review jobs);
  `flow_delete` (a flow's data); `chat_open`, `chat_send`, `chat_answer`, `chat_stop`, `chat_close`,
  `chat_events`, `chat_delete` (chats with a role card, P36). Each request is validated against a per-operation
  field list.
- **Three kinds of work, one daemon.** *Terminals* (`open`, `open_managed`) are PTY children. *Stream
  sessions* (`claude-stream`, `daemon_stream.py`, `stream_session.py`, `stream_journal.py`) are pipe-based, with
  no terminal and no typing: a dispatch is a sanitized line written to stdin and the answer is a stream of
  events, attributed, ordered and journalled (an event of an unknown kind, or with fields the version's
  constants do not list, is journalled as a `turn_anomaly` that names the unexpected top-level fields, at most 16
  names of `[A-Za-z0-9_]`, never a value, so a new Claude Code version can be diagnosed from the journal alone;
  a tool call the permission system refused, `system/permission_denied` in 2.1.296, is journalled as a
  `permission_denied` fact with the tool's name and the decision's type, filtered the same way (at most 16 facts
  per turn; the journal refuses a 17th), and does not make the turn invalid).
  *Chats* (`claude-chat`, `daemon_chat.py`, `chat_session.py`, `chat_protocol.py`, `chat_store.py`; P36) are
  pipe-based too. Claude Code asks on stdin about each tool call it does not allow by itself, and the daemon
  answers it itself or holds it as a permission card for the person. A chat's record is `chats/<chat_id>/`
  (`chat.json` and an append-only `events.jsonl`), and each role card works in its own `chat-work/<hash>/`
  folder. There is one process per role card and at most three in all. A process closes after 10 idle minutes,
  and the next message resumes the session. The argv carries `--setting-sources ""`, so none of the person's own
  Claude settings are read (the real CLI reports their extra folders otherwise), and `os.waitid` (Python 3.13+ on
  macOS) is required: without it `chat_send` answers `unsupported_python` and starts nothing. The process termination steps are shared with stream sessions
  (`stream_session.ProcessGroupEnd`).
  *Review jobs* (`daemon_review.py`, `review_*.py`) run Codex once,
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
  quest board 「輪到你」 (only `waiting` / `needs-input` agents) and task-card pickup all read this one answer; without
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
UI ── POST …/dispatch-preview {launch_id, text} ──▶ preview (id decided; text + fixed report request naming it) ──▶ daemon dispatch_prepare … POST …/dispatch {preview_id} ──▶ stream_send
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
- **A review's tokens.** `result.json` of a review record holds `usage` and `usage_problem`. `usage` is
  `{"counts": {<name>: int}, "complete": bool}`: the last turn total of the rollout's cumulative usage chain
  (`token_usage_record`: `input_tokens`, `cached_input_tokens`, `cache_write_input_tokens`, `output_tokens`,
  `reasoning_output_tokens`, `total_tokens`), taken only when every record was well formed, the chain added up and
  the file was read to its end. `complete` is true when that total is also what `turn.completed` reported; false
  for a turn with no `turn.completed` (a stop, a failure), where it is what was recorded so far, at least that much. When
  it cannot be had, `usage` is `null` and `usage_problem` is one of `no_rollout`, `walk_stopped`,
  `chain_mismatch`, `inconsistent` (the chain and `turn.completed` both exist and disagree: neither is a bound,
  so there is no number), `no_token_records`, `rebuilt` (a record rebuilt after a crash is not re-read). A record
  written before this field existed has neither key; readers (`review_validate.usage_view`, the summary tool)
  treat that as "unavailable", never as 0. The screen shows the counts and the note that VBear has no reliable
  price source, so nothing is converted to money. The usage does not decide a review's validity.
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
  acceptance and that `plan.txt` is the hash it names, at both `dispatch_prepare` and `stream_send` (a send is
  judged again with the approval its dispatch was prepared with); for a stream it also re-reads the executor's
  Claude fingerprint and compares the session manifest's CLI version and model with the acceptance
  (`_auto_live_problem`), and a difference stops the flow (`_auto_refuse`). `pipeline_mode_set` also refuses
  while a live session of the flow has a prepared and unsent dispatch (`_unsent_dispatch`, from the journal's
  `pending`; in either direction), on the same thread as `dispatch_prepare`; `stream_status` reports it as
  `unsent`, and `POST …/dispatch-send` (`FlowExecutor.dispatch_send`) sends exactly that dispatch in manual mode.
  At daemon start every flow with a mode record is
  persistently held ("daemon 重啟") before any request is answered; a mode record that cannot be read is auto with
  no approval that can match.
- **Approval.** `automation.py`: preview (plan text from the task card, the acceptance facts, one record of kind
  `automation`), confirm (under `<state>/automation/<flow>/.lock`: stage `plan.txt`, append the acceptance event
  naming its hash, rename it into place, `pipeline_mode_set`, `automation_mode` event), `disable`, `read_plan`.
  Texts: `risk_text.render_auto` (version `AUTO_RISK_TEXT_VERSION`).
- **Events** (flows.json, strict fields): `automation_mode` (console); `auto_dispatch_intent`, `auto_dispatch_sent`,
  `auto_report`, `auto_review_intent`, `auto_review_started`, `auto_review_result`, `auto_review_aborted`,
  `auto_stopped` (automation).
- **Dispatch text** (`runner._text`). The dispatch id is chosen first; the text is the approved plan (or the
  review opinion and the request to fix it) followed by `executor_report.report_request(dispatch_id)`, the same
  fixed report request a manual preview appends. The intent event records the id and the text's hash, and a
  recovery rebuilds the text from the id in the intent, so the same inputs give the same text.
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

## Chief of staff and dispatch — `vbear/chief*.py`, `vbear/dispatch*.py`, `vbear/autonomy.py`, `web/app.js` (`#/dispatch`, `#/actions`)

The CEO's chat page (`#/chat/<id>` of a card in the CEO position) has 請幕僚長安排. `GET /api/chief/preview?chat_id=` answers the counts,
the cap and what is left of the day (`vbear/chief.py`, pure functions: which messages are read, the list of employees as codes
C1.. and the schema). `POST /api/chief` starts `ChiefRunner` (`chief_runner.py`), a board of one turn on `board_engine.HeadlessBoard`
(the meetings' tool-less headless call, `sonnet`, US$0.30 at most, shared worker lock and shared day). Its records are
`<state>/chief/cos-<12 hex>.json`. `chief.validate_plan` voids a badly formed answer, removes what is off the list with a note, and
voids a plan with nothing left (`empty_plan`). A proposal that is ready calls the hook `Console._on_proposal`, which makes the
dispatch record (`Dispatcher.from_proposal`) and links it (`ChiefRunner.link_dispatch`); the proposal can no longer be retried.

A dispatch is `<state>/dispatch/d-<12 hex>.json` (`dispatch.py`; states proposed, confirming, running, paused, done, stopped, dismissed;
append-only events, each with `by`: `you`, `auto1`, `auto2` or `vbear`; the step events name the step in the field `step`). `Dispatcher`
confirms (the plan is checked again, only more strictly; new employees are made in safe mode with no skill; the task card), dismisses,
stops, continues, withdraws a card the dispatch made, deletes, and lists the actions (`GET /api/actions`). `DispatchRunner`
(`dispatch_runner.py`; a thread started by `serve()`, one pass every 2 seconds, a lock file `dispatch-runner.lock`) sends each step in a
new chat with `ChatService.send_for_dispatch`, the message marked with `origin = {dispatch, step}` in the chat record
(`chat_store`, `daemon_chat`), waits for the turn to end and hands its last reply on, framed as data. It pauses with a reason
(`daily_limit`, `plan_limit`, `busy`, `uncertain`, `turn_*` and so on) that `dispatch.PAUSE_TEXT` turns into plain words with the step, the AI tool and
the time; the person's 繼續 and 停止 go through `Dispatcher.stop` and `Dispatcher.resume`, which the runner carries out. The runner does
not answer permission cards. `GET/POST /api/settings/autonomy` is the only way to change the 自己動手 ticks (four booleans since v0.18: `create_cards`, `dispatch`, `routines`, `auto_continue`). A pause with a known time of recovery also counts down and, with item 5, is continued by `vbear/auto_continue.py` (below, "Skills and routines").

The page (`web/app.js`, the block between `// ---------- the chief of staff and the dispatch` and its end marker) draws the dialog, the
proposal card (a draft held in the page: edits, the 「你改過」 marks, the cost line, the red lamp from `/api/meetings/ledger`), the
dispatch list and page, `#/actions`, the lobby's 輪到你 entries and the note on a chat message that was sent by a dispatch. It
builds nodes with `el()` and `textContent` only. `tests/test_autonomy_guard.py` keeps the chief and dispatch modules from importing or
calling anything that changes a limit, starts a terminal or full mode, or installs a skill; `tools/qa_p40.py` is the coordinator's
real-machine check through the HTTP API.

## Group chats — `vbear/groups.py`, `vbear/group_runner.py`, `web/app.js` (`#/chat/group/<id>`)

A group is two or three employees the person talks to together (the 聊天 page, 開新群組). It is built on chats and adds nothing to
the runtime: `vbear/runtime/` is the same as in v0.15.0. `Groups.create` makes one chat per member with `ChatService.create` (nothing
is started or spent) and a folder `<state>/groups/g-<12 hex>/` with `group.json` (name, members in the order of the answers, and
each member's chat; `GuardedJsonStore`, 0600, 64 KiB) and `log.jsonl` (append-only, each line synced, 8 MiB; kinds `said`,
`turn_intent`, `turn_sent`, `turn_ended`, `skipped`, `paused`, `continued`, `round_ended`, `member_added`, `member_removed`,
`renamed`). An employee's reply is not stored there: the group page reads it from the member's chat by the `chat_id` and `turn` that
`turn_sent` names (`Groups.scan`, cached per chat). A round (what one sentence of the person causes) is derived from the log on every
pass (`current_round`, `round_state`, `next_member`), so a restart goes on by reading.

The one thing that starts a round is `POST /api/groups/<id>/messages {text, to}` (`Groups.say`, which writes `said` under the log's
`flock`); `to` is `"all"` or a list of members, kept in the group's order. `GroupRunner` (`group_runner.py`, a thread started by
`serve()`, one pass every 2 seconds, lock file `group-runner.lock`; shaped like `DispatchRunner` and sharing no code with it) asks the
members one at a time: it writes `turn_intent`, sends `Groups.message_for` with `ChatService.send_for_group` (the same `_send` as a
person's, no `origin`, only to a chat a group opened), writes `turn_sent`, waits for the chat's `turn_ended` and writes `turn_ended`
with the cost the chat recorded. `build_message` is the fixed group words the first time, then what was said since this employee last
spoke as one JSON string between `BEGIN_UNTRUSTED_JSON_STRING` and `END_UNTRUSTED_JSON_STRING` (6 KiB for an item, 12 KiB in all, 30 KiB for
the message), then the person's words outside the markers. It pauses (`daily_limit` with the next local midnight, `spend_unknown`,
`uncertain` after a restart, `violation`, or a chat's code) or leaves one employee out (`skipped`: `plan_limit`, `busy` after three
minutes of trying every ten seconds, the chat's code for a card or tool it will not run); `groups.PAUSE_TEXT` and `groups.SKIP_TEXT`
turn those into words. 繼續, 不用了 and 停止 are `Groups.resume`, `drop` and `stop` (`POST /api/groups/<id>/continue|drop|stop`, body
`{}`); the runner carries out what 停止 leaves. Members change with `POST …/members {add, remove}` (between rounds; two or three
remain; someone who comes back keeps her chat unless the card's tool changed), the name with `POST …/rename`, and
`DELETE /api/groups/<id>` deletes the chats (`ChatService.delete_for_group`) and then the folder. The browser's chat routes refuse a
group's chat (`group_member_chat`) and `GET /api/chats` leaves it out; `ChatService.get` carries `group` (`{id, name}` or `null`) so
a chat page opened by an old link can say which group it belongs to. A card that waits for the person is answered by the chat's own
`POST /api/chats/<chat_id>/answer`; no route of a group answers.

The page (`web/app.js`, `viewGroup` and the group helpers) draws the list rows among the chats, the dialog for a new group, the
group page (the members in the order of the answers, the conversation, the @ buttons, the cost line, the words being written and an
allow card under the employee who asks, which is `chatCardNode` itself, 停止, 繼續, 不用了, members, rename, delete) and the lobby's
輪到你 entries; it polls `GET /api/groups/<id>?after=<seq>` and, only while someone is answering, the live part of that member's chat
(`GET /api/chats/<chat_id>?after=999999999`). It builds nodes with `el()` and `textContent` only. `tests/test_autonomy_guard.py` scans
`vbear/group*.py` with the chief of staff's modules and, for groups, also fails on any call of `answer`; `tests/test_group_flow.py`
walks a group over the real HTTP routes with a fake daemon; `tools/qa_p41.py` is the coordinator's real-machine check through the HTTP
API (it needs `--state`, refuses `~/.vbear` and ports 7788 and 7789).

## Memory — `vbear/memory.py`, `vbear/runtime/memory_rules.py`, `vbear/memory_suggest*.py`, `web/app.js` (`#/memory`)

Memory is a few lines of the person's own (kind `about_you`, `work` or `decision`; at most 50 lines, 200 characters each, 4,000 in all)
that every employee whose card takes memory along is told when a new chat process starts. ADR 0008 gives the reasons. The files are
`<state>/memory/memory.json` (`GuardedJsonStore`, 0600, 64 KiB: `{v, entries, cards_off, cards_on}`; an entry has `id` `m-<10 hex>`,
`kind`, `text`, `created_at`, `updated_at`, `source` and `confirmed_warning`), `log.jsonl` (append-only; the action and the line's id,
kind and how it came, never a word; 1 MiB, then a new file and one old one kept) and `suggest/ms-<12 hex>.json` (the memory
suggestions, below). `vbear/memory.py` is the console's side: `view`, `for_card` (what a chat sends: `ChatMemory(readable, on,
entries)`; `DEFAULT_ON` says a Claude Code card is on and a Codex card is off until `cards_on` says otherwise) and the writers `add`,
`edit`, `delete`, `clear`, `set_card` and `export`, which only `vbear/server.py`'s `/api/memory*` routes call (`MEMORY_RE`; the
guard test `tests/test_autonomy_guard.py` fails the build otherwise, and scans `memory*.py` and `runtime/memory*.py` with the rules of
the chief of staff, dispatch and groups). The routes are `GET|POST /api/memory`, `PATCH|DELETE /api/memory/<id>`, `POST …/clear`
(`{confirm: "全部刪除"}`), `POST …/cards` (`{profile_id, on, confirm_company?}`) and `GET …/export` (`{filename, text}`); a save is
`add` with `{kind, text, confirm_warning?, source?}`, where `source` is `{how: "chat"|"group"|"suggested", …}` and the place it names must exist.

`vbear/runtime/memory_rules.py` is pure and shared, because the daemon does not import the console's modules: `check(text)` gives
`{refuse, warn}` (`bad_text`, `secret_password`, `secret_key`, `secret_account`, `secret_payment`; `looks_like_order`, `personal`),
`block(entries)` builds the one paragraph (VBear's fixed words, then the lines as a JSON string between `BEGIN_VBEAR_MEMORY_JSON` and
`END_VBEAR_MEMORY_JSON`), `prepare(memory)` is the daemon's closed-shape check of the `memory` field (every line checked again; one refused
line refuses the whole message), `combine` puts the paragraph after the card's instructions and `prompt_sha` fingerprints what a
session was started with. `ChatService._send` sends the `memory` field of `chat_send` when the card takes memory along and the file reads (for
a chat, a dispatch step or a group answer alike); the daemon appends the paragraph to Claude's `--append-system-prompt` (a chat's
added prompt may be 8,000 characters; a full-mode launch keeps 2,000) and to Codex's `developerInstructions`. A live process is **not** replaced when the memory or the card's instructions change, because
Claude Code 2.1.319 keeps the system prompt a session was started with and ignores a new one on `--resume` (found on a real machine,
P42-6); when a chat's new session starts the daemon keeps the `prompt_sha` and whether the memory was in it in
`<state>/chat-prompt/<chat id>.json` (`chat_store.set_prompt_start` / `prompt_start`, deleted with the chat). The chat record has no new
field; the daemon's log has `chat process memory entries=<N|none> instructions=<yes|no>`. `GET /api/chats/<id>` carries
`memory: {on, count, readable, changed, started_with_memory}` (`ChatService._prompt_changed` compares the fingerprint with the current
memory and the card's instructions); the chat page says a changed chat keeps what it started with and offers 開新聊天.

A memory suggestion (`memory_suggest.py` and `memory_suggest_runner.py`, `MemorySuggestRunner(HeadlessBoard)`, shaped like the chief
of staff's) is one tool-less Claude Code call on the meetings' engine over the newest messages of a one-to-one chat (`chief.select_messages`):
`POST /api/memory/suggest/preview {chat_id}` costs nothing and answers a `preview_id`, `POST /api/memory/suggest {preview_id}` starts it,
`GET /api/memory/suggest[/<id>]` reads, `POST …/<id>/saved {indexes}` and `…/dismiss` record what the person did, `…/cancel` and `DELETE`
end it. It never saves a line and never imports `vbear.memory`; its cost is counted in the day (`spend_kind`, the ledger's `includes`).

The page (`web/app.js`, from `// ---------- memory`) draws `viewMemory` (the two lines at the top, the usage, the three groups of lines with
`memoryRow`, `memoryAddForm`, the export through a `Blob`, 全部刪除 with a typed word, 誰帶記憶 with a switch per card and the
question before a Codex card goes on, and the sentence about terminals), `openMemoryRemember` (the box behind each 「記住」 on the chat and
group pages), `memoryChatLine` (the one line at the top of a chat page), `memoryCardLine` (the back of a role card) and
`memorySuggestDesk` (the button, the preview box and the suggestion card with every line unticked). It builds nodes with `el()` and
`textContent` only. `tests/test_memory_flow.py` walks one memory over the real routes, a real daemon and the fake Claude Code;
`tools/qa_p42.py` is the coordinator's real-machine check through the HTTP API (it needs `--state` and `--cards`, refuses `~/.vbear` and
ports 7788 and 7789, and prints no word of memory, of a conversation or of a model's reply).

## Shared folder — `vbear/shared_folder.py`, `vbear/shared_changes.py`, `vbear/runtime/shared_rules.py`, `web/app.js` (`#/shared`)

The shared folder is one folder, `<state>/shared` (0700; usually `~/.vbear/shared`), that every employee the person has switched on may read and
write, so one employee can hand a file to another or to the person. ADR 0009 gives the reasons. Two folders matter: `shared/` is the one employees can
write; `<state>/shared-meta/` is VBear's own and employees cannot (`settings.json`: `{v, cards_on: [profile id…]}`, `GuardedJsonStore`, 0600, at most 200
ids, every employee off by default and a file that cannot be read means all off; `log.jsonl`: `card_on`, `card_off` or `revealed` with the card's id and
`page`, `group` or `dispatch`, never a file name, 1 MiB then one old file; `changes/<g-…|d-…>.jsonl`, the names a group answer or a dispatch step left, below;
`pending/<d-…>.json`, `{v, on, confirm_company}`, whether the person ticked on this dispatch's confirmation).

`vbear/runtime/shared_rules.py` is pure and shared by the console and the daemon (the daemon does not import the console's modules): `shared_path(state)` (the
only place a path is computed; nothing from a browser or an RPC caller is ever a path), `folder_problem` (`shared_unsafe`: a link on the way, not mode 0700, not
the user's, the home folder or above it, inside one of VBear's own folders), `ensure_folder` (makes, never mends), `walk`/`usage` (`os.scandir` and `lstat`, links
not followed; 1 GiB or 10,000 entries is `over`), `snapshot`/`changes` (the comparison behind the hand-over; 50 names of 200 characters at most; `None` when there
are too many), `write_problem` (`.claude`, `.codex`, `.agents`, `.git` at any depth, the folder itself, a path out of the folder, a file with more than one hard link)
and `block` (the one paragraph the employee is told: fixed words, the path as a JSON string between `BEGIN_VBEAR_SHARED_JSON` and `END_VBEAR_SHARED_JSON`, 1,000
characters at most). `memory_rules.combine` and `prompt_sha` take it as a third part; without it they give v0.17.0's values byte for byte.

`vbear/shared_folder.py` is the console's side: `for_card` (read only; what `ChatService` asks), `view`/`listing` (the page: at most 200 files, newest first, names, sizes,
times and "link", never a content), and the writers `set_card`, `open_cards`, `close_cards`, `mark_dispatch` and `open_for_dispatch`, `reveal`, which only `vbear/server.py`
calls (`tests/test_autonomy_guard.py` fails the build otherwise and scans `shared*.py` and `runtime/shared*.py` with the rules of the chief of staff, dispatch, groups and
memory; `tests/test_shared_static.py` shows the modules never open, read, delete or run anything). The routes (token, `X-VBear` on a POST, closed bodies): `GET /api/shared`,
`POST /api/shared/cards {profile_id, on, confirm_company?}` (a Codex card needs `confirm_company: true`: 409 `shared_confirm`), `POST /api/shared/reveal {}` (Finder; the
command is a function `serve()` hands the console, `/usr/bin/open <path>` with no shell, 503 without it and 400 `not_mac`), the tick `shared_folder`/`confirm_company` of
`POST /api/groups` and `POST /api/dispatch/<id>/confirm` (checked **before** anything is made; for a dispatch the callback `Console._on_new_employee` opens an employee
the dispatch makes only when `pending/<d-…>.json` says `on`), and `GET /api/chats/<id>`'s `shared: {on, usable, code}`.

A chat with the folder on: `ChatService._send` sends `shared: true` (never a path; `false` or any other type is 400 in the daemon); the daemon computes the path, runs
`folder_problem` and `usage` (409 `shared_unsafe`, `shared_full`), checks that the version of the AI tool passed the chat check with the folder (`cli_versions.shared_verified`:
the report says `shared: passed`; else 409 `shared_unverified`, asked by the console first), and **replaces an idle process whose folder differs** (`close_gracefully` and
`restarting`, the same road as a change of model; a busy one answers `busy`). Claude Code: `chat_settings(shared=…)` adds the folder to `sandbox.filesystem.allowWrite`, the
manifest carries `shared` and is validated again, and `chat_protocol.judge(…, shared=…)` makes the folder a second root. Codex: `argv_for(…, shared=…)` adds
`-c sandbox_workspace_write.writable_roots=[…]`, `turn_start_line` sends `writableRoots`, `CodexTracker` expects the `thread/start`, `thread/resume` and settings answers to list exactly that
root, and `judge_file_change` applies `write_problem`. The paragraph is joined to the instructions and memory (the chat manifest may carry 9,000 characters; a full-mode launch keeps 2,000);
the daemon's log has one line per new process, `chat process shared=<on|off>`. Nothing is added to the chat's record (`KINDS`) or to the `chat-prompt` file's format.

The hand-over (`vbear/shared_changes.py`): `GroupRunner` and `DispatchRunner` take a `snapshot` before an employee answers and after, and `record` the new or changed names in `changes/`;
the next employee's message gets `paragraph(...)`: the names as one JSON string between `BEGIN_UNTRUSTED_JSON_STRING` and `END_UNTRUSTED_JSON_STRING` (at most 4,096 bytes), or, for an
employee who has the folder off, a sentence that there are new files he cannot read, or a sentence that none could be compared. `Groups.get` adds `shared_changes` to a reply
item only when there is something; `chief.py` adds `shared` to each employee of the list only when somebody has the folder on (with everyone off, the list, the fixed words and the hash of the
inputs are v0.17.0's). The two chat checks (`chat_check.py`, `codex_chat_check.py`) each have a shared part, and the report gains `shared` and `shared_steps`.

The page (`web/app.js`, from `// ---------- the shared folder`) draws `viewShared` (three fixed sentences, place and the Finder button, usage, the switches with the question before a Codex card goes on, the
files), `sharedCardLine` (the back of a role card), `sharedChatLine` (the line at the top of a chat), the tick in `openGroupDialog`, the tick in `proposalCard` and `groupSharedChanges` (the names under a
reply). The chat page has one 「檢查」 button for a version not checked with the folder (the note `sharedCheckNode`, `data-chat="shared-check"`, which posts `{engine, shared: true}` to
`/api/chat-support/verify`); nothing else on the pages posts that. Everything is `el()` and `textContent`: a file name that looks like markup is shown as it is.
`tests/test_shared_flow.py` walks the page, a group with the tick, a dispatch with the tick, the hand-over, switching off and the Finder button (a fake) over HTTP; `tools/qa_p43.py` is
the coordinator's real-machine check through the HTTP API on a temporary state (it refuses `~/.vbear` and the ports 7788 and 7789, never presses the Finder button, prints no word of a model's
and runs `codex sandbox` with VBear's own settings, which needs no login and calls no model).

## Skills and routines — `vbear/skillbook*.py`, `vbear/routine*.py`, `vbear/auto_continue.py`, `vbear/countdown.py`, `vbear/keep_awake.py`, `web/app.js` (`#/my-skills`, `#/routines`)

Three pieces and a countdown, built on chats and the dispatcher and adding nothing to the runtime except one pure function, `memory_rules.check_text`. ADR 0010 gives the reasons.

**Skills.** `vbear/skillbook.py` is the store (`<state>/skillbook/skills.json`, `GuardedJsonStore`, 0600: `{v: 1, skills}`, at most 100, each `{id: k-<12 hex>, name (1 to 40), text (1 to 4,000), source, created_at, updated_at}`;
`log.jsonl` has the action and the id only; a file that cannot be read is moved aside and every call after answers `skills_unreadable`, 503). `view` reads; the writers `add`, `edit`, `delete` and `store` are called only by the `/api/my-skills*` routes of `vbear/server.py`
(`SKILL_RE`; `tests/test_autonomy_guard.py` fails the build otherwise). `source` is `{how: typed}` or `{how: said|reply, chat_id|group_id}` (the place must exist) or `{how: suggested, suggestion_id: ks-<12 hex>}` (the record must be a plain file of ours); `reply` needs `confirm_warning`. The text is judged by
`memory_rules.check_text(text, max_chars, multiline=True)`, the shared rules of `check` over several lines (`skill_refused` 400; `looks_like_order`, `personal` and `employee_words` are 409 `confirm_warning`). A skill is never in the system prompt: nothing in `vbear/runtime/` knows it.
`vbear/skillbook_suggest.py` and `skillbook_suggest_runner.py` (`SkillSuggestRunner(HeadlessBoard)`, shaped like `memory_suggest*`) make 「整理成技能」: `POST /api/my-skills/suggest/preview {chat_id}` (nothing spent), `POST /api/my-skills/suggest {preview_id}`, `GET /api/my-skills/suggest[/<ks-id>]`, `POST …/<ks-id>/saved|dismiss|cancel`, `DELETE`; one tool-less call,
at most one `{name, text, note}` with `additionalProperties: false`, the conversation as one escaped JSON string between `BEGIN_UNTRUSTED_JSON_STRING` and `END_UNTRUSTED_JSON_STRING`, at most US$0.10, spending kind `skill_suggest` (in the four board runners' `spend_kinds` and the ledger's `includes`; **not** in the chat process's `_chat_day_spent`, a known gap written in the security model).
It never imports `skillbook` and never saves.

**Routines.** `vbear/routine_rules.py` is pure: `validate_fields` and `check_content` (the fields; the text through `check_text`), the local-time slots (`slots_between(routine, start, end, tz)`, `next_due`, `slot_due`; a slot key is `YYYY-MM-DDTHH:MM`, a skipped hour is done at the next minute that exists, a repeated hour once), the limits (`effective_daily_usd`,
`ROUTINE_DAILY_FRACTION` one half, never above the daily limit), the fixed line and `message_text`, `chat_title`. `vbear/routines.py` is the store in `<state>/routines/`: `routines.json` and `settings.json` (`daily_usd`, `keep_awake`; `GuardedJsonStore`, 0600), `runs.jsonl` (append-only, the last line of a `run_id` wins, a half-written last line is cut
at the next append; `new_run` refuses a second run of one (routine, slot); `update_run(run_id, expect, …)` changes a state only from the states given), `heartbeat.json` and `log.jsonl` (ids only); the writers (`create`, `edit`, `set_enabled`, `delete`, `set_settings`, `store`) are called only from `server.py`. `vbear/routine_runner.py`'s `RoutineRunner` is a thread `serve()` starts (one pass every 15 seconds,
the lock `<state>/routine-runner.lock`): `_look` turns the slots that are due into `waiting` runs (item 3 off) or `auto3` runs (item 3 on, read only as `autonomy.read(conf)["routines"]`), `_wake` is the wake-up list (the latest missed time per routine, `asleep_<n>`, 12 hours and three routines for item 3), `_drive` runs one at a time through the limits (`limits`, `_gate`: the lamp, the ledger, the routines' own limit) and
`ChatService.send_for_routine` (only a chat a routine opened; no `origin`; a run that may or may not have been sent is settled by reading the chat, else `uncertain`, never a second send), `catch_up`, `dismiss_missed` and `start_now` carry out the person's presses, `waiting_rows` and `actions` feed the page. `Console.routine_runner()` builds it with `AutoContinue` and `KeepAwake`; `GET /api/routines`, `POST /api/routines[/<id>[/delete|/start]]`,
`POST /api/routines/waiting/<rr-id>` (`start`|`skip`), `POST /api/routines/missed/<r-id>` (`run`|`dismiss`), `POST /api/routines/settings` and `GET /api/waiting` are the routes; `/api/actions` merges the `auto3` runs and the item 5 presses; `/api/chats` carries `routine_title` from `runs.jsonl` (the chat record has no new field).

**Waking up and the Mac.** `heartbeat.json` (`{v, at}`) is written about once a minute; two looks more than 90 seconds apart, or an old file at the console's start, make the wake-up list. `vbear/keep_awake.py`: `argv()` is the constant `["/usr/bin/caffeinate", "-i", "-w", "<pid>"]`; `launch(argv)` runs it with no shell and refuses any other argv; `KeepAwake.update(working, now, on=)` starts it once when there is work and the switch is on and ends it 30 seconds after
the last work or at once when the switch goes off; `serve()` alone sets `Console.keep_awake_command = keep_awake.launch`, so a console built any other way (all tests) has `None` and starts nothing.

**Counting down and continuing.** `vbear/countdown.py`'s `words(reason, until, now, tz)` makes the sentence for `daily_limit` and `plan_limit` pauses (`pause.countdown` in the dispatch view and `round.pause.countdown` in `groups.py`'s `_round_view`; the old pause words are unchanged). `vbear/auto_continue.py`'s `AutoContinue` is called once per pass of the routine runner: it lists `dispatch_resume` and `group_resume`
rows for `GET /api/waiting` and, only with item 5 (`autonomy.read(conf)["auto_continue"]`), presses 繼續 through `DispatchRunner.resume_dispatch(did, by="vbear", expect_pause_seq=…)` (it takes only `you` or `vbear`, refuses a `sending` step with `needs_look`), noting `{at, dispatch_id, event_seq, pause_seq, reason, item: 5}` in `<state>/routines/auto-continue.jsonl`; the limits (once for a pause, three for a dispatch, five a day, 10 minutes, 12 hours) read both that file and the
`continued` events by `vbear`. Nothing in `group*.py` imports it.

The page (`web/app.js`): the block `// ---------- my skills (P44-1` draws `viewMySkills`, `skillForm`, `openSkillSave` (the box behind each 「存成技能」 and behind the proposal of 「整理成技能」) and `skillUseButton`/`openSkillPicker`/`skillPut` (「用技能」 puts words in a box, and 「從技能帶入」 in a routine's form replaces the text); the block `// ---------- skill suggestions` draws `skillSuggestDesk`; the block
`// ---------- routines` draws `viewRoutines` (the fixed lines, the 「等你決定」 rows, each routine with its next time, switch, last ten runs and 「現在開始」, the form, the settings including 「讓 Mac 保持清醒」), `waitingBarText`/`refreshWaitingBar` (the line over every page, every 30 seconds) and the routine rows of the chat list; the block `// ---------- the countdown` draws the lines on the dispatch and group pages and
`resumeBarRows`; the settings page ticks items 1, 2, 3 and 5 and posts the four booleans together. It builds nodes with `el()` and `textContent` only: a skill's or a routine's name that looks like markup is shown as it is. `tests/test_skills_routines_flow.py` walks it once over HTTP with a fake clock and a fake chat service; `tools/qa_p44.py` is the coordinator's real-machine check through the HTTP API (it needs `--state` and `--cards`,
refuses `~/.vbear` and the ports 7788 and 7789, prints no word of a model's and runs no program except reading the `caffeinate` lines of `pmset -g assertions`); `tests/test_qa_p44.py` runs it against a fake console and a fake `pmset`.

## Team templates — `vbear/templates*.py`, `web/app.js` (`#/templates`)

A set of employees, skills and routines that the person ticks, previews and applies, built on the three stores that already exist and adding nothing to the runtime. ADR 0011 gives the reasons.

**The format and the plan.** `vbear/templates.py` is pure. A team template is `{id, name, about, builtin, cards, skills, routines}` (a closed format: a card has `key`, `name`, `position`, `instructions`, `claude_model`; a skill `key`, `name`, `text`; a routine `key`, `name`, `text`, `days`, `times`, `who`, the key of a card of the same template or null); `template_problem(template, builtin=)` says what is wrong with one in a sentence; the limits (a name 40, a text 4,000,
instructions 2,000; at most 12 employees, 24 skills and 12 routines in one template and one apply; 500 cards, 100 skills, 20 routines in all; 20 of the person's own) are written again here and compared with `agent_profiles`, `skillbook` and `routine_rules` by a test, because the guard test keeps this module from importing them. `plan(body, templates=…, current=…)` turns a request
`{tool, cards: [{from: {template, key}, name?}], skills, routines: [{from, to?}], confirm_warning?}` into what would be made (a ValueError for a request that is not well-formed; what the person can fix is in `problems`: a routine without an employee, a name that is empty, a limit passed, a second yes missing); `public()` drops the bodies for the preview. `card_body`, `skill_body` and `routine_body` make the bodies the
ordinary write functions take, with the three literals that matter: `launch_mode: "safe"`, `equipped_skill_ids: []`, `enabled: False`. `vbear/templates_builtin.py` holds the four built-in ones (`shop`, `creator`, `studio`, `life`), word for word, and a test pins their hash. `catalog()` is the content of `GET /api/templates`.

**Apply.** `vbear/server.py` is the one place that makes and deletes. `POST /api/templates/preview` only plans. `POST /api/templates/apply` plans again, refuses the plan's problems (409 `template_full`, 400, 409 `confirm_warning`), reads the record of the applies (503 `applies_unreadable`) and, under `TEMPLATE_WRITE_LOCK`, makes the employees with `_save_card` (the stretch of code `POST /api/agent-profiles` shares),
the skills with `skillbook.add` and the routines with `routines.create`, one at a time, writing each item as *intent*, then *made* (with its fingerprint) or *failed*; a step that fails stops the apply (409 `template_partial`). The routines are given the chat service's list of cards only after the employees exist. The apply asks the chat service for nothing but that list and calls no daemon, no meeting engine, no memory or shared-folder switch and no program.

**The record and the undo.** `vbear/templates_apply.py` keeps `<state>/templates/applies.json` (`GuardedJsonStore`, 0600; at most 50 applies; `{id: ta-<12 hex>, at, tool, state: applying|done|partial|interrupted, items: [{kind, id, from: {template, key}, state: intent|made|failed|unknown|deleted, why, fp, at}], undone_at}`; **no name and no word**) and `log.jsonl`; the functions `begin_apply`, `record_item`, `end_apply`, `record_undo`, `log_undo`;
`fingerprint(kind, record)` (`agent_profiles.profile_digest` for a card, a sha256 of the whole record for a skill and a routine); `recover()` (called by the console at its start, before a route is served: an `applying` apply becomes `interrupted`, an employee's intent whose card exists becomes *made*, a skill's or a routine's intent becomes *unknown*); `card_mentions(state_dir, ids)` (read only: plain files, no link followed, at most 4 MiB a file and 20,000 files, anything else counts as mentioned);
and `undo_plan(apply, facts)`, pure, which says what is deleted, kept (with a code that `KEPT_TEXT` turns into a sentence), already gone, and whether something is unsure. The server gathers the facts from the real files (`_templates_facts`), `undo-preview` shows the plan with the current names and the two fixed notes (`TERMINAL_NOTE` when an employee would be deleted, `SKILL_NOTE` when a skill is concerned), and `undo` plans again and deletes with `routines.delete`, `skillbook.delete` and
`agent_profiles.delete_profile`, routines first, then skills, then employees. The record has no names; the page reads them from the files now.

**The person's own.** `vbear/templates_mine.py` keeps `<state>/templates/mine.json` (`{v: 1, templates}`, 0600, closed) and its own `log.jsonl` lines: `read_mine()`, `save_mine(body, cards=, skills=, routines=)` (the server reads only the files the request names), `rename_mine`, `delete_mine`. `POST /api/templates/mine` (201), `POST /api/templates/mine/<tm-id>` (rename) and `…/delete`. A saved employee has no tool and no mode, so every apply of it is the safe mode. A `mine.json` that cannot be read is moved aside by the store, the page says so, and the four built-in ones go on.

**The page.** In `web/app.js`, the block `// ---------- team templates (v0.19` draws `viewTemplates` (the four fixed lines, a block for each team template with three ticked lists, the person's own, 「你現在的」 which is only for saving, the line with the counts and the two buttons, the 套用紀錄), `openTemplatesPreview` (the choice of the AI tool, the fixed sentences, who each routine goes to, the problems, 「套用」, the result), `openTemplatesUndo` (the lists, the notes and 「刪掉這些」)
and `openTemplatesSave`. It builds nodes with `el()` and `textContent` only: a name that looks like markup is shown as it is. The nav has 「團隊範本」 after the routines, and the role card pool has 「用團隊範本開始」. `tests/test_templates_flow.py` walks it once over HTTP with a fake chat service that lists the cards, traps for the daemon and the ledger, and a fake report of the AI tools; `tools/qa_p45.py` is the coordinator's real-machine check through the HTTP API
(it needs `--state`, refuses `~/.vbear` and the ports 7788 and 7789, prints no word of a model's and runs no program); `tests/test_qa_p45.py` runs it against a fake console.

## Start-up page — `vbear/ai_tool_status.py`, `web/app.js` (`#/setup`)

`ai_tool_status.report(conf)` answers, for each tool in `ai_tools.setup_ids()` (a hidden one only while its switch is on),
whether it is installed (found on the CLI search path and `--version` read by the registry's `version_pattern`), whether it is
logged in (the status command's exit code for Claude Code and Codex; the person's mark for AGY, Grok and MCODE), and the
resulting `state` (`not_installed`, `not_logged_in`, `ready`). `GET /api/setup/tools` serves the rows, `POST
/api/setup/tools/<id>/marker` sets or removes a mark, `POST /api/setup/settle` is the lobby's first look (a person who already
has a ready tool when they come to v0.12 is counted as done, with `setup_notice` set once), and `POST /api/setup/terminals`
opens the install or login terminal through the daemon's `open_setup` operation (see SECURITY-MODEL). The config keys
`setup_done` and `setup_notice` are written through `/api/config`. The page sends the lobby's person there when `setup_done` is
false; a config that does not say forces nobody.

After 開始使用, a person with no role card to chat with is led to `#/ceo` (`viewCeo` in `web/app.js`, 建立你的 CEO). `GET
/api/first-ceo` (`vbear/first_ceo.py`, read-only) answers `needed` (no enabled card on Claude Code or Codex), the ready tool the card
takes (Claude Code, else Codex; never a tool that has only a mark), `go: "setup"` when none is ready, and the name, instructions and
opening sentence to fill in. The page makes the card with the ordinary `POST /api/agent-profiles` in safe mode, opens a chat
with `POST /api/chats`, and only puts the opening sentence in the box; sending it is the person's own press. The config key
`first_ceo_id` (written through `/api/config`) makes the lobby offer a first chat with that card once.

In the app window only, the home page sends that person to `#/welcome` (`viewWelcome` in `web/app.js`, 第一次打開 VBear) first,
while the config key `welcome_seen` is false; reading it or skipping it writes `welcome_seen: true` through `/api/config` and goes on
to `#/setup`. Whether this is the app window is judged by `folderBridge()`, the native folder-chooser handler that only the app's
WKWebView gives the page (`macos/VBear/main.swift`); a browser does not have it and never gets the page. The page's picture is boxes
drawn with `el()` and CSS (an illustration, not a screenshot).

`ai_tool_status.report` keeps each tool's row in memory for `CACHE_TTL_S` (30 seconds, keyed by search path, tool and mark);
`GET /api/setup/tools?force=1` (with `X-VBear`), a mark, an install or login terminal and a try read the tools again.
「試一下」 is `POST /api/setup/tools/<id>/try` (`vbear/setup_try.py`): one fixed sentence, headless, in a scratch folder, with a
time limit; the answer is judged and dropped. Its cost is kept by `vbear/try_spend.py` (`setup-try.json`) and is one more kind
of the shared day in `meeting_runner.spend_kinds`, `staffing_runner.spend_kinds` and the daemon's chat check; the ledger lists
it as `setup_try`.

The same page asks for the daily limit (US$1, US$3 by default, or US$10): `GET /api/setup/daily-limit` gives the one in force,
`POST /api/setup/daily-limit` (`{"daily_usd": n}`) writes it. `vbear/daily_limit.py` works out what must come down with it:
the meetings' limit and call limit, the staffing record's total and the CEO's call, the chat turn; only ever down, never up.
The server checks the result with each family's own rule and writes `config.json` once (all or nothing). A write of
`meeting_limits.daily_usd` through `/api/config` brings the staffing and chat limits down the same way, but keeps refusing
a day under the meeting or call limit that the same request or the file holds, with the plain 「每次 ≤ 每場 ≤ 每天」.

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
  The tools a role card may name are `agent_profiles.TOOL_ORDER` (`claude`, `codex`, `agy`, `grok`, `mcode`, `shared`), and each implies a
  model family (`TOOL_FAMILY`; `agy` is Google, `grok` xAI, `mcode` MiniMax). Only `claude` and `codex` can be started in safe mode; the safe launch refuses an
  `agy`, `grok` or `mcode` card with its own sentence (`agent_launch.TOOL_NOT_LAUNCHABLE`), while full mode can start all five
  (`agent_sessions.FULL_ENGINES`; `mcode` is hidden until the config key `show_mcode` is true, and the catalog's `tool_list` leaves it out until then). The list of tools is written once, in `vbear/ai_tools.py`; `TOOL_ORDER`, `TOOL_FAMILY`,
  `FULL_ENGINES`, the model flags, `TOOL_NOT_LAUNCHABLE` and the catalog's `tool_list` are made from it, and
  `tests/test_ai_tools.py` keeps the tables of `web/app.js` equal to it. Adding a tool starts with one entry there. Two fields tell the safe side apart: `safe_launch` (the safe launch's code accepts the tool: claude and codex) and `safe_mode` (the safe mode can really start it in this build: claude only, because Codex's managed launch is refused); `agent_profiles.SAFE_MODE_TOOLS` and the catalog's `safe_mode_tools` come from `safe_mode`, and the "only full mode" mark on a card is `full_launch` without `safe_mode`.
  They never take an argv, environment variables, settings or credentials.
- **Cleanup.** When the session ends, the scratch directory and the per-launch files are removed only after
  every tracked process is proven dead. Otherwise the launch is kept in a `manual_review` state for you
  to inspect. Launches that were prepared but never opened expire after 600 s. At startup the daemon
  recovers the launches left behind by a previous run.
- **Codex.** A launch path exists (`codex_settings`), but the preview always reports that Codex is
  not launchable. With the pinned version, Codex's interactive mode still loads global MCP servers,
  plugins and hooks, and cannot ignore your user config.

## macOS app — `macos/`

`macos/build.sh` builds `VBear.app`. Every copy it leaves on disk sits in a folder whose name ends in `.noindex`
(`build/app.noindex/`, `build/dmg.noindex/` and the finished `dist/app.noindex/VBear.app`), because macOS does not index
such folders: build copies would otherwise appear in Spotlight and Launchpad beside the real app. The disk image is
still `dist/VBear-<version>-arm64.dmg` (with a `.sha256`) and holds `VBear.app` and an Applications shortcut. The app is a small Swift program (`macos/VBear/main.swift`) with a WebKit window,
plus a standalone CPython 3.13 (python-build-standalone, pinned by version and SHA-256) and a copy of `vbear/` and
`web/`. On launch it reuses a VBear that accepts the token in `server.token`, or starts
`python3 -B -m vbear serve --port <free port>` with a fresh token in `VBEAR_ACCESS_TOKEN`. The server removes that
variable from its environment at once, so the runtime daemon and terminals never inherit it. The window then loads
`http://127.0.0.1:<port>/#auth=<token>`. The bundle is ad-hoc signed and is never written to at run time
(`-B`, byte-compiled at build).

The opt-in `BrowserOnLaunch` UserDefaults preference runs the bundled Python's `vbear launch` instead of
creating a window. Option at startup overrides it. A successful launch exits the shell, leaving the CLI's
detached server alive; a nonzero exit, executable error or 15-second deadline opens the normal window and
an error sheet. The window's browser command opens the server's existing `open.html`, after checking it
matches this connection, without another token file or token-bearing subprocess argument. Acceptance uses
`VBEAR_APP_PORT` to avoid the production port and `-BrowserOnLaunch YES/NO` to override preferences without
writing the user's defaults. `macos/test_browser_mode.sh` exercises the Swift launch decision and failure paths;
`macos/smoke_test.sh <dmg> --browser` also checks detached server startup and reuse.

## Front end — `web/`

Plain HTML, CSS and JavaScript with no framework. The only dependency is the bundled xterm.js 5.5.0 with
its fit addon. A unit test pins the SHA-256 of both files, and CSP `script-src 'self'` keeps CDNs out.
All dynamic text goes through `textContent`, and `innerHTML` is not used. The chat pages (`#/chat`, `#/chat/<id>`) read the
live view with `fetch` and a stream reader (the header cannot be set on `EventSource`) and poll when it cannot be had.

## Tests

- `tests/test_*.py` use a synthetic `HOME` and start real runtime daemons in temporary directories. They
  never touch your real state directory.
- `tests/frontend/*.cjs` run the UI logic in Node against a minimal synthetic DOM. They are not browser tests.
- Some runtime tests measure timing, such as stream latency and an 8 s version probe, and can fail
  occasionally on a heavily loaded machine.
