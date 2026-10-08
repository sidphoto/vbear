# Stream executor evidence: Claude Code 2.1.292

Recorded on 2026-10-08 for the stream executor (design 2.2). It backs `cli_versions.STREAM_VERIFIED_VERSIONS`
containing 2.1.292 and the per-version constants in [`vbear/runtime/stream_protocol.py`](../../vbear/runtime/stream_protocol.py).
The constants were written from observed behaviour and reviewed; the probe confirms them, it does not learn them.

- Binary: Claude Code **2.1.292**, native build, macOS arm64; model `claude-haiku-4-5-20251001`.
- Check: `python3 -m vbear.boundary_check --mode stream --claude ~/.local/share/claude/versions/2.1.292`
  ([`vbear/stream_check.py`](../../vbear/stream_check.py)). The launch is VBear's own: `prepare_stream_launch`,
  `managed_argv` (design 2.1 argv, `--settings` with the pinned `env` block), `daemon.build_env`. Every stdout line
  goes through `strictjson` and the `EventTracker`; every fact into a `JournalWriter`; the turns are judged by
  `stream_journal.turn_validity` after the journal is read back. A temporary `VBEAR_HOME` held the HMAC key and the
  journal and was deleted (`ls -ld` afterwards: no such file or directory).
- End to end: [`tools/stream_daemon_probe.py`](../../tools/stream_daemon_probe.py) ran one real dispatch through a
  temporary runtime daemon (`open_stream` with its administrator-policy, acceptance and login-fingerprint checks,
  `dispatch_prepare`, `stream_send`, `stream_status`, `stream_close`).

## Result of the passing run

| Check | Result |
|---|---|
| Protocol: two turns follow design 2.4 (schema, attribution, order, response identity, `num_turns`), no anomaly, both valid | pass (3 model responses: 2 + 1; `num_turns` 3 and 2) |
| Second dispatch written right after the first `result`, before its `completed` lifecycle | pass |
| Sandbox (own work dir and scratch only; no peer, outside, HOME or shared `/tmp/claude-<uid>` writes; no internet, no proxy, no 127.0.0.1 listener, no unix socket) | pass, every item refused by the sandbox (EPERM/EACCES or the proxy's 403) |
| Endpoint pin: the work directory's `.claude/settings.json` and `settings.local.json` set `ANTHROPIC_BASE_URL` to a local listener | pass: 0 connections, run completed |
| Control for the pin: same project files, VBear's settings without the `env` block (its endpoint is the listener, so no API request) | 7 connections: the project file is read, so the pin is what kept the endpoint |
| Administrator policy sources and `~/.claude/remote-settings.json` | none present |
| `~/.claude.json` account fields usable | yes (only this boolean is recorded) |
| End to end through the daemon: valid turn, report checked against the files (`git_head`, `git_objects.commit_exists`), session closed and kept as `ended` | pass (1 model response) |

## What the probe found (and the constants now say)

1. **Later assistant events omit the attribution fields.** The first `assistant` event of a turn carries
   `user_message_uuid = d` and `user_message_uuids = [d]`; later ones carry neither key (the earlier measurement
   summarised with `get()`, which read "absent" as null). Design v29.6: absent or null is accepted on later events,
   any other value makes the turn invalid (VBear treats it as a protocol error); the first event must carry both,
   equal to the dispatch.
2. **`tool_result_meta`** appears on some tool-result events (top level, next to `tool_use_result`). VBear does not
   read it; it is in the allowed field set for `user/tool_result`.

## Key sets observed (keys only)

| Kind | Distinct key sets |
|---|---|
| `assistant` | the first event: `message, parent_tool_use_id, request_id, session_id, thinking_duration_ms, timestamp, type, user_message_uuid, user_message_uuids, uuid`; later: the same without the two `user_message_*`; or `message, parent_tool_use_id, request_id, session_id, timestamp, type, uuid, wire_tool_inputs` |
| `user/tool_result` | `message, parent_tool_use_id, session_id, timestamp, tool_use_result, type, uuid`, sometimes with `tool_result_meta` |
| `command_lifecycle`, `rate_limit_event`, `system/init`, `system/thinking_tokens`, `user/replay`, `result` | one key set each, all within the constants |

## Runs and model use

| Run | Outcome | Model responses |
|---|---|---|
| 1 | stopped at a later assistant event without the attribution keys (finding 1) | 1-3 (the CLI finished its turn before it was stopped; not counted) |
| 2 | the first turn completed; the journal refused the second dispatch after an unexpected `tool_result_meta`, and the probe did not catch that path yet | about 2 (no report was written; inferred from run 3's identical first turn) |
| 3 | the same, now reported: anomaly `extra_fields` on `user/tool_result` (finding 2) | 2 |
| 4 | all checks pass | 3 |
| end to end | pass | 1 |

The control runs send no request to Anthropic (their endpoint is the local listener, which accepts and closes
without reading). Cost reported by the CLI: run 3 USD 0.0104, run 4 USD 0.0138, end to end USD 0.0087; runs 1 and 2
did not record theirs.
