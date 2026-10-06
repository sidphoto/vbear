# VBear

**A local console for running and supervising coding agents on your own machine.**
VBear keeps your Claude Code and Codex terminals in one place. It explains what an agent
launch is allowed to do *before* it starts, and it shows your scattered agent skills and roles in plain language.

[繁體中文說明](README.zh-TW.md) · [Architecture](docs/ARCHITECTURE.md) · [Security model](docs/SECURITY-MODEL.md) · [Contributing](.github/CONTRIBUTING.md)

> **Status: early (v0.1).** It is built and used daily by one person on macOS.
> The interface is in Traditional Chinese (zh-TW).
> Expect rough edges, and read [Known limitations](#known-limitations) before relying on it.

## Features

- **Built-in terminal.** Open your login shell in any folder under your home directory from the
  「終端機」 page and type right away. Multiple terminals show as tabs. These are ordinary terminals
  under your account, **not sandboxed**, and the UI labels them that way.
- **Terminal workbench.** Agent terminals run in a small local daemon (the *VBear runtime*), so they keep
  running when the browser tab or the console closes. You can watch any terminal in the browser.
  Typing into it takes an explicit takeover, and only one tab can type at a time.
- **Previewed, sandboxed Claude launches.** You pick an *Agent Profile* and a work directory, and you
  get a preview of seven permission labels (read, write, test, commit, deploy, network, filesystem).
  Each label says how strongly it is enforced, with the evidence. The launch starts only after you
  confirm it. Claude's Bash tool can write only to the work directory and a private temporary directory
  for that session, and it has no network access. After the session ends, those files are removed only once every
  process of the session is proven gone.
- **Skill and role library.** It reads the skills and agent roles installed for Claude Code and Codex.
  For each one it shows whether the tool actually loads it, where it came from, and what it is
  for. Every fact carries its source, and it says *unknown* when there is no source.
- **Projects and team view.** It groups running terminals by git repository and by agent role. It also
  shows which model and which skills a session actually used, read from the agent's own session logs.
- **Task cards.** Local goal, scope and acceptance checklists. The status shows separately what an agent claimed,
  what tests reported and what you approved, and the console never labels a card "verified".
- **Your own notes.** Give skills friendly names, tags and notes. These are stored locally and never
  written into the skill files.

## Supported agents

| Agent | Watch and type in terminals | Profile launch with preview and sandbox |
|---|---|---|
| Claude Code | yes | yes, on **verified versions only** (2.1.286, 2.1.291); any other version is refused |
| Codex CLI | yes | **not yet.** The preview explains why: 0.159.2's interactive mode still loads your global config |

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
- macOS. This is the only platform it has been tested on; the managed launch uses macOS-specific paths.
- Python **3.13 or newer**, because the safe version check for agent CLIs needs `os.waitid`, which
  arrived on macOS in 3.13. The system `/usr/bin/python3` on macOS is 3.9 and will not work, so use
  Homebrew or python.org.
- Claude Code 2.1.291 or 2.1.286, only if you want profile launches. Claude Code updates itself often; a new version
  works in VBear once it passes [`tools/verify_claude_boundary.py`](tools/verify_claude_boundary.py) and is added to the
  verified list.

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
- Session-log scanning extracts only skill names, model names, session IDs, working directories and
  timestamps. Conversation content is never read out or stored. You can turn this off in Settings.
- The agents you launch talk to their own providers under your own login, as they would without VBear.

## Known limitations

- **Reads are not isolated.** A sandboxed Claude session can still read anything your user account can
  read. Only writes and the network are restricted.
- **`!` commands bypass the sandbox.** Commands you type yourself after `!` in Claude Code are not sandboxed.
  The preview says so.
- Commit cannot be blocked yet: the work directory's `.git` is writable, and you must acknowledge this before launch.
- Only one launch shape exists (Bash only, Edit and Write disabled, no network). Read-only,
  network-enabled and Codex launches are planned, not built.
- The console cannot tell whether an agent is working or waiting for you, so it shows *unknown*.
- **Programs running as your own user can drive VBear.** Other websites and other user accounts are kept out:
  every API call needs a per-launch token stored in a file only you can read. A program running under your
  account can read that file. See the [security model](docs/SECURITY-MODEL.md).

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
