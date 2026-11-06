# Codex 0.163.0, chat mode (draft)

**Status: draft, not boundary evidence.** The chat check `python3 -m vbear.boundary_check --mode codex-chat` has not
passed for any version, so `cli_versions.CODEX_CHAT_VERIFIED_VERSIONS` is empty and no Codex chat starts. This file records
what the design (ADR 0005) rests on. Everything below comes from the planner's notes of 2026-11-06 about the local
`codex-cli 0.163.0`: its `--help` output, the source of rust-v0.163.0, and ten short probe turns recorded as scrubbed
fixtures. The author of this draft did not run Codex. The coordinator completes the parts marked **to be confirmed** when the
check is run on a real Mac.

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

**To be confirmed on a real Mac** (待 --mode codex-chat 真機確認):

- That `codex login -c cli_auth_credentials_store=file` and `codex login status -c cli_auth_credentials_store=file` accept
  the `-c` after the subcommand in 0.163.0 (the review already passes it after `login`; `status` is not recorded).
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
as was done for Claude Code 2.1.318). Until then the list is taken over, not re-derived; the draft does not claim more.

## 5. What the probe turns showed (app-server, 0.163.0)

Recorded in `tests/fixtures/codex-chat/` once the protocol task lands them; the notes below are the planner's.

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

## 6. What this task (P38-2) built from it

The login folder and its checks, the fixed `chat_login` line, the exit-code-only login state, the pinned-binary choice,
`codex-chat-verified.json` (a version counts only with a report of mode `codex-chat` that passed and names the same version
as `codex_version`), the `CODEX_SOURCES["0.163.0"]` entry, and the Codex part of the chat support answer. It starts no
Codex chat; the protocol, the process and the check come in later tasks.
