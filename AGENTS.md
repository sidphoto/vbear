# Instructions for coding agents

This file is for AI coding agents (Claude Code, Codex and others) working on this repository.
Humans should read [CONTRIBUTING](.github/CONTRIBUTING.md) as well.

## Ground rules

- **Standard library only.** Do not add pip or npm dependencies. The front end has no build step;
  `web/vendor/xterm/` is the only vendored code, and its SHA-256 hashes are pinned by a test.
- **Truthful UI.** Every fact shown to the user must have a source. When there is no source, show
  "unknown"/「未知」. Never present a self-reported status as verified.
- **Fail closed** in launch and permission code. If something cannot be proven, such as a version, the sandbox,
  or that every process has exited, refuse or keep the state for manual review. Do not guess.
- **Never touch real user data in tests.** Tests must use a synthetic `HOME`, a temporary
  `VBEAR_HOME`, and `VBEAR_RUNTIME_AUTOSTART=0` unless they start their own daemon in a temp dir.
  Never connect to the user's console on port 7788 or to `~/.vbear/runtime.sock`.
- User-facing text is Traditional Chinese (zh-TW). Code, comments and commit messages are English.
- Match the surrounding code's style and comment density.

## Before you finish

```sh
python3 -m unittest discover -s tests
for f in tests/frontend/*.cjs; do node "$f" || exit 1; done
```

Both must pass. If you change behaviour, add a test that would catch a regression.
If you touch the launch boundary (`agent_launch.py`, `runtime/agent_sessions.py`,
`runtime/daemon.py` managed paths, `runtime/proctrack.py`), update
[docs/SECURITY-MODEL.md](docs/SECURITY-MODEL.md) in the same change.

## Map

See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).
