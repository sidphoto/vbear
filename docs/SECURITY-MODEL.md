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
  (where Claude Code's own installer puts it), in that order, after your own `PATH`. For Grok and MCODE (full mode only)
  it also looks in their own install folders, `~/.grok/bin` and `~/.minimax-code/bin`, after `.local/bin`.
  These folders are writable by you (and, for Homebrew, by your admin group), the same trust as your `PATH`. VBear scans no other folder, reads no
  shell startup file and starts no login shell. Finding the file changes none of the checks above: the version, the
  verified list and the translation boundary are decided afterwards, exactly as before. The Codex review does not use
  `.local/bin`; it runs the pinned Codex build only.
- **Verifying on this Mac.** 「驗證這個版本」 runs `vbear/boundary_check.py` headless and interactive against
  the binary a launch would use. The version is recorded as verified only if both runs pass every check; a
  refusal only counts if it is the sandbox's (`EPERM`/`EACCES`, or the proxy's 403). The record file is
  owner-only. Any program running as you could edit it, as it could edit anything else you own.
- **Fail closed** otherwise: the launch is refused if the sandbox is unavailable (`failIfUnavailable`), or if the
  profile, work directory, Claude Code binary or config changed since the preview.
- **Antigravity (AGY) has no safe launch.** In safe mode a role card whose tool is `agy` is a record for building teams: `launch_blockers`
  refuses it (`tool_not_launchable`, "安全模式不會啟動 AGY，要出發請選完整模式"), so no preview is
  prepared, no manifest is written and the loadout shows no armor and no tool list. Which skills AGY reads is judged
  from files only (see "Which skills AGY reads"), and even a skill AGY reads is never reported as one that loads: a
  skill chosen on an AGY card is a collection. The automatic review is unchanged: it is the Codex that
  VBear starts, and an AGY card on a review place is only the record of a manual review.
- **Grok and MCODE have no safe launch either (v0.12).** Both are full mode only, the same as AGY: in safe mode their
  cards are refused with `tool_not_launchable` ("目前只能用完整模式"), and the card says "這個 AI 工具目前只能用完整模式". They are
  separate model families (`xai`, `minimax`), so a review by one of them counts for another family's work. MCODE is a
  hidden tool: it is offered, and may be started, only while the server config key `show_mcode` is true (default
  false, written through `/api/config`). Turning it off deletes no card; a card that already names `mcode` is kept,
  shown and explained, but cannot be created, switched to, duplicated or started (`tool_hidden`) until the switch is on.
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
- **A full launch needs the person's "I understand" as well as the confirmation (ADR 0002).** The pass says "這個員工可以動你電腦上的任何檔案" and the confirm button stays off until the person ticks 我了解. The server does not rely on that: a confirmation of a full-mode preview without `accept_full_mode: true` is refused with 409 `full_mode_not_acknowledged` and a plain sentence, before the preview is used up (the same preview can be confirmed once the box is ticked), and `user_confirmed` is still required. A safe launch does not take the field.
- **The command is built on the server and is a list, never a shell string.** `claude [--model X] [--append-system-prompt
  <text>]`, `codex [-m X]`, `agy [--model X]`, `grok [-m X]`, `mcode [-m X]`, with the tool found as the first `claude`,
  `codex`, `agy`, `grok` or `mcode` on the search
  path VBear uses for the CLIs (its own `PATH`, Homebrew and `~/.local/bin`), by its absolute path. The pass shows the
  command and the path. The daemon accepts it only through its own `open_full` operation, which takes nothing but the
  tool name, that list, the folder and the terminal size, and refuses any list `agent_sessions.full_argv` could not have
  built (another flag, a model that looks like an option, a program with another name). The environment is the plain one
  every terminal gets (`PATH`, `TERM`, `LANG`, `HOME`, your user name); no credential is added, so the tool uses the login
  it already has.
- **The start-up page's install and login terminals are a separate, narrower door (v0.12).** `POST /api/setup/terminals` takes
  a tool id, an action (`install` or `login`), for MCODE's login a region (`global` or `cn`), and the terminal size; any
  other field is refused. The line that gets typed is looked up in `vbear/ai_tools.py` (the vendor's own install or login
  line, source notes in `docs/evidence/ai-tool-install-and-login-lines.md`), never taken from the request, and the daemon's
  `open_setup` operation is given only those same names: it opens the person's login shell in their home folder with the
  plain environment and types the one line into it, so the person sees it and the shell runs it as if they had typed it.
  Nothing downloaded is read or run by VBear itself. `/api/native/sessions` (any list) and `/api/native/terminals` (a plain
  login shell) are unchanged and are not used for this. The writing routes need the same `X-VBear` header as the others.
- **The status of an AI tool is read without reading any login.** `vbear/ai_tool_status.py` finds each tool on the search
  path, runs `<tool> --version` and, for Claude Code and Codex only, their own status command; for the status command only the
  exit code is used (0 is logged in) and its output goes to nowhere (not captured, not stored, not served). For AGY, Grok and
  MCODE the person's "I have logged in" mark is the only evidence; it is kept in `setup_marks.json` as the tool id and a time.
  No tool's own login folder is opened or listed by VBear. A look is kept in memory for 30 seconds (the page asks every 5
  seconds); the person's recheck, a mark, a terminal and a try make the next look fresh. A kept look is the row, never output.
- **「試一下」 sends one fixed sentence and keeps none of the answer (v0.12).** `POST /api/setup/tools/<id>/try` takes the tool
  in the path and `{"confirmed": true}` (the page sends it only after it showed "about under US$0.01" and the person pressed
  again); no sentence, flag, folder or environment comes from the request. `vbear/setup_try.py` starts the tool headless through
  `headless_cli.run`: a new empty scratch folder as its working directory (removed afterwards), a new process group that is
  killed however the call ends (an unconfirmed group writes `setup-try.blocked` and no further try starts), the plain
  environment of that runner (PATH, HOME, USER, LOGNAME, LANG, TMPDIR), 60 seconds, at most 1 MiB read, one try at a time.
  Claude Code gets `--safe-mode --setting-sources "" --tools "" --strict-mcp-config`, a small budget and no session kept;
  Codex runs without the person's config and rules (so no MCP servers), read-only, shell off; MCODE with permission off and one step; Grok
  with one turn and web search, memory, plan and subagents off. AGY has no flag for fewer tools that was checked, so it gets
  the sentence only (it may use tools; the sentence asks for none). The answer is read to see whether the tool answered and
  dropped: not stored, logged or passed on; neither is anything it prints about the account. The page gets success, not logged
  in (any failed exit), timeout, not found or odd answer, in plain words. The cost goes into `setup-try.json` (tool, times,
  cap, cost: nothing else) and counts toward the same day as the meetings, the staffing meetings and the chats: Claude Code's
  reported cost, else US$0.01; a try that started a program is booked even when it fails. When the day cannot take another
  US$0.01, or the record cannot be read, nothing starts.
- **Only Claude Code takes the instructions on the command line.** The card's instructions (its own text, else the
  position's default) go in as a single `--append-system-prompt` argument: control, format and separator characters other
  than a line break or tab are removed, it is cut to 2000 characters, and a text that starts with `-` gets a sentence in
  front, so it can never be read as a flag. The pass shows the whole text that will be carried. VBear did not verify that
  Claude Code receives it, or does what it says; it is words for the AI, as before. Codex, AGY, Grok and MCODE have no such option, so
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
- **`launch_mode` chooses between two launches, and only the exact word `full` chooses the full one.** The wizard starts a
  new card on `safe` where its tool has a safe mode (today Claude Code) and on `full` where the tool has only full mode
  (the catalog lists both sets), and the person can switch; the server never writes the field itself, and a card without the key
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
  stored: a snapshot with tool `agy` (and likewise `grok`, family `xai`, and `mcode`, family `minimax`) must sit on a
  role of the tool's own family, on input and in the stored shape; the other tools are accepted with any family, as before. Placing a card on a task card's team writes only `flows.json`; it starts,
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
  again before it is made and is skipped (`budget`) if it would pass a limit. When the chats' part of the day cannot be
  established, no meeting previews or starts and the next call is skipped (`spend_unknown`; see the chats' money
  below). A call costs what Claude Code reported in `total_cost_usd`, or the per-call limit when it reported nothing,
  and the record says which (`cost_source`). The figures
  are the CLI's estimate and a subscription plan is not billed that way. The day is the local date, and it counts the
  staffing meetings too (below); at 80% of the day's limit the ledger shows yellow, at 100% no meeting starts and no retry
  is offered.
- **Failure, retry, restart.** A failed call is never repeated by itself. A person can retry a failed or interrupted turn
  through its own preview (twice at most; the third failure is `blocked`), and only while the cards and the task card are the
  ones the meeting started from; retrying a speaker asks the CEO again, and costs are kept over all attempts. When the
  console restarts, the turn that was running is `interrupted` and costs the per-call limit, queued turns are
  interrupted without cost, and nothing resumes. One meeting runs at a time, a staffing meeting included
  (`meeting-worker.lock`); a process group that cannot be confirmed gone writes `meeting-worker.blocked` and blocks later
  meetings until a person removes it.
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

## Staffing meetings (組隊會議)

A staffing meeting asks the CEO card to staff one task card, after the staff have spoken. It is held by the meetings'
engine, so what the section above says of the call, its check, the time, the worker and a restart holds here too; this
section says what differs. Like a meeting it is **a new outbound data path through your authenticated local Claude Code**
that uses your quota or money. Only you start one, from `POST /api/staffing/preview` and then `POST /api/staffing` with
the preview id, and nothing in it is carried out by VBear.

- **Who speaks.** VBear suggests the speakers from a fixed table (the PM always; the full-stack engineer, the legal
  manager, the accountant, the social media manager and the art director when the task card's categories, derived from its
  words by the skills' keyword table, or an amount in it call for them), one enabled card per position, each with the
  reason; you change any of it. `GET /api/staffing/suggest?task_id=` only reads. Then each speaker says once, alone,
  without seeing the others, then the CEO writes a staffing proposal from what they said; when no speaker has an answer
  the CEO is not asked. A disabled card cannot speak, but it is on the list, marked, and may be proposed: enabling it is
  your step.
- **What is sent.** As for a meeting: the card's instructions, VBear's fixed rules, and inside
  `BEGIN/END_UNTRUSTED_JSON_STRING`, redacted, the same fields of the task card (never its folder or its id), your note,
  and a list of the role cards and of the skills a card can use. Every card and skill is on the list under an alias (`C1`,
  `S1`, ...), never its id; the record keeps the ids under the aliases. A skill's line is its fresh Chinese summary when
  there is one (a translation made from the skill as it is now), else its author's own text, marked as such. A speaker
  gets a short view of the list; the CEO the whole of it and every speaker's answer (cut to 3 KiB each, saying so). The
  CEO's list is made at the preview, at the most bytes (in whole KiB) that keep the CEO's text within its 64 KiB limit
  whatever the speakers write (each answer counted at the most the CEO can be given of it); a shorter list says how many
  cards and skills it left out, and a task card too long even for 1 KiB of list is refused at the preview (`too_large`).
  A start on a list that is not the one previewed (a card, a skill, a summary or the task card's words changed), or a
  retry on one that is not the one the record started from, is refused.
- **The call and the worker.** It is the meetings' call: the same argv and `--effort` (`meeting_speed`), the init event
  checked on every call and a version's pass revoked on a tool, the same clock with its last three minutes kept for the
  CEO (whose own call may run up to three minutes). It shares the meetings' one worker (`meeting-worker.lock`) and its
  `meeting-worker.blocked` marker, so a meeting and a staffing meeting run never at the same time: the one started second
  is refused (`busy`).
- **Money.** A speaker's call costs at most `meeting_limits.per_call_usd`, the CEO's at most
  `staffing_limits.proposal_call_usd` (US$0.50 by default, capped at 1), and a whole staffing record at most
  `staffing_limits.total_usd` (US$2.00 by default, capped at 10). `staffing_limits` is a top-level key of `config.json`,
  validated on write (the CEO's call ≤ the record ≤ the day); an unusable stored value falls back to the default. The
  preview reserves every speaker's call and the CEO's, and refuses what does not fit the record's room or what is left of
  the day; every call is checked again before it is made and skipped (`budget`) if it would pass a limit. A call that
  reported no cost, or one a stopped console left running, costs the worst case of its own kind of turn. It counts in
  the same day as the meetings: `meeting_limits.daily_usd` covers both, and the chats with a role card too, and the
  ledger says so (`includes: ["meetings", "staffing", "chats"]`).
- **Failure, retry, restart.** As for a meeting: nothing is repeated by itself; a person retries a failed or interrupted
  turn through its own preview (twice at most, then `blocked`), and retrying a speaker asks the CEO again; a restart
  interrupts what was running and resumes nothing.
- **What it is not.** No rule of the meetings (R1–R8) is run, and a staffing meeting is never held for you; a high risk a
  speaker wrote is shown as a reminder. The proposal is a record: VBear creates no card, inserts no skill and puts no one
  on a team; each of those is a step you take on its own page. The chairman's answer (adopt or dismiss, with a note) is a
  record of the console (「主控台記錄（未驗證身分）」) and does nothing by itself. An adoption may carry what was adopted:
  each place (one of the four, or a staff position) with the id of the card put there, the CEO's new card it was made
  from and the skills adopted for it, at most ten rows of 40 skills. VBear checks its shape and that a new card is one of
  the proposal's; it does not check that the card exists or that any step was done.
- **Adopting.** The page's adoption list (照草稿採用) sends nothing an endpoint VBear already had does not take: switching
  a card on (`POST /api/agent-profiles/<id>` with `enabled`), the card wizard's own save, a card's skills
  (`equipped_skill_ids`, after a dialog that shows the list before and after), a task card's team and the chairman's
  record. Each is a button the person presses, in a fixed order the page keeps (the server does not know the order). The
  team is put on the task card's board in this page's memory only: nothing reaches flows.json until the person presses
  建立隊伍 or 儲存隊伍 there. The draft and the cards made in the wizard are kept in this browser
  (`staffing.edit.<id>`, `staffing.made.<id>`) and sent nowhere.
- **Where it is kept.** One file per staffing meeting, `<state>/staffing/s-<12 hex>.json` (0600, folder 0700, 256 KiB, at
  most 200), through the guarded store as a meeting is: a damaged file blocks that record and no other. Not in
  `meetings/`, which v0.9.0 would quarantine. It stores the task card's id, your note, the participants, who VBear
  suggested and why, the ids and revisions under the aliases, the limits, each turn and the chairman's record; never a
  prompt, only its hash. A staffing meeting writes nothing else but the worker's lock.
- **API.** `GET /api/staffing[?task_id=]`, `/api/staffing/suggest?task_id=`, `/api/staffing/<id>` (reads run nothing);
  `POST /api/staffing/preview`, `/api/staffing`, `/api/staffing/<id>/retry-preview`, `/retry`, `/cancel`, `/chairman`;
  `DELETE /api/staffing/<id>`. The no-tool check is the meetings' (`POST /api/meetings/verify`). They sit behind the same
  Host, token, Origin and `X-VBear` checks as every other route, and their bodies are as strict.

## Chats with a role card

A chat lets you talk with one role card through your authenticated local Claude Code, which can run tools for it:
**a new outbound data path that uses your quota or money and can change files**. The console's `#/chat` page and
`/api/chats` reach the runtime's chat operations; no Claude Code version is chat-verified out of the box, so no chat
process starts until a version passes the chat check.

- **Who may open a chat.** Only an enabled role card whose tool is Claude Code or Codex (since v0.13 the second one
  runs on its own engine, see "Chats with a Codex role card"). The API checks this itself and answers a disabled card
  (`card_disabled`) or a card of another tool (`card_tool_unsupported`) with its reason; the page's button being shut is a
  courtesy, not the check. Opening a chat costs nothing; a message does.
- **Whose instructions go in.** Only the instructions written on the card, as one `--append-system-prompt` argument.
  The position's default text is not sent, and a card without instructions of its own sends none; the chat's record
  says whether any went in. Claude Code keeps a session's system prompt when it is resumed
  (`--system-prompt-snapshot` is on by default), so an edited card may not change a conversation that has begun.
  How it treats an edited one on resume has been checked on a real machine (Claude Code 2.1.319, v0.17.0): a resumed session
  kept the appended text it started with and did not take a new one given on the command line; a new chat did take it. The chat check still records the first as an observation and
  does not pass or fail on it.
- **A second paragraph: the person's memory (v0.17, ADR 0008).** After the card's own instructions (or alone, when the card
  has none) the same `--append-system-prompt` argument carries one fixed paragraph the daemon builds from the `memory` field
  of `chat_send`: VBear's own explanation, then the person's lines as one JSON string between `BEGIN_VBEAR_MEMORY_JSON` and
  `END_VBEAR_MEMORY_JSON`. The console sends the field when the role card takes memory along (a Claude Code card does by default; a Codex card only after the
  person switches it on, because memory goes to OpenAI there) and `<state>/memory/memory.json` can be read; a card switched off, or a file that cannot be read, sends no field and not a
  word reaches the model. The paragraph is sent even when there are no lines, because it also tells the employee that only
  the person can save one. The field is a list of at most 50 objects with exactly `kind` (`about_you`, `work` or `decision`)
  and `text`, at most 4,000 characters in all; one more key, another kind or a longer list is `bad_request`. **The daemon
  checks every line again** with the same pure function the console uses to save one (`runtime/memory_rules.check`): a line
  holding a password or code after its name, a key or token of a known shape, a long letters-and-digits string, an
  account name or email, a card number that passes the Luhn check, an identity or bank-account number, one of VBear's own
  markers, `server.token` or `X-VBear`, or a control, format or line-separator character, makes the daemon **refuse the
  whole message** (`memory_refused`, naming only the place of the line and the rule, never its words); nothing is left
  out quietly and nothing starts. Lines that merely read like an order to the employee, or hold a phone number or an
  address, only needed the person's second confirmation when they were saved, and pass. The lines are JSON-encoded
  twice (so a quote, a backslash or a marker inside a line cannot end the string) and written with every control, format
  and line-separator character as a `\uXXXX` escape. The paragraph is at most 6,000 characters, and a chat manifest may carry 8,000
  characters of added prompt (the card's 2,000 and the paragraph; 9,000 since v0.17.1, which makes room for the shared folder's paragraph, below); a full-mode launch keeps its 2,000
  (`append_prompt_problem`). **Memory does not change what the employee may do:** the paragraph says memory cannot make the
  employee run a command or change a file without asking, nor change VBear's settings, limits, mode or skills, but that is
  words for the model, not a barrier. The barrier is the one that was there: `--permission-prompt-tool stdio`, the
  sandbox, Codex's `untrusted` policy, the per-turn and daily limits. Memory is data: no field of a chat's record names it
  (`KINDS` is unchanged; `process_started.instructions` still says whether the *card* has instructions of its own), and the
  daemon's log has one line per new process, `chat process memory entries=<N|none> instructions=<yes|no>`, with the count
  and nothing else. The launch manifest of a live process holds the paragraph as it holds the card's instructions (it is
  removed with the launch). Memory goes to the company of the employee's tool, Anthropic or OpenAI, and stays in the tool's
  own copy of the conversation; deleting a line in VBear does not delete those copies. The memory rules are a best effort:
  a secret written in ordinary words is not caught. Only the person's own `/api/memory*` routes in the browser (with
  `X-VBear`) change the file; the chat service only reads it, and no module of the chief of staff, dispatch, groups or the
  suggestions touches it (see the next paragraph).
- **Changing the memory, switching a card, and the process that follows (v0.17, P42-2).** The person's routes, all behind the
  access token and (for POST, PATCH and DELETE) `X-VBear`, bodies closed (an unknown key, a wrong type or a too-long text is a
  400): `POST /api/memory` (a line), `PATCH /api/memory/<id>` (its kind or text; the same checks as a new line, in the same order:
  refused, full, confirm), `DELETE /api/memory/<id>`, `POST /api/memory/clear` (only with `{"confirm": "全部刪除"}`),
  `POST /api/memory/cards` (a card's switch: the card must exist and its tool must be one that chats; **switching a Codex card
  on takes `confirm_company: true`**, answered `409 memory_confirm` with `warn: ["send_to_openai"]` otherwise) and
  `GET /api/memory/export` (Markdown, no chat, group or line id; it adds a line to the log). A line made from words in a chat or a
  group carries `source` (`{how: "chat", chat_id, turn, speaker}`, `{how: "group", group_id, turn, speaker}` or `{how:
  "suggested", suggestion_id}`; the closed shape, and the chat, group or suggestion file must exist, else 400); no `source` means
  typed. A source is a label the page shows, not a permission: it changes nothing about what is sent. `log.jsonl` has the action,
  the line's id, kind and how it came (or a card's id, or a count) and never a word of a line. **Who can write is kept by
  `tests/test_autonomy_guard.py`:** `memory*.py` (and `runtime/memory_rules.py`) are scanned like the chief, dispatch and group
  modules (no `config.json` write, no launch code, no skills, no `answer`, no role card made or changed), and a second rule fails
  the build when any module other than `server.py` and `memory.py` reaches `add`, `edit`, `delete`, `clear`, `set_card`,
  `export` or `store` of the memory module. **A changed memory or changed card instructions reach a new chat only
  (P42-6).** The first real-machine run found that Claude Code 2.1.319 does not apply a new `--append-system-prompt` when it resumes
  a session: it keeps the one the session was started with, so replacing the process (what v0.17.0 first did when the hash of
  the card's instructions and the memory paragraph differed) cost more and changed nothing. That code is gone: the daemon no longer
  closes a live process or answers `restarting` for a changed prompt, and a resumed process still gets the current paragraph on its
  command line (a later Claude Code may use it). When a chat's **new** session is started the daemon keeps, in
  `<state>/chat-prompt/<chat id>.json` (0600, a flat file of VBear's own, **not a field of the chat record**, gone with the chat), the
  fingerprint of its system prompt and whether the memory paragraph was in it: no word of the memory or the instructions. `GET
  /api/chats/<id>` compares it with the current memory and the card's instructions and answers `memory: {on, count, readable,
  changed, started_with_memory}` (the state now; counts and yes/no, no line), and the chat page then says the chat still has what it
  started with and offers a new chat; if the card is switched off now, that what was already sent cannot be taken back. A chat
  with no such file (made before v0.17.0, or the file does not read) says nothing. The paragraph is therefore **not** a thing a
  person can take back from a chat: switching a card off, or deleting a line, stops it from reaching new chats and nothing else
  (the tools keep their copy of a conversation in any case). Codex is treated the same, because whether `thread/resume` applies new
  developer instructions was not verified. **The tools' own memory stays off,
  with a second lock:** a Claude Code chat process gets `CLAUDE_CODE_DISABLE_AUTO_MEMORY=1` and
  `CLAUDE_CODE_DISABLE_CLAUDE_MDS=1` in its environment, set in `daemon_chat` only (the chat check starts its processes through
  the same daemon code, so it carries them; terminals in full mode, meetings and the other checks do not), on top of
  `--safe-mode`, `--setting-sources ""` and `--strict-mcp-config`, which stay (tests pin the argv). The evidence is read from the
  installed program's text, not from a run: `docs/evidence/claude-code-2.1.319-memory.md`.
- **The shared folder (v0.17.1, ADR 0009).** `<state>/shared` is one folder that every employee the person has switched on may read
  and write, so that one employee can hand a file to another. It changes the launch boundary in four places, each pinned by tests,
  and in none of them does it remove a question: every Bash command and every Edit or Write there is still a card, `--permission-prompt-tool stdio`,
  `permissions.ask: ["Bash"]`, `autoAllowBashIfSandboxed: false`, `allowUnsandboxedCommands: false` and the `system/init` check are
  unchanged, no `--add-dir` is used, and `permissions.additionalDirectories` stays `[]`.
  - **Where it is and who names it.** Only VBear computes the path (`shared_rules.shared_path`: the real path of the state folder
    plus `shared`). A browser or an RPC caller never sends one: the console sends `shared: true` or nothing, and the daemon's
    `chat_send` takes that field as exactly `true` (false or any other type is 400 `bad_request`). A Claude Code chat and a Codex chat both take it (P43-2); the daemon refuses it with `shared_unverified` for a version of the AI tool that has not passed the chat check with the shared folder (the next bullets and "The chat check").
    The daemon checks the folder when a message arrives (`folder_problem`) and refuses `shared_unsafe` unless it is a real folder
    of this user, mode exactly 0700, with no link on the way (`realpath` equals the path), not the home folder or above it, and not one
    of the state folder's own folders. A folder that is not right is **never mended, moved or removed**: the page says so and the
    person looks at it in Finder. A folder that is not there yet is made (0700) when the person switches an employee on, presses
    「在 Finder 打開」 or a message needs it.
  - **The switches.** `<state>/shared-meta/settings.json` (`{"v": 1, "cards_on": [...]}`, 0600, at most 200 ids; every employee is off
    until the person switches it on) and `log.jsonl` (0600, append-only, 1 MiB then a new file keeping one old one: `card_on`, `card_off`
    or `revealed`, the card's id and `page`, `group` or `dispatch`; **never a file name**). They live in `shared-meta`, **not** in the
    shared folder, and the sandbox does not let an employee write there, so nothing an employee puts in the shared folder can decide
    a permission. `set_card` is called only from the `/api/shared*` routes of `vbear/server.py` (`tests/test_autonomy_guard.py`
    scans `shared*.py` and `runtime/shared*.py` with the rules of the chief of staff, dispatch, groups and memory, and fails when
    any other module reaches `set_card` or the store). The chat service only reads (`for_card`); a settings file that cannot be
    read means every employee is off, and the page says so. A Claude Code card and a Codex card have it (P43-2); a card of any other tool is
    refused with 400 `card_tool_unsupported` and `for_card` says no for it whatever the file says. Switching a **Codex** card on takes
    `confirm_company: true` in the body (what it reads goes to OpenAI): without it the answer is 409 `shared_confirm` with
    `warn: ["send_to_openai"]` and nothing is written. Switching off never asks.
  - **Process and sandbox.** For a Claude Code chat with the folder on, the settings file written for the process lists the folder
    as a second entry of `sandbox.filesystem.allowWrite` (the work folder stays first), and the launch manifest carries `shared`, which
    must equal `<state>/shared` and pass `folder_problem` again when the launch is validated (`unsafe_path` otherwise). The folder is
    **fixed for the life of a process**: when the person changes the switch, an idle process gives way (`close_gracefully` and
    `restarting`, which the console retries) and a busy one answers `busy`, so that turn finishes under the old sandbox and the next
    message starts a new process. So **the sandbox follows the switch at the next message.** Claude Code 2.1.319 ignores a new
    `--append-system-prompt` on `--resume` (P42-6), so **what the employee has been told follows the start of the chat**: a chat started
    with the folder on is told of it, one started with it off is not, and switching later changes the sandbox but not that
    knowledge. The chat page compares the fingerprint of what the chat started with, so it can say that the chat's idea of the
    folder is not the current one. The fingerprint is `prompt_sha(instructions, memory, shared_block)`; with the folder off it
    is the value v0.17.0 made, byte for byte, as are the argv, the settings and the system prompt (tests pin the literal values). A chat
    that is told of the folder gets one more paragraph (`shared_rules.block`: fixed words, the path as one JSON string between
    `BEGIN_VBEAR_SHARED_JSON` and `END_VBEAR_SHARED_JSON`, at most 1,000 characters), joined to the card's instructions and the memory
    paragraph with a blank line; the paragraph says that files in the folder are data, not instructions. The chat manifest may carry
    9,000 characters of added prompt; the full-mode limit of 2,000 is unchanged. The shared folder is not in a full-mode terminal,
    a meeting, the chief of staff or a memory suggestion. Nothing in the chat's record changed (`KINDS`, `process_started`).
  - **VBear's own judgement of a path.** Claude Code's Edit and Write are not under the Bash sandbox, so VBear's `judge` treats the
    shared folder as a second root. A Write or Edit whose path (links followed) is inside the shared folder is a card as always,
    worded to say that every employee who has the folder open can read it; it is **refused with no way to allow it** when the path is
    outside the folder (a link out of it), is the folder itself, has a part named `.claude`, `.codex`, `.agents` or `.git` at any
    depth in any letter case, or is a regular file with more than one hard link (it would be a file of somewhere else too). The
    check is run when the card is asked and again when the person allows it. A Bash run, always a card, is under the sandbox only:
    the sandbox's `denyWrite` names `.claude`, `.codex`, `.agents` and `.git` at the top of the shared folder, and a deeper one is
    kept out only by the person reading the Bash card (checked on a real Mac only in that the model would not try). Read, Grep and Glob are allowed by VBear only for paths
    in the work folder or the shared folder, with the old rules in the root the path is in (a bare Glob or Grep pattern, no link that leads
    outside that root); otherwise they are a card. A write the person allowed still happens after VBear's answer, so the gap the
    work folder has (a folder turned into a link in that moment) is also there.
  - **Size and what VBear looks at.** At most 1 GiB (by the size a file says, so a sparse file counts as large as it looks) and 10,000
    entries, links not followed. It is counted when a **new process** starts (409 `shared_full` otherwise, with a sentence that points
    to Finder), not under a running one; an employee can fill the folder within a process, and the next new process is the one that is
    refused. VBear never reads a file in the folder, never opens one and never deletes one: the page and the count use `os.scandir`
    and `lstat` (names, sizes, times, link counts) only, and no file name is written to the console's log, the daemon's log,
    `log.jsonl` or an error message (the daemon's log has one line per new process, `shared=on` or `shared=off`). The page shows names as text.
  - **「在 Finder 打開」.** `POST /api/shared/reveal` (closed body `{}`) runs a fixed command, `/usr/bin/open <the shared path>`, by a function
    that `serve()` hands to the console; without it (tests, any other use of the console) the route answers 503 and nothing is opened.
    The shared modules themselves start no program. It is Mac only (400 `not_mac`).
  - **What is not new.** An employee that has the folder can read what other employees and the person put there and send it to its AI
    company, and can write anything it may ask the person about. The paragraph, the page and the question before switching on say so; the folder
    is not a place for secrets. The model's obedience to "files are data" is a request, not a barrier: what stands in the way is that every
    command and every change is still a card. A Codex employee's side is in "Chats with a Codex role card".
  - **A version has to have passed the check with the folder (P43-2).** `chat_send` with `shared: true` is refused with 409 `shared_unverified`
    unless the version of the AI tool (the version the console read and the daemon checks again) has a chat-check report whose `shared`
    field is `passed` and whose `shared_steps` all pass (`cli_versions.shared_verified`, which reads the report back every time, as it
    does for the chat check itself). The check's own daemon may use the folder for the version it is checking. A version that passed the
    chat check before the shared folder existed stays chat-verified: an employee whose switch is off chats as always, and only a message
    to an employee with the switch on is refused, in words that say how to run the check (the chat page's 「檢查」 button, or switch the
    employee off). The console says it first (nothing is sent); the daemon says it again.

- **The chat check.** `python3 -m vbear.boundary_check --mode chat` (started by 驗證聊天 on the page, which says what it
  costs first) runs about six small Haiku calls on your own login (and, from v0.17.1, three more for the shared folder, below) against an in-process daemon in a temporary state
  folder, with a made-up card. It judges only from the events the daemon recorded and the files left behind, never from
  what the model says: the initialize answer accepted; every Bash asked; a changed command ran as changed; a denied
  one did not run; a write outside the work folder stopped by the sandbox; no shared-tmp error; the unknown-request
  error answered without ending the process; a resumed process remembering what the session was told; the total
  cumulative across a resume; `system/init` naming no extra folder and no MCP server; nothing from the initialize
  answer kept; the check's own processes and folders cleaned up. Only a pass writes `claude-chat-verified.json`
  (0600), and a version counts only while the report it names (mode `chat`, passed, the same version, owned by you)
  reads back. The few cents it spends are on your Claude account and are not in the day's ledger.
  **The shared folder part (P43-2).** After the six turns, and only when they all passed, a second chat of the same temporary daemon is sent
  with `shared: true` and the check's own `<state>/shared` (inside the temporary state folder; nothing of yours) and three more messages:
  a Write into the folder must be a card and the file must be there once allowed; a Bash `echo ok > <file>` there must be a card and the
  file must be there once allowed (the sandbox's `allowWrite` took the folder); a Write through a link inside the folder that leads outside
  must be refused by VBear with no card and no file outside. The result is the report's `shared` (`passed` or `failed`) and `shared_steps`,
  and it does **not** change `passed` or the record: a failure leaves the version chat-verified and "not checked with the shared folder". The
  report names no file of the shared folder. Not yet seen on a real machine at the time of writing: whether the real Claude Code writes through
  the second `allowWrite` entry; that is what this part is for, on the person's own Mac (about US$0.03 more).
- **Administrator policy.** For 2.1.318 and 2.1.319 (the same list) the places checked are the directory `/Library/Application Support/ClaudeCode`,
  the managed preferences for `com.anthropic.claudecode`, `~/.claude/remote-settings.json` and
  `~/.claude/policy-limits.json`. Any of them present, or not establishable, means no chat starts. Nothing says what
  `policy-limits.json` can change, so it is refused whole (evidence: `docs/evidence/claude-code-2.1.318-chat.md`). A chat runs the newest version in Claude Code's `versions` folder that passed the chat
  check, else the newest with chat constants, else PATH's `claude`; having constants is never enough to chat.
- **The console is not a second authority.** The server adds no rule of its own about a tool call: it relays the
  card, its token and your answer to the runtime and the runtime checks again when you allow. A live view
  (`GET /api/chats/<id>/stream`, server-sent events) needs the same `X-VBear` header as a write, and at most four are
  open at once. A refusal reaches the page as a code and a sentence; nothing the initialize answer carries is in any
  reply or log.

- **The process.** Each chat process is a managed launch with engine `claude-chat` under `sessions/`, read and checked
  like the others (an exact manifest schema, settings that must be the approved shape, the CLI's identity, the work
  folder), and cleaned up the same way. A terminal launch refuses a chat manifest. The argv is fixed:
  `-p --input-format stream-json --output-format stream-json --verbose --include-partial-messages --permission-prompts
  host --permission-prompt-tool stdio --permission-mode default --safe-mode --settings <launch>/settings.json
  --setting-sources "" --strict-mcp-config --tools Bash,Read,Edit,Write,Grep,Glob --max-budget-usd <x> --model <id>`, then `--session-id`
  the first time and `--resume` after that. The settings are the managed sandbox (writes only to the card's work folder
  and the launch's scratch, no network, no unsandboxed commands, Bash never allowed by the sandbox alone), plus
  `permissions.ask: ["Bash"]`, `permissions.additionalDirectories: []` and the pinned endpoint.
- **`--setting-sources ""`: no settings of yours are read.** Recorded with the real 2.1.318: with only `--settings`, `system/init`
  still names the extra folders of your own Claude user settings, and `permissions.additionalDirectories: []` in
  `--settings` does not remove them (VBear stops such a chat, as below, and the chat check fails). An empty list of
  sources loads no user, project or local settings at all, so VBear's `--settings` is the only one; your login still
  works and a turn still succeeds. The empty string is chosen over `project,local` on purpose: the employee may write in
  its own work folder, `.claude/` of it included, and a settings file it wrote there would be read by the next process.
  `additionalDirectories: []` and the check of `system/init` stay as the second layer. A chat does not see your own
  Claude settings (permission rules, extra folders, hooks, models): that is the price.
- **The Python that runs VBear.** A chat process is managed through `os.waitid`, which reached macOS in Python 3.13
  (macOS's own `/usr/bin/python3` is 3.9 and has none). A daemon or a check on such a Python starts nothing: `chat_send`
  answers `unsupported_python`, and `python3 -m vbear.boundary_check --mode chat` says so and exits before it makes a
  folder or a process. If an unexpected error still happens while a chat process is managed, the process is ended
  (after the identity check: its group is killed, the leader seen to exit, the group proven empty, the leader reaped)
  and its launch cleaned up; only when that cannot be shown is it left, unsignalled, with a person.
- **The work folder.** Each role card has one folder, `<state>/chat-work/<first 24 hex digits of the SHA-256 of its
  id>/` (0700). A hash is used because the file system ignores case, so two ids that differ only in case still get two
  folders. Deleting a chat keeps the folder.
- **Who decides a tool call.** Claude Code asks VBear on stdin about every tool call it does not allow by itself,
  and VBear answers. With VBear's settings it may still allow by itself a read in its own folder. VBear sees such a
  read only afterwards, by its tool result, and stops the chat when it would not have allowed that read under the rule
  below. By then the read has happened.
  - Bash, Edit and Write always get a card, and you allow, refuse, or change the command, content or new text and then
    allow.
  - An Edit or Write whose path, after links are followed, is outside the work folder, or has a part named `.claude` (since
    v0.17.1 at any depth below the work folder and in any letter case, because the file system of a Mac does not tell
    `.claude` from `.Claude`), is refused with no way to allow it. With the shared folder on, the second root has its own rule
    (below). This is checked when the card is asked and again when you allow it, with what you
    changed. A path whose folder became a link out of the work folder while the card waited is refused then, and the
    record says so.
  - The second check narrows the gap between the check and the write; it does not close it. Claude Code writes the
    file itself after VBear's answer, so a folder changed in that moment is not seen. Edit and Write are Claude Code's
    own tools and do not run under the Bash sandbox, so the sandbox does not catch such a write either. A link in the
    work folder can come from a command you allowed or from another program on the Mac.
  - VBear allows Read, Grep and Glob by itself only when all three hold: every path, after links are followed, is
    inside the work folder; a Glob or Grep file pattern is a bare name, with no `/`, `..` or `~`; and the folder holds no
    link that leads outside it. Otherwise the read gets a card.
  - Any other tool, and any other kind of control request, is refused.
  - "Allow every time" does not exist.
- **What stops a chat.** VBear reads only `claude_code_version` and `current_permission_mode` from the initialize
  answer. The account, commands, models and extra folders it also carries are never stored, logged or passed on. A chat
  is stopped in any of these cases:
  - the initialize answer is not this version's, or not the `default` mode;
  - `system/init` names another session, version, mode, tool list or folder, any MCP server, or any extra folder
    (only how many is recorded);
  - Claude Code shows a tool result for a call VBear did not allow.

  An event of an unknown kind is recorded by its field names only and not shown.
- **What is kept.** `<state>/chats/<chat_id>/` (0700) holds `chat.json` (written once) and `events.jsonl` (0600,
  append-only, fixed fields per kind, fsync'd, 8 MiB). Text is masked with the scanner's redaction before it is written
  and cut to a fixed length. For a card's input this happens at every level, by key name and value. stderr is not kept.
  A file that does not read back cleanly is never written to again.
- **Money.** Each turn has a cap. The cap is the per-turn limit (`chat_limits.per_turn_usd`, US$0.50 by
  default, at most 5) or what is left of the day's limit (`meeting_limits.daily_usd`), whichever is smaller,
  rounded down to the cent. A new process gets that cap as its `--max-budget-usd`. A live process takes the next
  message only when what it may still spend under its own cap is no more than the new cap; that headroom is then
  the turn's cap. Otherwise the process is closed and a new one starts. Accounting:
  - a turn costs the difference between the cumulative `total_cost_usd` and the last one, kept exactly;
  - when no usable total comes back (the turn was stopped, timed out or cut off by a violation, the process
    ended, or a stopped daemon left it running), the turn costs its cap;
  - a turn whose message never reached the CLI costs nothing;
  - while a turn runs, it counts at its cap.

  Chats count toward the same day's limit as the meetings and staffing meetings. On a red lamp, or with less than
  a cent left, no message is sent. Deleting a chat keeps what its last three days cost in `<state>/chat-spend/`.

  The chats' part of the day is counted in full or not at all, never as zero or as only what reads. It is unknown
  (`spend_unknown`) when any of these holds:
  - a chat's events do not read whole: damaged, cut short, missing or unsafe;
  - a deleted chat's spend record does not read whole;
  - the chats cannot be listed.

  While it is unknown, no chat message is sent. No meeting or staffing meeting previews or starts, the meetings'
  ledger gives no figure, and a meeting already running skips its next call. There is one exception. A record whose
  files were all written before today, by their times (the later of the modification and change times; the change
  time cannot be set back), counts nothing today, because nothing in it can be of today. A chat whose record does not
  read whole is not deleted through VBear, so what it spent is not lost; it needs a manual check of the state
  folder. A deleted chat's spend record that is gone counts nothing. VBear removes one only after its turns are more
  than three days old. A damaged meeting or staffing record still adds nothing to the day, as before (P35).
- **Who may answer a card.** Only the runtime socket's own user reaches the daemon. A card is answered through
  `chat_answer` with its one-use token. A second answer, a wrong token, an expired card (5 minutes) or a card of
  an ended turn is refused. Expiry is checked by the answer itself, not only by the daemon's timer, and an expired
  card is answered with a refusal.
- **Cards are shown whole.** All the waiting cards must fit one `chat_events` reply whole, because a card cut short
  could make you allow something you were not shown. VBear refuses a card, and records why, in each of these cases:
  - the card, as shown, is over 12 KiB;
  - eight cards are already waiting;
  - with the waiting cards it would pass 30 KiB.

  The reply being written is shown only as far as what is left of the live view allows (40 KiB in all), and is
  marked as cut.
- **Limits and time.** There is one chat process per role card and at most three in all, and each counts toward
  the daemon's session limit. A process that has not answered the initialize request within 30 seconds is ended.
  A turn over 10 minutes is ended at its cap. An idle process closes after 10 minutes by having its stdin closed,
  and the next message resumes the session in a new process. A process is ended like a stream session: TERM, then
  KILL, signals sent only to its own verified process group, and kept for manual review when that cannot be
  proven. A chat whose earlier process is under manual review takes no new message. At daemon start, a turn a
  previous daemon left open is closed at its cap.

## Chats with a Codex role card (engine `codex-chat`, v0.13)

A chat with a role card whose AI tool is Codex (ADR 0005 gives the reasons). It is the same kind of new outbound data
path as a Claude chat, on **your ChatGPT plan**, and it can change files in the card's work folder. The console's
`#/chat` page and `/api/chats*` reach it through the same runtime operations as a Claude chat, with an engine named.
No Codex version is chat-verified out of the box: no process starts until one passes `--mode codex-chat`.

- **The engine follows the card's tool and never changes.** `POST /api/chats` reads the role card's tool (`claude` is
  `claude-chat`, `codex` is `codex-chat`; any other tool is refused with `card_tool_unsupported`) and the chat keeps that
  engine for good. Every message checks the card again: a card whose tool is now the other one cannot go on in the old
  chat (`card_tool_changed`, nothing starts), a disabled card or a tool that cannot chat is refused as before. The daemon
  refuses a message that names an engine other than the chat's. The browser sends no binary, folder, command or model of
  its own: the console reads the pinned Codex and the card's model, and the daemon checks the lot again.
- **The support answer is the console's courtesy, not the check.** `GET /api/chat-support` carries Claude Code's keys and
  a `codex` object (`state`: not installed, unverified, administrator policy, chat folder refused, version unreadable,
  not logged in, ready; no path and no command output). A message to a Codex chat while the state is not ready is
  refused with the state's own sentence before the daemon is asked; the daemon refuses it again by itself.
  `POST /api/chat-support/verify {"engine": "codex"}` starts the check of the newest installed Codex in a child process
  (`vbear/codex_verify.py`) unless the administrator policy is in the way, and counts a pass only when
  `codex-chat-verified.json` lists the version afterwards, as for Claude Code. Any other `engine` value is a bad request.
- **The login is the person's, on a folder of VBear's.** The start-up page's 「讓聊天用的 Codex 登入」 types one fixed line
  into a terminal (`CODEX_HOME=<chat folder> codex login -c cli_auth_credentials_store=file`, taken from the tool list;
  the browser sends a tool and an action only). VBear never reads or copies the person's own `~/.codex`, and never sees
  the login.
- **The process.** One `codex app-server --listen stdio://` per role card, at most three chats in all with the Claude
  ones, each a managed launch with engine `codex-chat` under `sessions/` (an exact manifest schema, a settings file that
  must equal what the version's table in `codex_chat_protocol.VERSIONS` says, the CLI's identity, the card's work
  folder, the chat folder in the manifest). A terminal launch refuses it. The argv is that table and nothing else: `-c`
  settings (file credentials store, web search off, no update check, no notify, no history, no bundled skills, no
  project docs, no network and no `/tmp` in the sandbox, `project_root_markers=[]`, and the work folder's trust set to
  `untrusted`, see the next bullet but one) and `--disable` for twenty features (apps, plugins, hooks,
  browser, computer use, memories, multi-agent, worktrees and the rest). The binary is the pinned one under
  `~/.codex/packages/standalone/releases/`, never one found on `PATH`.
- **The environment is exactly seven variables:** `PATH`, `USER`, `LOGNAME`, `LANG`, `CODEX_HOME`
  (`<state>/codex-chat-home`), `HOME` (an empty folder in the launch's scratch) and
  `CODEX_INTERNAL_APP_SERVER_REMOTE_CONTROL_DISABLED=1`. `codex app-server` has no way to ignore the person's own
  `~/.codex`, so the chat logs in to a Codex home of its own; the person's settings, `AGENTS.md`, rules and MCP servers
  are not read. Before a process starts: the chat folder is the person's own 0700 plain folder with no link on its path
  and none of `config.toml`, `rules/`, `AGENTS.md` (VBear writes none of them: finding one means another program did),
  within 512 MiB; `codex login status` (exit code only) says logged in; the work folder holds no `.codex`; no
  administrator policy; the version is on the `codex-chat-verified.json` list. Anything else, and the chat is refused
  with the reason.
- **A home folder that is a git repository.** Found by hand on a real Mac, not in the first recording: when the person's
  home folder (`~`) is a git repository (`~/.git`), Codex 0.163.0 takes `~` for the project root, because it looks for
  `.git` upward from the work folder. A `CODEX_HOME` other than `~/.codex` means the person's own `~/.codex` is no longer
  skipped as the settings folder, so it was read as a *project layer* of `~`; and a `thread/start` with a writable sandbox
  made Codex write `[projects."~"] trust_level = "trusted"` into the chat folder's `config.toml`, which enabled that layer:
  the person's own MCP servers started (five in the probe), their skills (86) and their exec policy rules were loaded. The
  settings and the sandbox in the `thread/start` answer were as asked, and `mcpServerStatus/list` without a `threadId`
  answers for what the process loaded at its start, before any trust existed, so it said none. VBear now sends two more
  `-c` settings, **both of them**: `project_root_markers=[]` (the work folder is the project root; `~` and `~/.codex` are
  not searched) and `projects={"<the work folder>"={trust_level="untrusted"}}` (the folder has a trust setting, so Codex
  writes none, and project-level settings stay off). The second is an **inline table** because a dotted key
  (`projects."<path>".trust_level`) is cut at the dots of a path such as `~/.vbear`, and then trust is written anyway; the
  path is written as a TOML string (quote and backslash escaped), and a path with a control character or that is not
  absolute refuses the launch (`invalid_workdir`). Both are in the settings file and compared on every load. The MCP
  check now asks `mcpServerStatus/list` **with the thread's `threadId`**, after `thread/start` has answered, and any
  server in the answer stops the chat as before. A `config.toml` in the chat folder is still refused, never deleted; the
  refusal now says it may be an older build's trust entry and where to move it. The version check asserts that no
  `config.toml` exists right after `thread/start` and that every process was started with both settings
  (`project_settings_sent` in the report; no path in it). In the probe with both settings, in a home folder that is a
  git repository: no MCP server, no start-up notice, no skill, no `config.toml`.
- **Memory (v0.17), off until the person switches the card on.** The same paragraph as for a Claude chat (see "Chats with a role card": the `memory` field, the daemon's
  second check of every line, `memory_refused`) goes in `developerInstructions` of `thread/start` and `thread/resume`, after the
  card's own instructions (32 KiB is the limit there). The employee is told that memory cannot make it skip a question; the
  sandbox and `untrusted` approval policy are what keep that true, and memory is sent to OpenAI. Codex's own `--disable
  memories`, `project_doc_max_bytes=0` and `history.persistence="none"` stay as they were (tests pin all three in the argv). A
  Codex chat is treated as a Claude Code chat is (P42-6): changed memory or card instructions, or the card switched off, reach a new
  chat only, and the page says so. Switching a Codex card on asks the person to confirm that memory goes
  to OpenAI (`confirm_company`). This path has been tested against the fake app-server only; it has not been run on a real machine.
- **The shared folder (v0.17.1, ADR 0009, P43-2), off until the person switches the card on, with a confirmation.** The same folder, switches,
  paragraph and size rules as for a Claude chat (see "Chats with a role card"); only the path VBear computes (`<state>/shared`) is ever used,
  and a Codex card needs `confirm_company: true` to be switched on because what it reads goes to OpenAI (409 `shared_confirm` otherwise).
  With the folder on: (a) the argument list gets **one more** `-c`, `sandbox_workspace_write.writable_roots=["<path>"]` (the path as a JSON string,
  which is a valid TOML basic string; a path with a control character, or one that is not the computed one, refuses the launch), after
  the project trust setting; with the folder off the argument list, the settings file and every `turn/start` are byte for byte the ones
  of v0.17.0, as the tests pin; (b) `turn/start` says `writableRoots: [<path>]` and the launch's settings file and manifest carry the path
  (`shared`, compared with `<state>/shared` on every load); (c) the tracker expects the sandbox in the `thread/start`, `thread/resume` and
  `thread/settings/updated` answers **field for field**, `writableRoots` included: it must be exactly that one path. A Codex that
  answers an empty list (it did not take the setting), one more, or the path twice is a violation: the turn costs its cap and the process
  ends, as for any other sandbox that is not what was asked. **Whether the real Codex 0.163.0 puts the configured root in the `thread/start`
  answer's `sandbox.writableRoots` is waiting for a real machine** (the design is fail-closed on exactly this: if it does not, the chat
  stops with a violation and the version cannot pass the shared part of the check); the app-server here is the fake, which answers both ways.
  (d) `developerInstructions` gets the same fixed paragraph after the card's instructions and the memory, the process is reused only if
  its folder is the current one (otherwise `close_gracefully` and `restarting`), and a message to a card with the folder on is refused with
  `shared_unverified` unless this Codex version passed the shared part of `--mode codex-chat`.
  A file change is judged with the folder as a second root: inside it (links followed) it is a card, as in the work folder; **declined
  with no card** when a path leaves it through a link, is the folder itself, has a part named `.git`, `.codex`, `.agents` or `.claude` at any depth in any
  letter case, or is an existing file with more than one hard link. What the 0.163.0 sandbox itself does with the root was probed
  without a model (`docs/evidence/codex-0.163.0-shared.md`): the root is writable, a write through a link to the outside and into the
  three protected folders is refused, and **creating links and deleting files inside the root are allowed** (so a link in the folder is
  a residual risk, and VBear follows links in its own judgement). A shell command is a card as always; the warning that an allowed command
  may run outside the sandbox is unchanged.
- **Every command and file change is asked.** `thread/start` and every `turn/start` say `approvalPolicy: "untrusted"`,
  reviewer `user`, and ask for the legacy `workspace-write` sandbox (the work folder is its only writable place, no `/tmp`, network off;
  but see the residual risk (7): a command the person allows may run outside it). A
  command is a card with its whole text; a request that needs the network, or is not a command, is declined. A file
  change is judged first: a path outside the work folder (links followed), or under `.codex`, `.agents` or `.git` at any
  depth, is declined with no card; the rest is a card with each file's path, kind and diff. An allow is `accept` and is
  judged again when it is given. VBear never writes `acceptForSession`, an execpolicy or network amendment or `cancel`
  to a request (`decision_line` cannot write them), so there is no "allow from now on". Cards are VBear's, as for Claude:
  one-use token, five minutes, at most eight, 12 KiB each and 30 KiB together, shown whole or declined.
- **A changed command is not "allow, changed".** Codex has no such answer. VBear declines the request and sends
  `turn/steer` telling Codex to run exactly the person's text instead; Codex then asks again, with the changed text, in
  a card of its own that the person must allow. When the steer is refused (the turn is over) the text is sent as the
  next message, a new turn, within the day's limit. The text sent is in the chat's record (`card_edit_sent`).
- **What stops a chat.** Anything in the answers that says VBear's settings are not in force: a policy other than
  `untrusted`, a reviewer other than the person, a sandbox that is not field for field the one asked for, an instruction
  file loaded, any MCP server, remote control not disabled, another thread, a changed setting, an item kind outside
  command, file change, message, reasoning and plan, or a command or file change completed without VBear's yes. The
  turn costs its cap and the process is ended. An item that started and never completed (a command the sandbox
  stopped) is not a violation. A server request VBear does not know is answered with an error and noted by its method
  name only.
- **Money.** Codex reports tokens, not money. A turn costs its tokens at VBear's own rate (US$1.00 per million, rounded
  up to the cent, at least US$0.01; an accounting rule, not a price), counted from the thread's total, so a resumed
  thread's repeated first total is not counted twice. Each report is compared with the turn's cap (the per-turn limit or
  what is left of the day, whichever is less) and the turn is interrupted when it is reached. A turn cut off any other
  way costs its cap, or its estimate when that is more; a turn that never reached Codex costs nothing. Two reports can
  be a model call apart, so a turn can pass its cap by about one call. The estimate is not a bill.
- **What is kept.** Replies, commands, file changes, tokens and the plan's use as numbers (percent, window length,
  reset time, whether a limit was reached). Never kept or logged: the Codex home and user agent from `initialize`, the
  plan's kind, credits, installation id, host name, MCP server names, instruction file paths. Codex keeps its own copy
  of a conversation in `codex-chat-home/sessions`; deleting a chat does not delete it.
- **The version check.** `python3 -m vbear.boundary_check --mode codex-chat` (Python 3.13 or newer, as for `--mode chat`;
  `--codex` names the binary, else the newest the vendor's installer left) runs one real chat through this section's code
  in a temporary state folder inside the state folder (the chat records, work folder and the day's ledger are its own),
  with seven messages: text; `ls -a` (a command that only reads must still make a card) and a denied `rm` (the file is
  still there); a command changed in its card (`turn/steer` must be accepted: a refused one fails the check at the `edit`
  step and VBear's fallback is stopped, not used) which then runs as changed; a file change with its diff; a write
  outside the work folder (declined with no card, no file there, or the check fails; and an allowed shell write there, which is only noted, see the residual risk (7)); `turn/interrupt`;
  and a new process with `thread/resume` that must remember the first message. A second part, run only when all of that passed
  (`shared_steps` in the report, `shared: passed|failed`, which does not change `passed`), opens a second chat of the same
  temporary daemon with the check's own temporary shared folder and sends three more messages: a file made there with `apply_patch`
  (a card with its diff, the file there once allowed); a shell write there (a card, the file there once allowed; the sandbox is judged
  by the `thread/start` answer, not by this write, because of the residual risk (7)); an `apply_patch` through a link that leads outside
  (declined by VBear with no card, no file outside). It adds up to about eight more model calls under its own limit of US$0.15 by VBear's
  count and deletes its own thread. It also checks the answers of
  `thread/start` and `mcpServerStatus/list`, the token total across the resume, that `thread/delete` removes the
  thread the check made, that the idle process ends by itself within twenty seconds of its stdin closing, and that no
  process, folder or file in the person's chat folder is left, and that none of the account details above reached the
  records, the log or the report. The check never allows more than it asked for: it answers a card with an allow only
  for the one command or file it asked Codex to make. The only thing it takes from the person is the login: its
  temporary daemon runs Codex with the person's real `<state>/codex-chat-home` as `CODEX_HOME` (the daemon's
  `codex_chat_home`, set only by the check; the launch record still names the folder under the check's own state, and a
  daemon of the console never sets it). It costs about fourteen model calls on the person's ChatGPT plan, no more than
  US$0.30 by VBear's own counting (each step has a cap, and the check's day limit is US$0.30), and is not added to the
  day's ledger. A pass writes `codex-chat-verified.json` and a 0600 report that `cli_versions` reads back every time.
- **The page.** A card of a Codex chat shows the command whole, its folder and what Codex says it does, or each file's
  path, what is done to it and its diff, as text in `<pre>` (never as markup). A command card says, above its buttons,
  「允許後，這個指令可能在沙盒外執行：能改到工作資料夾以外的檔案，也能連網。只允許你看得懂、確定沒問題的指令。」 (a
  file card and a Claude card do not). Its buttons are 「允許這一次」, 「拒絕」 and
  「改內容再問」, whose note says VBear declines the original and Codex asks again, so the person must allow once more;
  nothing on the page says the change was applied. There is no "allow from now on". A reply's cost reads 「估計 US$x」 with
  the token count and says it is not a bill; the plan's use is one line from the last `plan_usage` record (percent per
  window as Codex reports it, and the reset time only when a limit was reached). The head of the chat says reading is not
  limited. The deletion confirmation says Codex's own copy stays in `codex-chat-home` (`sessions`) and is not deleted.
- **Residual risks.** (1) *Reading is not limited by the sandbox.* The legacy `workspace-write` sandbox does not limit reads: a command the person
  allows can read the whole machine, as a Claude chat's Bash can. What stands between the model and those files is the person reading each command; the permission profile that
  denies reading the whole disk made file changes fail on the recorded version, so it is not used. (2) *The cap is checked
  between reports.* A turn is interrupted when a token report reaches the cap, and two reports can be one model call apart
  (about 20,000 tokens, about US$0.02 by the rule), so a turn can pass its cap by about one call; the estimate is not a bill
  and the real cost is the person's plan use. (3) *It relies on a retired value.* `untrusted` is documented as retired
  (the vendor's agent-approvals page) though 0.163.0's `app-server` accepts it; a version that refuses it fails the check
  and the chat stays closed. (4) *The interface is experimental.* `codex app-server` is marked experimental and its request
  names, decisions and notices are the recorded version's: every Codex version must pass `--mode codex-chat` first, and
  anything unexpected stops the chat rather than being tried. (5) *Managed configuration can override the two settings.* A system (`/etc/codex/config.toml`), device-management or cloud
  managed configuration ranks above `-c` in Codex 0.163.0, so on a managed Mac it could set the project root markers or the
  trust back. VBear refuses a chat when a known administrator-policy source exists (`admin_policy`), and the response
  of `thread/start` and the MCP check would show the result, but it does not read Codex's merged configuration to prove
  the two settings took effect. (6) *Skills in the work folder.* With the two settings the work folder's own `.codex` is
  still a (disabled) project layer, and Codex loads skills from a disabled layer's `skills/` folder and from `.agents/skills`
  between the project root and the work folder, whatever the trust. A skill the model got into `<work folder>/.codex/skills`
  or `<work folder>/.agents/skills` would load in the next conversation. VBear declines a file change under `.codex`,
  `.agents` and `.git` at any depth, Codex's own sandbox makes them read-only under the project root, and a work folder that
  already holds a `.codex` is refused; a command the person allows can still create one. The person's `HOME` for the
  process is an empty folder, so `~/.agents/skills` is not read; that must stay so. (7) *An allowed command can run outside the sandbox.*
  Found on a real Mac, then read in the source (`docs/evidence/codex-0.163.0-chat.md`, 5b). Under `untrusted`, when a command
  the person allowed is stopped by the sandbox (its output says `operation not permitted` or the like), Codex runs it again
  without the sandbox and does not ask again; and when the model asks to leave the sandbox (`require_escalated`), an allow
  means it runs outside the sandbox the first time. A command run outside the sandbox can write anywhere the person's account
  can write and can reach the network. The card has no field that says which it will be, and no answer means "allow but stay
  in the sandbox", so VBear cannot tell the person on a particular card; every command card carries the warning quoted
  above. The only setting that keeps an allowed command inside the sandbox in 0.163.0 is a permission profile with `:root`
  set to `deny`, under which `apply_patch` fails, so no file change could be made; the person chose (2026-11-06) to release as
  it is and say so (ADR 0005, decision 7), and to switch to the profile when Codex fixes `apply_patch` there. File changes
  are not affected: VBear itself declines a path outside the work folder or under `.codex`, `.agents` and `.git`. What stands
  between the model and the rest of the machine is the person reading each command, as for reading in (1). The version check
  requires that `apply_patch` outside the work folder is declined with no card and leaves no file
  (`outside_patch_refused`); whether the allowed shell write got out is only noted (`observations.outside`), and the check
  removes what either wrote.
- **Not checked yet.** What happens in a long conversation (an item kind outside the list stops the chat) and whether the
  real Codex lets an unknown server request through are for the first real runs; the login's effect on the chat folder
  (it must add no `config.toml`, `rules/` or `AGENTS.md`) is checked by the folder test before every start.

## Chief of staff and dispatch (v0.15)

On the CEO's chat page the person presses 請幕僚長安排; the chief of staff proposes who does what; the person confirms; VBear
makes the new employees and sends the steps, one chat per step. ADR 0006 gives the reasons. Two things are new: **a new
outbound data path** (the person's conversation with the CEO goes to Anthropic) and **VBear sending messages to employees on its
own** after one confirmation. What it never does is fixed by the structure of the code, not by a prompt.

- **The chief of staff is one tool-less call, not a role card.** `vbear/chief_runner.py` runs one headless Claude Code call on
  the meetings' engine (`board_engine.HeadlessBoard`): `sonnet`, effort low, the same checks as a meeting (the init event
  must list only `StructuredOutput` and no MCP server, or the call is killed and the check is withdrawn), a limit of
  `min(US$0.30, what is left of the day)` and 120 seconds. Its instructions are in the code; the person cannot change them
  and no role card can override them. A Codex-only Mac gets 「幕僚長目前需要 Claude Code」; a CEO that is a Codex card still
  works, and the page says beside the button that the conversation goes to Claude Code.
- **What it reads and what leaves the Mac.** The newest 20 messages (12 KiB) of the CEO's chat, only the person's messages
  and the CEO's replies (no tool output, no allow cards), the person's optional one-line note (200 characters), and a list of
  the employees (a code C1.., name, position, tool; no id, no instruction text, no skill). This goes to Anthropic through the
  person's own Claude Code and plan. `GET /api/chief/preview` shows the counts and the money, never the words; the dialog
  says what is read and where it goes before the person presses. The record keeps the counts, sizes and SHA-256 sums, not the
  conversation or the prompt, and no log or API answer carries the conversation.
- **Three layers on what comes back.** The answer must fit a schema with `additionalProperties: false` everywhere and no field
  for a limit, a mode, a skill, a URL or a path: an answer with such a field is void. Then each item is checked against the
  list the call was given: an employee that is not on it, a new employee on a tool that cannot chat or in the CEO position,
  a bad reference, is removed and a note says so (the note holds only codes, never the model's words). A plan with no step and
  no question left is void (`empty_plan`). One to four steps, at most 1500 characters each, at most two new employees.
  Confirming checks the plan again, and only to be stricter.
- **The three things that are never done, by structure.** The chief of staff and the dispatch code (`vbear/chief*.py`,
  `vbear/dispatch*.py`, `vbear/autonomy.py`) never change a limit (the daily limit or any other), never start a terminal or a
  full-mode launch, and never install a skill. `tests/test_autonomy_guard.py` reads their source and fails on an import of
  the launch, skill, limit or process code, on a call that saves `config.json` or starts a process, on a `launch_mode` that is
  not the literal `"safe"`, and on the routes `/api/native/`, `/api/settings/autonomy`, `/api/config`, `/api/setup/daily-limit`
  and the word `acceptForSession` in the code of those modules. The test of a whole dispatch checks that `config.json` is
  byte for byte the same afterwards. A new employee is always made in safe mode with no skill and with the fixed
  instruction text of its position (not words the chief of staff wrote). The 自己動手 ticks are changed only by the person's
  `POST /api/settings/autonomy` from the settings page (with `X-VBear`); a proposal or a dispatch has no way to write them.
- **Sending goes through the chat service and nothing else.** `vbear/dispatch_runner.py` opens a new chat for each step and
  sends with `ChatService.send_for_dispatch`; the message is marked in the chat record with `origin = {dispatch, step}`
  and the chat page says 「VBear 依派工送出」. The runner has no way to answer an allow card: **every command and every file
  change the employee wants is still asked of the person, as in any chat**, and the employee's work folder and the
  limits of the chat are the card's own. A step is sent only when the day's lamp is green or yellow and the one before it
  ended normally; the runner sends one step at a time, writes the intent before the call and the result after it, and after
  a restart it reads the chat for the message before it decides anything (a step it cannot account for is paused as
  uncertain and never sent twice by itself).
- **Money.** The chief of staff's call is counted in the day (`GET /api/meetings/ledger` lists `chief` among what it includes).
  A step is a chat turn: the chat's per-turn limit and the daily limit apply. The proposal card says the most it can cost
  (steps × the per-turn limit) and what is left today before the person confirms; when the daily limit is reached, the
  dispatch pauses and says so, shows a countdown to the time the limit is over (v0.18) and then asks the person to press 「繼續」; only with
  自己動手 item 5 does VBear press it itself (see "Skills and routines (v0.18)", "Continuing a paused dispatch": `resume_dispatch(…, by="vbear")`, at most once per pause, three per dispatch and five a day).
- **The person can stop it and see all of it.** 「停止」 stops the running turn and sends no more; an employee VBear made can be
  taken back (switched off, not deleted; the chat record stays). `#/actions` (「AI 自己做了什麼」, `GET /api/actions`) lists
  every action with who decided: the person, 自己動手 item 1, item 2 (and, from v0.18, the routines' items 3 and 5), or VBear. A message that was sent cannot be taken back,
  and the list says so. 「繼續」 does not redo a step that was sent and did not end normally; it goes to the next one, and the
  page says so beside the button.

### Residual risks of the chief of staff and dispatch

1. **The reply of one step is the input of the next (a prompt-injection path).** Step N+1 is sent with the last reply of step
   N, put between `BEGIN_UNTRUSTED_JSON_STRING` and `END_UNTRUSTED_JSON_STRING` as an escaped JSON string (so the reply cannot
   write the closing line), cut at 8 KiB, introduced by a fixed sentence that says it is data and not an instruction. That is
   a request to the model, not a barrier: an employee that read something hostile (a file, a web page it was allowed to
   fetch) can write a reply that steers the next employee. What stands in the way is that the next employee also asks the
   person before each command and each file change; it is not stopped by VBear. The person who reads each card is the
   defense, and the proposal card shows every step's words in advance.
2. **An employee's allowed commands can reach VBear itself.** A command the person allows runs as the person and can read the
   console's access token and call VBear's own API, for example to raise a limit or to change the 自己動手 ticks. VBear
   guarantees only that **its own chief of staff and dispatch code** do not do the three forbidden things; it cannot stop a
   command the person allowed with their own hand. This is the same risk as in any chat with a role card (see "Chats with a
   role card") and the dispatch adds no new access to it, but it adds more such chats at once.
3. **The conversation goes to Anthropic.** What the chief of staff reads is sent to Anthropic through the person's Claude
   Code; the CEO's replies may hold what the person typed, including something they should not have. The page says where it
   goes before the first press, and the dialog shows the counts. Nothing of it is kept by VBear beyond counts and sums.
4. **A proposal is a model's opinion.** The chief of staff can propose a bad plan, a wrong employee for a step or a text that
   asks for too much. The checks above limit what it can name (listed employees, safe-mode new ones, no limit, no skill),
   not whether the plan is wise; the person reads and can edit it before confirming (and a proposal with any note or
   question is never started by itself, even with 自己動手 item 2 on).
5. **自己動手 items 1 and 2 remove the confirmation on purpose.** With item 2 on, a clean proposal (every employee already
   exists, nothing removed, no question) starts without the person's press; the cost bound and the stop button are what
   remain. Both items are off by default, and each asks for a plain confirmation before it is turned on.
6. **Not checked on a real machine.** That a real Claude Code fills the schema, that a closed chat stops being busy at once,
   that the second employee treats the handoff as data, and the real `plan_usage` of a Codex turn at its limit are for the
   first real run (`tools/qa_p40.py`). A Claude plan limit is not told apart from any other error in a chat's record, so a
   pause for it reads as an ordinary error with no resume time.

## Group chats (v0.16)

In the 聊天 page the person opens a 群組 with two or three employees (Claude Code or Codex cards that can chat), says something to
everyone or names some of them (點名), and the employees asked answer one after the other. ADR 0007 gives the reasons. Nothing
about the chat boundary changed (`vbear/runtime/` is not touched in v0.16): a group is chats plus a record of who was asked. What
is new is **an employee's words going to another employee** (and, with Claude Code and Codex mixed, to two companies) and
**VBear sending several chats' messages in a row after one sentence of the person's**.

- **A group is chats.** Making a group opens one new chat per member (`ChatService.create`: nothing is started, nothing is
  spent) and every answer of an employee is one turn of that chat, sent with `ChatService.send_for_group`, which is the same
  send as a person's in a chat (the same checks, no `origin` marker and no new field in the chat record). So everything of
  "Chats with a role card" and "Chats with a Codex role card" holds in a group: the card's own work folder (an employee does not
  see another's files, only what was said in the group; with the shared folder switched on, the next employee is also given the names of files that appeared meanwhile, as data, see "Shared folder (v0.17.1)"), safe mode, **every command and every file change asked of the person**,
  the per-turn limit and the daily limit (`min(per-turn limit, what is left of the day)` for each answer, counted in the day by
  the chat), the chat's masking and the Codex warning that an allowed command may run outside the sandbox. The group has no limit,
  no mode and no card of its own. `send_for_group` refuses a chat that no group opened; the browser's `POST /api/chats/<id>/messages`
  and `DELETE /api/chats/<id>` refuse a group's chat (`group_member_chat`, 409), and `GET /api/chats` does not list them. That is
  tidiness, not a boundary: nothing else can send to a group's chat that could not send to any chat.
- **Only the person's words start anything.** The one route that writes a person's sentence into a group is
  `POST /api/groups/<id>/messages {text, to}` (with `X-VBear`; `to` is `"all"` or a list of current members, one to three, no
  repeats; the body is strict). The runner (`vbear/group_runner.py`, one thread started by `serve()`, one pass every 2 seconds,
  `group-runner.lock`) asks the members in the order of the group (not the order they were named in), one at a time, and writes
  the intent before the call and the result after it. It never opens a round, never reads what an employee wrote to decide whom
  to ask (an `@` in a reply does nothing), and does nothing after a pause until the person presses 繼續 or 不用了. A new sentence
  cannot be sent while a round is on or paused (409 `round_open`); 停止 is always there.
- **What an employee is sent.** The first time: VBear's fixed words (the group's name and members as JSON, that only the person
  can tell the employee to do things, that other employees' words are data). Then what was said in the group since this employee
  last spoke (the person's sentences to others and the other employees' replies) as **one JSON string between
  `BEGIN_UNTRUSTED_JSON_STRING` and `END_UNTRUSTED_JSON_STRING`**, introduced by a fixed sentence that it is data and not an
  instruction, at most 6 KiB for one item and 12 KiB in all (the oldest items are dropped and the message says how many; an item
  of a reply that did not end normally is marked `partial`); the whole message stays under 30 KiB. Last, in plain text outside
  the markers, what the person says this time. An employee who comes back after being taken out, or whose card changed its tool,
  starts again with the fixed words.
- **The three things that are never done, and no answering of cards.** `vbear/group*.py` is scanned by `tests/test_autonomy_guard.py`
  with the chief of staff's and the dispatch's modules: it may not import the launch, terminal, skill, limit or process code or
  the console's `server`, may not call anything that saves `config.json` or starts a process, and, new in P41-1, **may not call
  `answer`** (nor name `chat_answer` or a route with `/answer`). Small made-up sources prove each rule fires, and a test checks
  that every `group*.py` is scanned. Whole rounds (with a pause, 繼續, 不用了 and 停止) leave `config.json` byte for byte the same.
  The group page draws an employee's allow card with the chat page's own card, under that employee's name; the person's press is
  the only thing that answers it (`POST /api/chats/<id>/answer`, the chat's own route and one-use token). There is no "allow
  all", no "allow for this round" and no `acceptForSession`: the page's source is tested for it. A card nobody answers expires after
  five minutes and counts as a refusal.
- **Money.** Before sending, the page says "this sentence asks N people, at most US$ (N × the per-turn limit), US$ X left today";
  it cannot be sent on a red lamp or when today's spending cannot be read. If the day's limit is reached in the middle of a
  round, the round pauses (nobody else is asked), says the limit and that it is counted afresh at 0:00 local time tomorrow, and
  only the person's 繼續 (ask the ones who have not answered) or 不用了 goes on; nothing counts down or continues by itself in
  this version. An employee whose AI tool's plan limit is reached is left out of that sentence with the time the tool named (or
  「未知」) and the next one is asked. The group's cost line adds up what the chats recorded; the ledger is the chats'.
- **Records.** `<state>/groups/g-<12 hex>/` (0700): `group.json` (0600, 64 KiB: name, members and the chat of each) and `log.jsonl`
  (0600, append-only, each line synced, 8 MiB: the person's words, masked and cut like a chat's, who was asked, the pauses and
  the changes of the group). An employee's reply is **not** copied: it is read from the member's chat by the turn the log names.
  A log that does not read back makes that group read-only and does not touch another group or the day's money. Nothing of a
  group's conversation is written to the console's log or an error message. Deleting a group (only between rounds) first deletes
  its chats (a chat still busy refuses everything, nothing is deleted), then the folder; the spending stays counted. Codex's own
  copy of a Codex employee's conversation stays in `codex-chat-home` (the confirmation says so).
- **Checked.** `tests/test_group_flow.py` walks one group through the real HTTP routes over a fake daemon (making it, everyone,
  naming, an allow card answered by the person, the daily limit and 繼續, 不用了, 停止, who comes and goes, deleting);
  `tools/qa_p41.py` is the coordinator's real-machine check through the HTTP API on a temporary state with Claude Code employees.

### Residual risks of group chats

1. **Another employee's words are the next employee's input (a prompt-injection path).** What one employee wrote, and what
   the person said to the others, reach the next employee between the markers as an escaped JSON string (so the text cannot
   write the closing line), with a sentence that says it is data. That is a request to the model, not a barrier: an employee that
   read something hostile (a file, a page it was allowed to fetch) can write a reply that steers the others. VBear does not stop
   it. What stands in the way is that every command and every file change of the others is still asked of the person, and that
   VBear never asks an employee because another employee said so. How a real model treats the data between the markers has not
   been tried on a real machine (待真機驗證); the code treats what it cannot read as a stop.
2. **「大家」 makes more cards.** One sentence to everyone can make each of up to three employees want a command or an edit, one
   after the other. The person reads and answers each card one at a time (no card is ever answered for them, and an unanswered
   card is a refusal after five minutes); the more cards, the more a tired press of 允許這一次 is a risk.
3. **Mixed Claude Code and Codex: the conversation goes to two companies.** What the person says in a group, and what each
   employee answers, is sent to every member's AI tool: to Anthropic for a Claude Code employee and to OpenAI for a Codex one,
   each through the person's own login. The dialog for a new group and for adding someone says so when both are present.
4. **An allowed command can reach VBear itself, and Codex may run outside its sandbox.** A command the person allows runs as the
   person and can read the console's access token and call VBear's API (to raise a limit, for example), and a Codex command may run
   outside the sandbox after it was allowed (the card says so). VBear guarantees only that **its own group code** does not do the
   three forbidden things or answer a card; it cannot stop what the person allowed with their own hand. This is the same risk as in
   any chat, and a group adds no new access, only more chats at once.
5. **Not checked on a real machine.** That a real model treats the group's data as data, how Codex employees behave in a group
   (the temporary state the check uses has no Codex chat login, so only Claude Code employees are tried), and whether 停止 really
   ends the turn of the last employee who was writing. A Claude plan limit is not told apart from another error in a chat's
   record, so such an employee is shown as having not finished normally, with no resume time.

## Memory (v0.17)

The 記憶 page keeps a few lines the person wrote or confirmed (about them, about their work, decisions they made), one book for all
employees, and every employee whose card takes memory along is given them when a new chat process starts. ADR 0008 gives the
reasons. The chat boundary did not move: the lines ride in the system prompt next to the card's own instructions ("Chats with a
role card", second paragraph, and the same for Codex), and everything else there holds. What is new is **text of the person's
that persists and is sent to a company's servers every time a process starts**, which is why only the person can write it.

- **Who can write it.** Only the browser's `/api/memory*` routes in `vbear/server.py` (token and `X-VBear`, closed bodies)
  change `<state>/memory/memory.json` (0600, 64 KiB, in a 0700 folder; `vbear/memory.py`). `tests/test_autonomy_guard.py` fails the
  build when any other module reaches the writers (`add`, `edit`, `delete`, `clear`, `set_card`, `export`, `store`), scans
  `memory*.py` and `runtime/memory*.py` with the rules of the chief of staff, dispatch and groups (no `config.json` write, no
  launch, terminal or skill code, no `answer`, no role card made or changed), and checks that `server.py` really calls each writer
  (so the rule is not empty). There is **no 「自己動手」 item for memory** and nothing parses an employee's reply for 「記住」: an
  employee that says it has remembered something has saved nothing, and the fixed paragraph tells it to ask the person to press
  「記住」. A line reaches the file in three ways, each the person's own press: typed on the page, 「記住」 beside a sentence of a chat or
  group (a box opens with the sentence cut to 200 characters; an employee's sentence is marked as the employee's), and 「存進記憶」 on
  a ticked memory suggestion (below). `source` (`typed`, `chat`, `group`, `suggested`) is a label for the page; the chat, group or
  suggestion must exist, and it changes nothing about what is sent. The save of a `suggested` line asks whether the suggestion is a
  plain file of ours, owned by the person (not a link, not a folder), and does not read it with `memory_suggest.exists`: that one
  reads the record whole and moves a damaged one aside, which a save of a line must not do (`tests/test_memory_flow.py`).
- **What may be saved: one function, run twice.** `runtime/memory_rules.check(text)` is run by the console when a line is saved
  and again by the daemon on every line before it builds the paragraph (it lives under `runtime/` because the daemon does not
  import the console's modules). Text is read after NFKC and with zero-width characters removed.
  **Refused** (never saved, never sent; 400 `memory_refused` with the reason in plain words): an empty line, more than 200
  characters, a control, format or line-separator character (a line break too: one line is one sentence), a VBear marker
  (`BEGIN_…`/`END_…`), `server.token` or `X-VBear` (`bad_text`); a password, code, PIN, OTP, recovery code, seed phrase or private
  key followed by `:`, `=`, 是, 為 or `is` and a value (`secret_password`); a key or token of a known shape (`sk-`, `sk-ant-`, GitHub,
  Slack, AWS, Google, GitLab, a private-key header, a JWT, `Bearer` with a long value, a URL with a password or `token=`) or any
  24-character-or-longer run with both letters and digits (`secret_key`); an email address, or an account or user name followed by a
  value (`secret_account`); a 13-to-19 digit number that passes the Luhn check, a Taiwan identity-number shape, or a bank-account
  word followed by eight or more digits (`secret_payment`). **Needs 「我確定」** (409 `memory_confirm`, saved when `confirm_warning:
  true` comes with it, and still passes the daemon): words that read like an order to the employee — 不用問, 直接執行, 允許, 權限,
  上限, 完整模式, 自己動手, 安裝技能, 忽略以上, `ignore previous`, `system prompt`, `sudo`, `rm -`, `curl`, `wget`, `chmod`
  (`looks_like_order`; the page says memory never makes an employee skip a question) — and a phone number or an address (`personal`:
  the person chose a second confirmation, not a refusal, because the line goes to an AI company). Every rule has a positive and a
  negative case in `tests/test_memory_rules.py`; the keys in them are built at run time. The check is a best effort and is
  **not a barrier**: a secret written in ordinary words passes. If a line the rules now refuse is found in the file, the daemon
  refuses the whole message (`memory_refused`, "check the memory page"), it never leaves the line out quietly.
- **Limits.** 50 lines, 200 characters each, 4,000 in all, and the paragraph at most 6,000 characters once encoded (a line with many
  quotes can make 409 `memory_full` earlier); at most 200 card switches in the file. A file that cannot be read is reported on the
  page (記憶的檔案有問題), VBear does not overwrite it, and chats go on **without** memory (not with half of it) and say so.
- **Which employees.** Per card, from `GET /api/memory`'s `cards` (`on`): a Claude Code card takes memory along by default (to Anthropic),
  a Codex card does not until the person switches it on (to OpenAI), and switching it on takes a question on the page and
  `confirm_company: true` in the body. A card that cannot chat has no switch. The meetings, staffing meetings, the chief of staff
  and full-mode terminals are never given memory. A card switched off sends not a word, even if there are lines.
- **The paragraph and the process.** Described under "Chats with a role card" (second paragraph: fixed words, a JSON string
  between `BEGIN_VBEAR_MEMORY_JSON` and `END_VBEAR_MEMORY_JSON`, the daemon's second check, 8,000 characters for a chat's added prompt
  and 2,000 for a full-mode launch; third paragraph: the fingerprint of what a chat started with, `<state>/chat-prompt/<chat id>.json`). In short: **an edit, a
  deletion or a switch reaches the next new chat**, not a chat that has begun: a resumed Claude Code session keeps the prompt it
  started with (seen on a real Mac), so VBear does not end a process to send a changed one, and the chat page of an older chat says
  that it still has what it started with and offers 開新聊天. A card switched off sends nothing in a new chat; what an older chat
  already sent cannot be taken back, and its page says so. Nothing is changed under a turn that is running.
- **The memory suggestion.** On a one-to-one chat page, 整理要記住的事 shows a preview that costs nothing (what will be read: at most
  the latest 20 messages and 12 KiB; the most it can cost, US$0.10, and what is left of the day; that the conversation goes to
  Anthropic, also when the chat is with a Codex employee) and, after a press, runs **one tool-less Claude Code call** on the meetings'
  engine (`vbear/memory_suggest.py`, `memory_suggest_runner.py`, shaped like the chief of staff's: sonnet, effort low, no retry; the
  conversation and the lines already kept go in as one escaped JSON string between `BEGIN_UNTRUSTED_JSON_STRING` and
  `END_UNTRUSTED_JSON_STRING`, with secrets masked first). The answer must be `{items: [{kind, text, why}]}` of at most five, with
  `additionalProperties: false`; anything else voids the whole answer. Each item is run through `check`; a refused one is shown with
  its reason and cannot be ticked, one that needs 「我確定」 says so, and **every line starts unticked, with no 「save all」**. The
  run saves nothing: the page sends one `POST /api/memory` per ticked line, the runner only records which indexes the person saved
  or that they said 不用了 (`tests/test_memory_suggest_api.py` shows `memory.json` byte for byte the same after a run). The cost is a
  chat-sized call counted in the day (`GET /api/meetings/ledger`'s `includes` lists `memory_suggest`; an unreadable record makes
  the day's spending unknown rather than zero). Without Claude Code it says 「這個功能目前需要 Claude Code」 and 「記住」 still works. It needs the
  tool-less check that the chief of staff and the meetings need; with it not done the dialog has the same 檢查 button (it asks first,
  says it costs a cent or less on the person's own Claude account, runs `POST /api/meetings/verify`, then asks for the preview
  again) and starts nothing by itself. Not for groups.
- **The tools' own memory stays off.** Claude Code in a chat: `--safe-mode`, `--setting-sources ""`, `--strict-mcp-config` and,
  new, `CLAUDE_CODE_DISABLE_AUTO_MEMORY=1` and `CLAUDE_CODE_DISABLE_CLAUDE_MDS=1` in the process environment (set in
  `daemon_chat` only; terminals and meetings do not get them). Codex: `--disable memories`, `project_doc_max_bytes=0`,
  `history.persistence="none"`, `skills.include_instructions=false`, its own `CODEX_HOME`. Tests pin each one. The Claude Code facts
  are read from the installed program's text, not from a run (`docs/evidence/claude-code-2.1.319-memory.md`).
- **Records.** `<state>/memory/`: `memory.json`, `log.jsonl` (0600, append-only, 1 MiB then a new file keeping one old one: the
  action, the line's id, kind and how it came, a card's id or a count; **never a word of a line**) and `suggest/ms-<12 hex>.json`
  (0600, at most 200: how much was read, hashes, the proposed lines and which the person saved; not the conversation). The words of
  a line are in `memory.json`, in a suggestion's record, in the launch manifest of a live process (removed with it), and in the
  tool's own copy of a conversation. They are not in the console's log, the daemon's log (only a count per process), an error
  message, a chat's record (`KINDS` did not change; `process_started.instructions` still means the *card's* instructions) or the
  group's log. Export (`GET /api/memory/export`) is a Markdown file the browser saves; it has the lines, where they came from and
  dates, never a chat, group or line id. Delete and 全部刪除 (the word must be typed) remove lines from VBear; they do not remove the
  copies Claude Code and Codex keep of conversations that already carried them (the confirmation says so).
- **Checked.** `tests/test_memory_flow.py` walks one memory over the real routes, a real daemon and the fake Claude Code: a phone
  number needing 「我確定」, a password refused, a new chat carrying the lines and saying how many, a suggestion that saved nothing,
  a line saved from it as `suggested`, an edit that does not reach the chat already started (the page says so) but reaches a new chat, a card off and on, a Codex card needing the
  word about OpenAI, the export, and clearing; `config.json` is byte for byte the same at the end. `tools/qa_p42.py` is the
  coordinator's real-machine check through the HTTP API on a temporary state with Claude Code employees (it refuses `~/.vbear` and the
  ports 7788 and 7789 and prints no word of memory, of a conversation or of a model's reply).

### Residual risks of memory

1. **Memory is a persistent prompt-injection path.** Only the person can save a line, but the person can save words an employee
   said (an employee may have read a page or a file that was hostile and repeated it), and from then on every new process of every
   employee that takes memory along is given the line. What stands in the way: an employee's sentence is marked as the employee's in the
   box, suggestions start unticked, lines that read like orders need a second confirmation, the fixed paragraph says memory cannot make
   an employee skip a question or change a setting, and **every command and every file change is still asked of the person**.
   The paragraph is a request to the model, not a barrier; how a real model treats a memory line that reads like an instruction has
   been seen once (the first real run, with a line that said not to ask: the model still asked, the person's refusal held and nothing
   was written); one run is not a study.
2. **A command the person allowed can add a line.** It runs as the person, can read the console's access token and call VBear's
   API (an existing risk of every chat), and so can post a line. The memory page lists every line with its source, but a line
   made through the API says it was typed. The person should read the page now and then.
3. **Memory goes to Anthropic and to OpenAI.** Every new process of a Claude Code employee carries the lines to Anthropic, and every
   one of a Codex employee that was switched on carries them to OpenAI, through the person's own login; the tools keep them in their copy
   of the conversation. The page says so at the top, in the box that saves a line and in the question before a Codex card is switched
   on. A memory suggestion sends the conversation to Anthropic whatever the chat's tool.
4. **The rules catch shapes, not meanings.** A password or a name written in ordinary words, a phone number written in letters, or a
   secret split over two lines of memory passes. Memory is not a place for secrets, and the page says so.
5. **A change of the memory reaches only a new chat; what a chat was given cannot be taken back.** A real run showed that Claude Code
   2.1.319 keeps a session's system prompt on `--resume` (see above). An edit, a deleted line or a card switched off therefore changes
   what new chats get; a chat that already carries a line goes on with it (and the tool's copy of the conversation has it for good).
   The chat page says so with a button for a new chat. Whether Codex's `thread/resume` applies new developer instructions was not
   tried, and the page says the same of Codex. A later Claude Code that does apply it makes the page's sentence too careful, not
   unsafe. The edit stage of `tools/qa_p42.py` checks this on a real machine.
6. **The two environment variables rest mostly on static evidence.** They were found in the installed program's text. The first real run
   saw them in a chat process's environment and found no memory folder, `CLAUDE.md` or `MEMORY.md` under the chat's work folder or
   its Claude Code project folder, but a run with and without them was not compared, so what each lock does alone is not known. Safe mode
   is the first lock; a newer version that renames either variable leaves one lock, and every new Claude Code version still goes through
   the chat check first.
7. **Not run on a real machine:** how a Codex employee behaves with memory (only the fake app-server was used), and whether Codex's
   `thread/resume` applies new developer instructions (待真機驗證). A model answered from the memory in the first real run of Claude Code, once.

## Shared folder (v0.17.1)

`<state>/shared` (usually `~/.vbear/shared`) is one folder that every employee the person has switched on may read and write, so
that one employee can hand a file to another or to the person. ADR 0009 gives the reasons. The launch side (the sandbox's second
writable root, VBear's own judgement of a path, the paragraph the employee is told, the size check, the Finder button, the version
check) is written under "Chats with a role card" (the bullet "The shared folder"), "Chats with a Codex role card" and "The chat
check"; this section is the whole picture: who can switch it on, what is handed on, what never changes, what was and was not seen on a
real machine, and the residual risks. Nothing about it removes a question: every Bash command and every Edit, Write or Codex file
change in it is still a card.

- **Only the person switches it on, and only in the browser.** Every employee is off until the person switches it on, in one of three
  places, each a browser request with the access token and `X-VBear`: the 共用資料夾 page (`POST /api/shared/cards`), the tick 「讓這幾位都能用共用資料夾」 on
  the new-group dialog (`POST /api/groups` with `shared_folder: true`, default off) and the tick 「替這次派工的員工打開共用資料夾」 on a
  dispatch's proposal card (`POST /api/dispatch/<id>/confirm` with `shared_folder: true`, default off). A Codex employee needs
  `confirm_company: true` on each (409 `shared_confirm` otherwise, with nothing made and nothing switched). The ticks must be booleans and
  `confirm_company` must come with `shared_folder` (400 otherwise). A refusal before anything is made (a Codex member without the word, a tool that
  cannot use the folder, a folder that is not right) comes **before** the group or the dispatch is made. For a dispatch, the employees who
  exist are switched on before the first message is sent, and those the dispatch is about to make are switched on by a callback
  that `server.py` hands the dispatcher (`Console._on_new_employee`), only when `<state>/shared-meta/pending/<d-…>.json` (`{v, on,
  confirm_company}`, written by the confirmation route and set back to `on: false` when it is over) says the person ticked; a confirmation that does not go through takes the ticks back.
  **Nothing else can switch an employee on:** the writers (`set_card`, `open_cards`, `close_cards`, `mark_dispatch`,
  `open_for_dispatch`, the settings store) are called only from `vbear/server.py` (`tests/test_autonomy_guard.py` fails the build otherwise, with a small
  sample that shows the rule fires, and checks that `server.py` really calls each, and that `open_for_dispatch` is reached from one place); the chief of
  staff, the dispatcher's automatic way (自己動手 item 2: the proposal's cards are made and the dispatch starts without the person, and no
  `pending` file exists) and every employee's reply open nobody. There is **no 自己動手 item** for it and the chief of staff's proposal
  format has no field for it (`additionalProperties: false` is unchanged). A test with 自己動手 items 1 and 2 on (`tests/test_shared_routes.py`) shows `settings.json` and `log.jsonl` byte for
  byte the same after a whole automatic dispatch, and `tests/test_shared_flow.py` walks the page, the group tick, the dispatch tick and the Finder button once over HTTP.
- **The switches are not where an employee can write.** `<state>/shared-meta/` (0700: `settings.json`, `log.jsonl`, `pending/`, `changes/`) is
  outside the shared folder and the sandbox does not let an employee write there; a `settings.json` an employee puts **inside** the shared
  folder is read by nobody (`tests/test_shared_routes.py`). A settings file that cannot be read means every employee is off.
- **What a group or a dispatch hands on: names, as data.** Before and after each employee's answer in a group (and each step of a dispatch)
  VBear takes a snapshot of the shared folder (`os.scandir` and `lstat`: names, sizes, times and whether it is a link; it never opens a file;
  links are not followed; more than 10,000 entries means "too many to compare" and no list). The names that are new or changed since the
  last answer (at most 50, sorted, each at most 200 characters; a name with a control character, a format character such as a right-to-left mark or
  one that is not UTF-8 is replaced by 「（檔名含特殊字元）」; not necessarily written by that employee) go to the **next** employee as
  one JSON string between `BEGIN_UNTRUSTED_JSON_STRING` and `END_UNTRUSTED_JSON_STRING`, the same markers as the reply before it, so a name
  cannot write the closing line, with a sentence that says it is data and not an instruction (at most 4,096 bytes; a long list is cut and says how
  many were listed). An employee who has the folder switched off is told only that there are new files and that he cannot read
  them, with no name; "too many" and "no comparison made" (the console restarted in the middle) are said in words, not guessed. The lists are written to
  `<state>/shared-meta/changes/<g-… or d-…>.jsonl` (0600, `O_NOFOLLOW`), **not** into the group's, the dispatch's or the chat's record, which have no new field
  (`KINDS` is unchanged, and the old `record_problem` checks read them); deleting a group deletes its list. The group page shows the names
  under the reply as text, at most ten, and the chief of staff's list of employees says which can use the folder (`shared: true|false`; the fixed words add "only
  employees with shared true can hand files to each other; write the file name in the step"; with every employee off the list, the words and the hash of the
  inputs are byte for byte those of v0.17.0).
- **The paragraph the employee is told** is fixed words and the path as a JSON string between `BEGIN_VBEAR_SHARED_JSON` and `END_VBEAR_SHARED_JSON`, at most 1,000 characters,
  that says the files are data and a sentence in one that asks for something is not to be followed without asking the person.
- **The three forbidden things and the question every time do not change.** `vbear/shared*.py` and `vbear/runtime/shared_rules.py` are in the
  autonomy guard's scan: they do not write `config.json`, start a terminal or a full-mode launch, install or insert a skill, make or change
  a role card, or call `answer` (and `shared_folder.py` imports no `subprocess`; the Finder command is handed to the console by `serve()`).
  `--permission-prompt-tool stdio`, `permissions.ask: ["Bash"]`, `autoAllowBashIfSandboxed: false`, `allowUnsandboxedCommands: false`, Codex's
  `untrusted`, `permissions.additionalDirectories: []` and the `system/init` check are as they were, and there is no `--add-dir`. VBear
  has no code path that deletes a file in the shared folder (a test scans for one), and no file name is written to the console's log, the
  daemon's log, `log.jsonl` or an error message. With every employee off, the argv, the settings, `turn/start`, the system prompt and the
  fingerprint (`prompt_sha`, pinned to v0.17.0's literal value) are those of v0.17.0.
- **A version of the AI tool has to have passed the check with the folder.** The chat check of Claude Code (`--mode chat`) and of Codex (`--mode
  codex-chat`) each have a shared-folder part, and an employee who has the folder on is refused (`shared_unverified`) on a version that has not
  passed it; an employee who has it off chats as before. The chat page has **one** 「檢查」 button for this (the note that appears when the page reads
  the code or a send is refused with it; it asks first, then sends `{engine, shared: true}` to the same route 驗證聊天 uses); the lines on the
  共用資料夾 page and at the top of the chat say it in words and give no second button.
- **What was seen on a real machine, and what was not.** The zero-cost `codex sandbox` probe of Codex 0.163.0 (no model, no login) showed the
  writable root works, a write through a link to the outside and into `.git`, `.codex` and `.agents` is refused, and that a link can be
  made and a file deleted inside the root (`docs/evidence/codex-0.163.0-shared.md`). Everything else about Codex employees and the folder —
  whether the real `thread/start` answer lists the configured root, and how a real Codex behaves reading and writing there — was tested **only against the fake
  app-server**, and the person decided (2026-11-07) that it is not verified on a real machine for this release; the version check is the gate, and it is
  fail closed. For Claude Code, the real-machine results of the release (the check's shared part, `tools/qa_p43.py`) are in the changelog.
  How a model treats a file as data, and whether a line in a file can steer it, has no record at all (待真機驗證).

### Residual risks of the shared folder

1. **A file one employee wrote is another employee's input (a prompt-injection path).** Like the reply handed on in a dispatch and the words in a group,
   but a file can be longer and hide more. The fixed paragraph says files are data and that a sentence in one that tells the employee to do something,
   run a command, change a setting or ignore instructions must not be followed without asking the person. That is a request to the model, not a barrier.
   What stands in the way is that every command and every file change is still asked of the person, and VBear never asks an employee because a file said so.
2. **What an employee reads goes to its AI company, and with mixed tools it crosses companies.** A file a Claude Code employee wrote and a Codex
   employee read goes to OpenAI (and the other way round); a file the person dropped in goes to whoever reads it. The page says so at the top and
   the question before a Codex employee is switched on says it; the folder is not a place for passwords, accounts or keys.
3. **Links and hard links.** A command the person allowed can make a link or a hard link in the folder (Codex 0.163.0 was seen to allow it). VBear's Edit,
   Write and Codex file changes follow links, refuse a path that leaves the folder and refuse an existing file with more than one hard link, and the
   Codex sandbox refuses a write through a link to the outside (seen for 0.163.0, `codex sandbox`; for Claude Code's Bash sandbox it is the version check's job to see it); a command that made a hard link to a file elsewhere, followed by a write
   through it, changes the original. This is the work folder's existing risk; what stands in the way is that the person read the command.
4. **Codex may run an allowed command outside its sandbox** (ADR 0005, point 7). The folder neither improves nor worsens this: a command that writes into the
   folder succeeds inside the sandbox, but any other write the sandbox stops is run again outside it after the person allowed the command.
5. **The person may open what an employee left.** In Finder, double-clicking a `.command`, `.app` or `.sh` file an employee wrote runs it as the person.
   The page warns; VBear cannot stop it.
6. **The size is checked only when a process starts.** The limits are 1 GiB (by the size a file says, so a sparse file counts as large as it looks) and 10,000 entries; a running employee can fill the folder, and the next new process is refused (`shared_full`).
7. **A command the person allowed can reach VBear itself.** It can read the access token and call the API, including `POST /api/shared/cards`, which switches
   another employee on (the existing risk of every chat). `log.jsonl` records each switch with its time and how it came and the page lists it; the person
   should read it now and then.
8. **Codex employees and the shared folder were not tried on a real machine** (the person's decision for this release; see above), and whether the real Claude
   Code writes through the second `allowWrite` entry was only seen by the version check and the coordinator's run; **how a model treats the files** has not been tried at all.

### Going back to v0.17.0

Read from the code and not run. `<state>/shared/` and `<state>/shared-meta/` stay and are not read; v0.17.0 passes no `shared` to a chat, adds no writable root
and has `judge` refuse an Edit or Write outside the work folder and `judge_file_change` a change outside it, so an employee can no longer write into the folder
(it can still be asked to read it, which is a card). The records of chats, groups and dispatches have no new field and read as before; groups and dispatches no longer hand on names.
A chat that began with the folder on has a fingerprint that includes the folder's paragraph, so v0.17.0's chat page shows it as different from its start (which is true).
The chat-check reports gain `shared` and `shared_steps`; v0.17.0 reads `mode`, `passed` and the version only (that it accepts the extra keys is read, not run: 待確認).
No key of `config.json` was added.

## Skills and routines (v0.18)

A **skill** is words the person saved in VBear to say to an employee later; a **routine** hands one employee a job at times the person chose; a paused dispatch can be **continued** when its limit is over. ADR 0010 gives the reasons. What is new is
**VBear starting work while the person is away** (a routine with 自己動手 item 3; a continuation with item 5), one **new program VBear starts** (`caffeinate`, only on the person's switch) and **words the person saved** reaching the employees later. The part that
stays as it was is fixed by the structure of the code: every message goes through `ChatService` into a safe-mode chat, so every command and every file change is still asked of the person, a card nobody answers within 5 minutes counts as refused, and **no card is answered**
by any of this code. `vbear/runtime/` gains one function, `memory_rules.check_text` (and its tests); `agent_sessions.py`, `daemon*.py`, `chat_protocol.py`, `codex_chat_protocol.py`, `chat_session.py`, `chat_store.py` (`KINDS`, `origin_ok`) and `proctrack.py` are not touched, so the launch
boundary of every chat is v0.17.1's.

### Skills

- **Only the person saves one, and only in the browser.** `<state>/skillbook/skills.json` (0600, `GuardedJsonStore`: `{v: 1, skills: […]}`; an id `k-<12 hex>`, a name of 1 to 40 characters, a text of 1 to 4,000, a `source` and two times) holds at most 100 skills; `log.jsonl` has `{at, action, id}` and
  never a name or a word. The writers (`add`, `edit`, `delete`, `store`) are called only from `vbear/server.py`'s routes, `POST /api/my-skills`, `POST /api/my-skills/<id>` and `POST /api/my-skills/<id>/delete` (token and `X-VBear`, closed bodies). The ways to a save are three: the person
  writes one on the 技能 page; presses 「存成技能」 beside a line of a chat or a group (a line the employee wrote needs the tick 「我確定」 in the dialog and `confirm_warning: true`, 409 `employee_words` otherwise, because once saved it is something the person says to the employee); or presses
  「整理成技能」 on a one-to-one chat and then changes the proposal and presses 「存」. `tests/test_autonomy_guard.py` (rule 8) fails the build when any module but `server.py` calls a writer, and when `skillbook_suggest*.py` imports `skillbook`, with a small sample that shows the rule fires.
- **The words are judged as memory's are.** The name and the text go through `memory_rules.check_text` (the same refuse and warn rules as `check`, which is unchanged): a password, a key, an account, a card or an identity number is refused (400 `skill_refused`); something that sounds like an order to act
  without asking, a phone number or an address asks for `confirm_warning` (409). A `skills.json` that cannot be read is moved aside by the store (as memory's is) and the page says so; chats go on and no skill can be saved until the person looks.
- **A skill is not an instruction of VBear's.** It is never in the system prompt, never on a role card and never written as a skill file of an AI tool (`skillbook*.py` import none of `armory`, `loadout`, `skill_fit`, `scan` or the writers of `agent_profiles`, and write nothing outside `<state>/skillbook/`); `memory_rules.combine`, `prompt_sha`, the
  `chat-prompt` format, `--append-system-prompt` and Codex's `developerInstructions` are as they were. 「用技能」 only puts the words in the box of a chat or a group (a `GET /api/my-skills` and nothing sent); the person reads them, may change them, and presses send, so
  what goes out is **the person's own message**, with the weight of one the person typed. A test with the real daemon and the fake Claude Code compares the `argv`, the first message and the `prompt_sha` of a chat that used a skill with one that typed the same words, and they are equal.
- **「整理成技能」 sends the conversation to Anthropic.** It is one tool-less Claude Code call on the meetings' engine (`HeadlessBoard`, as 「整理要記住的事」): the newest messages of one one-to-one chat (the person's and the employee's words, no tool output, no allow card) go to Anthropic through the
  person's own Claude Code, also when the chat is a Codex employee's; a Codex-only Mac is told it needs Claude Code. The preview (`POST /api/my-skills/suggest/preview`) costs nothing and says how many messages, where they go and the most it can cost, **US$0.10**, and it is counted in the day
  (the spending kind `skill_suggest`, in the ledger's `includes`). The conversation is put in the prompt as one escaped JSON string between `BEGIN_UNTRUSTED_JSON_STRING` and `END_UNTRUSTED_JSON_STRING`; the answer must be `{items: […]}` with at most one `{name, text, note}` and no other field, or it is void; the record
  `<state>/skillbook/suggest/ks-<12 hex>.json` keeps sizes and sums, not the conversation. Nothing is saved by it.

### Routines

- **Only the person makes, changes, switches on, switches off or deletes one.** `<state>/routines/routines.json` (0600): at most 20 routines, ten of them on; each is one employee who can chat (a Claude Code or Codex card), a text of 1 to 4,000 characters (the same check as a skill's), days of the week and one to three
  times at least 60 minutes apart. The writers (`create`, `edit`, `set_enabled`, `delete`, `set_settings`, `store`) are called only from `vbear/server.py`'s `POST /api/routines`, `POST /api/routines/<id>`, `…/delete` and `POST /api/routines/settings` (token and `X-VBear`); the functions that record a run are called only in `routines.py`,
  `routine_runner.py` and `server.py`; `routine*.py` never calls `save_profile` or `create_profile`. `tests/test_autonomy_guard.py` (rule 9) fails the build otherwise. The chief of staff's proposal format is unchanged (`additionalProperties: false`, no field for a routine or a skill), VBear does not read an
  employee's words for anything, and **what an employee says (「我幫你排好每天的工作了」) makes nothing**. There is **no 自己動手 item** for making a routine: item 3 makes a routine *start* and *catch up*, never exist or be switched on.
- **A run is one turn of a new chat.** `RoutineRunner` (`vbear/routine_runner.py`, a thread started by `serve()`, one pass every 15 seconds, the lock `<state>/routine-runner.lock`) opens a chat with `ChatService.create` and sends with `ChatService.send_for_routine`. That method takes only a chat a routine opened (the run is `starting` and names the
  chat), is called nowhere else (`tests/test_autonomy_guard.py` knows the name only in `chat_service.py` and `routine_runner.py`), is reached by no route of the browser and adds no `origin` (the chat record has no new field). What is sent is one fixed line (that this is a routine the person set up, that the person may not be at the Mac, that commands and file
  changes will still be asked and that no answer counts as refused), the name and the time as one escaped JSON string between `BEGIN_UNTRUSTED_JSON_STRING` and `END_UNTRUSTED_JSON_STRING`, a blank line, and then the person's text outside the markers (it is the person's instruction). The chat then runs by the chat's own rules:
  safe mode, a card for every command and file change, **a card nobody answers in 5 minutes counts as refused**, 10 minutes a turn, the per-turn limit, the daily limit, memory and the shared folder as that employee's switches say. A routine never uses the full mode or a terminal, never installs or inserts a skill, never changes a role card, never writes `config.json` and never answers a card.
  That a model follows the fixed line has no record (待真機驗證).
- **Without item 3, a routine only reminds.** At the time (within 2 minutes, and VBear looking all along) the run is `waiting` and a line over every page says so (`GET /api/waiting`, names, times and counts, no word of any text) with 「現在開始」 and 「這次跳過」; nothing is sent and nothing is spent. A reminder nobody pressed is put away at the routine's next time or after 12 hours.
  With item 3 on the run starts by itself (`by: auto3`) and 「AI 自己做了什麼」 says 「自己動手第 3 項」. Item 3 is read in one place from `autonomy.read(conf)["routines"]`; a missing key, a value that is not `True` or a `config.json` that cannot be read means off (the behaviour test in rule 10 runs the runner with each and counts `send_for_routine` calls: 0).
- **One time of a routine starts at most once.** `<state>/routines/runs.jsonl` (append-only; `{run_id, routine_id, slot, state, by, why, chat_id, turn, cost_usd, reason, at}`; no name and no text) is the record: a slot that has a run never gets another, whatever a restart, a clock set back or a catch-up does. Clock changes (a day that skips an hour or repeats one) are handled
  on the local clock. Runs go one at a time; an employee who is busy or a full house is asked again every 30 seconds for 12 minutes and then the run is `skipped`. If the console stops between the send and the note, the next start reads the chat: the message is there and it is noted, or it is not and the run is `uncertain`
  and **is never sent again by itself**.
- **Money.** A run is one chat turn, counted in the chat: the per-turn limit, then the routines' own daily limit, then the daily limit, which still caps everything. The routines' limit is `daily_usd` in `<state>/routines/settings.json` (never in `config.json`), **half of the daily limit unless the person sets it, and never above the daily limit** (the person decided on 2026-11-08);
  once the routines spent it, no new run starts (one that is going can spend one more turn's limit). A run is not started with the day's lamp red or the ledger unreadable; it is `skipped` with the reason, not counted down and not continued, and the next time comes as always. Codex employees' runs are estimated from tokens, as in a chat.

### Waking up and keeping the Mac awake

A routine only runs while VBear is open and the Mac is awake: VBear installs nothing that runs when it is closed (no LaunchAgent, no login item, no crontab, no change to how the app starts or ends) and schedules no `pmset` wake-up. This part covers the two things around it.

- **Missed times are only a list, unless item 3 is ticked.** The runner writes `<state>/routines/heartbeat.json` (`{"v": 1, "at": <seconds>}`,
  0600, replaced whole, never followed through a link, no name and no word of a routine) about once a minute. When two looks are more than
  90 seconds apart (the Mac slept) or, at a console's start, the file is older than that (VBear was closed), the times that passed in
  between are *missed*: counted from the later of the routine's `enabled_at` and the last heartbeat, at most seven days back. No heartbeat file
  (a fresh upgrade) or one that cannot be read counts nothing. Every routine offers only its **latest** missed time (a run in the state
  `waiting`, `why: catch_up`); the earlier ones are recorded `missed` so that no time is ever done twice. Nothing is sent by this: the
  person presses 補做 (`POST /api/routines/missed/<id>`, `X-VBear`; the run is `by: you`) or 不用了. Only with 「自己動手」 item 3 (read in the
  one place the runner reads it) does VBear queue the run itself: the latest missed time must be younger than 12 hours, at most three
  routines per wake-up (the earliest first), and the runs go one at a time. They begin through the same checks as any run: the day's lamp,
  the routines' own daily limit, a card that can chat. A run those stop is `skipped` with its reason and is not tried again. A listed
  row is put away (`missed`) at the routine's next time or after 24 hours; a routine whose own time is due when the Mac wakes is
  just its ordinary reminder or run and does not also catch up.
- **`caffeinate` is the one program VBear starts that is not an AI tool**, and only when the person has switched on 「有工作在跑時不讓 Mac
  睡著」 (`keep_awake` in `<state>/routines/settings.json`, default off, changed only by `POST /api/routines/settings`, never in
  `config.json`). While a routine's run is going or a dispatch is running, `vbear/keep_awake.py` runs `/usr/bin/caffeinate` with the argv
  `["/usr/bin/caffeinate", "-i", "-w", "<the console's pid>"]`: a constant, no shell, no input or output, nothing taken from a record, a
  request or a setting. `-i` only stops *idle* sleep (a closed lid still sleeps), `-w` ends it when the console ends, and it is ended by
  VBear 30 seconds after the last work or at once when the switch is turned off. `serve()` alone hands the launch to a console
  (`Console.keep_awake_command`); a console built any other way has none and starts nothing. A guard test (rule 12 of
  `tests/test_autonomy_guard.py`) keeps it so: no other file of `vbear/` names the program, its argv is one constant list, `routine*.py`,
  `skillbook*.py` and `auto_continue.py` start no program, and only `server.py` imports the module.

### Continuing a paused dispatch

- **A countdown, then a reminder; the press itself only with item 5.** A dispatch paused for the daily limit (the time is midnight on this Mac) or for an AI tool's plan limit (the time the tool reported: Codex does, Claude Code does not, and then the page says 「AI 工具沒說什麼時候恢復」, there is no countdown and nothing continues
  by itself) shows 「還有 H 小時 M 分可以繼續」 on its page and in the line over every page; the group page shows the same for a round paused at the daily limit. Two minutes after the time, if the lamp is not red and (for a plan limit) the tool's last report does not say full, the line says 「派工『X』可以繼續了」 with 「繼續」 (the old `resume_dispatch`, `by: you`).
  With 自己動手 item 5, `vbear/auto_continue.py` makes the press (`resume_dispatch(did, by="vbear")`, which takes only `you` or `vbear`, writes a `continued` event by `vbear` that v0.17.1 reads, and refuses a step that may have been sent) and notes it in `<state>/routines/auto-continue.jsonl` (`{at, dispatch_id, event_seq, pause_seq, reason, item: 5}`, no name or word). **The step the limit cut off is not done again** and the next step is told that the
  one before did not end normally. Limits: once for a pause, three for a dispatch, five a day in all (the local day), not again when the dispatch was stopped by the same reason within 10 minutes of a press, not when the time went by 12 hours ago (listed for the person instead), and never for another reason (`uncertain`, `interrupted`, `runner_error`, `turn_*`, `busy`, `limit`). A group never continues by itself
  (`group*.py` do not import `auto_continue`): only the person's words make an employee answer. Item 5 is read in one place, `autonomy.read(conf)["auto_continue"]`; off means `resume_dispatch` is not called (rule 11). The records have no new field (`BYS` and `_EVENT_FIELDS` are unchanged); 「AI 自己做了什麼」 shows the press as 「自己動手第 5 項」.

### What stays as it was

`routine*.py`, `skillbook*.py` and `auto_continue.py` are in the autonomy guard's scan with the rules of the chief of staff, dispatch and groups: they never write `config.json`, start a terminal or a full-mode launch, install or insert a skill, make or change a role card or call `answer`, and the
scan of `autonomy.py` goes on. `config.json` gains two keys inside `autonomy` (`routines`, `auto_continue`, exactly four booleans), written only by `POST /api/settings/autonomy`; the routines' own settings are in `<state>/routines/settings.json`. Logs hold ids, times, states, counts and amounts, never a name or a word of a skill or a routine
(`log.jsonl`, `runs.jsonl`, the console's log, the daemon's log, errors). `tests/test_skills_routines_flow.py` walks it once over HTTP (a skill saved and used, a routine made, the reminder, 「現在開始」, item 3 on and a run by itself, a closed VBear and the catch-up, a paused dispatch and item 5) with a fake clock and a fake chat service, and shows `config.json` changed
only where the settings page's route writes it. `tools/qa_p44.py` is the coordinator's real-machine check through the HTTP API.

### A known gap in the day's money

The chat process in the runtime adds up the day's spending in `_chat_day_spent` (`vbear/runtime/daemon_chat.py`) from a fixed list of kinds (the chief of staff, memory suggestions and the meetings). It **does not include** what 「整理成技能」 (`skill_suggest`) spent: the guard rules forbid the runtime to know about skills, and this release does not change the launch boundary. The result is one-sided:
the per-turn check of a chat can allow up to US$0.10 more for each 「整理成技能」 run that day than the daily limit says, while 「整理成技能」 itself checks the day including the chats, and the ledger counts it. To be settled in a later release.

### Residual risks of skills and routines

1. **A saved line of an employee becomes the person's order.** 「存成技能」 on an employee's line keeps words the employee wrote, and later 「用技能」 sends them as the person's message. What stands in the way is the tick 「我確定」 and the sentence at save time, the box where the person reads and may change the words before sending, and that every command and every file change is still a card.
   A skill that sounds like an order to act without asking asks for `confirm_warning` again. A prompt-injection path remains: an employee that read something hostile writes a line, the person saves it without reading, uses it later.
2. **A routine runs when the person is away, with item 3 ticked.** The model's reply (a draft, a summary) is made and paid for within the routines' daily limit; what the employee wants to run or change is a card that counts as refused after 5 minutes, so it does not happen. A routine's text is the person's, but a file the employee reads or a page it fetches can steer the reply (the existing risk of any chat).
3. **A command the person allowed can reach VBear itself.** It can read the access token and call the API, including `POST /api/routines` (make and switch on a routine), `POST /api/my-skills` and `POST /api/settings/autonomy` (tick items 3 and 5): the existing risk of every chat, now with more to reach. Nothing runs from a card nobody answered, so this needs the person to allow the command with their own hand.
4. **Item 5 continues in the night.** A dispatch continues by itself after the limit's time; the step cut off by the limit is not redone, but the next step may get an incomplete reply (it is told so). The limits (once, three, five, ten minutes) bound it.
5. **The clock is the evidence.** A clock set forward by hand looks like a sleep (missed times are offered, or with item 3 queued once, within the limits); a clock set back cannot make a time run twice. `keep_awake` on keeps an idle Mac awake while a long dispatch runs, which costs battery. `caffeinate` is the macOS tool; whether it really holds off the sleep, and a Mac that really sleeps and wakes (a closed VBear stands in, and
   the detection is the same), were **not tried on a real machine** by this task (待真機驗證).
6. **「整理成技能」 sends a conversation to Anthropic** (also from a Codex employee's chat) and its US$0.10 is not in the chat process's own count of the day (the known gap above).
7. **Codex employees and routines were not tried on a real machine**, and the automatic continuation after midnight was only run on a fake clock; both are not verified on a real machine. How a model treats a skill's words and the routine's fixed line has no record (待真機驗證).

### Going back to v0.17.1

Read from the code and not run. `<state>/skillbook/`, `<state>/routines/` and `<state>/routine-runner.lock` stay and are not read: routines no longer run and nothing is caught up, skills are not offered, nothing is deleted. A running `caffeinate` ends with the v0.18.0 console (`-w`). `config.json`'s `autonomy` keeps
`routines` and `auto_continue`; v0.17.1 reads `create_cards` and `dispatch` only, and a save on its settings page writes those two back (items 3 and 5 come back off). Chats, dispatches and groups have no new field and read as before: a routine's chats are ordinary one-to-one chats, 「用技能」 sent ordinary messages, and an automatic continuation is a
`continued` by `vbear` (in v0.17.1's `BYS`), shown as 「VBear」; `auto-continue.jsonl` is not read. A paused dispatch or group waits for the person's press. The `memory_rules.check_text` function is unused. 「整理成技能」's records are in their own folder, which v0.17.1's ledger does not read (tested with v0.17.1's code), so that day's total in v0.17.1 leaves them out (at most US$0.10 each); the ledger does not become unreadable.
How a v0.18.0 process still running at that moment ends: 待確認.

## Team templates (v0.19)

A **team template** (團隊範本) is a ready-made set of employees (role cards), skills and routines. Four are built into the program (小店, 自媒體, 接案工作室, 個人生活助理: 12 employees, 12 skills and 6 routines in all) and the person can save templates of their own (at most 20). ADR 0011 gives the reasons. What is new is **a button that makes many things at once**: employees whose standing instructions are words
VBear wrote, skills and routines. The part that stays as it was is fixed by the structure of the code: an apply makes them only through the write functions the person's own presses already use, in the browser's routes, with every check they have; it opens nothing (safe mode, no skill card, every routine switched off, memory and the shared folder as the card's default says),
uses no AI and costs nothing; every command and every file change is still asked of the person (also of a new employee), and a card nobody answers within 5 minutes counts as refused. **`vbear/runtime/` is not changed at all** (`git diff v0.18.0 -- vbear/runtime` is empty), so the launch boundary of every chat is v0.18.0's, and no record file of the cards, the skills, the routines, the chats, the dispatches or the groups has a new field.

### Who can apply, and what it checks

- **Only the person, only in the browser.** `POST /api/templates/preview`, `POST /api/templates/apply`, `POST /api/templates/applies/<id>/undo-preview` and `…/undo`, and `POST /api/templates/mine`, `…/mine/<id>` and `…/mine/<id>/delete` are routes of `vbear/server.py` that need the access token and `X-VBear`, with closed bodies (an unknown field or a wrong type is 400). The chief of staff's proposal format is unchanged (`additionalProperties: false`, no field for a team template); nothing an employee says applies or saves one.
  There is **no 自己動手 item** for team templates: the five items of ADR 0003 are as they were. The modules of the chief of staff, the dispatch, the groups, the memory, the shared folder, the skills, the routines and the automatic continuation may not import a team template module, and no scanned module may name `/api/templates` (guard rule 13a to 13c, below).
- **The preview writes nothing** (a test compares every file of the state folder, with its size and time, before and after) and starts no program. The state of the two AI tools comes from the start-up page's own cached report; nothing is run and no model is asked.
- **An apply checks everything before it makes anything.** The files of the cards, the skills, the routines and the record of the applies can be read (else 503 and nothing is made); the number after the apply stays within the old limits (500 role cards, 100 skills, 20 routines: else 409 `template_full` and it says by how many) and within the new ones (one apply and one team template hold at most 12 employees, 24 skills and 12 routines);
  a routine has an employee who can chat; text that the rules of memory call a warning (an order to act without asking, a phone number, an address) needs `confirm_warning: true` (409 otherwise; the four built-in team templates have none, a test says so). The request is planned again on the server; nothing the browser's preview said is trusted.
- **Then it makes, one at a time, with the ordinary functions.** Each employee through `_save_card`, the one piece of code that `POST /api/agent-profiles` uses (the hidden-tool refusal, the known skills and professions, `save_profile`; the route's behaviour and tests did not change), each skill through `skillbook.add` (so `memory_rules.check_text` judges it as for any skill), each routine through `routines.create` (so the employee must be able to chat). Each item is written in `<state>/templates/applies.json` as an
  *intent* before it is made and as *made* (with its fingerprint) after. A whole apply runs under one lock (`TEMPLATE_WRITE_LOCK`). If one step fails the apply stops there: 409 `template_partial`, the screen says what was made, and 復原這次套用 can take it back. The console that stops in the middle leaves the apply `applying`; at the next start `recover()` marks it interrupted before any route is served, an employee whose intent is known and whose card exists is noted as made, and a skill or a routine whose id was not yet known is `unknown` and **is never deleted by the undo**.

### What an apply never opens

- **Never full mode.** The body of a card is built by `card_body` with the literal `launch_mode: "safe"`, `equipped_skill_ids: []` and `VERIFIED_INTENTS` (the same marker the starter deck gives, which has no power; Claude Code's safe-mode terminal launch needs it), no `enabled` key (a new card is on), no profession, and the model `{tool, model_id}` where `model_id` is the template's alias for Claude Code and empty for Codex (Codex's own default).
  A Codex card in the safe mode can chat in VBear and cannot start in a terminal (VBear's terminal starts Codex only in the full mode), as with the cards a dispatch makes. The format of a team template has no field for the tool, the mode, a skill card, a profession, permissions, a switch, memory, the shared folder, a chat or an id, and `mine.json` is a closed format (one field more is a file that cannot be read).
- **Every routine is made switched off** (`routine_body` has the literal `enabled: False`; every `enabled` in a template module must be `False`, rule 13c). Switching one on is the routines page's press, with the old checks (at most ten on), and after that a routine follows v0.18.0: a reminder, or a start by itself only with 自己動手 item 3.
- **Memory, the shared folder, `config.json`, the 自己動手 ticks and the limits are not touched:** the apply routes call none of `memory.set_card`, `shared_folder.set_card` and `open_cards`, the dispatch's `on_new_employee`, the chat service's `create` and `send`, the daemon, the meetings' engine, `config.save` or `autonomy`. `config.json`, `memory/memory.json` and `shared-meta/` are the same bytes after an apply and after an undo (a test compares them), the chat service is asked only for the list of cards and the daemon is a trap that fails on any call.
  So the new employees have the card's default: Claude Code's takes memory along, Codex's does not (it would go to OpenAI), and none has the shared folder.
- **No AI, no money, no program.** `subprocess` is a trap in the tests of the apply; the ledger of the day is the same after. Talking to a new employee afterwards is an ordinary chat under the per-turn and the daily limits.
- **No way out of this computer.** No route exports, imports, uploads or downloads a team template, and a template module imports none of `urllib`, `http` and `socket` (a test says so; `/api/templates/mine/<id>/export` and the like are 404).

### 復原這次套用 (the undo)

Every apply can be taken back, in two presses. `POST /api/templates/applies/<id>/undo-preview` writes nothing and lists what would be **deleted**, what would be **kept** (with the reason) and what is **already gone**; `POST …/undo {delete: [ids]}` works the plan out again on the server and deletes only the ids that are in the person's list **and** can still be deleted, routines first, then skills, then employees, each with the function of the page's own 「刪除」
(`routines.delete`, `skillbook.delete`, `agent_profiles.delete_profile`) and each written down as it goes. An id that the apply did not make is 400 and nothing is deleted. The undo touches only the ids the record says were made; `intent`, `unknown` and `failed` items and everything the person had before are never touched.

- **A routine is kept** when it was changed or switched on (its fingerprint differs: the whole record including `updated_at` and `enabled`), has any run in `runs.jsonl` (a reminder, a miss, a skip or a run all count), or cannot be read.
- **A skill is kept** when it was changed (the fingerprint of the whole record) or cannot be read. **VBear does not record that a skill was used** (using one only puts its words in the box and what is sent is the person's own message), so the undo looks only at whether it was changed; the preview says so (`SKILL_NOTE`). Deleting an unchanged skill loses nothing: its words are the template's and applying again brings it back.
- **An employee is kept** when, in this order: the record cannot be read; the card was changed (`profile_digest` of the card, which includes `updated_at`, so any save counts: name, instructions, model, switched off); something mentions him (`card_mentions`: a chat in `chats/*/chat.json` or his work folder in `chat-work/`, a file in `groups/`, `dispatch/`, `chief/`, `meetings/`, `staffing/`, `sessions/`, `flows.json`, `tasks.json`); his memory or shared-folder switch was changed (his id is in `memory/memory.json` or `shared-meta/`);
  or a routine that stays still goes to him. The search reads only plain files, follows no link, reads at most 4 MiB of a file and 20,000 files in all, and **anything it cannot read, or finds too large or too many, counts as "mentioned" and keeps the card**.
- **The server works the plan out again at the second press**, so an employee the person talked to between the preview and the press is kept; the plan can only shrink.
- **The records:** `<state>/templates/applies.json` (0600, `GuardedJsonStore`, the last 50 applies; each item has its kind, id, the template and key it came from, its state, a fingerprint and a time) and `<state>/templates/log.jsonl` (0600, append only, 1 MiB then replaced; the action, the id and the counts). **Neither has a name or a word of what was made, and neither do the console's log and the errors**; a text refused by `check_text` is not repeated in the answer.

### A known limit of the undo: the terminal and the skills

VBear cannot see whether the person used an employee in a terminal. Read from the code, not guessed: the card's id appears in the safe-mode launch only in the preview in memory, and neither the spec handed to the runtime nor the manifest the runtime writes in `<state>/sessions/` carries it; a full-mode launch leaves no record at all (`tests/test_templates_undo.py` pins the first three: if a launch ever leaves the card's id, those tests fail, and only then may the line below go).
So the preview of the undo always has the line `TERMINAL_NOTE` whenever it would delete an employee (「如果你在終端機用過這些員工，VBear 看不出來；確定再刪。」) and the person decides before pressing 「刪掉這些」; and it has `SKILL_NOTE` about skills. This is the one place where "used" is the person's judgement and not VBear's.

### Saving the person's own team template

- **A copy of now, of the things the request names.** `templates_mine.save_mine` takes the cards, skills and routines that `server.py` read for the request (a file that cannot be read is 503 and nothing is saved) and stores a copy in `<state>/templates/mine.json` (0600, `{v: 1, templates: […]}`, closed, at most 20 of your own; a file with a field more or less, a repeated id or a link is left where it is, the page says so, no new template can be saved and the four built-in ones still work).
  An employee is saved with the name, the position (if it is one of the eight), the instructions only if the person wrote them (not a position's default text) and the Claude model alias only if it is one; **not** the tool, the mode, the skill cards, the profession, the permissions, whether the card is switched off, memory, the shared folder, the chats, the work folder, the id or a time. A skill is saved as name and words (no `source`). A routine is saved as name, words, days, times and which employee (if that employee was saved in the same template), never as switched on and without its runs.
- **A full-mode employee can be saved, and a full-mode employee is saved without a launch mode.** The saved employee has no mode at all, so every apply makes the safe mode; the dialog and the answer (`full_mode_saved_safe`) say so, and a test shows the file has no `launch_mode` and an apply of it makes a card whose `launch_mode` is `safe`.
- **The words are judged again** by `memory_rules.check_text` over the name of the template and every text: a key, a password, an account or a card is 400 `template_refused` with only the place named (kind, index, field), not the words; an order to act without asking needs `confirm_warning` (409) and is asked once more at the apply. Renaming and deleting a template touch nothing it made or was made from.

### What the guard test says

`tests/test_autonomy_guard.py` has rule 13: (13a) every `template*.py` is scanned with rules 1 to 12, and a test fails for a template module that is not on its list; (13b) no other scanned module imports a team template module, and a template module imports none of the chat service, the meetings, the board engine, the headless runner, the automatic continuation, `keep_awake`, `scan`, `urllib`, `http` and `socket`, and calls no write function of the cards; (13c) every `enabled` in a template module is `False`, and `/api/templates` is named only in `vbear/server.py`;
(13d) the functions that write the record of the applies (`begin_apply`, `record_item`, `end_apply`, `record_undo`, `recover`, `applies_store`) are called only from `vbear/server.py` and `templates_apply.py`, the apply and undo functions of the console use only `_save_card`, `skillbook.add`, `routines.create`, `routines.delete`, `skillbook.delete` and `agent_profiles.delete_profile` and name no switch, chat, launch, setting, ledger or program (a `memory.set_card` put into the apply function was tried and the test failed); (13e) `save_mine`, `rename_mine`, `delete_mine` and `mine_store` are called only from `vbear/server.py` and `templates_mine.py`,
and those modules import no skill, routine, memory, shared-folder, chat or network module and have no export, import, upload, download, send or fetch function. Each rule has a small made-up source that shows it fires. **Rule 13b has no exception for `templates_apply`:** the plan said to open the narrowest exception for it, and it was not needed, because every write is in `vbear/server.py`, where the write functions have always been called from, and `templates_apply.py` only keeps the record and the rules and calls none of them. Nothing was added to any list of who may write, and a test puts the same call into each template module and into the modules of the chief of staff, the dispatch, the groups and the routines and shows it is still caught.
`tests/test_templates_flow.py` walks it once over HTTP (the list, a mix of two team templates, the preview, the apply, a chat, a change, the preview of the undo, the undo, your own template, its apply and undo) and shows `config.json`, the memory and the shared folder are the same bytes at the end. `tools/qa_p45.py` is the coordinator's real-machine check through the HTTP API.

### Residual risks of team templates

1. **Words VBear wrote reach the employees.** The standing instructions of the built-in employees and the words of their skills and routines are in the program; each was judged by `check_text` with no warning, the person sees the first 80 characters in the preview and can open the whole text on the page, and an employee still asks about every command and every file change. But that a model follows them as meant has no record (待真機驗證; the real-machine check tries one employee for one turn).
2. **A saved team template carries the person's own words** (including a skill saved from an employee's line, ADR 0010 risk 1). They go through `check_text` at the save and again at the apply, and a warning is asked twice; a hostile text the person saved without reading remains a prompt-injection path.
3. **"Used" is VBear's record and the person's judgement.** VBear cannot see whether the person used an employee in a terminal and does not record the use of a skill; the preview says both. An employee whom the person used only in a terminal and never changed would be deleted if the person presses 「刪掉這些」 without reading the line.
4. **The preview and the second press can differ** (the person changes something in another tab in between). The server works the plan out again, so the only difference is that fewer things are deleted.
5. **A command the person allowed can reach VBear itself.** It can read the access token and call the API, including `POST /api/templates/apply` (make employees, skills and routines, all switched off or safe) and the undo (delete only unchanged things an apply made): the existing risk of every chat. Nothing runs from a card nobody answered.
6. **Codex employees of a team template were not tried on a real machine** (the scratch state has no Codex login for chat; a fake app-server and the unit tests cover them), and routines made by a team template really running at their time were not tried either; both are not verified on a real machine. The built-in texts are in Traditional Chinese and were not checked by anyone but the tests and the person.

### Going back to v0.18.0

Read from the code and not run. `<state>/templates/` (`mine.json`, `applies.json`, `log.jsonl`) stays and is not read (no code of v0.18.0 names that folder); the page and the routes are gone, so **an apply cannot be undone from v0.18.0** and what it made is deleted one by one on the role card page, the 技能 page and the 例行工作 page; nothing is deleted by going back. Everything an apply made has v0.18.0's own formats (`_save_card` and the write functions were not changed): cards with `launch_mode: "safe"`, skills with `source: {how: "typed"}`, routines with their six fields and switched off.
`config.json` has no new key and `vbear/runtime/` is unchanged. Coming back to v0.19.0 the record is read again and 復原這次套用 works: what was changed, talked to, run or switched on in v0.18.0 shows in the fingerprint, the chat record or the runs and is kept, and what was deleted is 「已經不在了」; an apply that was cut off stays `applying` for v0.18.0 and `recover()` marks it interrupted at the next start. No process is left running by this release (it starts no program).
Whether the macOS app of v0.18.0 does anything with a `templates` folder it does not know is 待確認.

## Chats with an AGY role card (engine `agy-chat`, v0.20)

*Draft. P46-2 wrote the part about what has to be true before a process may start (`vbear/runtime/agy_chat_env.py`, `admin_policy.AGY_SOURCES`, the AGY records in `cli_versions.py`); P46-3 added the process, the launch and the console's side (the second half of this section, "The process, the launch and the console's side"); P46-6 makes it final. ADR 0012 gives the reasons.*

A chat with a role card whose AI tool is AGY (Antigravity CLI) runs `agy acp` with a settings folder of VBear's and the person's own AGY login, on **the person's Google plan**. The first half of this section is what has to be true before any such process may start; the program it looks at is only `agy --version`, which starts AGY and not a model.

- **VBear's own settings folder, written by VBear.** `<state>/agy-chat-home` (0700, this user's, no link on its path, never shared with `codex-chat-home`). Before every process `write_settings` writes `antigravity-cli/settings.json` with fixed content (`toolPermission: request-review`, `allowNonWorkspaceAccess: false`, `enableTerminalSandbox: true`, `useG1Credits: false`, empty `permissions`): a new name in the same folder, renamed over the old file, 0600, so a link or a file left in its place is replaced and never written through. `settings_intact` compares the file byte for byte (a link, a folder or any other size is a no) and is what the process code asks after each turn and when the process ends. That `useG1Credits` is a key of this file is read from the binary's strings and not proven; the version check says whether AGY still starts with it.
- **What VBear never writes there is refused when found.** `GEMINI.md`, `AGENTS.md` at the top, `hooks.json`, `skills`, `workflows`, `global_workflows`, `plugins`, `projects` in `config/` (any kind of entry, a link included, compared without regard to case as the file system does), and an MCP configuration (`config/mcp_config.json`) that is not missing, empty (`{}`, `{"mcpServers":{}}`, nothing but empty values) and at most 64 KiB, a plain file read without following a link. The sentence names the entry and carries no path. Over 512 MiB, or anything that cannot be counted (a link, a special file, more than 100,000 entries), is refused too. VBear never deletes any of it and never deletes AGY's own saved conversations.
- **The person's own `~/.agents/hooks.json` stops the chat.** `home_hooks_state` does `lstat` on that one name and nothing else: a file, a folder, a link or a dangling link is a refusal, and so is any failure to tell (only "not there" passes). The file is never opened; VBear does not move it for the person.
- **The work folder (and an open shared folder) must hold nothing AGY would read as settings or rules.** `check_workdir` refuses a top level with `.agents`, `.agent`, `.gemini`, `GEMINI.md` or `AGENTS.md` (case-insensitive), and any link whose end lies outside the folder (a name is resolved to see where it ends; no file is opened; at most 10,000 entries). It is a look before the start; a link made while AGY runs is for the process code to catch.
- **The administrator policy.** `/etc/antigravity` (the whole folder) and the managed preferences domain `com.google.antigravity` refuse the chat, and an AGY version without a list cannot start. The list comes from reading the strings of the 1.5.3 binary, not from the vendor's documentation, and the domain is a candidate.
- **The binary.** The first executable `agy` on the daemon's search path (the one full-mode terminals use), at its real path, a plain file of this user or root that nobody else can write, with every folder on its way (the link's and the file's) owned by this user or root and not writable by group or others (a sticky folder like /tmp passes). `agy --version` is run from "/" with the daemon's safe environment (no `ANTIGRAVITY_*`, `GEMINI_*`, `GOOGLE_*`) and must print exactly one `X.Y.Z` line and exit 0; the file must be the same before and after the run (`cli_identity`, the six numbers a launch manifest keeps). The version must be in the code's table (`1.5.3`) and listed in `agy-chat-verified.json`, which counts a version only when the report it names is of mode `agy-chat`, passed and names that version under `agy_version` (and `"shared": "passed"` for the shared folder). AGY updates itself: a new version is unsupported or unverified until the check is run for it.
- **The answer** (`agy_chat_env.status`) is one dictionary with no path and no command output: `not_installed`, `unsupported`, `unverified`, `policy`, `hooks`, `folder`, `version_unreadable` or `ready`, in the order of the checks. Not being logged in is not a state; it shows when a chat starts.
- **The person's skills are loaded by AGY anyway** (ADR 0012, decision 1): a skill is text for the model and not a permission; every command and file change is still asked, and commands still run in AGY's sandbox. The screen says so.

### The process, the launch and the console's side (P46-3)

- **The engine is a third row of the engine table** (`chat_engines.TABLE`: tool `agy`, engine `agy-chat`, check mode `agy-chat`), and nothing else in the console branches on "which tool". A role card whose tool is AGY opens an `agy-chat` chat; the engine never changes (`card_tool_changed`), and `card_tool_unsupported` now names the three tools that chat. The chat record has the same five fields as a Codex chat's and **no new kind of event**: a test lists what an AGY chat writes and holds it to the kinds of v0.19.0. AGY's session id is kept as the `thread_id` of `session_bound`; the cost of a turn is a `turn_ended` with `estimate` and `tokens`, as for Codex.
- **A terminal never runs an AGY chat's launch.** The launch is a managed manifest of engine `agy-chat` (`agent_sessions.prepare_agy_chat_launch`): the table's model, the chat id and card id, whether it resumes (and which session), the chat folder and, for an employee with it, the shared folder (which must be the one VBear computes for the state folder, and safe). `managed_argv` refuses it (`manifest_invalid`), `agy_chat_manifest_problem` accepts nothing but exactly this shape (the common fields are checked by the terminal manifest's own checks, so the two cannot drift apart), and `load_validated` compares the recorded `settings.json` of the launch (what VBear asks of AGY: the table's settings, model, sandbox switch and argument list) with what the table says now. AGY cards in a terminal are as before: full mode only (`safe_launch` and `safe_mode` stay false).
- **The argument list and the environment come from the table and nothing else.** `acp --gemini-dir <state>/agy-chat-home --sandbox --disable-telemetry` and, with the shared folder, `--add-dir <that folder>`; a path with a control character or a newline refuses the launch. The environment is exactly `PATH USER LOGNAME LANG TMPDIR HOME`, each from the daemon's own environment, none empty, `HOME` and `TMPDIR` absolute, and it is the person's real `HOME` (AGY's login follows it): nothing named `ANTIGRAVITY_*`, `GEMINI_*`, `GOOGLE_*` or any key is passed on, whatever the daemon has. The settings, versions and forbidden names are one table (`agy_chat_protocol.VERSIONS`); `agy_chat_env` takes its constants from it and a test holds them identical.
- **Before every process the daemon checks** (and a message that fails any of it starts nothing and costs nothing): the version has constants and is verified (or is the version the chat check's own daemon is probing), the administrator policy, `~/.agents/hooks.json` (`lstat` only), the work folder's top level and, for the shared folder, its top level too, the chat folder, and then it writes `settings.json` itself. It also checks what every chat checks (one process per role card, the three places, the binary being the file that was checked, no earlier launch waiting for a person, the day's money). The chat service says the same reasons first, in words, as a courtesy; the daemon does not trust it.
- **While it runs:** each request of AGY is answered by VBear with "allow once" or "reject once" and nothing else, or with "cancelled" when a turn is stopped; a request AGY makes that VBear does not know is answered with an error. VBear answers itself when it refuses (outside the sandbox, a file outside the work folder or a protected name, the network, a tool it has no card for, a card that is too long or too many) and when it allows (a read inside the work folder or the shared folder); everything else is a card with the command (and the folder, the work folder) or each file's path and diff, or the places a read wants and the sentence that the content goes to Google. An allow is judged again when it is pressed (a folder on the path may have become a link while the card waited); that narrows a race and does not close it, as for Claude and Codex.
- **A card cannot be edited into an allow.** "Change it and ask again" refuses the original; when AGY has finished the turn, the changed text is sent as the next message (a new turn, counted and capped like any) and AGY asks again, in a card of its own. Nothing says the changed command was run. If the day's money or the chat's state does not allow the new turn, the record says the changed text was not sent.
- **A violation stops the chat at once**: something ran that VBear had not allowed, the mode was switched, a message was of another session, or `settings.json` is not byte for byte what VBear wrote (checked after every turn and when the process ends). The turn is cancelled, the process group is ended, and the turn costs its cap.
- **Money.** AGY reports tokens, only at the end of a turn. A turn costs `totalTokens` at VBear's rate (US$1 per million, up to the cent, at least US$0.01) when AGY ended it and the count adds up (the three that make it); anything else (cut off, timed out, process ended, no usable count) costs the turn's cap, and a turn that never reached AGY costs nothing. The cap is checked before a turn starts only; a turn can cost more than it, and the record says what it cost. Stopping sends `session/cancel` and waits 10 seconds for AGY's own end (its usage then counts); after that the process group is ended and the turn costs its cap.
- **What the record keeps** is the same as for a Codex chat: nothing about the plan, the sign-in methods, the thoughts, the names of AGY's commands or skills, or the chat folder's path; AGY's own copy of the conversation stays in the chat folder and is never deleted by VBear.
- **The verified list gates it.** No AGY version is verified out of the box; a message to an AGY chat on a version that did not pass `--mode agy-chat` (P46-4) is `unverified`. The console's `POST /api/chat-support/verify {"engine": "agy"}` is refused when the check could not pass anyway and otherwise starts the check (`agy_verifier`; wired by P46-4).
- **Residual risks** (final wording in P46-6): the AGY process itself is not in the sandbox and runs with the person's real `HOME` and the skills in `~/.agents/skills`; a read inside the work folder does not pass through VBear (VBear sees the path afterwards and stops the chat when it is outside, which can be too late); the sandbox writes the temporary folders; a turn can cost more than its cap; the session code's behaviour was only played against synthetic scripts until the first real run of the check.

## The start-up page (v0.12)

The start-up page (`#/setup`) installs, signs in, checks and tries AI tools for a person who may never have opened a terminal,
so what it can make VBear run is kept narrow. The details are in "Full-mode launches" above (the install and login terminals,
the status reading and 「試一下」); this section is the short list of what holds.

- **A command that VBear sends comes only from the list in `vbear/ai_tools.py`, never from the request.** The page names a
  tool and an action (`install` or `login`, and for MCODE a region); `POST /api/setup/terminals` refuses every other field
  (`command`, `argv`, `cwd`, `env`), an unknown tool or action, and a hidden tool while its switch (`show_mcode`) is off. The
  daemon's `open_setup` operation takes only those same names, looks the line up itself and types it into the person's login
  shell, where it can be seen. VBear downloads and runs nothing by itself. Grok and MCODE are on the same list under the
  same rule. The writing routes need the `X-VBear` header.
- **A status command is read by its exit code only.** For Claude Code and Codex, VBear runs the tool's own status command and
  uses only the exit code (0 means signed in; anything else, including a timeout, counts as not signed in). The output goes to nowhere:
  it is not captured, stored, logged or served. For AGY, Grok and MCODE there is no such command, so the person's
  「我登入好了」 mark is the only evidence, and the page says VBear cannot confirm it. The mark file `setup_marks.json` holds a
  tool id and a time. No tool's login folder is opened or listed.
- **A try is isolated and booked.** 「試一下」 sends one fixed sentence headless, in a new empty scratch folder (removed
  afterwards), in a new process group that is ended however the call ends, with a 60 second limit, at most 1 MiB read, one at
  a time, and a plain environment. Only whether the tool answered is read; the answer and anything about the account are
  dropped. Its cost goes into `setup-try.json` (tool, times, cap, cost) and counts toward the same daily limit as the
  meetings, staffing meetings and chats (what Claude Code reports, else US$0.01; a try that started a program is booked even
  if it fails). When the day cannot take another US$0.01, or the record cannot be read, nothing starts. Claude Code gets no
  tools and none of the person's settings; Codex runs without the person's config and rules (so no MCP servers), read-only, with its
  shell tool off (Codex 0.163.0 has no feature named `mcp`, so none is disabled by name). Codex's `--ask-for-approval` (set to `never`) is a top-level option of `codex`, so it goes before `exec` (`codex exec --help` does
  not list it). AGY has no flag for fewer tools that was checked, so it gets only the sentence. The flags were checked against
  each tool's `--help`; no real tool was run.
- **The daily limit the person picks only ever lowers other limits.** `POST /api/setup/daily-limit` accepts a number from
  0.01 to 50, writes the three limit families together or not at all, and never raises one.
- **The first-time page writes one yes/no.** `#/welcome` is shown only in the app window (judged by the native folder-chooser
  handler the window gives the page) and writes only `welcome_seen` through `/api/config`; it runs and sends nothing else. Its
  picture is an illustration the page draws itself, not a screenshot, so no part of the person's System Settings is shown or
  stored.
- **Grok and MCODE** start only in full mode, with the tick on 我了解 like the other tools; MCODE is hidden unless `show_mcode`
  is on, and the server refuses to create or switch a card to it while it is off.

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

## The AGY chat protocol (v0.20, draft from P46-1)

`vbear/runtime/agy_chat_protocol.py` (ADR 0012) is the part of the AGY chat that decides what VBear writes to `agy acp` and what it
believes of what comes back. The process that uses it is described in "Chats with an AGY role card"; what it fixes, and what `tests/test_agy_chat_protocol.py` and rules 14a–14c of `tests/test_autonomy_guard.py` hold it to:

- **The command line is one table**: `acp --gemini-dir <state>/agy-chat-home --sandbox --disable-telemetry`, and `--add-dir <shared
  folder>` for an employee who has it. The switches that skip permissions, sign in, move the app data or load the person's default
  customizations are never passed, and no file that builds the command names them.
- **The settings file is one fixed byte string** (`request-review`, terminal sandbox on, non-workspace access off, paid credits off, no
  permission rules); VBear writes it before every process and compares it after every turn.
- **Only two answers exist**: the option of kind "allow once" and the one of kind "reject once", chosen by kind, and the cancelled outcome. A
  list of options that does not hold exactly one of each is not answered "yes". The two kinds that would remember an answer are named in one
  constant and are never a value to send.
- **A request to run outside the sandbox (`BypassSandbox`, any value but `false`) is refused by VBear with no card.** So is anything that
  reaches the network, and any kind of tool VBear has no card for.
- **File tools are judged by VBear** (they are not in AGY's sandbox), every place the call names (a move names where it goes; a move with no
  destination is refused; any member of the raw input that is not on a short list of describing or content ones is read as a possible place,
  and one that cannot be read is refused): inside the work folder (or the shared folder the employee has), links
  followed, none of `.git`, `.agents`, `.agent`, `.gemini`, `.codex`, `.claude` or a `GEMINI.md` / `AGENTS.md` at any depth, no file with another
  hard link, and a card that fits; otherwise refused with no card. A read inside the folders is VBear's own yes; outside, a card that says the
  content goes to Google.
- **The chat stops (a violation) when** a command, a file change, a network use or any other tool ran and VBear had not answered "allow once"
  (or the call changed after the yes: any member of its raw input but a short list of describing ones, or `BypassSandbox`, or the kind of tool), a read ran outside
  the folders without a request, a search ran without a request unless every string in it is a bare name, the work folder has no link to the
  outside and every place it names is an absolute path with no `~ { * ? [` inside the folders (a member named like a pattern is never a place, and a string in one that holds `/`, `..` or `~` makes a read or a search a card, never VBear's own yes; the rule of a Claude chat's Glob and Grep), the mode is not `default`, a message is of another
  session, or the model could not be set. The tracker reads nothing after that.
- **AGY 1.5.3 announces a command or file change as `in_progress` before it asks, and only that exact order is not a violation.** For those kinds (`announced_kinds` of the version table) the order is `tool_call` in_progress, `tool_call_update` pending, `session/request_permission`, the answer, and after a refusal `in_progress` (once) and then `failed` or `cancelled`; an extra `in_progress`, any other order, an unknown status, any output (text or an exit code) before a yes, a call that completes or fails without being asked, and a call still announced when the turn ends are all violations, and a yes is still checked against what runs (the signature); for every other kind and version `in_progress` without a yes stops the chat.
- **AGY's own built-in skills and plugin are pinned by name.** The chat folder's `antigravity-cli/builtin` is the one place where names like `skills` and `plugins` pass the forbidden-name scan, and only as the exact paths the version table lists (`builtin_paths`); any other path there, a link, or the same names anywhere else is refused.
- **`antigravity-cli/persistent_terminals`, which AGY makes when it runs a command, is a closed folder**: it is in the table of names AGY makes (`home_created`) but only the names the table lists for it (`cli_closed`, none yet) may be inside, so anything in it is refused by name until a real run shows what AGY puts there. The built-in table lists all 62 paths of a real AGY 1.5.3's `builtin` (fourth real run) one by one; `builtin/.manifest` is only compared with them in the check's report and never decides anything.
- **Nothing about the person is kept**: not the plan name, the sign-in methods, the thoughts or the names of the commands and skills.

What is still only synthetic: the fixtures are built from the investigation's facts and ACP's public formats, since its raw messages were not
kept; `docs/evidence/agy-1.5.3-chat.md` section 11 lists what the first real `--mode agy-chat` run must confirm.
