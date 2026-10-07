# Changelog

## Unreleased

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
