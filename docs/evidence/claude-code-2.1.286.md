# Boundary evidence: Claude Code 2.1.286

This is a public summary of the maintainer's tests behind the launch preview's labels. The raw logs contain
local paths and stay private. The test harness is not yet published as a reusable script.

- Binary: Claude Code **2.1.286** (native build, macOS arm64), one of the verified versions in
  `vbear/runtime/cli_versions.py`.
- Settings: exactly what `claude_settings()` in `vbear/runtime/agent_sessions.py` produces, with flags
  `--safe-mode --tools Bash --disallowedTools Edit,Write --strict-mcp-config`.
- Dates: 2026-10-02 to 2026-10-04. A small model was told to run fixed probe commands. Results were read from the probe's own
  output files and errno values, not from the model's reply.

## Writes

Tested in three ways: two Claude sessions in parallel (A and B), one real interactive PTY session, and the full
product path (preview, confirm, daemon `open_managed`).

| Probe from inside the Bash tool | Result |
|---|---|
| Write in its own work directory | allowed |
| Write in its own scratch directory (`CLAUDE_CODE_TMPDIR`) | allowed |
| Write in the other session's work directory | `EPERM` |
| Write in the other session's scratch directory | `EPERM` |
| Write through a symlink pointing at the other session's work directory | `EPERM` |
| Write outside both (another directory, a file in `HOME`) | `EPERM` |

The shared per-user temp directory (`/tmp/claude-<uid>`) is explicitly denied, because Claude Code falls
back to it when the scratch path is longer than 44 bytes. The product keeps its scratch path short and checks the length.

## Network

| Probe from inside the Bash tool | Result |
|---|---|
| Direct TCP connect to `1.1.1.1:443` | `EPERM` |
| HTTPS request through the sandbox proxy (`example.com`) | refused by the proxy (403) |
| Same request outside the sandbox (control) | 200 |

Other protocols were not tested separately.

### Loopback

Added 2026-10-06 and tested on **Claude Code 2.1.291** in headless mode. It has not been re-run on 2.1.286.

| Probe from inside the Bash tool | Result |
|---|---|
| HTTP to the VBear port on `127.0.0.1` | `EPERM` |
| Connect to the VBear runtime unix socket | `EPERM` |

## Lifecycle

- In every run the launch's scratch directory and per-launch files were removed only after every tracked
  process had exited; no processes were left behind.
- The global Claude Code install, `~/.claude` settings and Codex config were unchanged afterwards.
  This was checked against a hash inventory taken before the run.

## Not claimed

- Read isolation: the product's settings do not restrict reads.
- Commands typed with `!` in the Claude Code prompt, which run outside the sandbox.
- Any other Claude Code version, any other settings shape, or the Edit and Write tools.
- Isolation between processes running under the same uid in general.
