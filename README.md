# VBear

**Pick your AI coding agent like a game character: see its class, skills and armor before you send it in.**

VBear is a console that runs on your own Mac. When you start Claude Code from one of its profiles, it shows what
that launch is allowed to do *before* anything starts. It also shows who is working and who is waiting for you,
and where a team of agents stops for your approval. (A terminal tab you open yourself inside VBear is an
ordinary terminal and is not covered by these protections.)

[繁體中文說明](README.zh-TW.md) · [Architecture](docs/ARCHITECTURE.md) · [Security model](docs/SECURITY-MODEL.md) · [Contributing](.github/CONTRIBUTING.md)

> **Status: early (v0.3).** It is built and used daily by one person on macOS.
> The interface is in Traditional Chinese (zh-TW).
> Expect rough edges, and read [Good to know before you start](#good-to-know-before-you-start) before relying on it.

## What is VBear?

Claude Code and Codex can edit files and run commands for you, but it is hard to tell what a launch will really be
allowed to do, or what several agents are up to. VBear puts that on one screen. You choose a character, see its
armor, and only then send it in. If you give a job to a team, VBear shows who is on it and stops at the gates
where you decide.

The game words below are only a way to read VBear's screens. Each one points at something VBear really has.

| In a game | In VBear | Where you see it |
|---|---|---|
| **Character** | An **Agent Profile**: a saved setup (name, role, tool, skills) that you can launch | Workbench → the 「角色」 tab in the right column |
| **Class** | A **role label** on the profile, chosen from the agent roles VBear found for Claude Code or Codex. It is only a label: launching does not load the role's instructions into Claude Code | Same place |
| **Faction** | The **tool** it runs on: Claude Code or Codex CLI. Launching from a profile works with Claude Code only for now | Same place |
| **Skill cards** | The **Skills** VBear found: some installed on your Mac, some only a copy on a marketplace that is not installed yet. The Armory marks each one as available, installed, added to a profile, and whether it was ever seen in use | 技能庫 → Armory |
| **Armor** | The **protection a launch actually puts on, and the weak spots it does not cover**: writes kept inside the work directory, no network, Edit/Write tools off. Seven permission labels, each saying how strongly it holds | 「出發前檢查」 |
| **Party** | A **flow**: the planner (who writes the plan), the executor (who does the work) and the reviewers (who check it) on one task, each with a model family. The planner is a role recorded in the flow: automatic mode runs the plan you approved, and VBear never starts a planner | 流程 |
| **Gates** | **Approval, merge and push gates**: where VBear stops and waits for you | Home page 「需要你處理」 |
| **Stamina** | The **limits** you set for automatic runs, like a stop-loss: reviews, dispatches, model responses, time, executor budget. When one is reached, VBear stops the flow. Some usage is only known afterwards (cost, for example), so the real figure can end up above a limit; set them low the first time | The approval screen and the executor panel's meters |

VBear has no levels, hit points or scores. It shows only what it can read or check, and says *unknown* when it
cannot. Adding a skill to a profile only records your choice. VBear starts Claude Code in its safe mode, which
switches off skills, CLAUDE.md files, installed plugins, hooks and MCP servers, so a launched Claude Code does not use
skills for now: a profile's skill list is a record of your picks.

## What you can do with it

**See what an agent may do before it starts.**
When you launch Claude Code from a profile, pick a work directory and you get a preview of seven permission labels
(read, write, test, commit, deploy, network, filesystem), each with how strongly it holds and the evidence. A profile
launch starts only after you confirm. The Bash tool can write only to the work directory and a private temporary
folder, and it has no network; where a limit does not hold (reading files, commits), the label says so.

**Keep your skills and roles in one place, and save your picks as characters.**
VBear reads the skills and agent roles it finds for Claude Code and Codex and shows, for each one, whether
the tool actually loads it, where it came from and what it is for. Every fact carries its source. You can save a
choice of skills and a role as a profile (that records your choice; a launch does not load them). Your own names and notes are
stored locally and never written into the skill files.

**See who is working and who is waiting.**
Agent terminals run in a small background program on your Mac, so they keep running when you close the browser
tab. You can watch any of them, and typing takes an explicit takeover (one tab at a time). For Claude Code that you
launched from a profile, on a version with recorded evidence, the console shows whether it is working or waiting
for you.

**Put several agents on one task and see where it stands.**
A flow records who plans, who does the work and who checks it, and which AI maker each one is from. The 「流程」 page
shows the phase, the review rounds and a timeline, and the home page lists the gates waiting for you. A review counts
as a pass only when the checker and the one who did the work are from different makers, so nobody grades their own
work; and a pass is marked out of date as soon as the code changes.

**Let the loop run, and have it stop at the gate.**
Approve a plan once and VBear can hand it to a Claude Code executor, check the executor's report against the
files, ask Codex to review, send NEEDS WORK comments back, and stop at the merge gate. You can stop it at any time and
nothing resumes by itself. It has been run end to end with real models
([evidence](docs/evidence/s3-real-e2e-2026-10-12.md)). It spends your own usage. The limits you set work like a
stop-loss: when one is reached VBear stops the flow, and since some usage is only known afterwards, the real figure
can end up above it, so set them low the first time. VBear never runs `git`: merging and pushing stay with you.

**Everything stays on your Mac.**
No telemetry, no accounts, no cloud. VBear makes no outbound network requests and its server listens on
`127.0.0.1` only. The agents you launch talk to their own providers under your own login, as they would without VBear.

## What VBear promises, in short

- **It holds:** Claude Code that VBear starts can write only inside the work directory, has no network, and changes
  files only through the Bash tool.
- **It does not hold:** reading, because Claude Code can still read any file your Mac account can read, and
  commands you type yourself after `!`, which are not sandboxed.
- **Merging, pushing and publishing are always yours.** VBear never runs `git` for you.
- **Automatic mode uses your accounts' usage.** The limits you set are a stop-loss, not a guarantee of the bill.
- **A review PASS is another AI's opinion, not proof.** Read the changes yourself before you merge.
- **Deleting a flow cannot be undone.**
- **The app is not signed with an Apple Developer ID.** The first time, allow it under System Settings →
  Privacy & Security → **Open Anyway**.
- The full list, with what you can do about each, is in
  [Good to know before you start](#good-to-know-before-you-start).

## Getting started: 3 steps

**Before you set out:** Claude Code is installed on your Mac and you are signed in to it
([get Claude Code](https://claude.com/product/claude-code)). VBear launches it for you, but it does not install it.

1. **Install.** Download `VBear-<version>-arm64.dmg` from the
   [latest release](https://github.com/sidphoto/vbear/releases/latest), open it and drag **VBear** into
   Applications. The first time, macOS refuses to open it: go to **System Settings → Privacy & Security**, scroll
   down and click **Open Anyway** next to VBear. Homebrew and running from source are in [Install](#install).
2. **Open VBear.** The app opens its own window. The menu on the left has 我的工作台, 終端機, 終端工作台, 流程,
   技能庫, Agent 團隊, 專案 and 設定. VBear lists the skills and agent roles it finds on your Mac (read-only; it
   changes none of them).
3. **Pick a character and preview the launch.**
   - Click **終端工作台** in the left menu, then the **角色** tab in the right column.
   - Click **+ 建立 Agent Profile**. Give it a name, optionally a role (職業), the tool `claude`, and the skills you
     want (**選入 →** adds one), then click **建立 Profile**.
   - Click **出發前檢查** on the profile. Type the work directory: the folder's full path, inside your home
     folder (for example `/Users/you/projects/demo`). To get a path without typing it, right-click the folder in
     Finder, hold the Option key and choose **Copy “folder” as Pathname**, then paste it into the box.
   - Read the seven labels. They sit in five boxes (擋住了 blocked, 部分擋住 partly blocked, 沒有專用權限 no
     dedicated permission, 沒有擋 not blocked, 未證明 not proven); in each box a label keeps its own name and the
     word for how strongly it holds (the screen uses words, not colors). Below them is the list of skills you
     chose, marked as not going with the launch. The words: 「強制」 and 「部分強制」 mean the limit really holds; 「僅意圖」, 「未限制」,
     「未驗證」 and 「未知」 mean it is not enforced or not proven; 「不授予」 means it is not given at all.
     The short version: look at the **Write** and **Network** rows. 「強制」 there means VBear really blocked it. Reading
     is not limited: it can read any file you can read.
   - Tick the box about commits, and click **確認啟動** only if you are happy with what you see.

## Good to know before you start

VBear's rule is to say how far each protection really reaches, and where it does not. Here is where it does not,
and what you can do about each.

- **Files can still be read.** Claude Code launched from a profile can write only inside the work directory and its
  own temporary folder, and it has no network. It can still *read* anything your Mac account can read. Choose the
  work directory with that in mind.
- **Commands you type after `!` are not sandboxed.** In Claude Code, a command you type yourself after `!` runs as
  you, without the sandbox. Type those only when you mean to; the preview says so.
- **Commits cannot be blocked yet.** The work directory's `.git` can be written, so the agent can save commits (a
  commit is a saved snapshot of the code in git) there. You tick a box to acknowledge this before launch; look over
  the history before you merge or push.
- **One launch shape for now.** Only Bash is allowed, Edit and Write are off, and there is no network. Read-only,
  network-enabled and Codex profile launches are planned, not built.
- **Skills are switched off in launches for now.** VBear starts Claude Code with `--safe-mode`, which (as Claude
  Code's own help says) disables skills, CLAUDE.md files, installed plugins, hooks, MCP servers and custom commands
  and agents; sign-in, model choice and the built-in tools work as usual. A profile's skill list is therefore a
  record of your picks, not something the launch loads or uses. A Claude Code you start yourself in a terminal is
  not launched by VBear and is not affected.
- **"Working / waiting" is not known everywhere.** It is shown only for Claude Code launched from a profile, on a
  version with recorded evidence (2.1.291, 2.1.292, or verified on your Mac). After Claude Code updates itself, the
  new version shows *unknown* until you press 「驗證這個版本」 in the launch dialog. It cannot tell waiting for your
  next message from waiting on a dialog, and other terminals and Codex show *unknown*.
- **A task card goes out of date only when a commit changes.** Uncommitted changes made after an approval do not
  make it stale, so commit before you approve.
- **Automatic mode runs while you are away.** It spends usage on your accounts. The limits you set work like a
  stop-loss: when one is reached VBear stops the flow. Some usage is only known afterwards (cost, for example), so the
  real figure can end up above a limit, and the limits differ in strength; for the first run, set them low. Review comments, which
  the reviewed code can influence, go to the executor without your approving each one. A turn that was stopped can
  keep running until it ends. After the background program restarts, automatic flows stop and you press 「繼續」:
  VBear first checks the risk acceptance, the limits and the other conditions, and a turn that was cut off is
  counted at its worst case (often the whole budget), so you raise the limit, accept again and approve automatic
  mode again. It was verified end to end with real models on a small toy project (Claude Code 2.1.296 as the
  executor, Codex 0.160.0 as the reviewer; three runs: full loop, stop, console restart): that is evidence it works
  as designed, not a guarantee for your project. Start with low limits, and read the
  [evidence](docs/evidence/s3-real-e2e-2026-10-12.md) and the
  [security model](docs/SECURITY-MODEL.md#phase-3-automatic-mode) before turning it on.
- **A review PASS is not proof.** Letting an agent do the work and Codex review it carries risks you accept once per
  flow (Codex's tools cannot be listed in advance and its multi-agent mode cannot be turned off, only detected; the
  limits differ in strength; settings managed by an organization cannot be seen locally). The same content can get
  different review conclusions, so read the changes yourself before you merge. Deleting a flow cannot be undone;
  a flow whose records are damaged, or cannot be proven to be its own, is refused with the reason, and there is no
  forced delete, so such a flow is cleaned up by hand (see
  [when a flow cannot be deleted](docs/SECURITY-MODEL.md#when-a-flow-cannot-be-deleted)). The full list is in the
  [security model](docs/SECURITY-MODEL.md#phase-2-coordination).
- **Programs running as you can drive VBear.** Other websites and other user accounts are kept out: every request
  needs a token that is renewed at each start and stored in a file only you can read. A program running under your
  account can read that file, so treat VBear like anything else that runs under your account. See the
  [security model](docs/SECURITY-MODEL.md).
- **The app is not signed with an Apple Developer ID**, so macOS refuses to open it the first time. Allow it once
  under System Settings (see [Install](#install)).

## Supported agents

| Agent | Watch and type in terminals | Profile launch with preview and sandbox |
|---|---|---|
| Claude Code | yes | yes. Verified versions (2.1.286, 2.1.291, 2.1.292, 2.1.296, plus any you verify) get enforced labels; other releases launch only after you tick that you know they are **unverified** |
| Codex CLI | yes | **not yet.** The preview explains why: 0.159.2's interactive mode still loads your global config |

The executor (the Claude Code that a flow runs in the background) needs Claude Code 2.1.292 or 2.1.296; Codex review
needs Codex 0.160.0. Other versions are refused with the reason before anything starts.

Skill and role scanning reads Claude Code (`~/.claude`), Codex (`~/.codex`) and shared skills
(`~/.agents`). It never modifies them.

## Install

### The app (recommended)

1. Download `VBear-<version>-arm64.dmg` from the [latest release](https://github.com/sidphoto/vbear/releases/latest),
   open it and drag **VBear** into Applications. It needs an Apple Silicon Mac (M1 or later) and macOS 13 or newer.
   Python is included, so there is nothing else to install.
2. **First open:** the app is not yet signed with an Apple Developer ID, so macOS will refuse to open it the first time.
   Open **System Settings → Privacy & Security**, scroll down, and click **Open Anyway** next to VBear. You only
   need to do this once.

Or with Homebrew:

```sh
brew install --cask sidphoto/tap/vbear
```

Quitting the app stops its window and server. Terminals you opened keep running, and they are there again
the next time you open VBear.

### From source

Requirements:
- macOS. This is the only platform it has been tested on; launching from a profile uses macOS-specific paths.
- Python **3.13 or newer**, because the safe version check for agent CLIs needs `os.waitid`, which
  arrived on macOS in 3.13. The system `/usr/bin/python3` on macOS is 3.9 and will not work, so use
  Homebrew or python.org.
- Claude Code, only if you want profile launches. Claude Code updates itself often. A version VBear has not verified
  still launches, but its permission labels say **unverified** and you must tick that you know. The launch dialog's
  **驗證這個版本** button runs the boundary check on it (two small model calls with your own Claude login, about
  1–3 minutes); once it passes, that version counts as verified on your Mac. The same check is
  [`tools/verify_claude_boundary.py`](tools/verify_claude_boundary.py).

There are no packages to install. The backend uses only the Python standard library, and the web UI
has no build step.

```sh
git clone https://github.com/sidphoto/vbear.git
cd vbear
python3 -m vbear launch     # starts the console in the background and opens http://127.0.0.1:7788
```

Other commands:

```sh
python3 -m vbear serve --open   # run in the foreground
python3 -m vbear doctor         # check skill sources and the VBear runtime
python3 -m vbear scan           # rescan skills and print a summary
```

Data lives in `~/.vbear/`. Set `VBEAR_HOME` to use another directory.

## Privacy

- **No telemetry, no accounts, no cloud.** VBear makes no outbound network requests. The server
  binds to `127.0.0.1` only.
- Scanning the agents' own logs extracts only skill names, model names, session IDs, working directories and
  timestamps. Conversation content is never read out or stored. You can turn this off in Settings.
- The agents you launch talk to their own providers under your own login, as they would without VBear.

## The details behind the cards

- **Built-in terminal.** Open your login shell in any folder under your home directory from the
  「終端機」 page and type right away. Multiple terminals show as tabs. These are ordinary terminals
  under your account, **not sandboxed**, and the UI labels them that way.
- **Terminal workbench.** Agent terminals run in a small local background program (the *VBear runtime*), so they keep
  running when the browser tab or the console closes. You can watch any terminal in the browser.
  Typing into it takes an explicit takeover, and only one tab can type at a time.
- **Previewed, sandboxed Claude launches** (launches that VBear starts and keeps watch of). You pick an *Agent Profile* and a work directory, and you
  get a preview of seven permission labels (read, write, test, commit, deploy, network, filesystem).
  Each label says how strongly it is enforced, with the evidence. The launch starts only after you
  confirm it. Claude's Bash tool can write only to the work directory and a private temporary directory
  for that run, and it has no network access. After the run ends, those files are removed only once every
  process of the run is proven gone.
- **Skill and role library.** It reads the skills and agent roles installed for Claude Code and Codex.
  For each one it shows whether the tool actually loads it, where it came from, and what it is
  for. Every fact carries its source, and it says *unknown* when there is no source.
- **Projects and team view.** It groups running terminals by git repository and by agent role. It also
  shows which model and which skills a run actually used, read from the agent's own session logs.
- **Working or waiting.** For Claude Code launched from a profile, on a version with recorded evidence
  (2.1.291 and 2.1.292 built in, plus any version whose title check passed on your Mac), the console shows whether
  the agent is working or waiting for you, read from the terminal title Claude sets, and lists the waiting ones on
  the home page. Every status says what it is based on; anything else shows *unknown*. 「驗證這個版本」 in the
  launch dialog checks the title in the same run as the launch boundary.
- **Task cards.** Local goal, scope and acceptance checklists. The status shows separately what an agent claimed,
  what tests reported and what you approved, and the console never labels a card "verified". With a work
  directory, a test result and an approval are tied to the commit they were given for and go stale when it moves.
  Marking a card done or blocked asks what follows; a handoff closes the card and opens its successor with the
  chain of earlier cards; whether anyone is on it is worked out from the linked terminal, not typed in.
- **Flows (look-only).** One task card carried by several agents: who plans, who executes, who reviews, each
  with a model family (the maker of the model: Anthropic, OpenAI, Google and so on). The 「流程」 page shows the phase (planning, awaiting approval, implementing, review round N,
  needs fix, passed and awaiting merge, review out of date, awaiting push, done), the review rounds and a timeline,
  and the home page lists the gates waiting for you. Phases are derived on every read, never stored. A review
  counts as a pass only when reviewer and executor are of different, known model families, and a pass goes out of
  date as soon as the executor's directory moves off the reviewed commit. Every event is entered by hand and
  labelled 「手動記錄（未驗證）」. The board's recording routes do not dispatch work, type into a terminal, run `git`
  or start an agent (the executor below is separate). Like the home page, the flows pages read the live
  view, which can start VBear's own runtime.
- **Executor and review (Phase 2).** From a flow you can start a Claude Code executor that VBear runs in
  the background (no terminal) and ask Codex to review its latest commit in a separate sandboxed clone. You accept
  three residual risks per flow, approve each dispatch as the exact text that will be sent, see the executor's own
  report apart from VBear's file checks, read the reviewer's report as plain text, and get the merge and push
  commands to run yourself: VBear never runs `git` for you. Needs Claude Code 2.1.292 or 2.1.296 and Codex 0.160.0 (the
  verified versions) and costs usage on your own accounts. Data stays until you delete the flow. See the
  [security model](docs/SECURITY-MODEL.md#phase-2-coordination) before using it.
- **Automatic mode (Phase 3).** After you approve a plan, VBear can run the loop itself: dispatch the plan, check
  the executor's report against the files, ask Codex to review, forward NEEDS WORK comments back (as marked data),
  and stop at the merge gate for you. The approval shows the whole plan, the limits, the accounts and every risk
  at once; you can stop it at any time; nothing resumes by itself; a restart stops every automatic flow. VBear
  still never runs `git` for you. It has been verified end to end with the real models (Claude Code 2.1.296 and
  Codex 0.160.0: a full run to the merge gate, a stop while a review runs, and a console restart while a review runs;
  see the [evidence](docs/evidence/s3-real-e2e-2026-10-12.md)). After the background program restarts, every
  automatic flow is stopped and runs again only when you press 「繼續」. VBear first checks that your risk acceptance
  still counts and that HEAD, the reviews and the limits allow it. A turn that was cut off is charged at its worst
  case (often the session's whole budget): then you raise the limit, accept again and approve automatic mode again.
- **Names on the screens.** Some names changed to match the game words above (old → new): 「角色裝備」 tab →
  「角色」; 「職業角色」 → 「職業」; 「模型工具」 → 「工具（遊戲用語：陣營）」; 「已裝備技能 (Equipped Skill Loadout)」 →
  「已選技能」; 「加入裝備 →」 → 「選入 →」; 「預覽並啟動」 → 「出發前檢查」; the Armory's 「已裝備到 Profile」 → 「已加入角色」; the limits' heading
  「上限」 → 「體力（停損設定）」; a flow's 「階段」 → 「任務進度」 and its 「角色」 section → 「隊伍」.
- **Your own notes.** Give skills friendly names, tags and notes. These are stored locally and never
  written into the skill files.

## Technical details

- **Standard library only.** The backend uses only the Python 3.13+ standard library (no pip packages, no cloud
  services). The web UI has no build step. Its one dependency is the MIT-licensed `@xterm/xterm` and
  `@xterm/addon-fit`, bundled in `web/vendor/xterm/` at a pinned version and checked against fixed SHA-256 hashes by
  the tests. Nothing is loaded from a CDN, and the content security policy keeps `script-src 'self'`.
- **Read-only sources.** VBear reads only the external sources you select and changes no skill or role file. It
  runs no script found in a skill. (VBear's own settings, notes and terminal actions are the exceptions.)
- **Sourced facts.** Every fact is labelled with where it came from (the author's description, derived by VBear,
  observed at run time, or not provided), and *unknown* is shown when there is no source.
- **Where things are.** How it is built is in [ARCHITECTURE](docs/ARCHITECTURE.md); what it defends against and
  what it cannot is in the [security model](docs/SECURITY-MODEL.md).
- **Reference sections only in Traditional Chinese.** The page-by-page tour, where each fact comes from, the skill
  states, the security details, the state directory and the source layout are currently written out only in
  [docs/REFERENCE.zh-TW.md](docs/REFERENCE.zh-TW.md). For the English side, see
  [ARCHITECTURE](docs/ARCHITECTURE.md) and the [security model](docs/SECURITY-MODEL.md).

## Developing

```sh
python3 -m unittest discover -s tests              # backend tests (synthetic HOME, no network)
for f in tests/frontend/*.cjs; do node "$f"; done   # frontend behaviour tests (Node, synthetic DOM)
```

See [CONTRIBUTING](.github/CONTRIBUTING.md) for the workflow and [AGENTS.md](AGENTS.md) for
instructions aimed at coding agents working on this repository.

## Community & support

- Questions and ideas: [GitHub Discussions](https://github.com/sidphoto/vbear/discussions)
- Bugs and feature requests: [GitHub Issues](https://github.com/sidphoto/vbear/issues)
- Security issues: please **do not** open a public issue. See [SECURITY.md](SECURITY.md).

Issues and discussions in English or Traditional Chinese are both welcome.

## License

[MIT](LICENSE). The bundled [xterm.js](https://github.com/xtermjs/xterm.js) and its fit addon
(`web/vendor/xterm/`) are MIT-licensed by their authors; see `web/vendor/xterm/LICENSE`.

## About

VBear is named after the Formosan black bear and the V-shaped mark on its chest. Like the bear,
it watches before it acts: VBear shows you what a launch may do before anything starts.

It was called **SID Console** until v0.1.0, and it began as a plugin for the Herdr terminal multiplexer.
The last Herdr-based version is tagged `last-herdr`. On first start, VBear moves an existing
`~/.sid-console` state directory to `~/.vbear`.
