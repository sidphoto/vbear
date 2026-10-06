# Boundary evidence: Claude Code 2.1.291

Produced with [`tools/verify_claude_boundary.py`](../../tools/verify_claude_boundary.py), which anyone can re-run.
The script builds the sandbox settings and launch arguments with VBear's own code
(`claude_settings()`, `claude_argv()`), runs one real Claude Code session, asks a small model to run a probe
script with the Bash tool, and judges only the probe's own output file and errno values.

- Binary: Claude Code **2.1.291**, native build, macOS arm64.
- Date: 2026-10-07.
- Runs: one **headless** (`-p`) run and one **interactive** run (the TUI in a real PTY, which is how VBear launches
  it), each with `claude-haiku-4-5-20251001`. Both runs gave the same result.

## Writes

| Probe from inside the Bash tool | Expected | Result (both runs) |
|---|---|---|
| Write in its own work directory | allowed | allowed |
| Write in its own scratch directory (`CLAUDE_CODE_TMPDIR`) | allowed | allowed |
| `TMPDIR` inside the session is its own scratch directory | yes | yes (`<scratch>/claude-<uid>`) |
| Write in a peer work directory | refused | `EPERM` |
| Write in a peer scratch directory | refused | `EPERM` |
| Write through a symlink in the work directory pointing at the peer | refused | `EPERM` |
| Write in an unrelated directory | refused | `EPERM` |
| Write a file in `HOME` | refused | `EPERM` |
| Write in the shared `/tmp/claude-<uid>` | refused | `EPERM` |

Afterwards, none of the refused files existed.

## Network

| Probe from inside the Bash tool | Expected | Result (both runs) |
|---|---|---|
| Direct TCP connect to `1.1.1.1:443` | refused | `EPERM` |
| HTTPS request through the sandbox proxy (`example.com`) | refused | proxy answered 403 |
| TCP connect to a listener on `127.0.0.1` (stands in for the VBear port) | refused | `EPERM`; the listener saw 0 connections (headless run) |
| Connect to a unix socket (stands in for the VBear runtime socket) | refused | `EPERM`; 0 connections (headless run) |

The interactive run's connection counters were not collected: a bug in the harness's PTY teardown, since fixed, hung the
script after the probe had written its results. Its probe recorded `EPERM` for both connects.

## Lifecycle

Through the full product path on an isolated VBear (preview, confirm, daemon `open_managed`, close), with no prompt
and no model call:
- the preview chose the 2.1.291 binary and pointed its evidence at this page;
- closing reported `cleaned: true`;
- afterwards the scratch directory and the per-launch files were gone, and no Claude process was left.

## Not claimed

- Read isolation: the product's settings do not restrict reads.
- Commands typed with `!` in the Claude Code prompt, which run outside the sandbox.
- Any other version, settings shape, or the Edit and Write tools.
