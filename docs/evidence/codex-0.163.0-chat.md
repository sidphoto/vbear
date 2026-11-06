# Codex 0.163.0, chat mode

**Status: the evidence the design rests on; not yet boundary evidence.** The chat check
`python3 -m vbear.boundary_check --mode codex-chat` is what lets a version chat, and its result is recorded in
`codex-chat-verified.json` on each Mac, never here. Until a version has passed it, `cli_versions.CODEX_CHAT_VERIFIED_VERSIONS`
is empty and no Codex chat starts. Everything below comes from notes of 2026-11-06 about the local `codex-cli 0.163.0`: its
`--help` output, the source of rust-v0.163.0, and ten short probe turns recorded as scrubbed fixtures
(`tests/fixtures/codex-chat/`), plus a few points confirmed by hand on a real Mac afterwards (marked **confirmed**). The code
and its tests run only a stand-in `codex`; the real one is run only by the check and by a person.

## 1. Why the chat uses `codex app-server` and its own `CODEX_HOME`

| Interface | Long-lived, many turns | Asks the host before a tool | Result |
|---|---|---|---|
| `codex app-server` (stdio, one JSON-RPC message per line) | yes: after `thread/start`, many `turn/start`; a new process uses `thread/resume` | yes: the server sends `item/commandExecution/requestApproval` and `item/fileChange/requestApproval`, the host answers with a decision | used |
| `codex exec --json` and `exec resume` | one process per turn | no: headless forces `approval_policy=never` (source, `codex-rs/exec/src/lib.rs`) | not used: only allow-all or deny-all |
| `codex mcp-server`, `codex proto` | not in 0.163.0 (`codex mcp-server --help` prints the general help) | | do not exist |
| `codex app-server daemon`, `remote-control`, `--remote` | a shared background app-server | | not used: VBear starts its own stdio process |

`codex app-server` takes only `-c`, `--enable`, `--disable`, `--strict-config`, `--listen`, `--stdio`,
`--analytics-default-enabled` and the websocket authentication flags. It has **no** `--ignore-user-config`,
`--ignore-rules`, `--ephemeral` or `--no-daemon` (each was rejected with `unexpected argument`). The source
(`codex-rs/cli/src/main.rs`) starts app-server with `LoaderOverrides::default()`, so `ignore_user_config` is always false.
The only way not to read the person's Codex settings is another `CODEX_HOME`.

During the probe the person's own settings were read: one `AGENTS.md` (`instructionSources` had one entry even with
`-c project_doc_max_bytes=0`) and five MCP servers. That is the reason for the dedicated folder.

## 2. The login folder and the login state

- The login is kept where `CODEX_HOME` says (source, `codex-rs/login/src/auth/storage.rs`, `get_auth_file(codex_home)`).
  A new `CODEX_HOME` reports `codex login status` with exit code 1. With HOME replaced and `CODEX_HOME` pointing at the real
  folder, the exit code was also 1: the person's own login cannot be borrowed that way.
- VBear therefore uses `<state>/codex-chat-home` (0700, no link on its path) and has the person log in once more with one
  fixed line typed into a terminal: `CODEX_HOME=<that folder> codex login -c cli_auth_credentials_store=file`.
  VBear does not copy, link or read anything of the person's own `~/.codex`.
- The login state is the exit code of `CODEX_HOME=<that folder> codex login status -c cli_auth_credentials_store=file`
  (0 logged in). Its output is not read and not kept.
- The folder is refused when it holds a `config.toml`, a `rules/` or an `AGENTS.md` (VBear never writes these there), when
  its path has a link, when it is not the user's own 0700 folder, or when it is over 512 MiB (counted as the review's
  `codex-home` is). It is not the review's `codex-home`.

**Confirmed on a real Mac (2026-11-06):** `CODEX_HOME=<empty folder> codex login status -c cli_auth_credentials_store=file`
exits with 1 and prints no argument error, so the `-c` after `login status` is accepted by 0.163.0. A `status` alone makes a
`tmp/` folder inside the Codex home (not a `config.toml`, `rules` or `AGENTS.md`), so the folder check must not refuse `tmp/`
and does not. The person's Codex was the vendor's installer's (`~/.codex/packages/standalone/releases/0.163.0-<arch>-apple-darwin`),
which is where the pinned binary is looked for.

**To be confirmed on a real Mac** (待 --mode codex-chat 真機確認):

- That a successful login writes nothing named `config.toml`, `rules` or `AGENTS.md` into the folder. If it does, the folder
  is refused (fail closed) and the check must say so.
- That the login output of a missing folder (the first run) is the same as an empty one.

## 3. The pinned binary

The binary is `~/.codex/packages/standalone/releases/<version>-<arch>-apple-darwin/bin/codex`, a plain executable file with no
link on its path (`review_codex.codex_binary`). The version is the newest installed one that passed the chat check, and
`codex --version` must print exactly `codex-cli <that version>`. A copy found on PATH is never used for chatting.

## 4. Administrator policy sources

`admin_policy.CODEX_SOURCES["0.163.0"]` is the list of 0.160.0, unchanged: the folder `/etc/codex` and the managed
preferences domain `com.openai.codex` (in `/Library/Managed Preferences/` and in every per-user folder under it). That list
comes from the vendor's documentation as read on 2026-10-08 for 0.160.0.

**To be confirmed on a real Mac:** that 0.163.0 reads no other system or managed layer (the strings of the installed binary,
as was done for Claude Code 2.1.318). Until then the list is taken over, not re-derived; this file does not claim more.

## 5. What the probe turns showed (app-server, 0.163.0)

Recorded in `tests/fixtures/codex-chat/` (scrubbed of the recorder's own settings, host and account details).

- `thread/start` with `approvalPolicy: "untrusted"` answers `approvalPolicy: "untrusted"` and `approvalsReviewer: "user"`. The
  official documentation calls `untrusted` retired, yet 0.163.0's app-server accepts it. A later version that refuses it
  makes the chat check fail and the chat stay closed.
- Every command asked first, a read-only `ls -a` included. A file change always asks (source, `codex-rs/core/src/safety.rs`).
  The decisions the server lists are `accept`, `acceptForSession`, `acceptWithExecpolicyAmendment`,
  `applyNetworkPolicyAmendment`, `decline`, `cancel` (a file change: `accept`, `acceptForSession`, `decline`, `cancel`).
  There is no "edit first". VBear sends only `accept` and `decline`.
- The older `workspace-write` sandbox let `apply_patch` write; a permission profile that denies the whole disk made
  `apply_patch` fail after it was allowed. The old sandbox does not block reading outside the work folder. It does not
  keep an *allowed* command inside it either: see 5b.
- Token use is reported as `thread/tokenUsage/updated` (a running total for the thread, continued after `thread/resume`).
  No field carries money.

## 5a. A home folder that is a git repository (found by hand, then probed; no model called)

On a real Mac whose home folder (`~`) was a git repository, a chat loaded the person's own MCP servers although the
recorded settings and the `thread/start` answer were as asked. A probe with the real 0.163.0 (a temporary state folder,
a made-up `HOME`, no turn sent, no login needed for `thread/start`) found why. Source: rust-v0.163.0, `codex-rs/`.

- **The project root is the nearest ancestor holding a `.git`** (`config/src/loader/mod.rs`, `discover_project_root`; the
  default `project_root_markers` is `[".git"]`). With `~/.git`, `~` is the project root and `~/.codex/` becomes a project
  layer. A person's own `CODEX_HOME` is `~/.codex`, which the loader skips; VBear's is `<state>/codex-chat-home`, so the skip
  no longer applied and the person's `~/.codex/config.toml` (with its `mcp_servers`) was read as the project's.
- **Codex writes trust by itself.** `thread/start` with a `cwd` and a writable sandbox, when the project has no trust
  setting and a project root or git checkout is found, writes `[projects."<git root>"] trust_level = "trusted"` into
  `CODEX_HOME/config.toml` (`app-server/src/request_processors/thread_processor.rs`, `thread_start_task`), then reloads. The
  layer is enabled and its MCP servers start. Probe: 5 servers for the thread (4 start-up notices of `starting`, one
  `failed`, three `ready`), 86 skills, a `config.toml` holding the trust of `~`, two `configWarning` and one `warning`.
- **The MCP check missed it.** `mcpServerStatus/list` without a `threadId` answers for what the process loaded at its start,
  before any trust, and said 0; with the thread's `threadId` it said 5. The `thread/start` answer (policy, reviewer, sandbox,
  empty `instructionSources`) was the same with and without the problem.
- **Fix, both settings.** `-c project_root_markers=[]` alone is not enough (the official way to take the current folder
  as the root): Codex still finds the git checkout at `~` and writes trust for `~` into the chat folder (probe B), which would
  enable the person's layers in any later start without the setting. `-c projects={"<work folder>"={trust_level="untrusted"}}`
  alone stops the trust write and disables project config, but skills still load from a disabled layer (86 in the probe;
  Codex's own warning says "but skills still load"). Both: no MCP server, no notice, no skill, no `config.toml` (probe D,
  also with the state folder under a path with a dot, `~/.vbr-…`).
- **The second setting must be an inline table.** The dotted `projects."<path>".trust_level="untrusted"` is cut at every `.`
  of the path (`config/src/overrides.rs` splits on `.` without reading quotes), so a state folder such as `~/.vbear` breaks
  the key; Codex printed "ignoring 1 unrecognized configuration setting" and still wrote trust (probe F). The inline table
  `projects={"<path>"={trust_level="untrusted"}}` is read as TOML. The same two keys in `thread/start`'s `config` work for that
  thread only, not for the process-level reads, so VBear puts them on the command line.
- **Remaining risks, as found.** (1) *Managed configuration.* System (`/etc/codex/config.toml`), device-management and cloud
  managed layers rank above `-c` (`merge_managed_config_for_discovery`), so a managed Mac could put the markers or trust
  back; the file was empty on the probed Mac. VBear refuses on a known administrator-policy source and does not read the merged
  configuration. (2) *Skills.* A disabled project layer's `skills/` folder, and `.agents/skills` between the project root and
  the work folder, are still skill roots whatever the trust (`ext/skills/src/host_roots.rs`); the `user` layer reads
  `$HOME/.agents/skills`, which is why the process's `HOME` is an empty folder. (3) A `config.toml` from an older build is
  refused by the chat-folder check, and not deleted.
- These are 0.163.0's behaviours. A new version needs the root-finding, the trust write and the key splitting looked at again
  before it is added to the table (the probe script of the task can be run again).

## 5b. An allowed command can run again without the sandbox (found on a real Mac, then read in the source; no model called)

On the real check the shell command the check allowed for a write outside the work folder wrote the file. A reading of the
source (rust-v0.163.0, `codex-rs/`) and zero-cost runs (`codex sandbox`, `thread/start`; temporary `CODEX_HOME`, no turn)
found why. Under `untrusted` this is Codex's design, not a setting of VBear's that failed to apply.

- **Run again without the sandbox, no second question.** `core/src/tools/orchestrator.rs` (header: "approval, select sandbox,
  attempt, retry with an escalated sandbox strategy on denial, no re-approval thanks to caching"). Under `untrusted` a command
  not allowed by a rule is asked (`core/src/exec_policy.rs`); once allowed, `already_approved` is true. It first runs in the
  sandbox (`sandbox_override_for_first_attempt`, `core/src/tools/sandboxing.rs`). If it fails and the output looks like a sandbox
  denial (`sandboxing/src/denial.rs`: an exit code other than 0, 2, 126, 127 and `operation not permitted`, `permission
  denied`, `read-only file system`, `sandbox`, `seccomp`, `landlock` or `failed to write file` in the output), it is run again
  without the sandbox (`SandboxType::None`) and not asked again (`should_bypass_approval`). Only `untrusted` (and a granular
  policy with `sandbox_approval`) reaches that retry (`wants_no_sandbox_approval`). Zero-cost check: a write to the home folder
  inside `codex sandbox -P ':workspace'` answers `operation not permitted` with exit code 1, so it counts as a denial.
- **A model's request to leave the sandbox.** A tool call with `sandbox_permissions` set to `require_escalated` runs, once
  allowed, without the sandbox on the first attempt (`BypassSandboxFirstAttempt`).
- **The card cannot say it.** `CommandExecutionRequestApprovalParams` (`app-server-protocol/src/protocol/v2/item.rs`) has no
  field for "this will run without the sandbox"; `additionalPermissions` and `availableDecisions` are experimental and are
  dropped with `experimentalApi: false`; `reason` is the model's own optional justification. The decisions are `accept`,
  `acceptForSession`, `acceptWithExecpolicyAmendment`, `applyNetworkPolicyAmendment`, `decline`, `cancel`: none is "allow but
  stay in the sandbox".
- **Network.** A command run without the sandbox can reach the network (no Seatbelt; a full escalation also skips the managed
  network proxy). Whether a retry happens depends on the error text: `curl` to a name or address failed with exit code 6 or 7 and
  no keyword, so no retry; a `perl` socket gave `Operation not permitted`, which is a denial, so under `untrusted` it would be
  run again without the sandbox and connect.
- **The ways to stay inside, and why none was used.** (a) `on-request`: ordinary commands are not asked (reading too),
  `require_escalated` is still allowed out. (b) `never`: no card at all, no way out of the sandbox, `apply_patch` inside the
  work folder works, but reading is unlimited and unasked. (c) a granular policy: only through `config`, close to `never`.
  (e) **the permission profile with `:root` set to `deny`** (the vendor's "file access limited to workspace" example, sent in
  `thread/start`'s `config`; no experimental API): every command asked, no retry (`orchestrator.rs`: a policy with a denied read
  does not retry), an escalation does not widen it (`protocol/src/permissions/target.rs`), network stays off. But
  `apply_patch` fails in it (P38-0 fact; it runs a helper `codex --codex-run-as-fs-helper` under another Seatbelt profile that
  lacks the temporary-folder access the ordinary one has; run by hand in the ordinary profile the same write succeeded).
  Denying reads of a few folders only would not do: an escalation is then widened to the whole disk being writable.
  Not confirmed with a model turn: whether the shell can write the work folder in that profile when the folder is not under
  `/tmp`.
- **Decision (2026-11-06, the person's):** release as it is and say it on the card and in the documents (ADR 0005, decision
  7), then use the permission profile when Codex fixes `apply_patch` under it. The version check no longer fails on an allowed
  shell write that got out (it notes it and removes the file); an `apply_patch` outside the work folder must still be declined
  by VBear with no card and leave no file.
- **Retired value.** The vendor's documentation says `approval_policy = "untrusted"` is no longer supported; 0.163.0's
  `thread/start` still takes it as a parameter (a settings file with it is refused).

## 6. What was built from it (P38-1 to P38-5)

- The protocol, the tracker and the stand-in server that replays the recordings (`codex_chat_protocol.py`,
  `tests/fake_codex_app_server.py`): every line VBear writes, every notice and request it understands, what it counts as a
  violation, the estimate of money from tokens.
- The login folder and its checks, the fixed `chat_login` line, the exit-code-only login state, the pinned-binary choice,
  `codex-chat-verified.json` (a version counts only with a report of mode `codex-chat` that passed and names the same
  version as `codex_version`), the `CODEX_SOURCES["0.163.0"]` entry, and the Codex part of the chat support answer.
- The daemon's Codex chat (`codex-chat` engine, `codex_chat_session.py`), the chat record version 2, and the check itself
  (`codex_chat_check.py`).
- The console's side (P38-5): the engine follows the role card's tool, `card_tool_changed`, the support answer with a
  `codex` object, `POST /api/chat-support/verify {"engine": "codex"}`, and the page (command and file cards with diffs,
  改內容再問, the estimate, the plan's use, the deletion note).

## 7. Still to be confirmed with `--mode codex-chat` on a real Mac

These are written down as unknown in the code and decided fail-closed; the check or a first real chat settles them.

- That `turn/steer` is accepted when `initialize` says `experimentalApi: false` (a changed command depends on it; a refusal
  fails the check at its `edit` step, and the fallback of sending the text as the next message is stopped, not used).
- That Codex ends cleanly when its stdin closes (the idle close and the stop depend on it), and what `turn/interrupt` answers
  and in which order.
- That `thread/delete` removes Codex's own copy under `codex-chat-home/sessions` (the file name holding the thread id is an
  assumption, recorded as an observation, not a pass condition).
- That the real model does what the check's prompts ask (one command at a time, `apply_patch` once before a shell command).
- That a file path outside the work folder is judged right through a link (tested with files and links the tests make, not
  yet with a real Codex).
- Whether a request kind VBear does not know can be made to arrive at all (recorded as "not observed", neither a pass nor a fail).
