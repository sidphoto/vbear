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
  `apply_patch` fail after it was allowed. The old sandbox does not block reading outside the work folder.
- Token use is reported as `thread/tokenUsage/updated` (a running total for the thread, continued after `thread/resume`).
  No field carries money.

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
