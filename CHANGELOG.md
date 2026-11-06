# Changelog

## v0.15.0 — the chief of staff

On the CEO's chat page, 請幕僚長安排 lets VBear's chief of staff read your recent conversation with the CEO and propose who
does what. You read and change the proposal on a card, press 確認派工 once, and VBear makes the new employees and sends the steps to
your employees, one chat per step. It never answers a permission card (every command and every file change is still asked of
you), never changes a limit, never starts a terminal or full mode and never installs a skill, and the whole run can be stopped
and read in 「AI 自己做了什麼」. Six tasks (P40-1 to P40-6; v0.14 was never released, so this version follows v0.13.0):

- **The chief of staff's one call (P40-1).** `vbear/chief.py` (pure: which messages are read, the list of employees as codes
  C1.., the answer's schema with `additionalProperties: false` and no field for a limit, mode, skill, URL or path, and
  `validate_plan` with its three layers: a badly formed answer is void, what is off the list is removed with a note, a plan
  with nothing left is void as `empty_plan`) and `vbear/chief_runner.py` (a board of one turn on the meetings' engine
  `board_engine.HeadlessBoard`: tool-less, `sonnet`, effort low, `min(US$0.30, what is left of the day)`, 120 seconds, the init
  event must list only `StructuredOutput`). `GET /api/chief/preview?chat_id=`, `POST /api/chief`, `GET /api/chief`,
  `GET /api/chief/<id>`, `POST /api/chief/<id>/retry` and `/cancel`. Its records are `<state>/chief/` and count in the day's
  ledger (`GET /api/meetings/ledger` lists `chief` in `includes`). The record keeps counts, sizes and SHA-256 sums, not the
  conversation.
- **自己動手, two items (P40-2).** `vbear/autonomy.py`, `GET/POST /api/settings/autonomy` and a section of the settings page.
  Item 1 lets the chief of staff make new employees by itself; item 2 lets it start a clean proposal by itself. Both are off by
  default, each asks a plain question before it is turned on, and nothing but that POST changes them. The other three items
  of ADR 0003 come later (v0.18.0). `tests/test_autonomy_guard.py` reads the source of `vbear/chief*.py`, `vbear/dispatch*.py`
  and `vbear/autonomy.py` and fails on an import or call that changes a limit, starts a terminal or full mode, or installs a skill.
- **The dispatch record and its confirmation (P40-3).** `vbear/dispatch.py`, `<state>/dispatch/d-<12 hex>.json`: states
  proposed, confirming, running, paused, done, stopped, dismissed; append-only events, each saying who decided
  (`by`: `you`, `auto1`, `auto2`, `vbear`). Confirming checks the plan again, only more strictly, then makes the new employees (safe
  mode, no skill, the fixed instruction text of the position) and a task card. `POST /api/dispatch/<id>/confirm|dismiss|stop|
  continue|withdraw-card|delete`, `GET /api/dispatch`, `GET /api/dispatch/<id>`, `GET /api/actions`. A message a dispatch
  sends is marked `origin = {dispatch, step}` in the chat record (`chat_store`, an optional field of `user_message`).
- **The runner (P40-4).** `vbear/dispatch_runner.py`, a thread started by `serve()`: one step at a time, each in a new chat,
  sent with `ChatService.send_for_dispatch`; a step goes out only after the one before ended normally, with that step's last
  reply handed on between `BEGIN_UNTRUSTED_JSON_STRING` and `END_UNTRUSTED_JSON_STRING` (at most 8 KiB, said to be data). It pauses and
  says why (the daily limit, a Codex plan limit, a busy chat, a step it cannot account for after a restart, a turn that ended in an error), 繼續 and 停止 are
  the person's. 繼續 skips a step that was sent and did not end normally. The step events name the step in the field `step`.
- **The pages (P40-5).** The CEO chat page gains 請幕僚長安排 and its dialog (what is read, where it goes, the most it can cost,
  what is left today, a note); the proposal card (edit the words, delete a step, swap the employee, change a new employee, 「你改過」
  marks, the most it can cost, 確認派工, 不採用); `#/dispatch` and `#/dispatch/<id>` (every step's state, 停止, 繼續 with a sentence
  that it skips the step that did not finish, taking back an employee VBear made, deleting); `#/actions` 「AI 自己做了什麼」
  (every action and who decided; a link from the settings page's 自己動手 section); the lobby's 輪到你 lists a proposal to confirm and
  a dispatch that is paused; a chat message sent by a dispatch says 「VBear 依派工送出」. Plain words for `empty_plan` and the other
  codes; a Codex CEO card says that the conversation goes to Claude Code; a Mac with Codex only reads 「幕僚長目前需要 Claude Code」.
  `GET /api/dispatch/<id>` also carries `tools` (the AI tools a new employee may name) and the actions carry the `profile_id` of a card a
  dispatch made. `tools/qa_p40.py` is the real-machine check through the HTTP API (it needs `--state`).
- **Fixes from the real-machine check (P40-6).** Claude Code 2.1.319 can chat: it has chat constants and an administrator-source
  list (its `--help` is identical to 2.1.318's and its binary names the same places; evidence in `docs/evidence/claude-code-2.1.318-chat.md`),
  but it is **not** yet verified and chats only after `boundary_check --mode chat` passes on your Mac. A chat now also picks, among
  the versions in Claude Code's own `versions` folder, the newest that passed the chat check, else the newest VBear has constants for,
  else PATH's; a version without constants is told in words which versions work. A new employee taken back before you confirm is
  now refused at 確認派工 (it used to start and then pause). Smaller: 「你按的」 in the actions list beside a withdrawal, stop,
  continue and dismissal; the chief of staff no longer writes how VBear will go about it, and the card says what really happens to
  the new employees; `tools/qa_p40.py` got its own fixes and `--from <dispatch id>`.
- **Documents.** `docs/SECURITY-MODEL.md` has "Chief of staff and dispatch" with its residual risks: the previous step's reply
  handed to the next step is a prompt-injection path, and an employee's allowed commands can read VBear's access token and call
  VBear's API, so VBear guarantees only that its own chief of staff and dispatch code do not do the three forbidden things.
  `docs/adr/0006-chief-of-staff-dispatch.md` records the decisions; both READMEs, `docs/ARCHITECTURE.md`,
  `docs/REFERENCE.zh-TW.md` and `GLOSSARY.md` (派工, 提議卡, AI 自己做了什麼; 幕僚長 and CEO updated) say what it is.
- **Money.** The chief of staff's call is counted in the day. A step is a chat turn under the chat's per-turn limit and the daily
  limit; the proposal card says the most it can cost (steps × the per-turn limit) and what is left today before you confirm. When
  the daily limit is reached the dispatch pauses, and 繼續 is yours; nothing counts down or goes on by itself in this version.
- **Not run on a real machine for this change:** that a real Claude Code fills the schema, that a closed chat stops being busy at
  once, that the second employee treats the handed-on reply as data, and the `resets_at` unit of a Codex plan limit. A Claude plan
  limit is not told apart from another error in a chat's record, so its pause carries no resume time. No code or test ran a real AI tool.
- **Going back to v0.13.0.** v0.13.0 does not know the dispatch. A chat message that a dispatch sent has an `origin` field that
  v0.13.0 does not accept in a `user_message`, so v0.13.0 reads that record as damaged: it lists the chat with a problem, cannot send to
  it and cannot delete it, and, as for the chats of v0.13.0 read by v0.12.0, it counts what it cannot read as spend it does not
  know, so on the day such a chat was written it refuses to start any meeting, staffing meeting or chat (`spend_unknown`) until you
  move that chat's folder out of `<state>/chats/`. Delete or move the chats of dispatched steps before going back. `<state>/chief/` and
  `<state>/dispatch/` are left alone and unread, and v0.13.0 does not count the chief of staff's calls in the day, so
  on a day you asked for proposals its ledger shows less than was spent. The employees and task cards a dispatch made are plain cards and stay. The
  config key `autonomy` stays in `config.json`, unread (v0.13.0 keeps keys it does not know). This was read from the v0.13.0 code and was not run.

## v0.13.0 — Codex chat

A role card whose AI tool is Codex can be chatted with, as one whose tool is Claude Code already could. Every command and every
file change is asked first, none is ever allowed from now on, and the cost is an estimate on your ChatGPT plan. A Codex
version chats only after it has passed `python3 -m vbear.boundary_check --mode codex-chat` on your Mac. Six tasks (P38-1 to
P38-6):

- **Protocol and a stand-in Codex (P38-1).** `vbear/runtime/codex_chat_protocol.py` holds, for Codex 0.163.0, every line VBear
  writes to `codex app-server` (it never writes `acceptForSession`, an execpolicy or network amendment, or `cancel`), the
  notices and requests it understands, what it counts as a violation, and the estimate of money from tokens. The ten short
  turns recorded with the real 0.163.0 are kept, scrubbed, in `tests/fixtures/codex-chat/`, and `tests/fake_codex_app_server.py`
  replays them, so no test runs the real `codex`.
- **A Codex login of the chat's own (P38-2).** `codex app-server` cannot be told to ignore your own `~/.codex` (your
  `AGENTS.md` and MCP servers were read in the recorded run), so the chat uses `<state>/codex-chat-home` and you log in to it once
  more. The start-up page's Codex row gains 讓聊天用的 Codex 登入, which types one fixed line into a terminal
  (`CODEX_HOME=<that folder> codex login -c cli_auth_credentials_store=file`; the page sends a tool and an action, never a
  command). The state is the exit code of `codex login status` alone. VBear refuses the folder when it holds a `config.toml`,
  `rules/` or `AGENTS.md`, has a link on its path, or passes 512 MiB. The Codex that runs is the pinned one under
  `~/.codex/packages/standalone/releases/`, never one from `PATH`; `codex-chat-verified.json` lists the versions that passed;
  the administrator-policy sources of 0.163.0 are the 0.160.0 list (`/etc/codex`, the managed preferences domain
  `com.openai.codex`). `docs/evidence/codex-0.163.0-chat.md` keeps what all this rests on.
- **The daemon runs Codex chats (P38-3).** A new engine `codex-chat` (`runtime/codex_chat_session.py`): one `codex app-server`
  per role card, at most three chats in all with the Claude ones, an environment of exactly seven variables, `untrusted` approval
  with reviewer `user`, and asks for the legacy `workspace-write` sandbox (the card's folder as its only writable place, network off, no `/tmp`; an allowed command may still run outside it, see below). A command
  is a card with its whole text; a file change is a card with each file's path, kind and diff, unless a path is outside the folder
  or under `.codex`, `.agents` or `.git`, which is declined without a card. A changed command is not "allow, changed": VBear
  declines it and sends `turn/steer`, and Codex asks again in a card of its own. Anything that shows VBear's settings are not
  in force stops the chat (an extra MCP server, another thread, a command completed without a yes, a changed policy). The chat
  record is version 2 (`chat.json` gains `engine`; version 1 files read as `claude-chat`) with the records `session_bound`,
  `usage`, `plan_usage` and `card_edit_sent`, and a turn's end gains `estimate` and `tokens`.
- **The version check (P38-4).** `python3 -m vbear.boundary_check --mode codex-chat` runs one real chat through VBear's own
  Codex code in a temporary state folder, with seven messages (text; `ls -a` must make a card, and a denied `rm`; a changed
  command; a file change; `apply_patch` outside the folder; stop; `thread/resume`), about fourteen short model calls on your ChatGPT
  plan and at most US$0.30 by VBear's own counting, not added to the day's ledger. A pass writes `codex-chat-verified.json` and a
  0600 report that is read back every time. The report holds no Codex home, user agent, plan kind, credits or e-mail-like text.
- **The console and the page (P38-5).** `POST /api/chats` reads the role card's tool and fixes the chat's engine for good; a
  card whose tool is Grok, AGY, MCODE or shared is refused with `card_tool_unsupported` (this replaces `card_not_claude`), and
  a card whose tool changed after the chat began gets `card_tool_changed` and nothing starts. `GET /api/chat-support` keeps
  Claude Code's keys and carries a `codex` object (not installed, not verified, administrator policy, folder refused, version
  unreadable, not logged in, ready); `POST /api/chat-support/verify` takes `{"engine": "codex"}`
  (`vbear/codex_verify.py`; no engine still means Claude Code). The chat page names each chat's AI tool, shows the notice of the
  chosen card's tool, and for Codex draws the command card (command, folder, what Codex says it does), the file card (path,
  what is done, diff, as text), 改內容再問 (VBear refuses the original and Codex asks again, so you allow once more), each
  reply's cost as 「估計 US$0.02」 with the token count and 「不是帳單」, one line of the ChatGPT plan's use as Codex reports it
  (and the reset time only when a limit was reached), and a deletion note saying Codex's own copy of the conversation in
  `codex-chat-home/sessions` is not deleted. `session_ready` records the CLI's version in `cli_version` (Claude chats keep
  `claude_code_version`; both read). The chat note on the page now says chats work with Claude Code or Codex. New sentences
  for `card_tool_unsupported`, `card_tool_changed` and `codex_version`; `not_logged_in` and `codex_home` have theirs.
  **Money:** Codex reports tokens, not money. A turn is estimated as tokens ÷ 1,000,000 × US$1.00, rounded up to the cent, at
  least US$0.01 (VBear's accounting rule, not a price), and counted in the same `meeting_limits.daily_usd`; a turn cut off
  without a count costs its cap. Two token reports can be a model call apart, so a turn can pass its cap by about one call.
  **Reading is not limited:** the sandbox does not limit reads, so a command you allow can read the whole machine; the
  permission profile that would stop reads made file changes fail on the recorded version.
  Documents: `docs/SECURITY-MODEL.md` has "Chats with a Codex role card" with its residual risks, `docs/adr/0005-codex-chat-boundary.md`
  records the decisions, and both READMEs, `docs/ARCHITECTURE.md` and `docs/REFERENCE.zh-TW.md` say what Codex chat is.
- **A home folder that is a git repository.** Found before release: Codex took `~` for the project root, read the person's own
  MCP servers and skills as a project's, and wrote that trust itself. A Codex chat now starts with `project_root_markers=[]` and
  the work folder's trust set to `untrusted` (both `-c`, the second an inline table), asks `mcpServerStatus/list` with the
  thread's `threadId`, and the version check asserts both were sent and that no `config.toml` appears; a `config.toml` already in
  the chat folder is refused with a plain reason, never deleted (`docs/evidence/codex-0.163.0-chat.md`).
- **An allowed command can run outside the sandbox.** Found on a real Mac, then read in the Codex source: under `untrusted`, when
  the sandbox stops a command you allowed, Codex runs it again without the sandbox and does not ask again, and a command the model
  asked to run outside the sandbox (`require_escalated`) does so the first time you allow it. Such a command can write anywhere
  your account can write and can reach the network, and the card cannot tell which it will be. So a Codex command card now says,
  above 允許這一次: 「允許後，這個指令可能在沙盒外執行：能改到工作資料夾以外的檔案，也能連網。只允許你看得懂、確定沒問題的指令。」
  A Claude chat's card and a Codex file card are unchanged; VBear still declines a file change outside the work folder or under
  `.codex`, `.agents`, `.git` by itself, with no card. The version check's `outside` step now requires only that `apply_patch`
  outside the folder is declined with no card and leaves no file (`outside_patch_refused`); whether the allowed shell write got
  out is only noted in the report and the file is removed. You chose this over the permission profile (every command asked and
  kept in the sandbox, but `apply_patch` fails in it) and over `never` (no cards, reads unasked); VBear will move to the profile
  when Codex fixes `apply_patch` there (`docs/adr/0005-codex-chat-boundary.md`, decision 7; `docs/evidence/codex-0.163.0-chat.md`, 5b).
- **Packaging copies stay out of Spotlight and Launchpad (P38-6).** `macos/build.sh` keeps every `VBear.app` it leaves on disk
  in a folder whose name ends in `.noindex` (`build/app.noindex`, `build/dmg.noindex`, `dist/app.noindex`); the DMG stays
  `dist/VBear-<version>-arm64.dmg`. The release workflow's smoke check reads the new path. It deletes only the old copies inside
  the repository.
- **The first CEO (P38-8).** After all your AI tools were logged in, pressing 開始使用 left a person with an empty lobby and no
  idea what to do (and with 「輪到 p」 and a card for a deleted task at the front of it). Now, when there is no role card you can
  chat with, 開始使用 leads to `#/ceo`, 建立你的 CEO: a card named CEO (position CEO, safe mode, a short plain description you can
  change) on the ready Claude Code, else the ready Codex; one press makes it and opens a chat with it, with the opening sentence
  「你好，請先問我三個問題，了解我想做什麼。」 only put in the box (you can change it; only your own press of 送出 sends it, so
  nothing is spent by the step). `GET /api/first-ceo` (`vbear/first_ceo.py`) tells the page whether the step is needed, which
  tool the card takes (a tool that is only marked as logged in, such as AGY or Grok, is never chosen; with no ready tool it says
  to go back to 開始設定) and the words to fill in; the card itself is made by the ordinary `POST /api/agent-profiles`. The
  config key `first_ceo_id` makes the lobby offer 跟你的 CEO 聊聊 once (until pressed, put away, or you have already talked
  with that card); while there is no card, the lobby offers 建立你的 CEO. A CEO is a plain role card: it chats and turns your idea
  into a plan; it cannot create employees or hand out work (the chief of staff, v0.15, will). In the lobby, flows whose task card
  is deleted or unreadable are folded away under 「其他進行中的任務」 (closed until you open it), and a role named with one or
  two letters or digits reads 「輪到規劃者」, 「輪到執行者」, 「輪到審查者」 instead of 「輪到 p」.
- **Not run on a real machine for this change:** the real Codex was never run by the code or its tests; whether `turn/steer` is
  accepted without the experimental API, whether Codex ends when its stdin closes, what `turn/interrupt` answers, and that a
  login writes nothing into the chat folder are for the first real `--mode codex-chat` (see section 7 of the evidence file).
- **Going back to v0.12.0.** v0.12.0 does not know Codex chats or the version 2 chat file. Every chat made by v0.13.0, a Claude
  chat included, has a `chat.json` that v0.12.0 reads as damaged: it lists the chat with a problem, cannot send to it and cannot
  delete it, and the files stay. A Codex chat's record also holds kinds v0.12.0 does not know (`session_bound`, `usage`,
  `plan_usage`, `card_edit_sent`), and v0.12.0 counts a record it cannot read whole as spend it does not know, so on the day such
  a chat was written it refuses to start any meeting, staffing meeting or chat (`spend_unknown`) until you move the chat's folder
  out of `<state>/chats/`. Chats made by v0.12.0 itself read as before in v0.13.0. Move or delete the Codex chats before going back.
  `codex-chat-home/` and `codex-chat-verified.json` are left alone and unread, and a role card with the Codex tool reads as
  before (v0.12.0 refuses to chat with it). v0.13.0 adds no config key. The launch records of Codex chats under `sessions/` are
  an engine v0.12.0 does not know; how it treats them was not checked. This was read from the v0.12.0 code and was not run.

## v0.12.0 — the start-up page

The start-up page: a new person is taken through installing and signing in to an AI
tool, picking a daily limit and trying the tool once, before anything else.

- **A start-up page (`#/setup`, 開始設定) and a left-menu entry.** It lists the AI tools side by side (Claude Code, Codex,
  Antigravity (AGY), Grok; MCODE only while it is switched on) with where each stands: 還沒安裝, 還沒登入 or 就緒. 安裝 and 登入 open a
  terminal inside VBear and type the tool maker's own install or login line into it; the line comes only from the list in
  `vbear/ai_tools.py` (the page sends a tool and an action, never a command), and the person sees it and the shell runs it.
  MCODE's login has two buttons, one per region. Claude Code and Codex are checked with their own status command and only
  the exit code is used (0 means signed in; the output is not captured, stored or served); AGY, Grok and MCODE have no such
  command, so the person presses 我登入好了, and the page says VBear cannot confirm it. The mark is kept in `setup_marks.json`
  (tool id and time only). Nothing reads any tool's own login folder. The page reads the tools again every 5 seconds (a look
  is kept for 30 seconds, and a forced recheck, a mark, a terminal or a try makes the next look fresh). The runtime daemon
  has one new operation, `open_setup`, which takes only a tool, an action, a region and a terminal size.
- **First time, and upgrading.** New config keys `setup_done` and `setup_notice` (both false by default, written through
  `/api/config`, booleans only). The home page sends a person who has not finished and has no ready tool to `#/setup`;
  someone who already has a ready tool when they upgrade is counted as done and told once. If the server cannot say, nobody
  is forced anywhere.
- **A first-time page (`#/welcome`, 第一次打開 VBear), app window only.** Shown once, before the start-up page, and it can be
  skipped. It says what to do when the Mac stops an app that is not signed with an Apple Developer ID: System Settings,
  隱私權與安全性, press 強制打開 (the same as the README's Open Anyway steps). Its picture is an illustration the page draws
  itself, not a screenshot, so nothing from anyone's real settings is in it, and it says so. Whether it is the app window is
  judged by the folder chooser the app window gives the page (a browser does not have it), so a browser never gets the
  page. New config key `welcome_seen` (false by default, boolean only) is set when it is read or skipped.
- **Grok and MCODE as employees.** Grok (xAI's Grok Build) and MCODE (MiniMax Code) can be put on role cards and started in
  full mode (`grok [-m X]`, `mcode [-m X]`); neither has a safe mode, and the instructions go in only through 貼上職位指示.
  MCODE is hidden: the config key `show_mcode` (false by default) is switched on by 「顯示 MCODE」 in the settings. While it is
  off, MCODE is not offered anywhere, cannot be given to a card and is left out of the staffing proposal's tool list; a card
  that already uses it is kept and says why it cannot be chosen. VBear now also looks for the tools in `~/.grok/bin` and
  `~/.minimax-code/bin` after `~/.local/bin`. xAI and MiniMax are two more makers, each its own family for the independent
  review rule.
- **Full mode needs a tick on 我了解, and new cards start in safe mode.** A full-mode launch is refused with
  `full_mode_not_acknowledged` (409) unless the confirmation carries `accept_full_mode: true`; the pass shows 「這個員工可以動
  你電腦上的任何檔案」 and 確認啟動 stays off until the box is ticked. New role cards start in safe mode when their tool has
  one (only Claude Code), otherwise in full mode with the reason; the catalog's default is `safe`. Cards that exist are not
  changed. Codex has a safe launch in the tool list but VBear refuses it for its interactive mode, so in practice Codex runs
  in full mode only.
- **試一下.** Each installed tool has a button that sends one fixed short sentence headless, in a new empty scratch folder
  and a new process group that is ended however the call ends, with a 60 second limit, and reads only whether it answered
  (the answer and anything about the account are dropped, never stored). The page says it costs about under US$0.01 and
  needs a second press to confirm. The result is success, not logged in, timeout, not found or an answer VBear cannot read.
  The cost is kept in `setup-try.json` (tool, times, cap, cost) and counts in the same day as the meetings, staffing meetings
  and chats: what Claude Code reports, else US$0.01 (a try that started a program is booked even when it fails); when the
  day cannot take another US$0.01 nothing starts. The ledger's `includes` list gains `setup_try`.
  Codex's try puts `--ask-for-approval never` before `exec`, because it is a top-level option of `codex` and
  `codex exec --help` does not list it; the other flags were checked against each tool's own `--help`. None of these calls
  was run against a real tool for this change.
- **Choose a daily limit (每天上限) on the start-up page.** US$1, US$3 (the default) or US$10, each with a sentence on what
  it roughly covers, written for the default per-call limits. It sets `meeting_limits.daily_usd`, shared by chats, meetings,
  staffing meetings and tries, and only ever lowers the other limits that would otherwise be above it (the meeting, per
  call, staffing total and chat turn limits); choosing US$10 raises none. The same rule now applies when
  `meeting_limits` is written through `/api/config`.
- **A note where a page needs Claude Code.** The meetings, staffing meetings, chat and skill-translation pages show
  「這個功能目前需要 Claude Code」, how to get it and a button to the start-up page when Claude Code is not ready; when the state
  cannot be read nothing is shown and the page works as before.
- **The tool list is in one place (`vbear/ai_tools.py`).** The Python tables that used to repeat the tools (profiles,
  position guide, flows, launch, runtime, the catalog's `tool_list`) are built from it, and a test keeps the page's own copy
  equal to it.
- **Sentences that said VBear cannot start AGY are corrected.** They now say safe mode does not start AGY and full mode does,
  for example 「安全模式不會啟動 AGY，要出發請選完整模式」.
- **Documents.** Both READMEs describe the start-up page, Grok and hidden MCODE, Codex as full mode only, the daily limit,
  the 我了解 tick, safe mode for new cards, what a try costs and the first-time page. `SECURITY.md` and
  `docs/SECURITY-MODEL.md` say that the start-up page's commands come only from the server's list, how a try is isolated
  and booked, and that status commands are read by exit code only.
- **Going back to v0.11.0.** v0.11.0 reads the new config keys (`setup_done`, `setup_notice`, `welcome_seen`, `show_mcode`)
  as extra keys and leaves them in `config.json`; it leaves `setup_marks.json`, `setup-try.json` and `setup-try.blocked` as
  they are, and it has no start-up page. **v0.11.0 does not count tries in the day's ledger**, so on a day that tries spent
  money here it lets meetings spend the whole of `meeting_limits.daily_usd` again. Daily limits lowered by the start-up page
  stay lowered. **Role cards that use Grok or MCODE are the one thing to fix first:** v0.11.0 does not know those tools and
  treats `agent_profiles.json` with such a card as damaged. It moves the file aside, marks it, and stops reading and writing
  role cards until you recover it by hand. Before going back, change those cards to another tool or delete them (switching
  `show_mcode` off is not enough). This was read from the v0.11.0 code and was not run; flows and task cards that name a
  Grok or MCODE card were not checked.

## v0.11.0 — chatting with role cards

You can now talk with a role card. Pick an enabled card whose tool is Claude Code, say something, and the card answers
through your own Claude Code in its own work folder. When it wants to run a command, change a file or write one, a card
asks you and nothing happens until you allow it. A chat uses your Claude usage, and no Claude Code version is allowed to
chat until it has passed a real check on your Mac.

- **A chat page (`#/chat`, `#/chat/<id>`) and a chat button on a role card.** The list shows the chats, the day's
  lamp and spend, and the cards you may open a chat with. A card that is off or whose tool is not Claude Code is listed
  with the reason and cannot be picked; the card's own 聊天 button is shut for it the same way. A chat is opened only
  by 開始聊天 and costs nothing until you send a message. One chat shows the record in order (what you said, the reply,
  each tool the card used and its result, each card and how it ended, what each turn cost), the reply while it is being
  written, a stop button, and a delete button. The first visit opens a short explainer: what it is, what it costs, that
  nothing runs without your yes, and which instructions go in.
- **Permission cards.** Bash, Edit and Write always ask. Each card says what is asked and has 允許這一次, 拒絕 and
  改內容再允許 (the command, the content or the new text is yours to change; a card with nothing to change has the other
  two). There is no 「以後都允許」. A card can be answered once, within 5 minutes; after that it is refused for you, and the
  record says so. When you press allow, VBear judges the call again as it will be sent: an Edit or Write that is now
  outside the work folder is refused with the reason (`refused`). Reading inside the work folder is allowed without a
  card.
- **Whose instructions go in.** Only the instructions you wrote on the card, as one `--append-system-prompt` argument
  (the flag is in Claude Code 2.1.318's `--help`). The default text of the card's position is never sent, and a card
  with no instructions of its own sends none; each chat says in its record whether instructions went in. Claude Code
  keeps the system prompt of a session when it is resumed (`--system-prompt-snapshot` is on by default), so editing the
  card does not change a conversation that has begun. **This was not checked on a real machine**: neither that Claude
  Code applies the appended text nor how it treats an edited one on resume. The chat check records whether the first
  reply followed a made-up instruction, as an observation and not as a pass condition.
- **Money.** A turn costs at most `chat_limits.per_turn_usd` (new top-level key of `config.json`, US$0.50 by default,
  US$0.01 to US$5, never more than the daily limit) or what is left of the day, whichever is smaller. The chats count
  in the same day as the meetings and the staffing meetings: `meeting_limits.daily_usd` covers all three, and the
  lamp says so. Amounts are Claude Code's estimates, shown as such; a turn whose cost Claude Code did not report is
  counted at its cap. On a red lamp, or with less than a cent left, no message is sent.
- **Which Claude Code may chat.** No version is chat-verified out of the box. The page shows the detected version and
  whether it passed; for one that did not, 驗證聊天 runs `python3 -m vbear.boundary_check --mode chat` after telling you
  it makes about six small Haiku calls on your own login. It opens a chat with a made-up card in a temporary state
  folder and sends six messages: a streamed text turn, a Bash card allowed with a changed command (which also tries a
  write inside and outside the work folder), a Bash card denied, a Bash card answered with the error VBear gives a
  request it does not know, a resumed process that must remember a code word, and a resume under the smallest budget.
  It judges from the events VBear recorded and the files left behind: the initialize answer was accepted, every Bash
  asked, the chosen command ran, a denied one did not, the sandbox stopped the write outside, no shared-tmp error, the
  total is cumulative across a resume, `system/init` named no extra folder and no MCP server, nothing from the
  initialize answer was kept, the check cleaned up. Only a pass writes `<state>/claude-chat-verified.json`; the version
  counts only while the report it names (mode `chat`, passed, the same version, owned by you) reads back, so a record
  without a passing report counts for nothing. It also records what a resumed session's `--max-budget-usd` counts (it
  can tell only when the session already spent more than the smallest budget). The check's few cents go on your
  Claude account and not into the day's ledger.
- **Administrator policy for 2.1.318.** The version has its own list of the places Claude Code reads policy from: the
  directory `/Library/Application Support/ClaudeCode`, the managed preferences for `com.anthropic.claudecode`,
  `~/.claude/remote-settings.json`, and, new in this version, `~/.claude/policy-limits.json`. If any exists, or its
  existence cannot be established, no chat starts and the page says which. The last one is stricter than the older
  versions on purpose: nothing says what it can change. The evidence is in
  `docs/evidence/claude-code-2.1.318-chat.md`. **If your Mac already has `~/.claude/policy-limits.json`, chats stay
  shut.**
- **No settings of yours are read by a chat (`--setting-sources ""`).** Found by running the check on the real 2.1.318:
  `system/init` still named the extra folders of your own Claude user settings, which `--settings` cannot remove, so the
  chat was stopped and the check failed. The chat's argv now loads no user, project or local settings, so VBear's own
  settings are the only ones; your login still works. A chat therefore does not see your own permission rules, extra
  folders or hooks. `additionalDirectories: []` and the check of `system/init` stay as a second layer.
- **A Python without `os.waitid` starts no chat.** macOS's own `/usr/bin/python3` (3.9) has none, and VBear needs Python
  3.13 or newer. The check and a chat now say so (`unsupported_python`) before starting anything; before, the first turn
  ended in an `AttributeError` and left a process for a person to look at. An unexpected error while a chat process is
  managed now ends the process (after the identity check) and cleans up its launch instead of leaving it.
- **Every refusal is said in words.** The console answers a refusal with a sentence, not a code: 這張卡片過期（5 分鐘）,
  VBear 又檢查了一次所以拒絕 (`refused`), 員工的程序正在換新的所以你的訊息還沒送出 (`restarting`, tried again by itself
  a few times first), 今天已經花了多少讀不出來 (`spend_unknown`), and 這個聊天的紀錄有問題 (`damaged`: it is not written
  to, not sent to and not deleted, because deleting it would drop what it spent from the day). A test reads every code
  the runtime can give and fails until it has a sentence.
- **A meeting turn skipped because the day's spend is unknown** now reads 無法確認花費, with the reason underneath,
  on a meeting and on a staffing meeting, instead of 沒有發言.
- **Under the chats.** The console talks to the runtime daemon, which owns the chat processes and is the only writer
  of a chat's record. `GET /api/chats/<id>/stream` is a live view as server-sent events and needs the same `X-VBear`
  header as every write (the page reads it with `fetch`, and polls when the stream cannot be had); at most four
  streams are open at once. Nothing of what a chat's initialize answer carries (the account, the commands, the models,
  the extra folders) is kept or sent to the page.
- **Going back to v0.10.0.** v0.10.0 does not know chats: it leaves `chats/`, `chat-work/`, `chat-spend/` and
  `claude-chat-verified.json` as they are, and `chat_limits` stays in `config.json`. **v0.10.0's daily ledger does not
  count what the chats spent**, so on a day a chat spent money here, v0.10.0 lets meetings spend the whole of
  `meeting_limits.daily_usd` again. A meeting turn this version skipped for an unknown spend shows there as 沒有發言 with
  代碼：spend_unknown. The explainer's "seen" mark is kept in this browser only.

## v0.10.0 — staffing meetings, shorter meetings, and adopting a team step by step

The CEO card can now staff a task card: the positions say who and which skills the task needs, the CEO writes a staffing
proposal, and you change it as a draft and adopt it one step at a time, each step a button you press. Meetings got
shorter: Claude Code thinks at low or medium effort and a meeting runs on a clock. This section is everything since
v0.9.0; going back to v0.9.0 is described once, at the end.

- **A staffing meeting (組隊會議) asks the CEO card to staff one task card.** 請 CEO 組隊 on a task card (in the lobby,
  the workbench and its team board) opens a form (`#/staffing?task=`) with the speakers VBear ticked from a fixed table,
  one enabled card per position, each with its reason (固定規則，不是 AI 判斷); you change any of it. A disabled card
  cannot speak, but the CEO may propose it. The preview shows every text each call sends, the models and the effort, the
  money it reserves (each speaker's call and the CEO's), the day's lamp and how many cards and skills the list left out;
  only 開始組隊會議 starts it. Each speaker says once, alone, then the CEO writes the proposal: who goes in the four places of
  the task card, which staff to bring to a meeting, which new cards to make, the skills for each card, the skill gaps,
  the risks, the questions for you, and which opinions it adopted and which not, with why. Cards and skills are sent
  under aliases (`C1`, `S1`, ...), never their ids; the page shows each alias as the card's or the skill's name today,
  or 「找不到」. A skill gap comes with a search of this console's skill library, never a link out. Each record is a
  file of its own in `staffing/`.
- **What a staffing meeting costs, and when it can run.** A speaker's call costs at most `meeting_limits.per_call_usd`,
  the CEO's at most `staffing_limits.proposal_call_usd` (US$0.50 by default) and a whole staffing record at most
  `staffing_limits.total_usd` (US$2.00 by default); `staffing_limits` is a new top-level key of `config.json`. It counts
  in the same day as the meetings: `meeting_limits.daily_usd` covers both, and the ledger says so. It uses the meetings'
  one worker, so a meeting and a staffing meeting never run at the same time; the one started second is refused. A failed
  turn is retried only by you, through its own preview (twice at most), and retrying a speaker asks the CEO again; a
  restart interrupts what was running and resumes nothing. VBear runs no rule of the meetings (R1–R8) on it.
- **Your draft of the proposal.** On a staffing record (`#/staffing/<id>`), 改成你要的樣子（草稿） lets you put
  someone else in a place, empty a place or take a staff row out, add a staff position, and add or untick skills; only
  the skills that card can read are offered. VBear checks each row again by the page's own rules (the card as it is now,
  the place it fits, a review's camp against the executor's, as on a task card) and does not tick a row it flags; a row
  you tick yourself stays ticked. The draft is kept in this browser only, and a draft of an earlier proposal is not used.
- **Adopting the draft, one step at a time.** Under the draft, 照草稿採用 lists six steps in a fixed order: 啟用 (switch
  a disabled card on), 建新卡 (the card wizard opens filled from the CEO's new card: name, position, camp, model and the
  skills it can read; nothing is saved until 建立), 插技能 (a dialog shows the card's skills before and after;
  插上技能只是紀錄，不會安裝或下載), 帶到隊伍 (the task card opens with the team placed on its board but not saved: `flows.json` is
  written only when you press 建立隊伍 or 儲存隊伍 there; a place the proposal does not name stays as it is, and leaving
  the page drops what was placed), 帶去開會 (optional: the meeting form with the staff ticked as speakers; nothing is
  sent until 預覽) and 記下. Each step is a button you press and goes through an endpoint VBear already had; a step waits
  for the ones before it, and 記下：採用 is offered only once the first four are done. The adoption keeps the rows as
  they are on the cards (each place, the card in it, the CEO's new card it was made from and its skills); like 記下：不採用
  it is a record of the console (主控台記錄（未驗證身分）) and does nothing by itself. A record whose proposal the CEO did
  not finish can only be dismissed. The cards made in the wizard are remembered in this browser.
- **Meetings are shorter, and say why they cost money.** A speaker thinks at low effort and the CEO at medium
  (`meeting_speed`, a new top-level key of `config.json`; high is not offered), and a meeting runs at most 15 minutes (5
  to 30) with the last three kept for the CEO; a speaker with less than a minute left is skipped, 時間到沒發言. The
  meeting pages and their previews say the speed and the clock, and why a meeting costs money: each speaker (and the
  CEO) is one call of a model through your own Claude Code; the dollars are Claude Code's estimate, and a subscription
  uses your usage instead of being charged apart. The same holds for a staffing meeting.
- **The office and the board show the staffing meetings.** The office's 會議室 also seats a staffing meeting that runs
  or waits, marked 組隊會議, its seats leading to its record, and the 董事長桌 counts 組隊提案待你看, with 去看提案. The home
  page's 「輪到你」 lists a proposal waiting for you. A staffing list that cannot be read is said (讀不到組隊會議), not
  taken as none.
- **Under the meetings.** The meetings' engine is split out of the meeting runner (`board_engine.py`), with no change in
  how a meeting behaves, and a turn whose text cannot be made now ends as failed instead of staying queued.
  `skill_fit.py` is a Python copy of the page's rules for which skill a card can take, so the server checks a proposal
  as the page checks a card.
- **Going back to v0.9.0.** v0.9.0 reads what this version wrote, except the staffing meetings: it does not know the
  `staffing/` folder and leaves it as it is, so coming back finds the records again. `staffing_limits` and
  `meeting_speed` stay in `config.json` (v0.9.0 keeps a top-level key it does not know when it saves) and are not used
  there; its meetings run without `--effort` and without the clock, and a turn this version skipped for time shows there
  as 沒有發言 with 代碼：time_up. **v0.9.0's daily ledger does not count what the staffing meetings spent**: on a day a
  staffing meeting spent money here, v0.9.0 lets meetings spend the whole of `meeting_limits.daily_usd` again, so that
  day can go over it. `meeting-worker.lock` and `meeting-worker.blocked` are the meetings' own files both ways. The
  drafts and the cards made in the wizard (kept in this browser) and a team placed on a board but not saved are not used
  there; a role card, a skill, a task card or a flow changed by an adoption is an ordinary one there, because each step
  went through an endpoint v0.9.0 has too.

## v0.9.0 — seven positions, role instructions, full-mode launches and office meetings

Role cards now follow the seven positions of a one-person company, carry instructions and a launch mode, and can hold
a meeting: the positions talk a question over in writing, the CEO decides, and what is major waits for you, the
chairman. A card in the new full mode starts its tool the way you would in your own terminal, with nothing limited by
VBear; the safe mode is the sandboxed launch VBear had before, unchanged, and every card saved before this version
stays in it. This version was never published on its own, so this section is everything since v0.8.9, the profession
picker and the hover box for skill descriptions included; going back to v0.8.9 is described once, at the end.

- **A role card's suggested position now follows the seven positions of a one-person company.** Step 2 of the card
  wizard offers CEO, 全端工程師, 社群媒體經理 and 藝術總監 as the positions done on a task card, PM, 法務經理 and 會計師
  as staff, and 先不指定 beside the staff row. The independent review is not one of the seven: it is VBear's own review
  gate, offered apart as 「VBear 內建：審查關卡（給任務卡的審查位）」. A position you pick shows what it does, where on a
  task card it is suggested to go, the camp and model it is suggested for (the art director's is AGY, which VBear does not
  start, and the box says so), and a one-line reminder of the division of work, which is also added to the note about
  permissions. Positions are labels only: every one still suggests the same permission intents (the one combination a
  launch honours), and the reminder is words for you to write into the task card's goal, because VBear cannot enforce
  it. The ids planner, executor and reviewer keep their meaning and only change their words (CEO, 全端工程師, 獨立審查;
  the badges are 長, 工, 審), so a card saved in v0.8.9 reads as before. The starter deck's second card is now named
  全端工程師. The ids that only a local build of this version wrote are read as the position they became (qa as 獨立審查,
  product and records as PM, design as 藝術總監) and marked 舊位置; research and business have no successor, so those cards
  show 先不指定 with 請重選. Nothing is rewritten by looking: a card is rewritten when you save it in the wizard, and a
  stored value the page cannot show stays until you press a position button. A save accepts only the eight listed ids.
  On a task card each place says what suits it (適合：…), and 放上任務卡 on a card made for a place of the task card has
  that place chosen for you (a review card gets the empty review place; a PM or other staff card gets none); nothing is
  written until you press 放上去. The profession picker guesses among the same eight positions (a security, test or review
  role fits the review gate, a legal or compliance role 法務經理, a finance role 會計師). The task card's places and its
  saved flow are unchanged.
- **A role card's position is now kept on the card, not only in the browser.** The card has an optional `position`
  field, so the position is still there in another browser or on another port (the app picks 7789 and up when 7788 is
  busy, and each port was its own browser store). The wizard and the starter deck send the position with the card, a
  copy carries it, and switching a card off or on leaves it alone. A card whose position was only remembered in the
  browser looks as before, and the position is written onto the card when you save it in the wizard; the browser's
  note is still written too. A card with no position stores nothing new, so its revision does not change, while a
  position counts in the revision like any other field. A position this version does not list (written by a newer
  one) shows as 先不指定, is kept when you save without touching it, and does not make the card file unreadable. The
  save refuses a position outside the eight listed ones.
- **A role card can carry its own instructions, a launch mode and the boundaries that go with them.** The card
  wizard's step 2 has a box for the position's instructions (starting from the position's default, up to 2000
  characters, with 回復預設), a choice of how the card departs (完整模式 for a new card, 安全模式 for the sandboxed
  launch; a card saved before this stays safe) and, below, what each position's boundaries are for the tool and mode you
  chose, each marked as enforced when launched, only a reminder, not possible or not applicable. In the safe mode the
  instructions are not sent into the tool when it starts. After you take over a terminal,
  貼上職位指示 pastes them into the input box without pressing Enter; you read them and press Enter yourself. The back of
  a card and the pass say where the instructions go, the pass suggests a folder name for the position (a suggestion, not
  a check), and step 3 marks the skills that fit the position as 推薦 with a 只看推薦 toggle. Two skill categories are new,
  法規與合規 and 財務與帳務, so the skill index version is now 3 and the index is rebuilt once. Cards without the new
  fields store nothing new.
- **A card in full mode now departs, with nothing limited.** 完整模式 starts Claude Code, Codex or AGY the way you would
  start it in your own terminal: your own settings, skills, `CLAUDE.md`, MCP servers and plugins, and the network. VBear
  adds no sandbox, no `--safe-mode`, no settings file, no tool list and no scratch folder, so the pass for such a card
  starts with 「VBear 沒有限制這張卡」 and shows no shield; only the tool's own permission prompts are left, and a
  permission intent written as "deny" is listed as not kept. The command is built on the server and shown on the pass
  (`claude [--model X] [--append-system-prompt …]`, `codex [-m X]`, `agy [--model X]`); you confirm it as before, and the
  preview is voided if the card or the program file changes. Claude Code is started with the card's instructions as one
  `--append-system-prompt` argument, shown in full on the pass (VBear did not verify that Claude Code receives them);
  Codex and AGY have no such option, so their instructions stay the 貼上職位指示 button's. AGY can now be started this
  way (not in the safe mode). The terminal appears in the office and the workbench as an agent whose state reads 狀態未知,
  because no signal was checked for it. A card without `launch_mode` is still the safe one, started exactly as before.
- **The executor's role card can open the plan of automatic mode with its instructions.** When the card placed on a flow's
  executor place has instructions, the plan the approval shows, hashes and saves starts with them (naming the card),
  followed by the task; with no card or no instructions the plan is the same text as before, and an already approved
  flow keeps its own plan. The approval dialog says which card, and the dispatch box has 加上職位指示, which puts the same
  text first in the box without sending anything.
- **Meetings: the positions talk a question over in writing, the CEO decides, and what is major waits for you.** The new
  會議 page (`#/meetings`, also 開會討論 on a task card of the home page and of the workbench) takes a topic, an optional
  supplement and task card, a chair (an enabled card whose saved position is CEO), up to six speakers with one card per
  position (PM, 全端工程師, 社群媒體經理, 藝術總監, 法務經理, 會計師) and six 涉及 boxes (對外發布, 花錢, 刪除資料, 法律或合約,
  上線部署, 個資). 預覽（還不會開始） shows, before anything is sent, every card's instructions and the whole text each call
  will send, the model, the number of calls and the money reserved, the day's spending and whether this Claude Code
  version has passed the tool-less check; only 開始開會 starts the meeting, and the preview is used once and lapses after
  five minutes. Each speaker answers once without seeing the others (with a task card, the PM also gets a progress
  summary VBear writes from its records, and the accountant what the meeting has cost so far); then the CEO reads every
  answer and writes a decision with its reasons and actions. Every call is Claude Code with no tools at all, the kind of
  call a skill translation makes: each call's own start is checked for only StructuredOutput and no MCP server, and
  anything else stops it at once, throws its answer away and voids that version's check until it is checked again. A
  Codex or AGY card does not speak itself: Claude speaks for it with that position's instructions, marked 代發言. The
  texts go through your own Claude Code to Anthropic under your account, with secret-shaped text masked; a task card's
  fields are sent, never its folder. A fixed table, R1–R8, decides whether the decision goes to you: a box you ticked;
  an action that publishes, deploys, pays, deletes, signs or changes a price; a keyword or any amount of money in the
  topic, the supplement or the decision; a high risk, or a legal risk with no source (查無出處); the legal manager
  opposing; a speaker that failed; or anyone asking for you. A model's fields are read only to raise that verdict, never
  to lower it, and the keyword list can miss a paraphrase, which is what the 涉及 boxes are for. You approve or veto at
  the 董事長桌 with a note, a record in the console (主控台記錄（未驗證身分）): anyone who can use the console can press it.
  A decision that does not need you reads CEO 已決定, and you can still veto it. A decision is only a record: VBear
  carries out nothing, and 寫進任務卡 opens the task card's editor with the decision added to its goal, for you to save.
  Spending has three limits, kept in `config.json` as `meeting_limits` (US$0.20 per call, 1.50 per meeting and 3.00 per
  day by default): a call counts what Claude Code reported, or the per-call limit when it reported nothing; the figures
  are Claude Code's estimates, not a bill; the page turns yellow at 80% of the day's limit and starts no meeting and no
  retry at 100%. A failed speaker is never retried by itself: you can retry it twice through its own small preview, and
  a third failure blocks it. When the console restarts, the call that was running is interrupted and nothing resumes.
  When this Claude Code version has not passed the check, the preview offers 先做無工具安全檢查, asked in the page first:
  it is the translations' check and is kept in the same record, but always of Claude Code, whichever engine the
  translations use. Each meeting is one file in `meetings/` in VBear's state folder; a meeting writes no task card, no
  flow and nothing in a project folder.
- **The office has a meeting room and a chairman's desk, and the home page lists the meetings that wait for you.** The
  office's 會議室 shows the newest meeting that is running or waiting for you (the others as 還有 N 場): each participant
  at the table, drawn by its card's tool, with the words over it taken only from the meeting's record through a closed
  list (等發言, 發言中, 支持, 反對, 有條件支持, 要更多資訊, 失敗, …; for the CEO 整理意見中, 已決定, 交董事長), and a
  spoken-for card marked 代發言. The 董事長桌 under it counts the meetings waiting for your approval and has 去核准. The home
  page's 輪到你 lists those meetings (輪到你：董事長核准), and a task card in the workbench lists its own meetings. A meeting
  record that cannot be read is said so, never taken for no meeting.
- **The card wizard's profession is now a picker you can read and use.** It moved out of 進階 to step 2, under the
  suggested position, as one line (目前：…) that opens into a search, buttons for the position each role probably fits,
  and a list. It lists only your card's own tool (a Claude Code card no longer lists Codex roles) and no longer lists the
  two "main agent" entries, which were the tools themselves, not professions. Every name shows in Chinese beside the
  English once translated, with 待翻 on the ones that are not, and each row has one line of what the role does: the
  translated sentence (marked 機器翻譯), or the author's first 60 characters (marked 原文), plus a position guess made
  from the name or the first sentence of the description (marked as a guess; the roles it cannot place sit in 其他).
  Choosing a role shows what it brings and each item is one click: its guessed position (put on the card only when the
  card has none, otherwise offered as a button), the skills the template names that your card's tool can read (一起插上,
  seen in step 3), and the model it names (套用模型). Choosing only labels the card: launching still does not load the
  role's instructions. When names are still English, the open picker says so and offers 把職業名稱翻成中文; it asks
  before anything is sent, and when the first translation needs the one-time safety check it offers 先檢查 there (also
  asking first). 先不翻 folds the prompt into one small button. A label the card already holds from another tool, from
  the tool itself, or from a role the index no longer finds stays, with the reason and a 解除 button; nothing is cleared
  for you. Roles of a plugin that is switched off are behind 也顯示用不到的. The back of a card calls the row 職業 and adds
  the one Chinese sentence. VBear's own two main-agent names are no longer sent for translation. The choice is still
  saved as the role id.
- **Switching a card off or on no longer clears its profession.** The 停用／啟用 button on the 角色 tab of the terminal
  workbench sends only the new on/off state, and the save treated the missing profession as "none", so the card lost
  its profession. A save that leaves out the profession now keeps the stored one; sending `null` or an empty value still
  clears it, and the card wizard and the starter deck send the same data as before.
- **Skill descriptions that are cut short on a card can now be read whole.** Rest the pointer on a skill card (in the
  skill library, the four-state overview and step 3 of the card wizard) or on the description in the skills table, or
  move to it with the Tab key, and a small box opens with the full text: the whole Chinese description, when to use it
  and what it needs if the author said so, a line that it is a machine translation, and the original underneath; a
  skill that has no translation shows its whole original. A long text scrolls inside the box, you can move the pointer
  into it, and it moves out of the way of the window edge. Esc, moving away, or leaving the card closes it, and it never
  takes the keyboard focus or covers the card. The cards keep their short line, and 看完整說明 in the wizard is still
  there for touch screens. To make this possible the card wizard is now sent up to 2000 characters of a skill's
  original description (it was 140); nothing is sent anywhere else.
- **Going back to v0.8.9.** v0.8.9 reads what this version wrote. It reads the role card file and leaves the new fields
  `position`, `instructions` and `launch_mode` on every card it does not touch, but saving or copying a card there
  writes that card without them. It has no full mode: a card made for it is started there with v0.8.9's sandboxed launch
  (which starts Claude Code cards only). The page there shows the position this browser remembers, and only the three
  positions it knows (CEO, 全端工程師 and 獨立審查, which it calls 規劃, 執行 and 審查); any other reads as not specified.
  The skill index is rebuilt once each way (its version is 3 here and 2 there), and the two new skill categories are not
  there. The `meetings/` folder and the `meeting_limits` in `config.json` are left as they are and not used, so coming
  back finds them again. A flow approved here keeps the plan it saved in `plan.txt`, instructions included, and
  `translation-boundaries.json` is the same file both ways, so a version checked for meetings counts for translations
  there too.

## v0.8.9 — skills by use, role names in Chinese, a model menu

- **The profession menu in the card wizard can show the role names in Chinese.** Under 進階 → 職業標籤, a new button,
  「把職業名稱翻成中文（N 個未翻）」, translates the role names (Brand Guardian, Trend Researcher, …) on your own
  Claude account, usually under 1 US cent each, after a confirmation that says what is sent: only each role's name and
  the description its author wrote. Translated entries read 中文名稱（English name）・Claude Code, untranslated ones
  stay as they were, and the same Chinese name (with the English in brackets) is used on the back of a role card, on the
  role cards in the card pool and on the role page. The Chinese names are a machine translation and the menu says so.
  Nothing is translated unless you press the button, and the skill translations are not changed.
- **The model box in the card wizard is now a drop-down.** For a Claude Code or Codex card, step 2 (進階) lets you pick
  the model instead of typing it: 工具預設 (leave it to the tool), then for Claude the aliases `fable`, `opus`,
  `sonnet` and `haiku` (an alias always means the newest version, so it needs no update), then the full names VBear
  has seen in your own Claude Code usage. For Codex it lists the models Codex itself lists, taken from the cache Codex
  keeps, so it is only as fresh as the last time you opened Codex. 其他（自己輸入）… still lets you type any name, and a
  card that already holds a name not in the list keeps it. Antigravity and shared cards keep the text box. What is
  saved is the same text as before. VBear reads only each model's name from Codex's cache (never its other fields),
  runs no program and uses no network for this.

- **Step 3 of the card wizard sorts the skills by use.** Above the skill cards there is now a row of categories with
  how many skills each has, such as 設計與介面, 寫作與內容, 測試與審查 and AI 與代理, plus 全部 and 其他 (skills in no
  category). Pick one to see only those skills; it works together with the search box. These are the categories VBear
  already gives skills from words in their text, the same as in the skill library, so a skill can be in more than one
  and the sorting can be rough. Only categories the list has are shown, and which skills a card can take is unchanged.

## v0.8.8 — skill cards you can read in Chinese

- **A translated skill card in the card wizard reads whole, in Chinese.** The card used to show the first sentence of
  the long Chinese text, cut off after two lines with "…", and the fold beside it, 看原文, only held the English. The
  card now shows the translation's short "what it does" in full (50 characters at most, never cut) and, when the
  author said it, a line 「什麼時候用：…」. The fold is now 看完整說明: the whole Chinese text first, then the original.
  The search box also looks at the Chinese, so typing Chinese finds a translated skill. Cards without a translation
  are as before.

## v0.8.7 — the app finds Claude Code; delete works

- **The VBear app now finds Claude Code and Codex installed in your home folder's `.local/bin`.** Claude Code's own
  installer puts `claude` there, but an app started from Finder does not see your terminal's search path, so VBear
  could not find it. The translation check then wrongly said the safety boundary was "not verified", and the version
  check before a Claude Code launch could miss it the same way. VBear now also looks in `.local/bin` (after Homebrew
  and the system folders, never ahead of them), and nowhere else. If `claude` still cannot be found, the translation check now says
  so plainly ("找不到 Claude Code …") instead of blaming the boundary. "Not verified" appears only when the check
  really did not pass. No safety check was relaxed: finding the file does not verify it.

- **The small skill cards in step 3 of the card wizard read in one glance.** Each card is now three parts: the
  name, one small row of tags, and the description (still two lines). Before, every tag sat on a line of its own and
  a card was a stack of five or six short lines. Tags that told nothing are gone: "AGY reads it" (every skill an AGY
  card lists is read by AGY), the camp tag on a skill of the card's own camp (a Claude Code skill on a Claude Code
  card), and the "machine translation" badge on every card. A shared skill says "shared" on the other camps' cards, a
  skill from another camp says which one (for example "Codex" on an AGY card), and the row also holds the plain
  reason a skill is greyed or marked, "N more with this name" and "out of date". When some listed description is a
  machine translation, one line above the list says so and points to "see the original"; the library and the skill
  page keep their own translation badge. Long names still wrap instead of being cut, and picking, taking off, the
  keyboard and the greyed cards work as before.

- **The delete buttons on role cards and task cards now work in the app window.** They used the browser's own yes/no
  box, which the app window never shows, so pressing 刪除 did nothing there. They now ask in the page, like the other
  confirmations: a box titled 刪除角色卡 or 刪除任務卡 that names the card and says it cannot be undone. 取消 or closing
  the box sends nothing; 刪除 deletes the card as before. No other place used the browser's own boxes, and a test now
  keeps it that way.

## v0.8.6 — skill cards you can read

- **Small tidy-ups from the last two reviews.** In the card wizard's second step the four camp buttons now line up
  by the room they have: four in a row if they all fit, two by two otherwise, one under another on a narrow screen,
  and never three and one (the other button rows are unchanged). The launch pass of an Antigravity (AGY) card says
  once that VBear does not start AGY; the line beside the off start button now only points up to it. In the settings
  list, the AGY config file's row no longer repeats its own name at the front of each problem; the overview's problem
  list keeps the name, since it has no row title above it. How the file is read, and what it refuses, is unchanged.

- **Step 3 of the card wizard, the skill cards, is now readable.** The step opens with a few plain sentences: a skill
  card is a work note written for an AI (how to make slides, how to handle a PDF); inserting one only records what the
  role is good at, so the team looks divided when you build it; VBear does not load these skills when a role departs
  yet; and the step can be skipped. The list now shows only what the card's camp really uses: a Claude Code or Codex
  card lists that tool's active skills plus the shared ones, an AGY card what AGY reads, a shared card the shared skills.
  Skills of other camps, old cached versions, copies in a plugin marketplace that is not installed, disabled ones and
  ones a plugin ships but the tool does not load are behind a switch, "also show the skills that cannot be used (N)";
  with it on they are greyed or marked in plain words. Copies of one skill with the same name are listed once, with
  "N more with this name" on it. A skill already inserted stays under "inserted" with its reason even if the list
  hides it. Search looks only at what is shown, and says how many matches wait behind the switch. Which skills a card
  can take is unchanged, and so are the skill overview, the skill card page and the launch pass.

## v0.8.5 — the skills AGY reads

- **An AGY card can now hold the skills AGY actually reads.** VBear used to say it did not know which skills
  Antigravity (AGY) reads and let an AGY card hold only shared skill cards. It now works it out from files on your
  Mac, without running AGY: a project's `.agents/skills`, `~/.gemini/antigravity-cli/skills`, and the folders listed in
  `~/.gemini/config/skills.json` (only the skills directly in a folder, or the ones its `include_only` names). Skills
  VBear already knew are marked as read by AGY instead of being copied; a folder it did not scan becomes an AGY source in
  the settings list. In the card wizard those skills can be inserted and the rest are greyed with
  「AGY 不會讀這張技能卡（依這台電腦的 AGY 設定）」. The shared store `~/.agents/skills` is not AGY's unless that file
  lists it. A card saved earlier with a shared skill keeps it and shows 「AGY 不會讀」 on it, for you to take off or
  keep. It stays a collection (VBear does not start AGY), AGY's built-in and plugin skills are not covered, and only
  that one config file under `~/.gemini` is opened; a missing or unusable file is skipped and shown in the settings
  list. Claude Code, Codex and shared cards are unchanged.
- **No false launch warning on AGY and shared cards.** In the card wizard's second step, an Antigravity (AGY) card or a
  共用 card set to something like 「編輯寫入・拒絕」 no longer shows 「這個組合目前不能出發」. VBear never starts those
  cards, so the warning was noise; their permission intents stay what they always were, a record for building teams.
  A shared card now says so beside the camp row (「共用卡不能出發，權限意圖只是分工記錄。」), and the AGY card keeps its
  existing sentence. Switching the camp updates the step at once: from AGY back to Claude Code the warning returns when
  the combination cannot be launched. Claude Code and Codex cards, the launch pass and the server's launch checks are
  unchanged.

## v0.8.4 — an Antigravity (AGY) camp

**Role cards can be Antigravity (AGY) cards.** The card wizard's 「陣營」 row, and the card editor, now offer
Antigravity（AGY） beside Claude Code, Codex CLI and 共用. VBear does not start Antigravity (and does not yet know how
to), so an AGY card is a record for building teams, and the app says so in plain words wherever it matters.

- **The card.** An AGY card is the fox in the Google colours. Its model family is always Google, in the page and on the
  server alike: put on a task card's review place beside a Claude Code or Codex executor it counts as an independent
  review, and beside an executor written by hand as Google (Gemini), or beside another AGY card, it turns red with
  the usual reason. A flow that holds an AGY card with any other family is refused.
- **No launch.** 出發 on an AGY card opens a pass that says 「VBear 還不會啟動 AGY，這張卡目前只用來排隊伍與記錄」, with no
  preview, no start button, no shield and no limits listed; the card's light says the same. The server refuses to
  prepare a launch for it, and a team place or the next-steps list offers no 出發 for an AGY card.
- **Skill cards and role labels.** VBear does not know which skills AGY reads, so no skill is shown as one it would
  load. An AGY card can hold shared skill cards, as a collection only; every other skill card is greyed with
  「VBear 還不知道 AGY 會讀哪些技能」. VBear scans no Agent role of Antigravity, so there is no role label to pick, and a
  Claude Code or Codex one does not stand in for it.
- **Automatic mode is unchanged.** The automatic review is still the Codex that VBear starts, and it is recorded as
  that. An AGY card on a review place is a record of who reviews by hand; it is never described as the automatic reviewer.
- **Nothing existing changed.** Role cards and flows already stored read back as before, and any other tool name
  (`gemini`, `antigravity`, `AGY`) is still refused.

## v0.8.3 — keyboard focus and plain-language terminal errors

Two small interface fixes.

- **The keyboard stays inside the skill card window.** The window put the focus on 返回, then drew its buttons again
  once the skill had loaded, and the focus fell to the page: Esc did not close it and Tab started from the top of the
  page. The focus now ends up on 返回 after the load (also when the load fails), unless you had already moved it
  somewhere else in the window. A window you closed while it was still loading is left alone: nothing is drawn into it
  and the focus does not move. Closing returns the focus to the button that opened the window; when that button is
  gone (taking a skill off a role card redraws the card) it goes to the main region of the page instead of the top.
  The same fault is fixed where it was found elsewhere: taking a skill off the card with its 移除 button in the card
  wizard, and choosing a task card or a place in the 放上任務卡 window, no longer drop the focus when the list is drawn again.
- **Terminal, takeover and handoff failures are said in plain words.** When a takeover, 改成只觀看, typing, closing a
  terminal, opening a terminal, the stream, a handoff, or recording a terminal on a task card fails, the page used to
  print what the server or the runtime had answered (`目前沒有這個 Terminal`, `內部錯誤：TypeError`, `HTTP 502`, the
  reason a closed terminal's scratch was kept). It now says what happened and what to do next in a sentence of its own
  (for example 這個終端已經不存在了（可能已關閉）。要繼續的話，請重新開啟一個終端。). An answer the page does not know gets
  only a general sentence such as 沒能接手這個終端。 and no guess at the cause. The original is always kept: behind 「技術細節」
  in a notice (the takeover reminder now shows its failure inside the dialog, where it stays), and in brackets after the
  sentence in a toast (`（原文：…）`). The words are one table, shared with the line under a closed terminal. What the server
  and the runtime send, and their codes, are unchanged. A terminal that could not be recorded on its task card now says so
  in a sentence and puts the original at the end of the message.

## v0.8.2 — hardening and a dark icon

Hardening that follows the first security review of v0.8.1. It found no confirmed vulnerability; these two changes make
the code do what the documents already say. The entries after them are small interface changes.

- **Skill secrets under a name with no value are masked.** A secret-looking name whose line ends at the colon
  (`tokens:`, `api_key:`, `credentials:`) now masks the more deeply indented lines below it: a list, a value on the next
  line, a nested mapping, as a `|` block already did. It stops at the next line that is as shallow as the name. The same holds when the name's line carries only a comment,
  an opening bracket, a block header such as `|2` or `>-`, or a tag or anchor (`!vault |`, `&k`). A name
  that only describes a secret (`max_tokens`, `api_key_env`) keeps its harmless values visible, as before. Text such as
  `Passwords:` followed by an indented explanation is masked as well; masking more was chosen over missing a value. This
  applies to the raw SKILL.md and the referenced files in the skill details.
- **A managed launch's work directory follows the folder chooser's list.** The home directory itself, `~/.ssh`,
  `~/.gnupg`, `~/.aws`, `~/.config`, `~/.vbear`, `~/.claude`, `~/.codex`, `~/.gemini`, `~/Library`, the state directory
  and anything below them are refused as a work directory when a launch is previewed, prepared and again just before it
  starts. Names are compared without regard to case and symlinks are resolved first, so `~/.SSH` and a link that points
  at `~/.ssh` are refused too; the earlier protected places (`/tmp`, the scratch parent, `~/.claude`, `~/.codex`) are
  compared the same way. The refusal comes before the check that the folder exists and reads the same either way
  (`invalid_workdir`; the preview shows it as a reason the launch cannot start).
  **Behaviour change:** a work directory under `~/Library` (for example iCloud Drive's `~/Library/Mobile Documents`) or
  `~/.config`, which the folder chooser has always refused, is now refused for managed launches as well.
- **A skill can be taken off a role card from its back again.** The back of a role card now lists the skill cards on it,
  each with a 技能卡特性 button. Opened from there, the skill card window offers 從這個角色移除 (with the usual
  confirmation) and the card redraws by itself afterwards. This works in the card pool, the workbench's role tab and the
  office roster; sample cards and the armory's view stay read-only. A skill the index can no longer find is listed
  without a button and points to editing the card.
- **The small bear's plate has a visible edge in the light theme.** Its cream plate was almost the colour of the light
  sidebar. In the light theme the mark now has a one-pixel edge in a muted tan that follows the plate's stepped corners;
  the dark theme looks exactly as before. It follows VBear's own light/dark setting, whether chosen or following the
  system. The edge is drawn on the page only: the favicon is unchanged.
- **On macOS 26 and later the app icon follows light and dark mode.** The Dock and Finder show a dark plate with the
  bear outlined in cream in dark mode and the cream plate in light mode. The icon is now an Icon Composer `.icon`
  (`macos/AppIcon.icon`, compiled by `actool` into `Assets.car`), so macOS draws the plate itself: its rounded shape,
  edge and finish differ a little from the old hand-drawn plate, and the small sizes are scaled down from the large
  bear rather than drawn on their own 16 x 16 grid. Older macOS versions keep `AppIcon.icns`, unchanged, byte for byte.
  The build skips `Assets.car` when Xcode is not installed (and says so); the release workflow fails if the app has no
  `Assets.car` with both appearances.

## v0.8.1 — pixel black bear

- **New logo: a pixel Formosan black bear with a white V on its chest.** The app icon, the browser tab icon, the mark at
  the top left of the page and the banner at the top of both READMEs (the bear wears a headset there, and a dark version
  is shown on GitHub's dark theme) are all new. The icons are drawn cell by cell, so they stay sharp: the page mark is
  `web/logo.svg`, the tab icon `web/favicon.svg`, and the app icon is drawn by `macos/make_icon.swift` from the pixels in
  `macos/AppIcon.pixels.json` (the 16 and 32 pixel sizes use a simpler 16 x 16 bear). No behaviour changes.

## v0.8.0 — launch and hand over

- The import-a-project window: the list of projects VBear has seen (and the recent folders) now fades at its bottom
  edge and says 「共 N 個，往下捲動看更多」 while rows are hidden below it, so a cut-off last row no longer looks like
  the end of the list. The note for a folder without git no longer ends a full-width bracket right before a full stop,
  which read like a stray space; the same was done to a few other sentences on the main paths.

**After a start, and picking a task up.** A start from a task card now stays in the workbench: the new terminal sits
beside the same task card, and the terminal is noted on the card (a tracking record, nothing is sent into it; if you
changed the folder, or the note could not be saved, the page says so). A terminal this tab has just started from a launch
pass can be typed into at once, with one line saying so and a 「改成只觀看」 button; the right to type is held only in memory,
is used once, and lapses after two minutes, so a reload or a link never gets it. Taking over a terminal that is already
running now opens a 「接手提醒」: the task card linked to it and its next step, the agent's state as VBear can read it, whether
the card's flow waits for you, and three fixed lines; the focus starts on 「取消」. A task card made by a handoff shows a
「接手提醒」 at its top with the earlier card, its written note and its last state, and nothing the page does not know.

- **Workbench.** With no terminal open the task card is the page and one line says so, instead of an empty black area. The
  four-column 「狀態依據」 block and the project and global rules sit behind a folded 「進階（工程資訊）」. The card's top shows the
  flow's current gate, and the old mark (「草稿」) becomes small text. The 「角色」 tab shows the same two-sided role card as
  the card pool, and the office's 「打開角色卡」 opens that card in the card pool. Skill words say one thing: 「收藏在角色卡上」
  and 「出發時不會載入」 (a recorded pick, not a broken skill).
- **The next step's own buttons.** When it is your turn, the 「下一步」 box holds the button: 「核准計畫」 (a manual record,
  behind a confirmation) and 「核准計畫並開啟自動執行…」 (the same approval window as before); when it is your turn to merge or
  upload there is a sentence, not a button. The launch pass fetches its preview when the commit sentence is ticked (and
  fetches it on opening when that was ticked already); it never ticks it for you and the focus never lands on 「確認啟動」.
- **Plain words.** The flow and terminal pages say 版本 (commit), 執行階段, 上傳到遠端 and 只能觀看／你正在操作 instead of session,
  HEAD, push, Observe and Control; the technical values stay in small brackets, and the plan hash is still in the approval
  window. Flow phase names follow (「等你上傳」). Two cards or flows with the same title also show their folder and day; the
  common English skill categories show in Chinese (the filter values do not change). A terminal page's back button says
  where it goes (「回角色卡池」, and 「回任務卡」 for a terminal linked to a card). The home page no longer puts the cursor in the
  skill search.
- **Card feel.** The shields have new art with the same three meanings (solid, dashed, empty with a slash; partly blocked,
  untested and unknown still get none). Team places that hold a role card take the card's camp colour and the place's badge
  (規／執／審); the pool below the places is a row of small cards. Skill cards are chips with a cut corner and a band in the
  tool's colour. The starter deck and task cards have card frames; a task card has a header and three lights (規→執→審)
  that come only from the flow's real phase and are empty when there is none. The office has a small prop beside each
  station's title and a wooden strip under each desk character. Putting a card on a task card keeps you in the card pool
  and asks whether to fill another place.
- **Dark theme and small fixes.** The office outline, the deep red rule, the warning text and the solid shield now pass the
  contrast bar in the dark theme; the robot's eyes follow the camp instead of one blue; 「執行觀察」 is no longer said twice;
  the draft card's long explanation is one line with 「這是什麼」 for the rest (the meaning is kept: a mark, not a count of
  work); a role card's back says 「往下捲動看更多」 when it scrolls.
- **Last small fixes.** The launch pass no longer says 「S0 驗收」 (it now says the mode was tested to be able to write to your
  home folder, which is the same fact); 「輪到你」 has no stray space; a task card's template badge says 「自訂」 and so on
  instead of the stored key; a terminal that is gone says so in plain words, with the runtime's own sentence kept under
  「技術細節」; and on a narrow screen a long skill name no longer pushes the ⓘ out of its card.
- **Docs.** The README screenshots (both languages) were retaken for this state, mostly in the light theme and two in the
  dark theme, with new ones for the workbench task card, a handoff, a terminal just opened, the takeover reminder and the
  skills library.
- **Card back pattern.** The pattern along the top of a role card's back is now a tidy row of small crosses on a clear
  ground (「角色卡背面花紋改成整齊的小十字」), where it used to look like noise; it is drawn a little stronger so it still shows on
  every camp's card in both themes.


## v0.7.0 — card play

A first-time user can now build a team in three card moves, with no form to fill in: **collect** role cards (or take
the starter deck), **equip** skill cards, and **play** a card onto a task card's team place, then set out. A task card
is one folder, and an existing project can be brought in and managed.

**Words.** 「Agent 團隊」 is now 「角色卡池」; a profile is a 「角色卡」, chosen skills are 「技能卡」 in slots
(dashed 「收藏中」, solid 「生效中」 only when the loadout says a skill really loads, which no launch does today),
the tool is the 「陣營」, permission intents have Chinese labels and say they are a record, not a grant.

- **Card pool and wizard.** A card-pool page with a starter deck of three (CEO, 工匠, 審查員; the reviewer is left
  unticked when Codex is not installed), a three-step wizard (name and look, tool and place, skill cards) whose
  bottom buttons stay in view on a phone, suggested permission intents marked 「建議，可改」, and a same-name hint that
  never blocks. `GET /api/agent-builder/catalog` carries the deck, positions, `verified_intents` and
  `codex_installed`. All three starter cards (and the wizard's suggestions, with or without a place) carry the one
  combination a managed launch honours, so none of them is stopped by its own intents; the wizard says why the
  suggestions are all alike and, for a combination you change to, asks `GET /api/agent-builder/intent-check` and shows
  the server's reasons on the spot.
- **Codex cards.** A Codex card whose only reasons are `codex_` ones (it cannot open a terminal, but the flow's
  automatic review can use it) shows a neutral light, 「不能直接開終端」, not the red 「目前不能出發」.
- **Card art v3.** Position badges are a hard square with one character (規／執／審／？), the shields are flat-topped
  and pointed (filled, dashed, slashed), the folder and import icons are redrawn and used on the import dialog.
- **Role card.** Two faces (front: avatar, place, slots, a light that says why a launch is or is not possible; back:
  tool and model, permission intents with 「只是記錄，不是授權」, evidence, advanced). Flip with the button or F; no
  animation under reduced motion; the hidden face is `aria-hidden`. The office panel uses the same card.
  `loadout` skill rows now carry `will_load` and the block carries `all_inactive`; the page decides dashed or solid
  from that field and never from text.
- **Task card = folder; bring in a project.** 「＋ 任務卡（導入專案）」 picks a folder from the projects VBear saw, the
  recent folders or a pasted path (the app window also has a native chooser, `vbearPickFolder`, restricted to the main
  frame of the console's own origin, one panel at a time). New: `GET /api/folders/inspect`, read-only (a few
  `stat`s and the repository's HEAD, no git process, no walk), refusing the home directory itself and sensitive
  places (`~/.ssh`, `~/.gnupg`, `~/.aws`, `~/.config`, `~/.vbear`, `~/.claude`, `~/.codex`, `~/.gemini`, `~/Library`,
  and symlinks into them) with the same answer whether or not they exist. A folder that is not a git repository is
  said so plainly: reviews tied to a commit will not count there. Config gets `recent_folders` (at most 10) and
  `onboarding_dismissed`. A card's front names the folder, branch and HEAD, and counts the terminals whose working
  directory is in it, without saying which role card opened them.
- **Teams on a task card.** Team places (規劃位, 執行位, 審查位, an optional second review) filled by clicking, dragging
  or 「放上任務卡」. A review place that would not count turns red at once with the reason (`slotProblem`); an empty
  second place is not sent; errors show on the place. Flow roles can carry `profile_id` and a strict
  `profile_snapshot` (`name`, `tool`, `model_id`, `revision`), and the page says when a card changed after it was
  placed. `profile_digest` moved to `agent_profiles.py` with an unchanged value. A 「下一步」 list says whose turn each
  step is.
- **Launch pass (出發通行證).** The pre-launch check is now a pass. Its front has three lines: where it can write,
  whether the network is blocked, and always 「擋不住版本紀錄（commit）」. Each line is worded by the level the preview
  gives it; a check mark is drawn only for an enforced level, and partly blocked, untested and unknown items say so
  in words. A shield legend (solid, dashed, empty; shape, not only colour) explains the shields. The seven labels sit
  behind 「看七項細節」, unchanged. The commit acknowledgement is written out in plain words. Each reason that stops a
  launch has a button next to it (decide the intents, change the folder, tick the box), and fixing it returns to the
  same pass with a new preview. Server wording that said Profile follows the new name.
- **The first game and the board.** The home page starts with 「新手第一局」 (get role cards, bring in a project, put the
  team on it), each step ticked from real data, folded to one line when done, dismissable and restorable in
  settings. Flow cards on the board show their team and whose turn the next step is.
- **Phone menu.** At 720px and narrower the navigation folds behind one button that names the current page.
- **Skill translation.** The confirmation is one sentence (your own account, usually under one US cent) with the
  whole budget and timeout text behind 「詳細」. The progress bar folds away: success after 5 seconds, failure after
  10 seconds into a dot at the lower right that reopens the reason, a close button on each. A failure is also shown
  on the skill card the job was started from, with 「重試」 and 「原因」.
- **Opening with a login code.** `#auth=` is now traded for the session before anything else asks the server: the
  translation poll, hash changes and tab focus wait, and a 401 met in that moment no longer puts up 「請從 VBear 開啟」.
  The router no longer keeps polling after the login page is shown.
- **Closing fixes (P7).** The import box says how to get a folder's path (Finder: right-click, hold Option, copy as
  pathname) when no project or recent folder is listed, 「檢查」 is the main button and Enter or a pasted absolute path
  checks once (read-only). The next step on a task card has a button, 「讓 X 出發」, that goes through the same launch
  pass as a place's own 出發 button; in manual mode a sentence says VBear will not move the flow on and where to record
  the step, and after a launch from a place the card says 「已開啟 N 個終端」 from VBear's own launch result only (never
  which terminal belongs to which card). A skill's page says 收藏中（這次出發不載入）, like the card, and keeps 啟用／已停用
  for the card itself; weapons explain 鎖住; the intents are 「權限意圖（分工記號）」. Without a terminal chosen, the
  tracking box no longer says it is linked. 「工作中」 is only used for the working status ("N open terminals" elsewhere);
  the English words Terminal, Session, Armory, Context and Status Provenance are gone from the screens. The phone
  workbench opens at the task card and its team when you come from a task card, and 「右欄」 is 「任務與隊伍」. The same
  card cannot review itself. The pass words its commit note by the folder (no `.git` in it: it says so; a `.git`: it
  says that one is writable; `derive_labels` does one `lstat` for this), and a card's back, which has no folder, says
  「工作目錄內若有 .git」 instead of claiming one, names the field 「在哪裡做（工作資料夾）」, and says 「出發後 VBear
  暫時看不出它在忙還是在等你」 for an unverified Claude Code. `GET /api/live` also carries `managed_root`, the folder
  a launch may work in, and the pass's range hint is made from it. A role card's front has one line from its armor
  data (「出發後可以改檔案；擋不住 commit；詳情看出發通行證」, never more hopeful than the pass). The skill picker shows the
  Chinese 「what it does」 (marked 機器翻譯 or 過期) with the original behind 「看原文」. On the home page, 「到終端工作台」
  is a plain button while the first game is on. `VBEAR_QA_FRESH=1` no longer carries the HTML probe skill.
- **QA and tests.** The QA console gained `VBEAR_QA_FRESH=1` and `VBEAR_QA_TRANSLATE=fail`; the fake translation CLI
  follows the structured-output change. New tests cover the folder API, the config keys, flow role cards, `will_load`,
  the starter deck, the pass table level by level, the team places and the first game.
- **Docs: README screenshots retaken.** Both READMEs now show v0.7.0 (demo data): the home page and the fresh-install home, the card pool (front and back, the starter deck, the light theme), task cards and the project import, a flow's team places, the launch pass (the three-line front and 「看七項細節」), a skill card, and the office with its stage panel. Four older pictures (`role-card*.png`, `preflight-check.png`) are gone; the captions say only what a picture shows, and the status line reads v0.7.
- Add an opt-in macOS browser startup mode, an open-in-browser menu command, and an Option-key escape to
  window mode. Failed or timed-out browser launches fall back to the window with an error message.
- Isolate macOS smoke tests by port and process ID, and add optional browser startup/reuse acceptance.

## v0.6.0 — Chinese skill summaries

Skill descriptions can show Chinese machine translations and summaries alongside the author's original text.
Source fingerprints identify changes to the original text, and stale translations are marked; automatic
retranslation is off by default. Translation runs only after the installed Claude Code version passes a check that its translation run
offers no tool but StructuredOutput and no MCP server; the Codex translation engine is disabled.

- Add a guarded skill-translation candidate: redacted author-field fingerprints, a bounded atomic cache,
  stale/orphan states, sequential cancellable jobs, and consent-bound automatic work after explicit rescans.
- Add Chinese summaries and author-original toggles to skill cards/details, translated library search,
  cost/quota disclosures, global progress, settings and two-step orphan cleanup.
- Add fake-only translation tests and `VBEAR_QA_TRANSLATE=1` to the isolated QA console. Production CLI
  providers remain blocked until the exact no-tools boundary has version-specific evidence. No real model
  was called; existing launch and dispatch behaviour is unchanged.

## v0.5.0 — quest board and pixel office

The home page is now the quest board, 冒險者大廳, with flows and agents that need your attention and other open
tasks. The pixel office, `#/office`, places teams by their task phase, live terminals at desks and saved profiles
in the lounge. Characters have persona lines with evidence labels and expandable reasons; a station describes
task location. Safe-mode launches were tested on Claude Code 2.1.299: VBear's flags left user and project skills
unlisted and offered only Bash, so a profile's skill list remains a record of your picks.

- **Embodied office characters.** New supplied pixel art and camp colors, two-frame typing only for working
  desk sessions, and reduced-motion support. Panels add fixed persona lines with evidence labels and expandable
  reasons, plus a responsive SVG character stage with a status monitor and a locally saved collapse preference.
  Team and roster characters remain static; their monitors describe task location and roster membership.
  Waiting lines distinguish terminal-title and background-stream evidence; review lines describe the recorded
  phase without claiming that a review process is running.

- **A pixel office, `#/office`.** A new page after 冒險者大廳 in the menu. Four workstations (計畫板, 實作區,
  審查室, 合併關卡) hold the flows' teams by their phase (at most 3 per station, then 「這站還有 N 隊」; a team that
  waits for you is taken first); each live terminal sits at a desk with its state in words over the character
  (an ended one has none); the saved profiles stay in the lounge (at most 24, then a link). A station says only
  where the task is, never what an agent is doing. The red (#DA251D) is used only for 「輪到你」, and always with
  words. Click a character for its panel: weapons (the tools a launch offers), armor with solid frames for
  enforced and dashed for the rest, and its skill cards (a skill the index cannot find says so with the index
  time). A flow's team has no gear panel (flow roles record only a name and a model family) and a session's gear is
  unknown. Species (bear, fox, robot, alien) follows the tool or the model family; you can change a profile's
  species (kept in the browser). On a phone it is a list, not a scene. It reads only what the flows, live and
  profile APIs already return. The one backend change: `GET /api/agent-profiles/<id>/loadout` has a read-only
  `tools` object, taken from the same two constants the Claude argv is built from (`Bash`; `Edit,Write`), so the
  argv text is unchanged and a test locks it. The characters are original pixel art, inspired by Pixel-Crew
  (MIT) but using none of its art or code. `tests/qa_game_ui.py` has `VBEAR_QA_OFFICE=1` and `=stress`.
- **The home page is the quest board, 冒險者大廳.** 「我的工作台」 (the home page and the first menu item) is now
  冒險者大廳. Its first block, 「需要你處理」, became two blocks: 「輪到你」 (the flows the server marks as needing
  you, a stale review of a manual or stopped flow, and the agents that wait for your reply) and
  「其他進行中的任務」 (the other open flows, at most 4, then 「還有 N 則」 to the flows page). A flow card is one
  card with one link: the title, stretched over the card; its type label is the phase's own words and its
  frame is drawn with words beside it, so colour is never the only sign. A finished flow is never on the board.
  Manual flows say that VBear will not move them for you. It reads only what the flows and live APIs already
  return: no new API, no change to launches, dispatch or the state files. A failed flows read says so in both
  blocks and is never drawn as 「沒有任務」; with nothing at all, the board becomes a first-run block that points to
  the terminal workbench. It repaints on the 5-second refresh only when a shown field changed, so the search box
  keeps its focus. The other pages' flow and agent cards are unchanged. `tests/qa_game_ui.py` has
  `VBEAR_QA_LOBBY=1` (more flows) and `VBEAR_QA_LOBBY=empty` for it.
- **Safe-mode launches tested on Claude Code 2.1.299.** In a throwaway project with a project-level skill, a launch
  with VBear's flags listed none of the user's or the project's skills (a plain launch did), and its only tool was
  Bash, so there is no Skill tool to call even a built-in skill. The READMEs say so; the skill list of a profile
  is still only a record of your picks.
- **README: a picture of the home page.** `docs/images/lobby.png` (demo data).

## v0.4.0 — game-style screens

The READMEs were rewritten for first-time readers around a game-style vocabulary (character, class, skill card,
armor, party, gates, stamina), with screenshots of demo data. The role card, the skill card, the pre-launch check
and a flow's 任務進度 / 隊伍 / 體力 follow that vocabulary, and a flow's phase now also reads automatic mode's own
events. The README says what to do after Claude Code updates itself (the new version shows *unknown* until you
verify it), and the Codex review token figures from v0.3.0 (see below) are unchanged. A role VBear launches runs in
Claude Code's safe mode, so a role's skill list is only a record of your picks, not something a launch loads.

- **Game-style role card, skill card and pre-launch check.** The workbench's right tab 「角色」 shows a profile as a
  card: its role (a label), its chosen skills (each marked as not loaded by a launch, with the author's text and
  where it came from) and its armor in five groups with the original level words; the same skill card opens from
  the Armory. 「預覽並啟動」 is now 「出發前檢查」: the same one-time preview and confirmation, with the seven labels in
  the same five groups, the list of chosen skills marked 「本次不會載入」, and a reason beside the button while it is
  off. New read-only answers: `GET /api/agent-profiles/<id>/loadout` and `GET /api/skills/<id>?view=card`
  (from what is already loaded; nothing is scanned or started). Names on the screens changed; see the README.
  A flow's page shows 任務進度 as a row of gates (by the phase VBear already derives), 隊伍 as cards (the planner
  marked as only a record; each reviewer says whether it counts as independent of the executor), and 體力 as
  bars with the words: the executor's cost is split into what the CLI recorded and what is counted for turns
  without a result, with 「實際費用尚未知」; a figure that cannot be counted is not drawn as zero.
- **A flow's phase now follows automatic mode's own events.** The phase (and so 任務進度) was read only from the
  events entered by hand, so a flow that only the runner moved stayed at 「計畫中」 even after it had been
  reviewed. It now also reads the runner's events: turning automatic mode on counts as the plan's approval, a
  sent dispatch as the start of work, a verified report as the executor's report, and a valid review result as
  a review. The same fact recorded by hand and by the runner is one round and one review, not two (a report of the
  same commit after a review of it is a new round, whoever made the first); the last event on the timeline
  wins. An automatic result counts once, only for the job and round the runner started,
  and a repeated dispatch or job is ignored with a warning on the page. This changes only what the page derives
  and shows: nothing is written, and the merge gate and the 「需要你處理」 list are read as before. A review made
  by the runner counts as independent only when the executor's model family is known and is not OpenAI, and not
  when the roles were changed after it was made. In automatic mode, when the executor role names no work
  directory, HEAD is compared in the task's directory (the one the automation uses) and the page says so; if
  it cannot be read the pass stays unverified. The flows notice now says what VBear does in each mode instead
  of 「VBear 不會為流程派工」.
- **Screenshots in the READMEs.** Six pictures of demo data (a synthetic Claude Code and Codex in a temporary
  folder; the pre-launch picture has the lines that print the work and temporary folders cut out) are in
  `docs/images/`. They come from `tests/qa_game_ui.py` with `VBEAR_QA_DEMO=1`, which also drops the HTML probe
  skill and any path of the machine from the screens.
- **The pre-launch check of a Codex role speaks for Codex.** The dialog no longer shows Claude Code's version
  notice, the 「驗證這個版本」 button, the terminal-title notice or the Haiku call for a Codex role; it names
  「Codex CLI <version>」, lists the reasons it cannot be launched or the evidence of each label, and its armor
  groups list only the levels a Codex label can have (the preview now carries `armor_groups`). A profile of
  another tool (shared) gets neither tool's words and no Claude-only level, only the reasons. The reason a role
  cannot be launched is shown right under the buttons of its profile page. The question that asks whether to
  remove a skill from a role names the skill (「未提供（ID：…）」 without a name) instead of 「[object Object]」.
- **Correction to the v0.3.0 summary: what a daemon restart needs.** After the background program restarts,
  every automatic flow is stopped and runs again only when you press 「繼續」. VBear first checks that your risk
  acceptance still counts and that HEAD, the reviews and the limits allow it. A turn that was cut off is charged at
  its worst case (often the whole budget), and then you raise the limit, accept again and approve automatic mode
  again. The v0.3.0 summary said acceptance and approval are always needed again; that was too strong. The
  security model's note on how the loop was verified now names the real-model runs.
- **README rewritten for first-time readers.** Both READMEs now open with what VBear is and a game-style
  reading of its screens (character, class, faction, skill cards, armor, party, gates, stamina), then feature
  cards, what to know before you start (the limitations, in plain words) ahead of the install steps, a 3-step
  first use with the real screen names, and the earlier details and technical notes below. The automatic mode's
  note now says it was verified with real models, and says what happens after the background program restarts
  (stopped; you press continue; the limit may need raising and a new acceptance).
  Skills and roles are described as labels and choices a profile records, not as things a launch loads. The
  Traditional Chinese README's long reference sections moved to `docs/REFERENCE.zh-TW.md`.
  The README also says that a launch starts Claude Code in its safe mode, which turns skills off, and describes the
  limits as a stop-loss that real usage can pass.

## v0.3.0 — multi-agent flows

Multi-agent flows: a look-only flows board; a coordinator that runs each step only when you press it; after a
plan is approved, the executor and its reviews run on their own and stop at the merge gate. Claude Code 2.1.296
is stream-verified. Evidence of real-model end-to-end runs: `docs/evidence/s3-real-e2e-2026-10-12.md`.
Merging, pushing and tagging are always done by you, never by VBear. After the daemon restarts, automatic
execution continues only once you accept the risk again and approve the plan again.

- **Codex review tokens.** A review's record now keeps the tokens the review used, taken from the rollout's
  cumulative usage chain (input, cached input, cache-write input, output, reasoning output, total), and the
  reviews panel shows them. A turn that did not finish (a stop, a failure) shows "at least" the recorded part;
  a number that cannot be had (no rollout, a chain that does not add up or disagrees with `turn.completed`, a
  record from before this field or one rebuilt after a crash) reads 「無法取得」 and is never shown as 0. Nothing is converted to money: VBear has no
  reliable price source. The S3 run summary's whitelist carries the same counts. Older records stay readable.
- **Test ports and shared directories.** No test names a port: every test listener binds port 0 and reads the real
  one back, and a test fails the suite if one is added that does not. The test that checks a failed launch leaves
  no scratch directory looks at what its own call made, not at a listing of the shared `/private/tmp`, so two
  copies of the suite can run at the same time. The test that a close does not stall another session no longer
  counts that session's output changes (a CI virtual machine stretched its timer to 48 in a 3 s close); it
  measures the longest time without output over the whole close, trailing stretch included.
- **Unverified Claude Code version, said before start.** When the installed Claude Code has no verified stream mode,
  the flow page says so in the executor panel before the executor is started, and the start button is off. The
  message (also the answer to a refused acceptance, preparation or open) names the version found, lists the versions
  VBear supports (generated from the stream-verified lists) and says what can be done: install one of them, or wait
  for a VBear update. A version that cannot be read is shown as unreadable, never as unverified. The panel reads
  the version from the same cached fact the acceptance uses (at most once per ten seconds).
- **Flows board (look-only).** A new 「流程」 page records multi-agent work on a task card: planner, executor and
  reviewers with their model families, and an append-only event log entered by hand (「手動記錄（未驗證）」). The
  phase, review rounds and commit binding are derived on every read; a review counts as a pass only for different,
  known families, and a pass goes out of date when the executor's directory moves off the reviewed commit. The
  home page's 「需要你處理」 lists flow gates (approval, merge, push, a pass whose HEAD cannot be checked). Stored
  in `flows.json` under the same fail-closed rules as `tasks.json`, now shared in `vbear/jsonstore.py`. VBear does
  not dispatch work, type into a terminal, run `git` or start an agent through the board's recording routes; those
  routes read live state only from the console's cache and never start anything (the managed executor and review
  below are separate, gated routes). Like the home page, the flows pages load the live view,
  which can start VBear's own runtime; they wait for it at most 10 s. A session state from that cache is shown as
  current only when the cache is at most 30 s old, its time is valid, the runtime answered, and this page's own
  load succeeded. Otherwise the executor reads 「即時狀態未載入」 (no cache yet, or this page's load failed or timed
  out), 「即時狀態時間不明」 (the cache's time is missing, invalid or in the future), 「即時狀態已過期」 (older than
  30 s), 「runtime 未連線」 (the runtime did not answer) or 「runtime 狀態不明」 (the cache does not say).
- **Managed Claude stream executor and Codex review (Phase 2).** A flow can now run a pipe-based Claude Code
  `claude-stream` executor and daemon-managed Codex review jobs, started and driven from the console (risk
    acceptance and every dispatch are previewed and approved).
  - *Risk acceptance.* A per-flow dialog shows the three residual risks in full (text version `2026-10-11.1`),
    the CLI versions, models and account fingerprints (first 16 hex digits) it binds to, and nine limits with
    defaults and caps. The preview is stored server-side (five minutes, one use) and confirming carries only its
    id; a change in account, version, key or text voids it. Editing any field voids the held preview.
  - *Executor and dispatch.* Start, stop and continue the executor; each dispatch is previewed as the exact
    sanitized text and approved separately. Strict event attribution, order and tool/result checks decide valid
    turns; failures hold the flow, and a turn with no result is charged at its worst case (an estimate, not a
    bill). Boundary evidence: [Claude Code 2.1.292](docs/evidence/claude-code-2.1.292-stream.md) and [2.1.296](docs/evidence/claude-code-2.1.296-stream.md).
  - *Reports.* The executor's own statement is shown apart from VBear's file checks (HEAD and commit object, read
    without running `git`); a check that fails or cannot be read is not shown as a pass.
  - *Codex review.* Runs in a separate sandboxed clone with a dedicated `CODEX_HOME` and temporary `HOME`; the
    daemon checks completion, report format, events, rollout, usage, model family and the reviewed commit before
    accepting a result. Reports are shown as plain text; `BASE_IS_ANCESTOR` is labelled self-reported. Codex
    0.160.0 cannot disable multi-agent: closed record kinds and an `exec`-only allow-list detect it and
    `SUBAGENT_ACTIVITY` invalidates the whole review without undoing anything. Evidence:
    [Codex 0.160.0](docs/evidence/codex-0.160.0-review.md).
  - *Merge gate.* Three conditions must hold before commands are shown; VBear never runs them, and local refs
    are labelled as local.
  - *Data.* Stream and review records are bounded by a 4 GiB reservation ledger and write-time caps; they are
    kept until you delete the flow, which is refused while anything runs or awaits manual review. When the room
    is used up the console lists the deletable flows with their sizes.
  - *Known limits.* See the residual-risk list in the [security model](docs/SECURITY-MODEL.md#phase-2-coordination).
- **Automatic mode (Phase 3).** After you approve a plan, VBear dispatches it, starts the reviews, forwards NEEDS
  WORK comments (in a block marked as data) and stops at the merge gate, with no per-item approval.
  - *Approval.* One preview shows the plan text in full, the automatic-mode text, the three residual risks, both
    account prefixes and the nine limits (4 h elapsed prefilled); confirming records one event that is both plan
    approval and risk acceptance, saves `plan.txt` and names its hash. The daemon re-verifies the event, the plan
    hash and "newest acceptance" on every automatic action; manual dispatches, reviews and acceptances are refused
    meanwhile (console and daemon).
  - *Runner.* A console thread (one per state directory) writes intent, daemon call, result for every action;
    stops on any invalid turn, failed tests, a report that does not match the files, a bad review, a limit or a
    changed account, an event it cannot write, or anything unexpected; never releases a stop, never starts a
    session, never runs git. A console restart resumes from the events; a daemon restart stops every automatic
    flow until you continue.
  - *Stopping.* Stop is yours, takes effect for new actions at once and lets the executor's turn in progress finish
    by itself. After a turn without a result, continuing needs a higher limit and a new approval (worst-case
    charge). A review ended by a stop is run again as the next round if HEAD is unchanged.
  - *Screens.* The flow page shows the mode, the current step, the approval it runs on and who wrote each event;
    the home list shows stopped flows and flows waiting at the merge gate.
  - Verified with synthetic CLIs; see the [security model](docs/SECURITY-MODEL.md#phase-3-automatic-mode).
- At phone width a long sidebar now scrolls inside the nav instead of widening every page.
- Terminal attachments under backpressure now drop only frames and keep the handshake and protocol notices in
  order; client commands pause at 256 queued notices.
- Four timing-sensitive tests no longer fail on a busy machine: the abandoned-launch expiry log and the open/close
  round trip's hang-up grace no longer race; the linear-parse test budgets CPU time instead of wall time; the
  streaming-during-close test allows half a grace period instead of 0.2 s.

- **Working/waiting follows version verification.** 「驗證這個版本」 now also checks Claude Code's terminal title
  in the same interactive run (no extra model call) and records it apart from the launch-boundary result; a
  version whose title passed shows working/waiting on this Mac. A title failure leaves the launch verified and the
  state unknown. Versions whose boundary is verified but title is not get a notice and the same button. Claude Code
  **2.1.291** is now built in for the title signal too ([evidence](docs/evidence/claude-code-2.1.291-activity.md));
  2.1.286 is not installed here and stays trial.
Ideas adopted from OpenRig, re-implemented ([notes](docs/evidence/openrig-learnings.md)):

- **Working or waiting.** Profile-launched Claude Code sessions now show 「工作中」 or 「等你回覆」 instead of
  always 「狀態未知」, read from the terminal title Claude sets (its idle mark, or its working spinner). Only the
  title's first character is kept, never its text. The signal is used only for Claude Code versions with recorded
  evidence (2.1.292, [evidence](docs/evidence/claude-code-2.1.292-activity.md)); on other versions it is recorded as
  a trial and the state stays unknown. Every status badge says what it is based on. The home page's 「需要你處理」
  lists the agents waiting for you.
- **Task cards bind results to commits.** With a work directory set, a passed test and an approval record the
  commit the directory was on. When it moves, the card reads 「結果對應的版本已變更」 and no longer counts as
  verification asserted. HEAD is read from the `.git` files; VBear never runs `git` there.
- **Closure reasons.** Marking a card 「已回報完成」 or 「阻塞」 asks what follows (no follow-on, handed off,
  superseded, canceled, denied; blocked on, escalated), with a target where one is needed. Enforced by the API.
- **Handoff.** 「交接給…」 closes the card and creates its successor in one write, carrying the chain of earlier
  cards.
- **Pickup state.** Each card shows whether its linked terminal is working, waiting, gone or unclaimed, derived
  when the card is read.
- Research note on giving Codex its own `CODEX_HOME` on 0.160.0
  ([docs/evidence/codex-0.160.0-isolated-codex-home.md](docs/evidence/codex-0.160.0-isolated-codex-home.md)). Codex
  launches stay off; the note also records that the interactive command rejects all four exec-only flags in
  `codex_argv()`.
- The runtime daemon reports itself as `native-r2-s3`. A daemon started by an older VBear keeps running and does
  not report activity evidence until it is restarted.

## v0.2.1

- **Unverified Claude Code versions can launch.** Claude Code updates itself almost daily; a release VBear has not
  verified no longer blocks profile launches. Its permission labels say 「未驗證」, and you tick that you know before
  it starts. A verified version, when installed, is still preferred.
- **「驗證這個版本」** in the launch dialog runs the boundary check on the current Claude Code (two small model calls
  with your own login). A pass is recorded in `~/.vbear/claude-verified.json` and the version counts as verified.
- **Claude Code 2.1.292 verified** (headless and interactive, 15/15 each), through the new button itself.
- The verification script moved into the package (`vbear/boundary_check.py`); `tools/verify_claude_boundary.py`
  still works.
- The CLI version probe waits up to 8 s (was 3 s), so a busy Mac no longer blocks launches.
- GitHub secret scanning and push protection are on for the repositories.

## v0.2.0 — installable macOS workbench

- **macOS app** (Apple Silicon): `VBear.app` with Python 3.13 included, in a `.dmg`. It starts VBear in the
  background (or reuses a running one), signs its window in, and opens external links in your browser. Quitting
  stops only the server it started; terminals keep running. Ad-hoc signed: allow it once in Privacy & Security.
- **Claude Code 2.1.291 verified**: the version gate now accepts a list of verified versions (2.1.286, 2.1.291) and
  launches the newest one installed. New `tools/verify_claude_boundary.py` re-runs the boundary check on any version
  (one model call per run); evidence in `docs/evidence/claude-code-2.1.291.md`.
- Faster live refresh: project lookups are resolved once per build (about 4x faster with many sessions).
- **Access token on the local API**: each start creates a random token; `/api/` needs it as an HttpOnly cookie
  or a Bearer header. Other user accounts on the Mac can no longer drive VBear. Open VBear with
  `python3 -m vbear launch`, which signs the browser in through a private local file.
- **Built-in terminal**: a 「終端機」 page opens your login shell in a folder under your home directory,
  with tabs and direct typing. Labelled as an ordinary, unsandboxed terminal.

## v0.1.0 — first public release

First open-source release under the MIT License.

- **Renamed from SID Console to VBear.** The package is now `vbear` and the state directory is
  `~/.vbear` (an existing `~/.sid-console` is moved on first start). Environment variables are now
  `VBEAR_HOME` and `VBEAR_RUNTIME_AUTOSTART`, and the CSRF header is now `X-VBear`.

- **VBear runtime.** A local daemon that owns agent terminals, so they survive console restarts. Terminals can
  be watched in the browser, typed into after an explicit takeover (one controller at a time),
  and closed from the UI.
- **Profile-managed Claude Code launches** with a preview of seven permission labels, followed by confirmation.
  Bash writes are limited to the work directory and a scratch directory for each session, the network is
  off, Edit and Write are disabled, and files are cleaned up only after every process is proven gone.
  Requires Claude Code 2.1.286 exactly.
- **Codex.** Its terminals can be watched and typed into; profile-managed launch is not available yet (fail closed).
- Skill and agent-role library for Claude Code, Codex and shared skills, with load status, sources,
  search and your own notes.
- Projects and team views, task cards that keep self-reported and verified status separate.
- The Herdr compatibility layer was removed. The last Herdr-based version is tagged `last-herdr`.
- Requires macOS and Python 3.13 or newer.
