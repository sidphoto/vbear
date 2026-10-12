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
   `~/.claude/remote-settings.json`. It was checked for 2.1.296 on 2026-10-12 in two ways:
   - *Vendor documentation* (read 2026-10-12): the managed-settings page
     (`https://code.claude.com/docs/en/managed-settings`) names, on macOS, `/Library/Application Support/ClaudeCode/managed-settings.json`
     and the MDM managed-preferences domain `com.anthropic.claudecode`; its policy-helper source can only be
     configured through those two, so it is covered. Parent settings (the SDK's `managedSettings`) apply only to an
     embedding host; VBear is the launcher and passes none. The server-managed-settings page
     (`https://code.claude.com/docs/en/server-managed-settings`) names the cache `~/.claude/remote-settings.json`;
     `managed-mcp.json` sits in the system path, inside the checked `ClaudeCode` directory.
   - *The binary's strings.* The executable is the file `2.1.296` in Claude Code's `versions` directory, 240664432
     bytes, SHA-256 `c9b5341637becbd423ddffc5b254afb645682a3868cb708bbc6cc0e7bb419937`. Commands (first by the
     planner, repeated here with the same result):

     ```sh
     B=~/.local/share/claude/versions/2.1.296
     strings -a "$B" > claude.strings
     for p in "Application Support/ClaudeCode" "com.anthropic.claudecode" "managed-settings" "remote-settings" \
              "managed-mcp" "managed-policy" "policyHelper"; do printf '%s: ' "$p"; grep -c -F -- "$p" claude.strings; done
     grep -o -E "[A-Za-z0-9_./ -]*managed-settings[A-Za-z0-9_./ -]*" claude.strings | sort | uniq -c | sort -rn
     grep -o -E "/Library/[A-Za-z0-9_. /-]{3,60}" claude.strings | sort | uniq -c | sort -rn
     grep -o -E "/etc/[a-z0-9_.-]*claude[a-z0-9_./-]*" claude.strings | sort -u
     grep -o -E "[A-Za-z0-9_./ -]{0,40}remote-settings[A-Za-z0-9_./ -]{0,30}" claude.strings | sort -u
     ```

     Result: the macOS directory and the domain above are present, as are `managed-settings.json`,
     `managed-settings.d` (a drop-in directory inside the checked `ClaudeCode` directory, so covered, because the
     check is on the whole directory), `managed-mcp.json`, the managed-policy `CLAUDE.md` (also in that directory),
     the `~/.claude/remote-settings.json` cache and a `remote-settings-consent` record (a consent state, not a source
     of settings), `/Library/Managed Preferences/` (the MDM location the check already reads), and a
     `--managed-settings` flag (VBear builds the argv itself and passes none). `/etc/claude-code` is the Linux
     location and does not apply on macOS. No other source was found.
   The documentation also says that in a non-interactive run (VBear's stream mode, `-p`) server-managed settings
   that need the user's approval are applied for that run only and not written to the local cache, so a missing
   `remote-settings.json` does not show that there are none; the security model says so.

3. **`system/vcs_state_changed`** (found by the first real end-to-end run, 2026-10-12, not by the probe above: its
   turns write a result file but run no git). When a tool call is a `git commit`, 2.1.296 sends a `system` event
   with this subtype between the tool's call and its result (observed once per commit; `kind` was the commit, the
   branch and the work directory followed). Its fields, from a raw capture (`tools/stream_capture.py`; the raw
   lines stay in the throwaway sandbox, only names and types are recorded here): `type` (string), `subtype`
   (string), `kind` (string), `branch` (string), `cwd` (string, the session's work directory; accepted when it is that directory or below it), `uuid`
   (string, a UUID), `session_id` (string, the session). The tracker did not know the subtype, took it for an
   unknown type, and the turn was invalid. It is now a known kind **for 2.1.296 only**: shape and place are
   checked (the turn is running; the three strings are bounded; `cwd` is the work directory or a directory below it, compared by whole path components), it is neither a model
   response nor an anomaly, and it adds no journal fact. 2.1.292 and every other `system` subtype stay unknown
   types. The probe now has a third turn that edits a file and commits it in a git work directory, checks that its
   report's `head` is the repository's HEAD and the commit exists (`executor_report.verify`), and, for a version
   whose constants list the event, fails unless the event was seen (a probe that never saw it proved nothing about
   it). The CLI sent the event for `git add … && git commit -m "…"` as a Bash call of its own, and
   not for `sh -c '…'` or `git commit -q -m …`, so the turn is written the first way.
4. **The executor cannot know the dispatch id** (also found by that run, and not a Claude Code change): the report's
   schema requires `dispatch_id` to be the turn's UUID, which lived only in the transport `uuid` field of the stdin
   line. VBear now appends a fixed report request to every dispatch text that names the id and the report's
   fields (`executor_report.report_request`); see the security model.
5. **`wire_ingest_context`** (found by the second real end-to-end run, 2026-10-12, whose journal said only that
   four `assistant` events had extra fields; a replay capture of the same turn, same text and same starting
   commit, named the field). A new top-level field of `assistant` events: an object keyed by `tool_use` id whose
   values are objects with one string, `cwd`. It appears on the events of a longer turn (several Bash calls) and
   was not in any probe turn. It is in 2.1.296's allowed set and is not read. The journal's `turn_anomaly` now
   names the unexpected fields (names only), so this would have been readable from the run itself.

6. **`system/permission_denied`** (found by the third real end-to-end run, 2026-10-12, in the second turn, the one
   that answered the review's comments; the journal named the fields). A `system` event for a tool call the
   permission system refused. Its fields: `type`, `subtype`, `tool_name`, `tool_use_id`, `decision_reason_type`,
   `decision_reason`, `message` (strings as far as VBear reads them), `session_id`, `uuid`. It is a known kind for
   2.1.296 only; the turn stays valid; what is kept is the tool name and the decision's type (filtered), never the
   message or the reason. It could not be reproduced by a replay capture of the same turn (the model's attempts
   in that replay were two failed commands, not refusals), so what was refused is not recorded here.

## Runs and model use

| Run | Outcome | Model responses | Cost reported by the CLI |
|---|---|---|---|
| 0 | refused before any request: no 2.1.296 constants | 0 | USD 0 |
| 1 | the first turn was valid but for `thinking_display` (finding 1), so the journal refused the second dispatch; the version also had no administrator-source list (finding 2) | 2 | USD 0.0236 |
| 2 | all checks pass | 3 | USD 0.0135 |
| end to end | pass | 1 | USD 0.0087 |
| real end-to-end run 1 (aborted by the product on findings 3 and 4) | 1 dispatch, `vcs_state_changed` and an invented `dispatch_id` | 12 | USD 0.0403 |
| raw capture of a commit turn (`tools/stream_capture.py`) | one turn | 5 | USD 0.0162 |
| probe with the commit turn, `sh -c` form | pass, the event was not sent | 5 | USD 0.0198 |
| probe with the commit turn, `git commit -q` form | pass, the event was not sent | 8 | USD 0.0275 |
| probe with the commit turn, `git add … && git commit -m …` | all checks pass, the event seen and accepted | 7 | USD 0.0245 |
| real end-to-end run 2 (full; aborted by the product on finding 5) | 1 dispatch, 4 events with `wire_ingest_context` | 11 | USD 0.0500 |
| replay capture of that turn (`tools/stream_capture.py --text-file --repo --base`) | one turn, 2 repository-state events | 12 | USD 0.0457 |
| real end-to-end run 3 (full; first run through a review and a forward; aborted by the product on finding 6) | 2 dispatches, 1 review (NEEDS WORK), `permission_denied` in turn 2 | 21 | USD 0.1051 (Codex: 1 review) |
| replay capture of turn 2 (same text, base = the reviewed commit) | one turn, no refusal | 12 | USD 0.0539 |

The control run sends no request to Anthropic (its endpoint is the local listener, which accepts and closes without
reading). Boundary runs (headless, interactive) are in [claude-code-2.1.296.md](claude-code-2.1.296.md).
