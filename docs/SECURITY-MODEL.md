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
| Secrets inside skill files | API keys, tokens and PEM blocks are masked in the index, previews and warnings; when a secret-looking name has nothing after its colon (`tokens:`), the more deeply indented lines under it (a list, a value on the next line, a nested mapping) are masked too, and so are they when that line holds only a comment, an opening bracket, a block header or a tag or anchor |

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

The page trades the code **before it asks the server for anything else**: from the moment it sees `#auth=` until
`POST /api/auth` has answered, the translation poll, hash changes and tab-focus refreshes are held back and a 401
met in that window is not shown as "open VBear" (`authPending` in `web/app.js`; `tests/frontend/boot.cjs` holds the
trade open and checks that no other request leaves the page, and that a refused code ends the waiting state). This is
about order and wording on the page; it adds no credential and changes nothing the server checks.

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
While an attachment's command processing is paused, client commands that have not been processed yet are
discarded if the session closes in the meantime.


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
- **貼上職位指示 (P34-2) types nothing for you.** After you hold control of a terminal, the button next to a card's name
  reads that card's instructions with `GET /api/agent-profiles/<id>/instructions` (read-only; same Host, token and
  Origin checks as every other `GET /api/`) and hands them to xterm's `paste()`. The text is trimmed and control
  characters are removed; line breaks stay only while the program in the terminal has switched bracketed paste on,
  and become spaces otherwise, so the paste cannot submit itself. VBear never sends Enter: the text sits in the
  program's input box and you read it and press Enter yourself, or clear it. It goes through the same input path as
  your own typing, so it needs the same takeover, and it is only a convenience: a tool that ignores it, or a person who
  edits it, changes nothing VBear can see. The terminal does not know which card started it, so you pick the card in a
  drop-down beside the button; nothing is pasted until you press it, and a launch never pastes by itself.

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
| Bash cannot write outside the work directory and the session's scratch directory | Enforced by Claude Code's OS sandbox (Seatbelt) | Evidence for [2.1.296](evidence/claude-code-2.1.296.md#writes), [2.1.292](evidence/claude-code-2.1.292.md#writes), [2.1.291](evidence/claude-code-2.1.291.md#writes) and [2.1.286](evidence/claude-code-2.1.286.md#writes); the shared `/tmp/claude-<uid>` is explicitly denied |
| No network from Bash | Enforced: `allowedDomains: []`, `strictAllowlist: true` | Evidence for [2.1.296](evidence/claude-code-2.1.296.md#network), [2.1.292](evidence/claude-code-2.1.292.md#network), [2.1.291](evidence/claude-code-2.1.291.md#network) and [2.1.286](evidence/claude-code-2.1.286.md#network): external connection refused with `EPERM` |
| Bash cannot reach VBear itself | Enforced by the same sandbox | `127.0.0.1` listener and unix socket both refused with `EPERM`, headless and interactive, on [2.1.291](evidence/claude-code-2.1.291.md#network); headless-only spot check on 2.1.291 for the 2.1.286 page; **not re-run on 2.1.286 itself** |
| Edit and Write tools are unavailable | `--tools Bash --disallowedTools Edit,Write`; those tools would not be covered by the Bash sandbox | Launch argv is built server-side from trusted values only. Since the pixel office, the two lists are the constants `CLAUDE_TOOLS_ALLOWED` and `CLAUDE_TOOLS_BLOCKED` in `vbear/runtime/agent_sessions.py`: both argv shapes are joined from them when built, and the role card's `tools` field (`/api/agent-profiles/<id>/loadout`, read only) reads the same two constants, so what the page lists is what the argv carries. The argv text is unchanged (`Bash`, `Edit,Write`); tests in `tests/test_agent_sessions.py` and `tests/test_loadout_api.py` lock the text and the sharing |
| No MCP servers or project hooks from the work directory | `--safe-mode --strict-mcp-config` | |
| Commit is possible | **Not prevented.** `.git` is inside the writable work directory; you must acknowledge this before launch | |
| Deploy is denied | Only by the absence of network access | |
| Reads are isolated | **No.** A session can read anything your user account can read | |
| Commands you type with `!` are sandboxed | **No.** Claude Code runs `!` commands outside the sandbox; the preview says so | |

### The launch pass (出發通行證) is a way of reading these claims, not a new one

The pass is the page that used to be called the pre-launch check. Its front has three lines, and they are worded
**by the level the server gave that item**, never by what the page would like to say (`passSummary`, a pure function
of the preview's `derived_labels` and `canonical_paths`):

- The write and network lines say what was blocked only for the `強制` level; `部分強制` says it is partial,
  `未驗證` says the setting exists but this version was not tested, `未知` and `不授予` say the range is not known,
  and `僅意圖` / `未限制` say it is not blocked. A check mark is drawn only for `強制`. A level the page does not know
  reads as unknown. A write line cannot name a folder it was not given.
- The commit line is always 「擋不住版本紀錄（commit）」, whatever the label's level says, because `.git` is inside the
  writable folder (see the table above). It is on the front, not only behind the fold.
- Shields follow the level word (solid: enforced; dashed: intent only; empty: unrestricted) and only those three
  levels have one. Shape differs as well as colour. `tests/test_launch_pass_contract.py` compares the page's level
  table with the constants in `vbear/agent_launch.py`, so a changed word on either side fails a test.
- The seven labels, their five groups and the "can be bypassed" notice are unchanged and are one click away
  (「看七項細節」); the bypass notice stays on the front.
- The sentence the user ticks says that the role will create and change files in the folder and can save commits, which
  VBear cannot block. The same box still decides whether the preview is made with `commit: true`; a button that points
  at an unticked box only moves focus to it and never ticks it.
- A button next to a reason that stops a launch only leads to where that reason is changed: the card editor (an
  ordinary profile save through `POST /api/agent-profiles/<id>`), the folder chooser, or the checkbox. The rules stay
  in `launch_blockers`; the page repeats none of them. After a save the pass opens again on the same folder and asks
  for a **new preview**; nothing from the old preview is reused, and a preview is still single use.
- Permission intents on a role card are a record of the team's division of work. The page says so wherever it shows
  them, and a green light on a card is worded 「可以出發（權限意圖都已決定）」, not "safe".

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
- **Where VBear looks for the CLIs.** Besides the `PATH` it was started with, VBear looks for `claude` and `codex` in
  Homebrew's `/opt/homebrew/bin`, `/usr/local/bin`, the system folders, and `.local/bin` under your home directory
  (where Claude Code's own installer puts it), in that order, after your own `PATH`. These folders are writable by
  you (and, for Homebrew, by your admin group), the same trust as your `PATH`. VBear scans no other folder, reads no
  shell startup file and starts no login shell. Finding the file changes none of the checks above: the version, the
  verified list and the translation boundary are decided afterwards, exactly as before. The Codex review does not use
  `.local/bin`; it runs the pinned Codex build only.
- **Verifying on this Mac.** 「驗證這個版本」 runs `vbear/boundary_check.py` headless and interactive against
  the binary a launch would use. The version is recorded as verified only if both runs pass every check; a
  refusal only counts if it is the sandbox's (`EPERM`/`EACCES`, or the proxy's 403). The record file is
  owner-only. Any program running as you could edit it, as it could edit anything else you own.
- **Fail closed** otherwise: the launch is refused if the sandbox is unavailable (`failIfUnavailable`), or if the
  profile, work directory, Claude Code binary or config changed since the preview.
- **Antigravity (AGY) is not launched.** A role card whose tool is `agy` is a record for building teams: `launch_blockers`
  always refuses it (`tool_not_launchable`, "VBear 還不會啟動 AGY，這張卡目前只用來排隊伍與記錄"), so no preview is
  prepared, no manifest is written and the loadout shows no armor and no tool list. Which skills AGY reads is judged
  from files only (see "Which skills AGY reads"), and even a skill AGY reads is never reported as one that loads: a
  skill chosen on an AGY card is a collection. The automatic review is unchanged: it is the Codex that
  VBear starts, and an AGY card on a review place is only the record of a manual review.
- **No caller-supplied launch details.** The daemon's `open_managed` takes only a launch ID. It reads
  the manifest from its own state directory and re-validates the work directory. A launch ID is single-use.
- **Cleanup only when it is proven safe.** Files belonging to a launch are removed only after every
  descendant process is confirmed gone. Otherwise the launch is kept for manual review.

## Full-mode launches

A role card whose `launch_mode` is exactly `full` is started the way you would start the tool yourself in your own
terminal, and **VBear limits nothing about it.** Everything in "Profile-managed Claude launches" above is a claim about the
safe launch; none of it is claimed here, and the pass for a full card says so first (「VBear 沒有限制這張卡」).

- **What is the same as typing the command yourself.** The tool runs with your own settings, skills, `CLAUDE.md`, MCP
  servers and plugins, in the folder you chose, and it can use the network. It can read and write anywhere your account
  can, commit, publish or pay, exactly as a tool you started in Terminal.app can. The only gate left is the tool's own
  permission prompts. The position's boundaries read as reminders only; a card's permission intents are not applied (the
  pass lists any intent written as "deny" and says it is not kept). There is no sandbox, no `--safe-mode`, no settings
  file, no tool list, no scratch directory, no `CLAUDE_CODE_TMPDIR` and no launch manifest.
- **The command is built on the server and is a list, never a shell string.** `claude [--model X] [--append-system-prompt
  <text>]`, `codex [-m X]`, `agy [--model X]`, with the tool found as the first `claude`, `codex` or `agy` on the search
  path VBear uses for the CLIs (its own `PATH`, Homebrew and `~/.local/bin`), by its absolute path. The pass shows the
  command and the path. The daemon accepts it only through its own `open_full` operation, which takes nothing but the
  tool name, that list, the folder and the terminal size, and refuses any list `agent_sessions.full_argv` could not have
  built (another flag, a model that looks like an option, a program with another name). The environment is the plain one
  every terminal gets (`PATH`, `TERM`, `LANG`, `HOME`, your user name); no credential is added, so the tool uses the login
  it already has.
- **Only Claude Code takes the instructions on the command line.** The card's instructions (its own text, else the
  position's default) go in as a single `--append-system-prompt` argument: control, format and separator characters other
  than a line break or tab are removed, it is cut to 2000 characters, and a text that starts with `-` gets a sentence in
  front, so it can never be read as a flag. The pass shows the whole text that will be carried. VBear did not verify that
  Claude Code receives it, or does what it says; it is words for the AI, as before. Codex and AGY have no such option, so
  nothing is added for them: their instructions are only the paste button's (Terminals above), and VBear never presses
  Enter.
- **You still confirm, and the confirmation is for this exact command.** The preview is one-use and five minutes. It is
  bound to the card's digest (an edited card voids it) and to a digest of the command, the folder and the tool file's
  identity (a program replaced since the preview voids it, `cli_drift`), and `user_confirmed: true` is required. VBear does
  not run the tool to look at its version and makes no claim about it. The folder follows the same rules as the safe launch
  (inside the allowed root, never the home directory itself, credentials, tool state or VBear's own state), because it is
  the place the tool starts in. The commit sentence and the network input of the safe launch do not apply and are not asked.
- **What VBear says about its state is unchanged and small.** The terminal appears in the office and the workbench as an
  agent. VBear reads a working or waiting state only from signals checked against that tool and version in the safe
  launch; nothing was checked for a full-mode terminal, so it reads 狀態未知 and says why.
- **Not changed.** The safe launch, its argv and its evidence; automatic mode (the executor there is still the sandboxed
  stream session); the translation and review boundaries. A card without `launch_mode` is safe.

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

### Starter cards and the wizard's launch check

- **The starter deck carries the one combination a managed launch honours.** `launch_blockers` is a whitelist: read,
  write and test allowed, deploy denied (`VERIFIED_INTENTS`, defined in `vbear/agent_profiles.py` and imported by
  `agent_launch`). The three starter cards and the wizard's suggestions use it, taken from the catalog, so a person
  is never handed a card that cannot go. This is a choice of defaults, not a limit: that a planner or reviewer
  should not edit files cannot be enforced today, and the screens say so beside the suggestions.
- **`GET /api/agent-builder/intent-check?read=&write=&test=&deploy=` is pure.** Same Host, token and Origin checks as
  every other `GET /api/`. It runs `launch_blockers` for a stand-in enabled Claude card with the commit acknowledged
  and the network closed, so only the intents can speak, and returns the server's own reasons. It reads and writes
  nothing and starts no process; the four values must each be given once and be `allow`, `deny` or `unspecified`
  (anything else is `400`). The wizard uses it to tell a person, before saving, that a combination cannot be
  launched; the page holds none of those rules.
- **The wizard's model drop-down reads one cache for names.** `GET /api/agent-builder/catalog` carries `model_options`
  (P31). For Codex, VBear opens `~/.codex/models_cache.json` and keeps only each model's `slug` and `display_name`
  (using `visibility` and `priority` to choose and order them); no other field is read out or sent on. The read is
  bounded: a regular file owned by you, at most 1 MiB, never followed through a symbolic link at the file (the
  `.codex` folder may be a link only if it stays inside your home folder), strict JSON, a cap on entries, and a name
  must be letters, digits and `. - _ : /`. A missing or broken file gives an empty list and a one-line reason. The Claude
  list is the aliases from `claude --help` plus model names the usage scan already collected. No program is run and
  nothing is fetched. The list only fills a drop-down; it grants nothing, and the saved `model_id` is checked as before.
- **A card's suggested position is a record, kept on the card.** The role card has an optional `position` field (P32-3):
  a save without the key keeps the stored value, `null` or an empty string clears it, and anything outside the eight
  listed positions is `400`; the ids that only the unreleased v0.9.0 wrote (`RETIRED_POSITIONS`) are no longer listed,
  so saving one is `400` too. Reading is looser on purpose: only the type is checked (a string of at most 32
  characters), so a position a newer build wrote, or a retired one, does not isolate the card file. It does not change what a launch
  allows, but it is part of the card's digest, so changing it makes an open launch preview or a placed card read as
  changed, the same as any other field. A card without a position stores no key, so its digest is the one it had
  before.
- **The wizard's profession picker is shown and pre-filled from what the scan already holds.** For each role template
  the catalog (P32-4) also carries the first 300 characters of the author's own description (never VBear's wording),
  a guess at the position it fits (`origin: "derived"`, with the matched keyword, from a small visible table in
  `vbear/role_departments.py`), the skills it declares, the model it names (not `inherit`; control characters
  removed, at most 200 characters) and whether its plugin is switched off. These are fields `/api/roles` already
  serves to the same page, behind the same Host, token and Origin checks; the catalog adds no path, capability or
  limit. They only draw the picker and fill the card's own fields on a click (position, equipped skills, model
  string). The model string is saved through the same `model_id` check as a typed one, and equipped skills stay a
  collection. Choosing a profession still loads nothing into a tool and changes nothing about a launch.
- **A card's instructions are text you may paste, not a rule (P34-2).** The role card has two more optional fields,
  `instructions` (text, at most 2000 characters; control, format and line/paragraph-separator characters other than a
  line break or tab are refused with `400`, CRLF is stored as LF, blank or `null` clears it, and a save without the key
  keeps it) and `launch_mode` (`full` or `safe`). Reading only checks the type, so a card a newer build wrote does not
  isolate the card file. A card without either key stores nothing new, so its digest is the one it had before. When
  `instructions` is empty the position's default text is used (`vbear/position_guide.py`, served in the catalog;
  `CARD_POSITION_TABLE` and its parity test are not changed). The safe launch never carries it: no launch argument,
  environment variable, settings file or prompt does. A full-mode launch of Claude Code carries it as one
  `--append-system-prompt` argument (see "Full-mode launches" below); nothing else does, and the card back and the pass
  say which of the two applies to the card in front of you.
- **Boundaries are resolved by tool and by launch mode, and only what a launch enforces is called enforced.** Each
  position lists boundaries of four kinds: *enforced if launched* (it names an `armor_items` item whose level must be
  ENFORCED or PARTIAL; a contract test fails if one names an item that is missing or not enforced), *reminder*,
  *not possible* and *not applicable*. For Claude Code in safe mode the table's kinds stand. For Codex, AGY and a shared
  card nothing is enforced by VBear (it does not start them), so enforced and not-possible rows read as *not applicable*
  and only reminders stay. In full mode every row reads as a reminder. VBear still does not claim that skills, CLAUDE.md,
  hooks or MCP are switched off. A position's boundaries say nothing about meetings: a meeting does not use the card's launch, only its
  instructions and its model (see "Meetings" below).
- **`launch_mode` chooses between two launches, and only the exact word `full` chooses the full one.** The wizard offers
  `full` for a new card and `safe` on request; the server never writes the field itself, and a card without the key
  reads as `safe`. A missing, null or unknown value is safe, so an older card is never loosened by this build. A card in
  full mode is started by the launch described in "Full-mode launches" and by no other: it is never started as a safe
  one instead, and a safe card is never started as a full one. The loadout shows no armor for a full card (there is
  none to show). The mode is part of the card's digest like any other field.
- **The suggested work folder is advice.** The pass compares the folder's own name (NFC-normalized, one path component) with the
  position's suggestion (社群草稿, 素材, 法務報告, 帳務報告) and, if they differ, says so. It quotes only the folder name,
  never the path, refuses nothing and checks nothing about the folder's contents.
- **A Codex card's light.** Codex cannot open a terminal from VBear (`codex_` reasons), but the flow's automatic
  review does run it, in a scratch copy. When every reason on a card starts with `codex_` the card shows a neutral
  "can't open a terminal directly" light instead of the red one; any other reason keeps the red. It is a reading of
  the same `blockers`, not a new permission.

### A task card is a folder: folder inspection and the app's folder chooser

- **`GET /api/folders/inspect?path=` is read-only.** It sits behind the same Host, token and Origin checks as every
  other `GET /api/` route. It does a fixed number of `stat` calls and the same plain-file `HEAD` read as `git_head`
  (no `git` process, no tree walk, nothing written). It answers with a summary only: whether the folder exists, the
  repository root, branch and `HEAD` hash, the project-skill count taken from the skill index **already in memory**
  (it never loads or scans), the terminals of the last live view whose working directory is inside the folder, and
  the unfinished task cards bound to it. No file content is returned.
- **Places that can never be a project are refused before anything is looked at.** The path is made absolute and
  `realpath`-ed first (so a symlink into a refused place is refused too, and `~/.SSH` is refused as `~/.ssh` is:
  names are compared case-folded). The home directory itself, `~/.ssh`, `~/.gnupg`, `~/.aws`, `~/.config`,
  `~/.vbear`, `~/.claude`, `~/.codex`, `~/.gemini`, `~/Library`, the state directory in use, and anything below
  them answer `403` with one fixed sentence that is the same whether or not the place exists, so the endpoint
  cannot be used to probe for them. A place outside the home directory is `403` too. The list is the constant
  `SENSITIVE_HOME_DIRS` in `vbear/folders.py`; tests lock it, and lock that the page's copy of it (used only to leave
  such folders out of its lists) is identical.
- **A managed launch's work directory follows the same list.** The folder becomes writable for the session, so
  `_check_workdir` in `vbear/runtime/agent_sessions.py` refuses it by calling the same code (`refused_locations`):
  the home directory, the places above and anything below them, by `realpath` and with names compared case-folded.
  A work directory that would contain one of those places is refused too. The refusal comes before the check that the
  folder exists, says the same fixed sentence whether or not the place exists, and has the code `invalid_workdir`;
  the preview shows it as a blocker (`launchable: false`) and the check is repeated just before the launch starts. A
  folder under `~/Library` (for example iCloud Drive's `~/Library/Mobile Documents`) or `~/.config` cannot be a
  work directory, as it cannot be picked in the folder chooser.
- **Terminals are counted by working directory only.** The count and the list say nothing about which role card
  opened a terminal; the page words it as "this folder currently has N terminals", never as "working".
- **`recent_folders` and `onboarding_dismissed`** live in `config.json` (written with `write_private`, validated: at
  most 10 absolute path strings of at most 1024 characters without NUL; a boolean). A folder is remembered only after
  a task card with it was created or a launch preview for it was confirmed; a corrupt config is left alone.
- **The app window's folder chooser** (macOS app only) is the script message handler `vbearPickFolder`. The page
  sends `{requestId}` with a short token (`^[a-z0-9-]{1,32}$`, checked again in Swift). The app ignores any message
  that is not from the main frame of its own server (`http`, host `127.0.0.1`, the port the app started), answers
  `busy` while a panel is already open, and otherwise opens an `NSOpenPanel` that can choose one directory and no
  file. The answer goes back through `window.__vbearFolderPicked(JSON)` built with `JSONSerialization`, no string
  concatenation. The path is only text: the page asks `/api/folders/inspect` about it like about any typed path, and
  the chooser gives the page no file access. In a browser there is no chooser and the page says so.
- **Nothing here writes into a project folder or runs a program in it.** A folder without a git repository can
  still be a task card; the card is marked "no version history", because a review result binds to a commit and
  cannot count there (see "Task cards" above).

## Flows

- **The board's recording routes add no execution capability.** The Phase 1 board records and shows. Its routes
  (`POST /api/flows`, `/events`, `/roles`) write only `flows.json`; nothing in `vbear/flows.py` starts a process,
  sends input to a terminal, runs `git` or contacts the network. The managed executor and review of Phase 2 are
  separate routes with their own gates, described in [Phase 2 coordination](#phase-2-coordination). The only
  outside reads are the executor directory's HEAD through `git_head` (plain bounded file reads, as for task cards)
  and the last live view already built (`Store.live_cached()`). The flows routes never build a live view, so they
  never reach the runtime and cannot start its daemon; a test holds them to that.
- **`GET /api/live` also carries `managed_root`** (P7): the one folder a launch may work in, as the server holds it. It is
  a path the console already shows elsewhere, only used for the wording of the folder hint; the server still checks every
  folder itself. `derive_labels` (the pass's seven labels) now does one `os.path.isdir` and one `os.path.lexists` on
  `<folder>/.git` to word the Commit note for that folder; no walk, no git process, nothing written, and the level
  (not restricted) does not change.
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
- **A role can record the role card it was filled from, and that is only a note.** A role may carry `profile_id` and
  `profile_snapshot` (`name`, `tool`, `model_id`, `revision`), both or neither, each checked as plain data with a
  closed key set (anything extra, or of another type, is refused on input and blocks the store on load).
  `vbear/flows.py` still imports neither the launch nor the profile module and computes no digest: the revision is
  the `profile_digest` the profile API shows for the card (`revision`, response only; a request that carries one is
  refused), and a test locks that value. Nothing in a flow follows a card that is edited, copied or deleted
  afterwards: the page compares the recorded revision with the card's current one, says so, and updates the role
  only when the person presses the button (`POST /api/flows/<id>/roles`). The snapshot does not decide anything: the
  family a review is judged by is still the role's own `family`, which the page fills from the card's tool and the
  server does not derive. The one cross-check is for an Antigravity (AGY) card, a tool added after flows were already
  stored: a snapshot with tool `agy` must sit on a role of family `google`, on input and in the stored shape; the other
  tools are accepted with any family, as before. Placing a card on a task card's team writes only `flows.json`; it starts,
  sends and loads nothing.

## The home page's first game

The 「新手第一局」 block and the team and next step shown on a flow card on the board read only what the existing
`GET /api/agent-profiles`, `/api/tasks`, `/api/flows` and `/api/config` already return; nothing is written except the
one setting 「先不要」 saves (`onboarding_dismissed`, a boolean in `config.json`). A step is ticked from those records
(a role card that is not a demo card, a task card with a folder, a flow with a planner and an executor), and when
a list cannot be read the block shows nothing instead of guessing. The phone-width navigation menu only toggles a
class on the page.

## Phase 2 coordination

Phase 2 adds a managed Claude stream executor and daemon-managed Codex review jobs to a flow. This is a different
execution path from the Phase 1 look-only board above and from the interactive profile-launch path. VBear can send
an approved message to a stream executor and start a review using your accounts and usage allowance. It does not
create worktrees or run `git` in the task repository. Git commands for a review run inside Codex's sandbox against
a separate clone. Merge and push stay yours: the console shows the commands and never runs them.

### Trust boundaries

| Component | What is trusted; what is not |
|---|---|
| You | Trusted to choose the task worktree, inspect approvals, accept residual risks and decide merge and push. A click records a decision; it is not proof of code correctness or independently authenticated human identity. |
| VBear runtime daemon | Trusted to build fixed launch arguments, validate inputs and evidence, enforce gates, keep records, account for limits and manage processes. It re-reads and checks state rather than trusting caller-supplied launch details. |
| Console server and browser UI | VBear's server and shipped UI are trusted to present the exact server-held preview and to display output safely. Browser requests and submitted values remain untrusted; the daemon independently checks the accepted configuration and flow state. The access token protects local API access, not against programs running as the same user. |
| Managed Claude executor | Its generated content, completion statements, test results and protocol events are untrusted inputs. VBear checks protocol attribution and selected filesystem facts. A reported test pass is still the executor's statement; VBear does not rerun the tests. |
| Codex reviewer | Its report, verdict, tool calls and recorded state are untrusted inputs checked against version-specific rules. A valid review means those checks passed, not that its findings are complete or correct. |
| Reviewed repository | Files, comments, instructions, Git configuration and Git objects are untrusted data. Instructions in them are not authority for the reviewer or VBear. Repository code may execute when the reviewer runs commands inside its sandbox. |
| Codex and Claude CLI executables, their providers and the OS | Trusted to implement their documented behaviour, sandbox and model transport. Version checks and pinned paths are compatibility and launch checks, not vendor authentication. VBear does not defend against a malicious CLI vendor, a compromised OS, root, or hostile programs running as your UID. Known local administrator-policy sources are nevertheless checked and cause refusal. |

Sandbox restrictions on agent commands do **not** mean that the CLI itself makes no network connections: the
trusted CLI must contact its model provider. Reads are not isolated; a session may read files your account can
read. The executor may write and commit inside its task worktree, and VBear does not limit disk use in that
worktree or the executor's scratch directory.

### What the console does

Two things have a server-held, one-use preview record that the approval must name: the risk acceptance and each
dispatch (the text to be sent). What the browser sends with the approval is only that record's id; nothing else it
sends is recorded or executed. The other actions carry no content to preview, so they have no preview record of their
own and rest on other checks: starting the executor and starting a review are POSTs with empty bodies that the
server refuses without a valid risk acceptance and that the daemon verifies again (acceptance values, versions,
accounts, limits, holds, unresolved failures); a review takes its commit from the latest usable report, never from
the request; stopping, continuing and closing a session act on the flow or session the request names, and deleting
also names the flow in its body and asks twice on screen.

- **Risk acceptance.** `POST /api/flows/<id>/acceptance-preview` stores a preview (`<state>/previews/`, five
  minutes, one use). The dialog shows the three residual risks in full (text version `2026-10-11.1`), the CLI
  versions, models and the first 16 hex digits of the account fingerprints they bind to, and the nine limits with
  their defaults and caps. Confirming (`POST .../acceptance`) carries only the preview id. The preview is consumed
  before anything is recorded; if the account, version, key or text changed since, the answer is 409 and nothing is
  recorded. Changing any field in the dialog voids the held preview at once, and the screen's values are compared
  with the preview's once more just before sending. Without a login in the dedicated `CODEX_HOME` the dialog shows
  the exact `codex login` command and path and offers no acceptance: VBear never logs in for you and never reads
  credentials into a prompt, report or log.
- **Dispatch.** `POST .../dispatch-preview` decides the dispatch id, stores the sanitized full text (control and
  format characters become visible `\uXXXX`) with its hash and shows exactly that text, its size and whether the
  session is ready. The text is what the person typed plus a fixed report request that VBear appends and that
  names this dispatch's id and the report's fields (`executor_report.report_request`): the executor has no other
  way to know the id its report must carry, and a report with another id is not a valid report. The person
  approves the whole text, request included; the automatic mode's dispatch texts end with the same request.
  `POST .../dispatch` carries only the preview id. A dispatch the daemon refuses is not written; a lost answer is
  retried with the same id and never becomes a second dispatch.
- **Refused tool calls.** When Claude Code's permission system refuses a tool call of the executor
  (`system/permission_denied`), that is the safety mechanism working, not a protocol error: the turn stays valid,
  the call did not run, and the report area says how many calls were refused and which tools (names only,
  filtered to `[A-Za-z0-9_]`; at most 16 are recorded per turn, so at the limit it says "at least 16"; never the
  refusal's message or reason, which must be there, be strings and be at most 4096 characters, and are read nowhere). The event must name a call that the
  turn itself made and must arrive while the turn is running; otherwise it is a protocol error and the session
  takes no further dispatch. A refused attempt does not turn a review into a pass: the review and the merge gate
  are unchanged, and the person sees the refusals before merging.
- **Reports.** The executor's own statement (status, head, tests, notes) is shown apart from VBear's reading of
  the files: whether the reported head is the work directory's HEAD now and whether the commit object exists. A
  failed check is not shown as a pass, and a check that cannot be read is shown as unreadable. A review can only
  be started from a latest report whose checks all passed. "Latest" is by the creation time the daemon wrote for
  each session; if that order cannot be told, nothing is called the latest and no review starts.
- **Reviews.** The reviewer's report is shown as plain text (`textContent`; the page builds no element from it,
  and this is tested with hostile text). `BASE_IS_ANCESTOR` is labelled self-reported. Forwarding review comments
  to the executor only fills the dispatch box with a bounded, marked-as-data draft: you still preview and approve
  it as a dispatch.
- **Merge gate.** Three conditions (the latest review is valid, complete and PASS; the commit it is bound to is
  the work directory's HEAD now; that commit object exists) must hold before any command is shown. The commands are
  exact, shell-quoted text with a copy button; VBear does not run them. Local refs (`refs/heads/main`,
  `refs/remotes/origin/main`) are labelled as what this machine last recorded, not as the remote's state.
- **Retention and deletion.** A flow's data (stream sessions with their journals and dispatch texts, review
  records, the flow's directory) is kept until you delete the flow. Deleting is refused while any session or
  review of the flow is running, launching, in manual review or not yet cleaned, while a process group of it is
  not proven finished, while the flow is stopped or has a failure you have not released ("continue" first), and
  whenever something cannot be proven to be the flow's: a session directory must be the inode its manifest
  recorded, a review job must be named by both its manifest and the flow's own record of that round, and the
  task directory must have a start record naming the flow (there is one flow per task card). The daemon, the only
  writer of that data, re-decides all of this on its own thread, then moves the proven directories into
  `deleting/<flow>/` (an atomic rename; no flow's accounting reads that directory, so none meets a half-removed
  one, while the quota scan counts its bytes) and purges them from there. Every directory is opened without following a link and checked
  (owner, same device as the state directory so a mount point is refused, the inode seen a moment before); a
  special file refuses. While `deleting/<flow>` exists the flow counts as stopped, and asking again finishes the
  deletion from wherever it stopped, without needing any record that was already removed. Deleting is
  irreversible and also removes the flow's events from `flows.json`. The lifecycle, and the way out of each
  interruption, are in [How a deletion ends](#how-a-deletion-ends).

### Safeguards: prevention and detection

"Prevention" below blocks a prohibited launch, input, write or subsequent action within the stated boundary.
"Detection" checks observations and invalidates or stops work; it cannot undo earlier actions. Neither label
promises protection against components outside the trust boundary.

| Threat or condition | Safeguard and type | Limit of the claim |
|---|---|---|
| Launch settings controlled by the caller or repository | **Prevention:** server-built arguments and environment allow-lists; launch manifests are read and validated by the daemon. Stream launches require a stream-verified version; there is no unverified-version override for this path. | Trusts the CLI and OS. Known policy sources are version-specific. |
| Claude tools bypassing the Bash boundary | **Prevention:** `--safe-mode`, `--tools Bash`, `--disallowedTools Edit,Write`, `--strict-mcp-config` and the OS sandbox; `StructuredOutput` is used for reports. Bash writes are confined to the task worktree and its scratch directory; Bash network access, loopback and the runtime socket are denied. | Does not isolate reads, prevent commits in the worktree, or cap executor disk use. No interactive typing is available in a stream session. |
| Local settings redirecting Claude's provider | **Prevention:** fixed endpoint settings; launch refusal if a known administrator-policy source or `~/.claude/remote-settings.json` exists, or existence cannot be determined. | Server-managed settings that are not cached remain a residual risk: a non-interactive run (the stream executor, `-p`) applies settings that need the user's approval for that run only and never writes the cache, so a missing `remote-settings.json` does not show there are none. |
| Forged, injected or misattributed stream results | **Detection:** strict event schemas, closed event/tool sets, dispatch/session identity, order, unique response IDs, tool/result correspondence and a completed lifecycle; validity is reconstructed from journal facts; an unexpected event is journalled with the names (never values, at most 16, `[A-Za-z0-9_]` or `?`) of its unexpected top-level fields. Unexpected messages through Claude's local messaging channel fail attribution checks. | Checks recorded protocol behaviour, not the truth of generated content; detection can follow execution. |
| Duplicate or changed dispatches | **Prevention:** `dispatch_prepare` stores the sanitized full text and its hash before `stream_send`; the send step reads and rechecks it. IDs are idempotent for the same text and reject different text. Partial or uncertain delivery is not resent. Each human approval is bound to the exact one-use server-held preview. | Sanitizing control and format characters makes them visible; it does not remove persuasive instructions. |
| Fabricated completion or commit | **Detection:** independent report-schema validation, `git_head` comparison and `git_objects.commit_exists`, including recomputed commit hashes and pack/idx checksums with read/resource limits. These are bounded file reads, not daemon-run Git commands. | Does not prove test success, authenticate history, or include uncommitted edits. An indeterminate check is not a pass. |
| Repository content steering Codex | **Prevention:** dedicated `CODEX_HOME`, empty per-job `HOME`, fixed arguments, ignored user configuration and execpolicy rules, disabled known features and bundled skill instructions, restricted network and scratch writes for sandboxed commands. **Detection:** empty configured MCP list before launch, then recorded state, permissions and tool calls checked against version constants. | A prompt asks for a read-only review, but the sandbox permits scratch writes. The prompt's first step names the work directory as one always-quoted argument and the destination as `./repo` (a model once read an unquoted `…/toy` followed by `repo` as one directory name, and the review was, rightly, judged invalid: its clone was not where VBear looks; the reason now names the directories found, never their content). Available tools cannot be enumerated in advance; multi-agent capability cannot be disabled on 0.160.0. |
| Forged or incomplete review evidence | **Detection:** successful exit and final completion, strict event/rollout checks, sequential ordinals, identity/model/provider/family checks, usage accumulation, matching final reports, required report control lines and detached clone HEAD equal to the reviewed commit. | The CLI writes both evidence sources. VBear checks their consistency, not review quality or every command's intent. `BASE_IS_ANCESTOR` remains self-report. |
| Account, version, model or limits changing after acceptance | **Prevention:** valid per-flow `risk_acknowledged` required for stream launch and review; current risk text, HMAC key, account fingerprints, versions, models and limits are checked at their relevant launch/RPC/turn points. Display and acceptance come from the same one-use, five-minute server preview, and drift refuses. | A fingerprint binds the account locally; it is not a public account identifier or independent identity authentication. Secrets and account IDs do not enter reports, display or log summaries (the screen shows the first 16 hex digits only). |
| Excessive output or retained records | **Prevention:** bounded parsing; daemon-written review outputs capped while writing (`events.jsonl` 8 MiB, `stderr.log` 1 MiB, `last.md` 256 KiB); bounded rollout copying; reservation-based 4 GiB limit for protected daemon-written pipeline/session/review data, and the files a launch's preparation wrote count as used when the daemon opens it. When the room is used up, the answer says so and the console lists the flows that can be deleted with their sizes. **Detection:** periodic thresholds for Codex-written directories. | The 4 GiB limit is not a quota for all VBear state or all CLI disk writes. The ledger may count a prepared launch's files twice until its next rebuild (never too little). |
| Continued work after failure or stop | **Prevention of later actions:** failures hold the flow; unresolved failures are recomputed from disk, and opening a stream, preparing/sending new dispatches or starting reviews is refused until you continue. A hold ends an active review. **Detection:** missing-result usage is conservatively reconstructed. | A user-requested hold does not interrupt a Claude turn already running. A failed or uncertain dispatch is not automatically retried. |
| Unsafe signaling or cleanup | **Prevention:** validate process and directory identity; keep a live-owned leader unreaped until group signaling is complete; signal only its process group. **Detection:** an observed descendant that is still alive outside the (empty) group is waited for, polling the process table every 0.2 s for at most 10 s, with no signal sent (a command the CLI ran in a group of its own, or started as it was stopped, ends by itself once its parent is gone; the review or session is not over, and the flow stays held, meanwhile); only one that is still there afterwards, and any uncertain recovery, becomes `manual_review`, retaining data and blocking new reviews and deletion. A process table that cannot be read is never taken for "gone". | After daemon restart, uncertain/live processes are left for manual handling rather than signaled. Tracking cannot prove that every possible descendant was observed. |
| Review text hiding content or injecting browser markup | **Detection:** report format/control-line allow-list, rejection of HTML outside code fences and malformed fences. **Prevention:** `last.md` and all reviewer output are shown as plain text, with no HTML or Markdown rendering. | Format checks do not establish whether prose is truthful, safe or free of prompt injection. HTML source inside a code fence is allowed as literal text. |

The stream boundary evidence is for [Claude Code 2.1.292](evidence/claude-code-2.1.292-stream.md) and [2.1.296](evidence/claude-code-2.1.296-stream.md). The review
evidence is for [Codex 0.160.0](evidence/codex-0.160.0-review.md). These are bounded probes, not proof for every
repository, tool or later CLI version. Probes confirm predefined constants; they do not automatically expand the
tool allow-list.

### Residual risks

The first three items appear in full in the per-flow approval dialog under `RISK_TEXT_VERSION = "2026-10-11.1"`
(`vbear/risk_text.py`); the others are documented here.

1. **Codex's tool set cannot be proved in advance.** Codex 0.160.0 cannot enumerate all tools available to the
   review model. Known feature flags are preventive attempts; recorded state and calls are checked afterwards. An
   unused unknown tool is invisible to VBear. A called unknown tool invalidates the review, but its action has
   already happened and cannot be undone. Depending on the tool, repository-induced actions could reach connected
   services, make external connections, or read/write outside the sandbox. Multi-agent capability cannot be
   disabled on 0.160.0, despite `--disable multi_agent`. VBear pins `explicitRequestOnly` and detects sub-agent
   activity using closed record kinds and an `exec`-only tool allow-list. `SUBAGENT_ACTIVITY` invalidates the
   entire review. Sub-agents share the same sandbox and permissions, but invalidation does not reverse their
   actions.
2. **Limits have different strengths.** Claude main-conversation responses have a real-time hard limit, with the
   one response in progress possibly completing; auxiliary calls are excluded. Claude's budget is checked at turn
   end and has no guaranteed monetary ceiling within a turn. Subscription cost values are usage valuations, not
   actual bills. Codex response counts are monitored once per second, with no provable bound on responses between
   checks; its hard execution limit is time. `CODEX_HOME` at 512 MiB and scratch plus temporary `HOME` at 2 GiB
   are checked every 5 seconds, not enforced by disk quotas. Counting errors count as over-limit and end/refuse
   reviews. Writes between checks could exhaust remaining disk space and cause other programs' writes to fail.
   Daemon-written outputs have separate write-time hard limits.
3. **Server-managed settings (Team / Enterprise).** An organization Owner can supply cloud settings that override
   the fixed Claude endpoint or add hooks. The CLI could send data to an unexpected endpoint or run hooks VBear
   intended to disable. Known local policy sources and a present or indeterminate `~/.claude/remote-settings.json`
   cause refusal, but absence of the cache cannot establish absence of cloud settings: according to the vendor's
   documentation (read 2026-10-12), a non-interactive run, which is what VBear's stream executor is, applies
   server-managed settings that need the user's approval for that one run and does not write them to the cache
   (`remote-settings.json`), so a missing cache file does not show that none apply. VBear cannot detect them
   from the cache. Personal Pro/Max plans are not subject to this organization-managed
   mechanism.
4. **Same-UID binary replacement race.** `codex_binary` checks the pinned executable's path and file type before
   launch, but the subsequent execution is not atomic with that check. A program running as the same UID could
   replace it between check and execution. Such programs are outside this threat model; a pinned path and version
   output are not binary authentication.
5. **Report formatting is not semantic safety.** The format allow-list checks control lines and display hazards,
   not the report's truth or intent. The console always shows reviewer output as plain text. Transferred review
   comments are marked as data, with instructions not to execute commands within them, but this is not a guarantee
   against prompt injection. Each transfer requires your approval.
6. **Ancestry is self-reported.** The reviewer is asked to run `git merge-base --is-ancestor` and emit
   `BASE_IS_ANCESTOR: yes`. Missing, malformed or `no` results invalidate the review, but VBear does not
   independently verify ancestry. A false `yes` can survive the format check, and the screen says "self-reported".
7. **Codex helper symlinks (v29.10).** Codex creates links under `CODEX_HOME/tmp/arg0/<one-directory>/<name>`.
   Capacity scans count those links by their own `lstat` size and do not follow them; links elsewhere in
   `CODEX_HOME` still count as over-limit. This exception matches the fixed path structure, not a cryptographic
   proof that Codex created each link. Scratch and temporary `HOME` scans also count symlinks without following
   them. Counting a link does not account for its target's size or guarantee how the trusted CLI will use it.
8. **Review conclusions can differ for the same content.** The Codex probe received NEEDS WORK and PASS for the
   same source content. Its first run was procedurally invalid on `world_state` checks; its second was valid. The
   differing model conclusions still demonstrate why a verdict cannot establish correctness. VBear validates
   format and procedure; it does not judge review quality.
9. **Failures use worst-case accounting (v29.7).** If a dispatch may have reached the CLI but has no
   `turn_result`, its response count is charged at the sent turn cap and session cost is
   `max(last result total_cost_usd, session_started budget_usd)`. The same rule applies to runtime failures and
   restart recovery. It can consume the session's entire remaining budget in the flow ledger even if actual use
   was lower. Actual cost is unknown, and because budget checks occur at turn end this is not a guaranteed upper
   bound on real use. The flow stops; continuing requires renewed acceptance, with budget adjustment if needed.
   The screen says this is an estimate, not an observed bill.
10. **Deleting a flow is final, and ownership rests on records only the daemon writes.** The data and the flow's
    events are removed, with no trash. Files the executor wrote in its own worktree and the Codex-written
    areas (`CODEX_HOME`, which can hold copies of rollouts) are not VBear's to delete and stay where they are.
    Which directories are a flow's is proven from manifests, start and review records and directory inodes;
    those are plain files under the state directory, which only the daemon writes. A program running as your own
    UID that rewrites them could make VBear delete another flow's data; such programs are outside the threat
    model (see assumptions).

### When a flow cannot be deleted

The console gives the reason next to the flow in 「保存的資料」, and it is the daemon that decides again when you
press delete. There is **no forced delete**: it would bypass the proof that a directory is the flow's, and an
irreversible action is not given a shortcut around its own checks. The reasons and what they ask of you:

| Reason shown | What it means | What to do |
|---|---|---|
| The flow is stopped / has failures you have not released | A stop marker (`holds/<flow>`) exists or a failed turn or review is unreleased. | Press 「繼續」 on the flow page (close a failed session first), then delete. |
| A session or review is running, launching, in `manual_review` or not yet cleaned | Something may still be running or was kept for a person. | Close the session or cancel the review and wait for it to end. For `manual_review`, read `retained_reason` in the item's `manifest.json`, confirm that no process of it is alive (`ps`) and decide yourself. |
| A process group is not proven finished | The daemon could not prove every process of an ended session or review gone. | Check with `ps` that nothing of that launch is alive; VBear does not signal it for you after a restart. |
| A manifest or journal cannot be read, an entry is not shaped like a session or review job, or a record does not agree with another (the message names the entry) | VBear cannot tell which data is this flow's, so it refuses to touch any of it. | Inspect the named files by hand (below). |

The files involved, all under the state directory (`~/.vbear` by default), are
`sessions/<launch-id>/manifest.json` and `journal.jsonl`, `reviews/<job-id>/manifest.json`,
`pipelines/<task-id>/started.json`, `released.json` and `reviews/<round>/job.json`, `holds/<flow-id>` and
`deleting/<flow-id>/`. A session or job belongs to the flow named in its manifest (`pipeline_id`); the task
directory belongs to the flow named in `started.json`; each review's `job.json` must name the same job, commit and
flow as the review's own manifest.

If you have confirmed that nothing of the flow is running and that the data really is the flow's, you can remove
the named directories yourself with ordinary file commands. VBear does not offer to do this: nothing here is
undoable, and only you can tell a damaged flow from someone else's data. Once the damaged entry is gone, the
console's delete works again (a flow with nothing left on disk needs no daemon and only has its record removed).
A deletion that was begun and not finished (`deleting/<flow-id>/` exists) is finished by pressing delete again;
it is not a damaged flow (see [How a deletion ends](#how-a-deletion-ends)).

### How a deletion ends

| Where it stopped | State on disk | The way out |
|---|---|---|
| Refused before anything | nothing changed | fix the reason shown, then delete |
| After the marker, before or between the moves | `deleting/<flow>/` (possibly empty), the rest in place | press delete again: it is planned again from what is left |
| Between the moves and the purge, or during the purge | everything in `deleting/<flow>/` or partly purged | press delete again: the purge needs no record that was already removed |
| After the data is gone, before the record is removed | empty `deleting/<flow>/`, the flow record still there | press delete again: nothing is left to do, the record is removed |
| After the record is removed, before the marker is | empty `deleting/<flow>/` and no flow record | nothing to do by hand: the console asks the daemon to remove the marker when the storage list is read, when a delete names the flow, and when it starts; the daemon does it itself when it starts |
| A marker that is not empty | files in `deleting/<flow>/` | left for a person: the daemon says "刪除標記裡還有東西，交人工處理"; look at them and remove them by hand |
| An approval that arrives after (or during) the deletion | — | refused (409 deleting / 404), and nothing is created; a directory `automation/<flow>/` that holds only the approval lock of a flow that no longer exists is removed when the daemon starts, one that holds a plan is left for a person |

While the marker exists the flow counts as stopped, so nothing new starts in it, and the quota scan counts what is
inside. No step needs a restart of the daemon.

### What you must remember

- **A VBear review PASS does not mean the code has no problems.** It means a reviewer reported PASS and the
  required evidence checks passed. An executor's test statement is not an independently rerun test.
- **Merge and push remain human decisions.** Phase 2 has human gates for the plan, each dispatch, each review,
  merge and push. VBear does not execute merge or push commands. A locally read `refs/remotes/origin/main` is a
  local ref, not proof that the remote has been updated.
- Keep the distinction between a manual Phase 1 record, a valid managed review and your own approval. None is
  interchangeable with proof of correctness. Recheck the reviewed commit and any uncommitted work before deciding
  to merge.

### 繁體中文摘要

第 2 階段在流程裡新增受管 Claude 串流執行者與 Codex 審查工作。VBear 信任你、自己的 daemon／主控台、CLI 執行檔與
供應商及作業系統；不把模型輸出、被審 repo 的內容或審查結論當成可信指令。同 UID 的其他程式、root 與惡意 CLI 供應商
不在防護範圍。沙盒限制的是 Agent 指令，CLI 本身仍須連線到模型供應商，讀取也沒有隔離。Claude 可以在工作目錄內寫檔
與 commit；VBear 不限制執行者工作目錄與暫存區的磁碟用量。

預防措施包括固定啟動參數、沙盒、已知管理設定存在即拒絕、精確文字綁定與冪等派工、寫入時上限，以及失敗後阻止後續動作。
偵測措施包括事件歸屬與順序核對、commit 物件雜湊核對、rollout 逐筆核對、工具允許清單和定期容量監測。偵測後判無效或
停止，不能撤銷已發生的動作。停止流程也不會中斷正在執行的 Claude 回合；程序或清理身分不明時保留資料，交人工處理。

核准畫面完整揭露三項風險：工具集合無法事先證明（Codex 0.160.0 多 agent 關不掉，僅能偵測，`SUBAGENT_ACTIVITY`
使整次審查無效）、上限強度不一（費用可能超額，磁碟最壞會用光剩餘空間）、Team／Enterprise 伺服器管理設定。另有同 UID
替換執行檔競態、報告只核對格式、祖先關係自行回報、`tmp/arg0` 符號連結例外、同內容審查結論不同、失敗回合的最壞計數，
以及刪除流程無法復原。主控台一律以純文字顯示審查輸出；格式檢查不能保證內容正確或沒有誘導指令。沒有結果時，估計可能把整份
session 剩餘額度計入已用，但不代表實際帳單，也不是實際費用的保證上界；要繼續須重新接受。

VBear 審查 PASS 不等於程式沒問題。第 2 階段的計畫、派工、審查、合併與 push 都保留人工關卡；合併與 push 永遠由你決定，
VBear 不執行這些 Git 指令，只顯示指令。

## Phase 3 automatic mode

Phase 3 adds one thing to a flow: after you approve a plan, VBear itself sends the plan to the executor, starts the
reviews and forwards NEEDS WORK comments back, one step after another, and stops at the merge gate. It adds no
capability that Phase 2 did not have: everything it does is what you could do by hand, minus the per-item approval.
That is what the approval has to be informed consent for.

### The approval

- **One preview, one confirmation.** `POST /api/flows/<id>/automation-preview` stores a one-use, five-minute record
  holding the plan text (built from the task card: title, goal, scope, out of scope, deliverables, acceptance
  criteria, evidence; control characters made visible; at most 32 KiB), the thirteen acceptance values, and the text
  versions. The dialog shows the plan in full, the automatic-mode text (what it does by itself, the limits and the
  fixed rule that one failure stops it, the accounts, what it will not do, the risk of forwarding review comments,
  that `.git` is writable, how to stop and what happens after a stop), the three residual risks of Phase 2 in full,
  both account fingerprint prefixes and the nine limits (elapsed time is prefilled at 4 hours). Confirming
  (`POST .../automation`) carries only the preview id.
- **The executor card's instructions open the plan (P34-3).** When the flow's executor role holds a role card (the card
  placed on that place of the task card) and the card has instructions, its own or its position's default, the plan
  text starts with a block that names the card (`職位指示（來自角色卡「…」）：`), followed by the task. The card is read
  as it is at preview time; the dialog says which card, where the text comes from and, if the card changed after it was
  placed, that this is its current content. The block is part of the text the dialog shows, of the hash and size the
  event records and of `plan.txt`, so the daemon's checks cover it like the rest. It travels as the first dispatch, a
  user message, not a system prompt, and the later dispatches that forward review comments do not repeat it. With no card,
  an unreadable or missing card, or no instructions, the plan is exactly the text it was before (the dialog says why
  nothing was added). An already approved flow keeps its own `plan.txt`; editing or deleting the card later changes
  nothing in it. The instructions are words for the AI like any line of the plan: they add no limit to the executor.
- **One event is the plan approval and the risk acceptance.** It is a `risk_acknowledged` event with four more
  fields (`auto_text_version`, `automation_scope`, `plan_sha256`, `plan_bytes`). The plan text is saved
  (`<state>/automation/<flow>/plan.txt`, 0600, atomically, under one cross-process lock together with the event and
  the mode switch), and the event names its hash. A later change of the task card does not change what was approved.
- **The daemon, not the console, has the last word.** It switches the flow to automatic only when the event named by
  the approval id (`auto-<seq>`) exists, is valid now, carries the program's current automatic-mode text version, is
  the newest valid acceptance, `plan.txt` is a plain file whose size and sha256 are the event's, the flow is not
  stopped and has no unreleased failure. Afterwards it re-checks, on every automatic action and not from a cache:
  at `dispatch_prepare` and again at `stream_send` (judged with the approval the dispatch was prepared with) that
  the approval is still the one the mode was switched on with, still the newest valid acceptance and `plan.txt`
  is still its hash; and that the executor's Claude Code version and model (from the session's manifest) and the
  Claude account fingerprint in `~/.claude.json` are the accepted ones. A difference refuses the action, writes
  nothing, and stops the flow with the reason. `review_start` re-checks the approval the same way and, as for a
  manual review, the Codex version, model and the dedicated login's fingerprint. (Manual dispatches re-check the
  executor's account when a session starts, as in Phase 2, not on every dispatch.)
- **A prepared and unsent dispatch is settled before the mode changes.** A manual dispatch is two steps (prepare,
  then send); in between, its approval is a manual preview that automatic mode refuses, and a session accepts one
  unsent dispatch only. So the daemon refuses `pipeline_mode_set` to automatic while a live session of the flow has
  one ("還有一則手動派工已準備但還沒送出…請先送出或處理它，再開啟自動執行"), and the console does not offer the
  approval dialog meanwhile (409 `unsent_dispatch`). It is the same on the way back: an automatic dispatch that was
  prepared and not sent blocks switching to manual (press "continue" to let the runner send it, or close the
  session). The check and `dispatch_prepare` run on the daemon's one thread, so they cannot interleave. The ways
  out for a manual one: "send this dispatch" in the session row (`POST …/dispatch-send {launch_id, dispatch_id}`;
  it sends THAT dispatch with the text the person approved in the preview that made it, the daemon re-reads it and
  checks its hash and judges everything as for any send; nothing new is accepted, and it is refused in automatic
  mode, for a stopped flow, and for any dispatch that is not the session's unsent one), or closing the session
  (the dispatch ends with it and stays counted, at the worst case, as v29.7 says).
- **Changing anything means starting over.** While a flow is automatic, manual dispatches, manual reviews and manual
  acceptances are refused (by the console and by the daemon); to change a limit you stop the flow, switch back to
  manual, accept again and approve again.

### What the runner does and never does

The runner is a thread of the console (one per state directory: `<state>/runner.lock`). Each step is written as an
intent event, then the daemon is asked, then the result is written; a restart re-derives the flow's position from
the events and the daemon, and completes an interrupted step with the same dispatch id or review round, which
the daemon makes idempotent.

It sends the approved plan, waits for the turn, checks the executor's report against VBear's own reading of the
files, starts a review of that commit, forwards NEEDS WORK comments inside a block marked as data (never
truncated: too long is a stop), and stops at the merge gate. It **never** calls `pipeline_release` (continuing after
a stop is yours), never starts an executor session, never runs git, and never writes the quota-protected
directories. It stops the flow (the daemon's hold, then an event saying why) when: a turn is invalid or failed; the
report is missing, `blocked`, `needs_input`, has tests that did not pass, is not the newest, or fails VBear's file
checks (including "a new commit after NEEDS WORK"); a review is invalid, incomplete, in manual review or BLOCKED;
a limit, the acceptance, an account or a version no longer holds; a text is too long or cannot be made again
identically; an event cannot be written; or anything it did not expect happens.

### Stopping, restarting, continuing

- **Stop** (`POST .../hold`, the daemon applies it, then an event): no new dispatch or review; a review in
  progress ends and is counted invalid. The executor's turn already running is not interrupted: it may keep running
  and writing in the work directory until it ends or you close the session.
- **Nothing resumes by itself.** Restarting the console does not continue a stopped flow. Restarting the daemon
  marks every automatic flow stopped before it answers any request. Only your "continue" releases it, and it first
  checks that the acceptance still counts, HEAD is readable, no review is waiting for a person and no limit is
  reached.
- **A turn without a result is charged at its worst case** (Phase 2, v29.7): the session's whole budget. So after
  such a failure continuing needs a higher limit, which is a new acceptance and a new approval of automatic mode.
- **A review ended by a stop** is invalid and a round is never run twice: after you continue, the same commit is
  reviewed again as the next round if HEAD is still it (counted as a review); if HEAD moved, no review is started
  and the flow stops waiting for you.

### What is recorded

Every automatic event is written by the runner with source `automation`; the mode switch and the acceptance by the
console; manual events keep "manual (unverified)". The timeline shows who wrote each. A flow's events are limited
to 500; the approval is refused when the chosen limits could write more than the flow has room for (at most
`3 × dispatches + 4 × reviews + 22`; 182 at the caps).

### Residual risks of automatic mode

11. **Review comments reach the executor unreviewed.** What a review says is influenced by the reviewed
    repository. The data block, control-character visibility, the sandbox without network, the limits and the human
    merge gate reduce this; none of them proves a comment holds no hostile instruction. You accept this
    explicitly (the automatic-mode text, recorded as `auto_text_version`).
12. **A run is unattended.** It spends usage on your two accounts up to the limits you approved, including a turn
    that was stopped but keeps running, and the worst-case rule can use up a whole session budget on one failure.
13. **The plan and the mode are files.** `plan.txt`, `modes/<flow>` and the events are plain files of your user.
    The daemon verifies the plan's hash and the approval on every automatic action, but a program running as your
    own UID is outside the threat model (see assumptions).
14. **Verified end to end with real models three times; that shows it works as designed, not that it is right for
    your project.** The loop, the interruptions at every action boundary, the restarts and the stops are tested
    against synthetic Claude and Codex programs in the test suite. Three runs with the real models (a full loop to
    the merge gate, a stop while a review runs, a console restart while a review runs; Claude Code 2.1.296 as the
    executor and Codex 0.160.0 as the reviewer, on a small toy project) are recorded in
    [`docs/evidence/s3-real-e2e-2026-10-12.md`](evidence/s3-real-e2e-2026-10-12.md).

## Which skills AGY reads

VBear judges whether Antigravity (AGY) reads a skill from files alone. It never runs `agy` or `gemini`. The index
(`vbear/scan/agy.py`) reads three places, and what it finds only marks a skill (`read_by`) or adds a source of tool `agy`:

- a project's `.agents/skills` (already scanned; the skills directly under it get `read_by: ["agy"]` and stay Codex records),
- `~/.gemini/antigravity-cli/skills` (a new source; scanned only if it exists),
- every folder named by a `path` in `~/.gemini/config/skills.json` (`{"entries":[{"path":"..."}]}`, optionally with
  `include_only`). A folder VBear already scans (such as `~/.codex/skills`) is marked, not scanned again; any other
  folder becomes a new `agy` source. Only the skills directly under a folder count, or exactly the ones `include_only`
  lists (a listed path may be nested). Skills in a folder you turned off in the settings stay unscanned.

What is read, and what is not:

- **One config file.** `~/.gemini/config/skills.json` is the only file under `~/.gemini` that is opened, apart from the
  `SKILL.md` files of the skills folders above. It is opened by its real path, which must be a regular file inside the
  home folder; a symlink that leaves the home folder is not followed. It is read up to 64 KB and at most 50 entries
  (200 `include_only` items per entry). Login, credential, settings and every other file there are never opened or listed.
- **Unusable input is skipped and shown, never guessed.** Bad JSON, a wrong shape, an oversized file, a `path` that is
  not a string, a malformed `include_only` (the whole entry is skipped, so a restriction never turns into "everything"),
  a missing folder: each is listed under the config file in the settings page's source list and in the scan problems,
  and the file counts as absent where it cannot be used.
- **Paths.** Only an absolute path or a path starting with `~/`, strictly below the home folder, with no `..`, whose
  real path is also strictly below the home folder. The home folder itself, `~/.ssh`, `~/.aws` and `~/.gnupg` are
  refused. A symlinked skill folder inside a listed folder is not followed, and a `SKILL.md` that resolves outside its
  folder is not read.
- **Content.** Each skill is read like any other: only its `SKILL.md` (size-capped, secrets masked), and no file it
  mentions is opened or run.
- **Not covered.** AGY's built-in and plugin skills (under `~/.gemini/antigravity-cli/plugins`) are not scanned, and
  neither is the older `.agent/skills` spelling. The shared store `~/.agents/skills` is not read by AGY unless
  `skills.json` lists it.
- **A judgement, not a launch.** `read_by` says where a skill sits and what AGY's own config lists. It does not prove
  AGY loads the skill (VBear cannot see a per-skill switch), and a role card with such a skill is still only a record.

## Meetings (tool-less headless speech)

A meeting is a written discussion between role cards, held with the same kind of call as a skill translation: Claude Code
started with no tools at all. It is **a new outbound data path through your authenticated local Claude Code** that
uses your quota or money. Only you start one, from `POST /api/meetings/preview` and then `POST /api/meetings` with the
preview id; nothing starts one by itself, and a decision is never carried out by VBear.

- **What is sent, and to whom.** For each speaker: the card's instructions (its own text, else the position's default),
  VBear's fixed meeting rules, the topic, and, inside `BEGIN/END_UNTRUSTED_JSON_STRING`, your supplement and the fields of
  the task card (title, goal, scope, out of scope, deliverables, acceptance criteria, evidence, status; never its folder,
  its id or anything else). The PM also gets a progress summary VBear writes from the task card and its flows' records,
  the accountant what the meeting has cost so far (summed by VBear with `decimal.Decimal`). The CEO gets the same and
  every speaker's answer, after the answers passed the format check. Everything is redacted for secret-shaped text and
  sent through Claude Code to Anthropic under your account; VBear sends nothing anywhere else. A card of another tool
  (Codex, AGY) does not speak itself: Claude speaks for it with that position's instructions, and the record and the
  preview mark it as `proxy`.
- **The preview is the consent.** The only program a preview runs is `claude --version`, to learn which version is installed. It is held in memory, used once, and gone after five minutes. It shows every text that
  would be sent in full, the model each call uses, the number of calls, what is reserved, the day's spending and whether
  this Claude Code version has passed the no-tool check. A speaker's text carries a SHA-256 the worker checks before the call
  is made; the CEO's and the accountant's texts depend on what happened before them, so the preview shows their shape and
  the record keeps the hash of what was actually sent. A card that changed after the preview, or a Claude Code version
  that is not the one previewed, voids it. Without a passed check for the exact version the preview is not startable and
  says so (先檢查). That check is `POST /api/meetings/verify` (empty body, asked in the page first): the probe of
  `POST /api/translations/verify` and its record in `translation-boundaries.json`, but always of Claude Code, because a
  meeting speaks through nothing else. The translations' check follows the translation engine instead, and with Codex
  chosen there it refuses without running anything; the meeting's check does not read or change that setting.
- **The call.** The argv is `translations.translation_argv` with only `--model`, `--max-budget-usd` and the schema changed,
  and the output a stream with `--verbose` (the shape the check verified): `-p --safe-mode --tools "" --strict-mcp-config
  --mcp-config '{"mcpServers":{}}' --no-session-persistence`; then `--effort low` or `--effort medium`: a speaker at
  `meeting_speed.speaker_effort` (low by default), the CEO at `chair_effort` (medium by default). Nothing else is accepted,
  on write or in the argv, so a meeting never asks for high effort. The check that recorded the version's pass ran without
  `--effort`; what keeps the boundary is that every call checks its own init event (below), so a version that gave a tool
  with `--effort` would be stopped on its first call and its pass revoked. A version that does not know `--effort` fails
  the call (`cli_failed`), counted at the worst case, and keeps its pass. The runner is the translations' (`headless_cli`): an empty
  scratch directory, the prompt on stdin, no credential added, a 120-second deadline, a 256 KiB output limit and one
  process group that is killed and confirmed gone. **Every call checks its own init event as the line arrives:** exactly
  one, with `tools == ["StructuredOutput"]` and `mcp_servers == []`, and no `tool_use` of anything else. Anything else
  kills the group on the spot, the output is not used, and the version's pass is revoked until it is checked again. A
  stream that does not parse, has no result, or has a negative or non-numeric cost is a failure, not a guess. The empty
  directory is not read isolation, and HOME is still needed for the login, as for translations.
- **Time.** A meeting runs at most `meeting_speed.max_minutes` (15 by default, 5 to 30) from when it starts, and a retry
  on a clock of its own. The speakers' calls may run until three minutes before the end, which is kept for the CEO; no
  call runs longer than its own deadline. A speaker with less than a minute left is skipped (`time_up`, shown as
  「時間到沒發言」, and the CEO is told so); a call the clock cuts short is a failure (`time_up`) that costs what it reported
  or its worst case; a CEO's turn with less than a minute left fails without being sent and can be retried. The clock is
  kept in memory while the meeting runs (`GET /api/meetings/<id>` shows it); a restart ends the run as before.
  `meeting_speed` is a top-level key of `config.json`, not inside `meeting_limits` (v0.9.0 drops an unknown key there
  when it saves).
- **What the checks cannot prove.** That an opinion is true, that a legal source is real (VBear checks that a source is
  written, not that it exists: a risk of the legal manager with none is kept with 「查無出處，需人工複核」 and holds the
  meeting for you), or that the accountant used a program. A model's text is shown as text and never run.
- **Money.** Limits are in `config.json` as `meeting_limits` (US$0.20 per call, 1.50 per meeting, 3.00 per day by default;
  capped at 1, 10 and 50; validated on write, and an unusable stored value falls back to the default). The preview reserves
  calls × the per-call limit and refuses a meeting that does not fit the meeting's or the day's room; each call is checked
  again before it is made and is skipped (`budget`) if it would pass a limit. A call costs what Claude Code reported in
  `total_cost_usd`, or the per-call limit when it reported nothing, and the record says which (`cost_source`). The figures
  are the CLI's estimate and a subscription plan is not billed that way. The day is the local date; at 80% of the day's
  limit the ledger shows yellow, at 100% no meeting starts and no retry is offered.
- **Failure, retry, restart.** A failed call is never repeated by itself. A person can retry a failed or interrupted turn
  through its own preview (twice at most; the third failure is `blocked`), and only while the cards and the task card are the
  ones the meeting started from; retrying a speaker asks the CEO again, and costs are kept over all attempts. When the
  console restarts, the turn that was running is `interrupted` and costs the per-call limit, queued turns are
  interrupted without cost, and nothing resumes. One meeting runs at a time (`meeting-worker.lock`); a process group that
  cannot be confirmed gone writes `meeting-worker.blocked` and blocks later meetings until a person removes it.
- **When it goes to you.** `meeting_rules.py` is a fixed, visible table (R1–R8): something you ticked when making the
  meeting; a decision action of a type that publishes, deploys, pays, deletes, signs or changes a price (or one the table
  does not list); a keyword or an amount (any amount by default) in the topic, the supplement or the decision; a high risk or
  a legal source of 「查無出處」; the legal manager opposing; a turn that failed, was blocked, skipped or interrupted; or a
  speaker or the CEO asking for you. A model's fields are only read, and only to raise the verdict. The verdict is derived on
  every read, and the verdict stored when the decision was made can only keep a meeting major. The keyword list is Chinese
  and English only and matches words, so a paraphrase can be missed (for example a wire transfer is not a keyword); that is
  what the "涉及" boxes are for. Approval or a veto is a record in the console (「主控台記錄（未驗證身分）」): anyone who can
  use the console can press it.
- **Where it is kept.** One file per meeting, `<state>/meetings/m-<12 hex>.json` (0600, folder 0700, 256 KiB, at most 200
  meetings), written through the guarded store: a file that does not parse, is not a meeting this module could have written,
  is a link or is too big blocks that meeting and no other. A meeting stores the topic, the supplement, the participants,
  each turn's state, evidence and output, and the chairman's record; it never stores a prompt, only its hash. Deleting a
  meeting removes that file only. A meeting writes no task card, no flow, no `plan.txt` and nothing in a project folder.
- **API.** `GET /api/meetings`, `/api/meetings/ledger`, `/api/meetings/<id>` (reads run nothing); `POST /api/meetings/preview`,
  `/api/meetings`, `/api/meetings/verify`, `/api/meetings/<id>/retry-preview`, `/retry`, `/cancel`, `/chairman`;
  `DELETE /api/meetings/<id>`. They sit behind
  the same Host, token, Origin and `X-VBear` checks as every other route; bodies are strict (an unknown field, a bool or NaN
  where a number is wanted, or an over-long text is a 400).

## Data handling

- No telemetry, analytics, crash reporting or update checks. The only HTTP client in the code talks to
  the local console itself.
- State lives in `~/.vbear/`. The directory has mode `0700` and its files `0600`, written atomically.
- If `config.json` is corrupt, it is never overwritten. It is backed up, scanning is turned off, and a
  warning is shown.

## Skill translations (version-verified Claude boundary)

`translations.py` is separate from managed launches, dispatches and the runtime. Only an explicitly requested
single/batch translation or a rescan after engine-bound automatic consent can enqueue work. Automatic mode
is off by default, caps each rescan at 20 entries, skips unchanged fresh entries, and cools failed fingerprints
for five minutes. Changing engines turns automatic mode off unless the new engine is explicitly accepted;
turning it off cancels current work. Reads of `/api/translations` use the already loaded index, never scan or
start a CLI. POST and DELETE use the existing Host, token, Origin and X-VBear protections.

Only name and author-provenance description/when_to_use/inputs/outputs/dependencies are redacted and hashed;
derived fields are null. No file body, path, provenance detail, stderr or account information goes into the
prompt/cache/UI. This is a **new outbound data path through the user's authenticated local CLI** and may
consume the user's quota or money. Claude's `--max-budget-usd 0.05` is a requested budget checked by the CLI,
not a guaranteed invoice cap; Codex cost and tokens are unknown. VBear adds no API key or HTTP client.

Claude uses `claude-haiku-5-5`, safe mode, an empty explicit tools list and strict empty MCP config,
nonpersistent output, and a fixed `--json-schema` requiring exactly four string fields. The effective
boundary is **only StructuredOutput (returns structured results), no MCP**, verified per CLI version.
`POST /api/translations/verify`, behind the existing Host/token/Origin/X-VBear protections, runs an
explicit quota-consuming probe after UI confirmation. It uses the translation argv with only
`--output-format stream-json` and `--verbose` changed, a fixed harmless prompt, and the same empty cwd,
environment, budget, deadline, output cap and process-group cleanup. It requires exactly one system/init
with `tools == ["StructuredOutput"]` and `mcp_servers == []`; absent, malformed or different declarations
fail closed. It checks `--version` before and after the probe and stores version -> passing timestamp in
`translation-boundaries.json` via locked, atomic/0600 jsonstore. Reverification first revokes an old pass.
Before each translation, resolution probes the current executable's version; only a matching stored
pass enables it. This is version compatibility evidence, not binary authentication or proof against a
malicious replacement executable. No generic launch verifier or environment bypass grants a pass.
GET reads never run a probe or CLI; the UI does not claim that a stored pass proves the current version.
Verification shares the translation worker lock. Unconfirmed process extinction blocks later work.
Codex remains `boundary_unverified` unconditionally: read-only/tool-disable flags cannot prove its boundary.
The confirmation shown before a translation is one sentence (your own account, usually under one US cent per card) with the
whole disclosure above kept word for word behind 「詳細」; the figure is a plain-language estimate, and the requested
US$0.05 budget, its non-guarantee, the 60-second limit and "tokens unknown" are unchanged. The progress bar folds
away (5 seconds after success, 10 seconds after a failure into a dot that reopens the reason, a close button on
each, a closed job remembered in the browser's local storage by id): this is display only and does not change what is
sent or when. A failure is shown on a skill card only when this page started that very job, because a job does not name its skill.
All implementation tests use fake CLIs only; this change does not prepopulate any real-version pass.
The fake QA provider is injected in the QA Python process only.

Claude translation accepts only a JSON object with `type=result`, `is_error=false`, and an object in
`structured_output`, then applies the existing field/length validation. A missing structured result is
an error; text in `result` and Markdown fences are never extracted. The prompt requests Traditional Chinese
(Taiwan usage, no simplified characters). A small set of unambiguously simplified forms rejects output
with `not_traditional`; shared characters are excluded. This heuristic does not prove full linguistic accuracy.

A worker uses an empty temporary cwd, stdin for the untrusted JSON-string-delimited payload, fixed argv,
no shell, one process group, a 60-second deadline, 32 KiB input and 64 KiB stdout limits. Stderr is discarded.
On every exit it kills/reaps the group; unconfirmed group extinction blocks further work for manual review.
HOME is needed for authenticated CLI use; empty cwd alone is **not read isolation**. No credential is
copied. Prompt-injection instructions and strict output validation cannot prove semantic fidelity. Missing
author when/needs/description values are forced to 「原文未提供」 after validation; other machine translations
remain unverified content, labelled separately from author facts and rendered only as text.

The version-1 cache envelope (`translations.json`) is atomic/0600, locked across processes with jsonstore,
limited to 2 MiB before read/write, and quarantines invalid JSON/schema with a blocking marker. It never
silently replaces a damaged cache. Summaries are capped at 150 characters, description at 2000. Cache errors
use fixed classifications, not filesystem/CLI excerpts. Source hash mismatch keeps old text visibly stale;
an in-flight old result cannot appear fresh against a new index. Orphan deletion rechecks the current loaded
index and removes only cache entries, never skill files. Jobs are in-memory: console restart loses progress,
retains accepted translations and does not resume outbound work automatically.

Role-name translations (the profession menu of the card wizard) reuse this boundary but keep their own cache,
`role-translations.json` (same envelope, 2 MiB limit, 0600 and quarantine rules), so the skill cache's format and
data are untouched. Only the role's `name` and, when its origin is `author`, its `description` are sent, redacted the
same way; no path, tool, kind, model, capabilities, suitable tasks or limits. The result is `name_zh` (30 characters)
and `what` (50 characters, forced to 「原文未提供」 when there is no author description), checked for Traditional
characters. It uses the same provider resolution (a verified Claude Code version only), the same worker lock (a skill
job and a role job cannot run together) and the same error codes. It is started only by the user, from
`POST /api/role-translations/batch` after a confirmation in the page; `translation_auto` never starts it. A
translation whose source name or description changed is stale and is not shown.
VBear's own two main agents (`cli-claude`, `cli-codex`, kind `cli`) are not listed for translation and their names
are not sent: their Chinese names are VBear's, and the author wrote no description for them. An older translation of
one stays in `role-translations.json` unused; nothing reads it.
