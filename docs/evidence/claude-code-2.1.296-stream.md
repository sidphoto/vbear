# Stream executor evidence: Claude Code 2.1.296

Recorded on 2026-10-12 for the stream executor (design 2.2). It backs `cli_versions.STREAM_VERIFIED_VERSIONS`
containing 2.1.296, the `2.1.296` entries in [`vbear/runtime/stream_protocol.py`](../../vbear/runtime/stream_protocol.py)
and [`vbear/admin_policy.py`](../../vbear/admin_policy.py), and 2.1.296 in `cli_versions.VERIFIED_VERSIONS["claude"]`
(boundary evidence: [claude-code-2.1.296.md](claude-code-2.1.296.md)).

Why this version: Claude Code updates itself. The version this Mac had was 2.1.296 and the only stream-verified
version (2.1.292) was no longer installed, so the stream executor could not start at all (a version without constants
is refused before any request; there is no "start unverified"). The constants are 2.1.292's, plus what the probe
observed, which is listed below.

- Binary: Claude Code **2.1.296**, native build, macOS arm64; model `claude-haiku-4-5-20251001`.
- Check: `python3 -m vbear.boundary_check --mode stream --claude ~/.local/share/claude/versions/2.1.296`
  ([`vbear/stream_check.py`](../../vbear/stream_check.py)); the launch is VBear's own (`prepare_stream_launch`,
  `managed_argv`, `daemon.build_env`), every stdout line goes through `strictjson` and the `EventTracker`, and the turns
  are judged by `stream_journal.turn_validity` after the journal is read back.
- End to end: [`tools/stream_daemon_probe.py`](../../tools/stream_daemon_probe.py) ran one real dispatch through a
  temporary runtime daemon (`open_stream` with its administrator-policy, acceptance and login-fingerprint checks,
  `dispatch_prepare`, `stream_send`, `stream_status`, `stream_close`).

## Result of the passing run

| Check | Result |
|---|---|
| Protocol: two turns follow design 2.4 (schema, attribution, order, response identity, `num_turns`), no anomaly, both valid | pass (3 model responses: 2 + 1; `num_turns` 3 and 2) |
| Second dispatch written right after the first `result`, before its `completed` lifecycle | pass |
| Sandbox (own work dir and scratch only; no peer, outside, HOME or shared `/tmp/claude-<uid>` writes; no internet, no proxy, no 127.0.0.1 listener, no unix socket) | pass, every item refused |
| Endpoint pin: the work directory's project settings set `ANTHROPIC_BASE_URL` to a local listener | pass: 0 connections, run completed |
| Control for the pin: same project files, VBear's settings without the `env` block | 7 connections: the project file is read, so the pin is what kept the endpoint |
| Administrator policy sources and `~/.claude/remote-settings.json` | none present |
| `~/.claude.json` account fields usable | yes (only this boolean is recorded) |
| End to end through the daemon: valid turn, report checked against the files, session closed and kept as `ended` | pass (1 model response) |

## What the probe found (and the constants now say)

1. **`thinking_display`** is a new top-level field on `assistant` events (on the first event of a turn and on
   some later ones, next to `thinking_duration_ms`). VBear does not read it; it is in the allowed field set for
   `assistant`. This is the only difference in the stream's events from 2.1.292: no event of any kind carried a field
   outside 2.1.292's allowed sets (the probe's `unexpected_keys` was empty in run 2), `result`'s `num_turns` follows the same offset, and the init values (tools, permission mode,
   API-key source, lifecycle states) are unchanged.
2. **No administrator-source list for the version.** `admin_policy.CLAUDE_SOURCES` is a second per-version table
   (the first run reported "沒有管理員政策來源清單，不能啟動"). The 2.1.296 entry is 2.1.292's: the directory
   `/Library/Application Support/ClaudeCode`, the managed-preferences domain `com.anthropic.claudecode` and
   `~/.claude/remote-settings.json`. This is a copy, not a re-reading of the vendor's documentation; the reviewer is
   asked to check that.

## Runs and model use

| Run | Outcome | Model responses | Cost reported by the CLI |
|---|---|---|---|
| 0 | refused before any request: no 2.1.296 constants | 0 | USD 0 |
| 1 | the first turn was valid but for `thinking_display` (finding 1), so the journal refused the second dispatch; the version also had no administrator-source list (finding 2) | 2 | USD 0.0236 |
| 2 | all checks pass | 3 | USD 0.0135 |
| end to end | pass | 1 | USD 0.0087 |

The control run sends no request to Anthropic (its endpoint is the local listener, which accepts and closes without
reading). Boundary runs (headless, interactive) are in [claude-code-2.1.296.md](claude-code-2.1.296.md).
