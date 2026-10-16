# Changelog

## v0.7.0 — card play (unreleased)

A first-time user can now build a team in three card moves, with no form to fill in: **collect** role cards (or take
the starter deck), **equip** skill cards, and **play** a card onto a task card's team place, then set out. A task card
is one folder, and an existing project can be brought in and managed. The version number is not changed here; this
section lists what the branch holds so far.

**Words.** 「Agent 團隊」 is now 「角色卡池」; a profile is a 「角色卡」, chosen skills are 「技能卡」 in slots
(dashed 「收藏中」, solid 「生效中」 only when the loadout says a skill really loads, which no launch does today),
the tool is the 「陣營」, permission intents have Chinese labels and say they are a record, not a grant.

- **Card pool and wizard.** A card-pool page with a starter deck of three (CEO, 工匠, 審查員; the reviewer is left
  unticked when Codex is not installed), a three-step wizard (name and look, tool and place, skill cards) whose
  bottom buttons stay in view on a phone, suggested permission intents marked 「建議，可改」, and a same-name hint that
  never blocks. `GET /api/agent-builder/catalog` carries the deck, positions and `codex_installed`.
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
- **QA and tests.** The QA console gained `VBEAR_QA_FRESH=1` and `VBEAR_QA_TRANSLATE=fail`; the fake translation CLI
  follows the structured-output change. New tests cover the folder API, the config keys, flow role cards, `will_load`,
  the starter deck, the pass table level by level, the team places and the first game.
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
