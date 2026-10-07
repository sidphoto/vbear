# Boundary evidence: Claude Code 2.1.292

Produced on 2026-10-07 by VBear's own 「驗證這個版本」 button, which runs
[`vbear/boundary_check.py`](../../vbear/boundary_check.py) (the same check as `tools/verify_claude_boundary.py`):
VBear's own `claude_settings()` / `claude_argv()`, one real Claude Code session per mode, a small model told to run a
probe script with the Bash tool, and judgement from the probe's own output and errno values only. A refusal counts only
if it is the sandbox's (`EPERM`/`EACCES`, or the sandbox proxy's 403).

- Binary: Claude Code **2.1.292**, native build, macOS arm64.
- Runs: **headless** (`-p`) and **interactive** (the TUI in a real PTY, which is how VBear launches it), each with
  `claude-haiku-4-5-20251001`. Both passed 15/15. Total time for both: 27 seconds.

<a id="writes"></a><a id="network"></a>

| Check | Headless | Interactive |
|---|---|---|
| Write in its own work directory | allowed | allowed |
| Write in its own scratch directory | allowed | allowed |
| `TMPDIR` is its own scratch directory | allowed | allowed |
| Write in a peer work directory | `EPERM` | `EPERM` |
| Write in a peer scratch directory | `EPERM` | `EPERM` |
| Write through a symlink to the peer | `EPERM` | `EPERM` |
| Write in an unrelated directory | `EPERM` | `EPERM` |
| Write a file in `HOME` | `EPERM` | `EPERM` |
| Write in the shared `/tmp/claude-<uid>` | `EPERM` | `EPERM` |
| Direct TCP to `1.1.1.1:443` | `EPERM` | `EPERM` |
| HTTPS through the sandbox proxy | proxy 403 | proxy 403 |
| TCP to a listener on `127.0.0.1` | `EPERM` | `EPERM` |
| Connect to a local unix socket | `EPERM` | `EPERM` |
| Files left outside the allowed paths | none | none |
| Connections the local listeners saw | 0 connections | 0 connections |

## Lifecycle

Not re-run for this version: cleanup is VBear's own code and does not depend on the Claude Code version; it was
checked through the product path on [2.1.291](claude-code-2.1.291.md#lifecycle).

## Not claimed

- Read isolation: the product's settings do not restrict reads.
- Commands typed with `!` in the Claude Code prompt, which run outside the sandbox.
- Any other version, settings shape, or the Edit and Write tools.
