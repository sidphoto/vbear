# Boundary evidence: Claude Code 2.1.296

Produced on 2026-10-12 by VBear's own 「驗證這個版本」 flow (`vbear/claude_verify.py`), which runs
[`vbear/boundary_check.py`](../../vbear/boundary_check.py) once headless and once interactive: VBear's own
`claude_settings()` / `claude_argv()`, one real Claude Code session per mode, a small model told to run a probe script
with the Bash tool, and judgement from the probe's own output and errno values only. A refusal counts only if it is the
sandbox's (`EPERM`/`EACCES`, or the sandbox proxy's 403).

- Binary: Claude Code **2.1.296**, native build, macOS arm64.
- Runs: **headless** (`-p`) and **interactive** (the TUI in a real PTY, which is how VBear launches it), each with
  `claude-haiku-4-5-20251001`. Both passed 15/15 (5.6 s and 9.0 s). The reports do not carry the CLI's cost.
- The run was made into a throwaway state directory (`VBEAR_HOME`), so it recorded no verification in the user's
  `~/.vbear`; the built-in list now carries this version through the same code review as 2.1.292.

<a id="writes"></a><a id="network"></a>

| Check | Headless | Interactive |
|---|---|---|
| Write in its own work directory | allowed | allowed |
| Write in its own scratch directory | allowed | allowed |
| `TMPDIR` is its own scratch directory | allowed | allowed |
| Write in a peer work directory | refused by the sandbox | refused by the sandbox |
| Write in a peer scratch directory | refused by the sandbox | refused by the sandbox |
| Write through a symlink to the peer | refused by the sandbox | refused by the sandbox |
| Write in an unrelated directory | refused by the sandbox | refused by the sandbox |
| Write a file in `HOME` | refused by the sandbox | refused by the sandbox |
| Write in the shared `/tmp/claude-<uid>` | refused by the sandbox | refused by the sandbox |
| Direct TCP to `1.1.1.1:443` | refused by the sandbox | refused by the sandbox |
| HTTPS through the sandbox proxy | refused (proxy 403) | refused (proxy 403) |
| TCP to a listener on `127.0.0.1` | refused by the sandbox | refused by the sandbox |
| Connect to a local unix socket | refused by the sandbox | refused by the sandbox |
| Files left outside the allowed paths | none | none |
| Connections the local listeners saw | 0 | 0 |

The interactive run also passed the terminal-title checks (idle before the prompt, working after it, idle after the
turn, spinner cadence). No activity evidence file was written for this version: the 「工作中／等你回覆」 label still
requires `activity.py`'s own list, which this change does not touch.

## Not claimed

- Read isolation: the product's settings do not restrict reads.
- Commands typed with `!` in the Claude Code prompt, which run outside the sandbox.
- Any other version, settings shape, or the Edit and Write tools.
