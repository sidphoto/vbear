# Review evidence: Codex 0.160.0

Recorded on 2026-10-11 for VBear-launched reviews (design 5.2, 5.5, 5.6). It backs
`codex_constants.VERIFIED_VERSIONS` containing 0.160.0 and the constants in
[`vbear/runtime/codex_constants.py`](../../vbear/runtime/codex_constants.py). The constants were first written from the
design and one incomplete sample; the real run corrected them (below). The probe confirms, it does not decide.

- Binary: codex-cli **0.160.0**, macOS arm64, the pinned install under
  `~/.codex/packages/standalone/releases/0.160.0-aarch64-apple-darwin/`; model `gpt-6-luna`, reasoning effort high.
- Login: the user logged in once, themselves, in the dedicated `CODEX_HOME` (`codex login -c
  cli_auth_credentials_store=file`). VBear read `auth.json` only inside the probe process to compute the login
  fingerprint and to scan its own output for leaks; nothing from it is in any file kept.
- Tool: [`tools/review_daemon_probe.py`](../../tools/review_daemon_probe.py): the production path (flow, acceptance
  bound to the Codex login, the executor's start record with its base commit, `review_start`, the daemon's run,
  finish, record, clean-up) against a two-commit throw-away repository whose change has a plain defect (an average of
  an empty list). The executor session was the synthetic stream stand-in of the tests: no Claude, no model.
- Runs: two, both on 2026-10-11 (run 1 at 11:21, run 2 at 11:32, local time). Model calls: **2** (one `codex exec`
  each); `codex --version` and `codex mcp list --json` run without a model. The redacted reports (structure and
  descriptive values only) are in `_sandbox/20261011-review-probe-{1,2}/` (not committed).
- Leak check (the tool scans every file it keeps and the report for any string of `auth.json`, 64-hex strings and
  JWT-shaped strings): run 1: 3 files scanned, 0 hits; run 2: 3 files scanned, 0 hits. `ls -ld` of each run's
  temporary directory said "No such file or directory".
- The same content was reviewed both times: the probe builds the same throw-away repository on every run (a README
  and `calc.py` with `average(xs)` = `sum(xs) / len(xs)`; only the commit ids differ). The verdicts differ: run 1
  said NEEDS WORK (it pointed at the division by zero for an empty list), run 2 said PASS (it called it a small, correct
  two-line function and did not run tests). VBear checks the form and the process of a review, not its quality. The
  first run's *process* was invalid (three `world_state` rules, below), so its verdict is not a valid review; the
  second run's was valid. The two verdicts differ all the same, and that is a reminder of why the merge gate is the
  user's.

## What the first run changed

Run 1 exited 0 and gave a real review ("NEEDS WORK": it found the defect), but was invalid on three `world_state`
rules; everything else of 5.5 and 5.6 passed. Without a second model call (`codex debug prompt-input` renders the
model-visible prompt locally) it was found that:

| Finding | Consequence |
|---|---|
| `world_state` is `{"full": true, "state": {...}}`; the fields are under `state` | the validator reads `payload.state` and pins what was observed |
| `host_skills` was Codex's own `<skills_instructions>` block: four bundled system skills (`imagegen`, `openai-docs`, `skill-creator`, `skill-installer`) under `<CODEX_HOME>/skills/.system`; not the user's skills, not the reviewed repository's | `-c skills.bundled.enabled=false -c skills.include_instructions=false` added to the argv (v29.11); the block is gone and `skills/` is not created |
| `multi_agent_mode.mode` is `explicitRequestOnly`; `--disable multi_agent`, `features.multi_agent`, `--disable multi_agent_v2`, `agents.*` and `collaboration_mode` do not remove the prompt's multi-agent text | pinned as the accepted value; protection is detection only: closed record kinds, tool `exec` only, a reason of its own (`SUBAGENT_ACTIVITY`); recorded as a residual risk |
| The model used one tool, `exec` (6 `custom_tool_call`s) | allow-list is `exec` only |
| After `codex login` the dedicated home holds `tmp/arg0/codex-arg0XXXX/` with three symlinks Codex makes at every start | CODEX_HOME size counts links there by their own size, never followed; a link elsewhere is still over (v29.10) |

## Run 2 (passing)

| Check | Result |
|---|---|
| Outcome | `valid`, verdict PASS, `BASE_IS_ANCESTOR: yes`, exit 0, record complete (`last.md`, `events.jsonl`, `stderr.log`, `rollout.jsonl`, `result.json`) |
| Events | `thread.started`, `turn.started`, `item.started/completed` (`command_execution`, `agent_message`), `turn.completed` with usage (`input_tokens` ≈ 85 k, `cached_input_tokens`, `cache_write_input_tokens` 0, `output_tokens` ≈ 1.8 k, `reasoning_output_tokens`) |
| Rollout record kinds | `session_meta`, `world_state`, `turn_context`, `token_usage_record` (7), `event_msg` (`task_started`, `task_complete`, `token_count`, `item_completed`), `response_item` (`message`, `reasoning`, `custom_tool_call`, `custom_tool_call_output`); usage chain consistent; the last record's usage equals `turn.completed.usage` |
| `session_meta` | `originator` `codex_exec`, `source` `exec`, `model_provider` `openai`, `cli_version` 0.160.0, `cwd` the review scratch |
| `turn_context` | `approval_policy` never; `sandbox_policy` workspace-write, `network_access` false, `exclude_slash_tmp` and `exclude_tmpdir_env_var` true; `permission_profile.network` `restricted`; model `gpt-6-luna` |
| `world_state` | apps and plugins instructions false; `host_skills` `{"includeInstructions": false}`; `agents_md`, `managed_developer_instructions`, `persistent_mode` empty; `git_attribution`, `environments_instructions` false; `realtime.active` false; `collaboration_mode.mode` `default`; `multi_agent_mode.mode` `explicitRequestOnly` |
| `codex mcp list --json` (same `-c`/`--disable`) | exit 0, `[]` |
| stderr | one line, `Reading additional input from stdin...`; no connector or MCP connection records |
| Administrator and system settings | none on this Mac (`/etc/codex`, managed preferences) |
| Clean-up | the review scratch, the run home and the temporary directory removed; the state directory left holding only `codex-home` |

## Not covered

The probe reviewed a tiny repository. It does not prove the sandbox against a hostile repository (that is the
sandbox's own boundary, trusted as documented in design 5.9 and 10), that the model never spawns a sub-agent (only that
a spawn would be seen and invalidate the review), or other Codex versions.
