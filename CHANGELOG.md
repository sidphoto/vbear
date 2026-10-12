# Changelog

## Unreleased

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
