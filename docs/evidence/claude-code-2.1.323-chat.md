# Chat evidence: Claude Code 2.1.323

Why this file: a Mac that Claude Code updated itself to 2.1.323 could not chat, because VBear had constants and an administrator-source list only up to
2.1.322 ([claude-code-2.1.322-chat.md](claude-code-2.1.322-chat.md)). What follows is what was compared on 2026-11-13 (v0.25.5), side by side with the
installed 2.1.322, **without running any chat, without logging in, without the network and without reading any file of the account's configuration**.
The only things run were `--help` (in an environment of its own with an empty home folder) and `strings`. The writer of the code change ran none of them: the
files named below were made by the planner and handed over.

## What was compared

- Binaries (the files in Claude Code's `versions` directory):
  - `2.1.322`, 323702464 bytes, SHA-256 `a9d237949db816a0b7afd88a9a8e1df36b3a597a30f5a41d1c0539eb180a3450` (the file recorded in [claude-code-2.1.322-chat.md](claude-code-2.1.322-chat.md));
  - `2.1.323`, 344369984 bytes, SHA-256 `5432918d904a9b6afef7bb79d20df24d76052eabc1f41bceb84091d21f8889a7`.
- **`claude --help`:** the two outputs differ in one place only, the description of the `rm <id>` sub-command of background sessions (2.1.322: "Delete a background
  session, and its worktree when that is safe"; 2.1.323: the session leaves the list and its worktree is deleted when that is safe, the conversation is kept and
  `claude --resume` lists it). 313 lines against 315. Every flag the chat's argv uses is in both, once or more, with the same wording:
  `-p`, `--input-format`, `--output-format`, `--verbose`, `--include-partial-messages`, `--permission-prompts`, `--permission-prompt-tool`, `--permission-mode`,
  `--safe-mode`, `--settings`, `--setting-sources`, `--strict-mcp-config`, `--tools`, `--append-system-prompt`, `--max-budget-usd`, `--model`, `--resume`, `--session-id`;
  and `--disallowedTools`, which the stream executor's argv uses. So `chat_protocol.VERSIONS["2.1.323"]` is the same constants as 2.1.322's (and 2.1.319's, 2.1.318's).
  Neither help lists `--managed-settings`, `--managed-settings-in-initialize` or `--await-initialize` (see "A new way to hand it managed settings" below).
- **Administrator sources.** The method of the 2.1.318 file, run on both binaries (`strings -a`, then `grep`):

  | string | 2.1.322 | 2.1.323 |
  |---|---|---|
  | `Application Support/ClaudeCode` | 3 | 3 |
  | `com.anthropic.claudecode` | 2 | 2 |
  | `remote-settings` | 11 | 11 |
  | `policy-limits.json` | 5 | 5 |
  | `managed-settings` | 149 | 161 |
  | `managed-mcp` | 24 | 24 |
  | `managed-policy` | 22 | 20 |
  | `policyHelper` | 64 | 63 |

  The list of `/Library/...` paths and the list of `/etc/...claude...` paths are **identical** in the two binaries (a `diff` of the lists prints nothing). The strings
  around `remote-settings` and around `policy-limits` differ only in the names of minified functions and import chunks, which change with every build. The strings
  around `managed-settings` differ in the same way, and in the new lines named in the next section; the rest of the change of the count (149 to 161) is program text, as the
  small changes of `managed-policy` (22 to 20) and `policyHelper` (64 to 63) are. An exact accounting of the 12 was not made: the lines of the comparison were cut at a
  fixed length. The places the binary names are the same as in 2.1.322: the directory `/Library/Application Support/ClaudeCode`, the managed preferences
  `com.anthropic.claudecode` (per user and device-wide), `~/.claude/remote-settings.json` and `~/.claude/policy-limits.json` (`/etc/claude-code` is the Linux place).
  So `admin_policy.CLAUDE_SOURCES["2.1.323"]` is the 2.1.318 / 2.1.319 / 2.1.322 list, `policy-limits.json` included.

## A new way to hand it managed settings (not a place on disk)

The strings of 2.1.323 hold something 2.1.322's do not: a launch flag `--managed-settings-in-initialize`, and a key `managedSettings` in the SDK `initialize` request
("the managed settings of the host that starts Claude Code, in the same shape as the SDK `managedSettings` option, so that the launch command line does not grow with them").
What the strings say about it (the sentences are cut off in the comparison file, so the last words of two of them are inferred, not read):

- it is read **only by a process launched with both `--await-initialize` and `--managed-settings-in-initialize`**; the description string of the flag (in the binary, not in `--help`, which hides it) says "SDK use only; requires
  `--await-initialize`", and its error sentences say it needs `--input-format=stream-json` with stdin piped, cannot be used with `--managed-settings` (an older, hidden flag that
  2.1.322's strings already hold: the parser of its `agents` sub-command names it), `--sdk-url`, `--bg`, `--background`, `--routine`, `--tmux` or a sub-command, and that the process
  exits when `initialize.managedSettings` is not a JSON object, is nested too deep, or no usable `initialize` request was read;
- a second internal field tells whether the `managedSettings` of an `initialize` are the ones stored at launch, and says that "true" does not mean they are in force.

What this means for VBear, and how it was shown **from VBear's own code, not from the binary**:

- VBear's chat argv (`agent_sessions.chat_argv`) and its stream argv (`agent_sessions.claude_argv`) name none of the three flags; no module of `vbear/` has any of them or the
  words `managedSettings` / `managed_settings` in a string, a name, an attribute or a keyword (guard rule 24a, with bad samples).
- VBear **does** write an `initialize` control request to a chat's stdin (since the first chat: the permission requests reach VBear only after it, `chat_protocol` docstring), but it is
  exactly `{"type": "control_request", "request_id": ..., "request": {"subtype": "initialize"}}`. It carries no `managedSettings`, and the function builds it from a literal that
  a guard rule reads (24b). Every line the chat session queues for stdin is one `chat_protocol` built (24c).
- So with VBear as the launcher the channel is closed twice: no launch flag, and no key. Nothing in the administrator-source list is about it, because it is not a place on disk
  that a person's Mac can have: only the program that starts Claude Code can open it.

Not shown: that a process launched **without** the flags ignores a `managedSettings` it is sent. That is what the sentence in the strings says; no run tested it. VBear does not
depend on it, since it never sends the key.

## Not done

- No real stream recording of 2.1.323 was made (the events are assumed to be the ones recorded for 2.1.318, `tests/fixtures/chat`). What a signed-in 2.1.323 prints for
  `system/init`, permission requests, the order of events and the cost fields is for the chat check to show.
- The vendor's documentation was not read again (no network). `strings` cannot show behaviour, only names.
- No other version was compared: the installed `2.1.322` is the only one it was set against.

## Verification

2.1.323 is **not** in any verified list. It chats only after `python3 -m vbear.boundary_check --mode chat --claude <binary>` passed on the Mac (the 「聊天安全檢查」
button in the app does the same for the version a chat would run). That run is not recorded here: `--help` the same except one description, the lists of administrator
places the same, the new managed-settings channel unused by VBear, awaiting `boundary_check --mode chat` on a real machine.
On a Mac whose administrator has put a managed-settings file in `/Library/Application Support/ClaudeCode`, 2.1.323 is refused before it starts, as 2.1.322 is.
