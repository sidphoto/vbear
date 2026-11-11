# Chat evidence: Claude Code 2.1.322

Why this file: a Mac that Claude Code updated itself to 2.1.322 could not chat, because VBear had constants and an administrator-source list
only up to 2.1.319 ([claude-code-2.1.318-chat.md](claude-code-2.1.318-chat.md)). What follows is what was compared on 2026-11-11 (v0.22.1), side by
side with the installed 2.1.319, **without running any chat, without logging in, without the network and without reading any file of the account's
configuration**. The only things run were `--version`, `--help` and `strings`.

## What was compared

- Binaries (the files in Claude Code's `versions` directory, found with `command -v claude` and `readlink`):
  - `2.1.319`, 321995200 bytes, SHA-256 `1f53587e92dee8e089fa349188a4cda64fa34ace6e7b0ca2ee278ddaa3cc2ebd` (the file recorded in the 2.1.319 section of the evidence above);
  - `2.1.322`, 323702464 bytes, SHA-256 `a9d237949db816a0b7afd88a9a8e1df36b3a597a30f5a41d1c0539eb180a3450`; `claude --version` printed `2.1.322 (Claude Code)`.
- **`claude --help`:** identical (`diff` prints nothing; 313 lines each). Every flag the chat's argv uses is in it (`-p`, `--input-format`,
  `--output-format`, `--verbose`, `--include-partial-messages`, `--permission-prompt-tool`, `--permission-mode`, `--settings`,
  `--setting-sources`, `--strict-mcp-config`, `--tools`, `--append-system-prompt`, `--max-budget-usd`, `--model`, `--resume`, `--session-id`).
  So `chat_protocol.VERSIONS["2.1.322"]` is the same constants as 2.1.319's (and 2.1.318's).
- **Administrator sources.** The method of the 2.1.318 file, run on both binaries (`strings -a`, then `grep`):

  | string | 2.1.319 | 2.1.322 |
  |---|---|---|
  | `Application Support/ClaudeCode` | 3 | 3 |
  | `com.anthropic.claudecode` | 2 | 2 |
  | `remote-settings` | 11 | 11 |
  | `policy-limits.json` | 5 | 5 |
  | `managed-settings` | 148 | 149 |
  | `managed-mcp` | 25 | 24 |
  | `managed-policy` | 21 | 22 |
  | `policyHelper` | 62 | 64 |

  The lists of `/Library/...` paths, of `/etc/...claude...` paths, of strings around `remote-settings` and of strings around `policy-limits` are
  **identical** (`diff` of the sorted lists prints nothing). The list of strings around `managed-settings` differs in one line, a sentence of the
  program's own change notes ("Fixed a terminal whose Claude apps gateway sign-in had expired sending telemetry and managed-settings requests that
  the gateway refused..."): text, not a place. The small differences in the counts of `managed-mcp`, `managed-policy` and `policyHelper` are program
  text too, as they were between 2.1.318 and 2.1.319. The places the binary names are the same: the directory `/Library/Application Support/ClaudeCode`, the
  managed preferences `com.anthropic.claudecode` (per user and device-wide), `~/.claude/remote-settings.json` and `~/.claude/policy-limits.json`
  (`/etc/claude-code` is the Linux place). `/Library/Application Support/Claude/org-plugins`, `/etc/claude-desktop` and `/etc/claude/vertex-sa.json`
  are named in 2.1.319 as often as in 2.1.322 and were not sources in the 2.1.318 reading either; nothing changed there.
  So `admin_policy.CLAUDE_SOURCES["2.1.322"]` is the 2.1.318 / 2.1.319 list, `policy-limits.json` included.
- **Not done:** no real stream recording of 2.1.322 was made (the events are assumed to be the ones recorded for 2.1.318, `tests/fixtures/chat`); the
  vendor's documentation was not read again (no network); `strings` cannot show behaviour, only names. The installed `2.1.321` was not compared.

## Verification

2.1.322 is **not** in any verified list. It chats only after `python3 -m vbear.boundary_check --mode chat --claude <binary>` passed on the Mac (the
「聊天安全檢查」 button in the app does the same for the version a chat would run). That run is not recorded here: `--help` identical and the
administrator-source strings identical, awaiting `boundary_check --mode chat` on a real machine.
