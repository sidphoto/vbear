# Chat evidence: Claude Code 2.1.318

Why this file: a chat with a role card (P36) runs Claude Code 2.1.318, the version on the maintainer's Mac. A version
needs a source list in [`vbear/admin_policy.py`](../../vbear/admin_policy.py) (`CLAUDE_SOURCES`) before any process
starts, and a pass of `boundary_check --mode chat` before it counts as verified for chats. This file records the first;
the second is recorded on the Mac that ran it (`claude-chat-verified.json` and its report), not here.

## Administrator-source list

- Binary: the file `2.1.318` in Claude Code's `versions` directory, 319598464 bytes, SHA-256
  `677a2ea7bf576cedd20e191d973914ed8a41796f53a63b1923381ddc4d5b5e7d`. `claude --version` printed
  `2.1.318 (Claude Code)`.
- Method: the same one as [claude-code-2.1.296-stream.md](claude-code-2.1.296-stream.md), on the binary's strings only
  (no network, no file of the account's configuration read):

  ```sh
  B=~/.local/share/claude/versions/2.1.318
  strings -a "$B" > claude.strings
  for p in "Application Support/ClaudeCode" "com.anthropic.claudecode" "managed-settings" "remote-settings" \
           "managed-mcp" "managed-policy" "policyHelper"; do printf '%s: ' "$p"; grep -c -F -- "$p" claude.strings; done
  grep -o -E "[A-Za-z0-9_./ -]*managed-settings[A-Za-z0-9_./ -]*" claude.strings | sort | uniq -c | sort -rn
  grep -o -E "/Library/[A-Za-z0-9_. /-]{3,60}" claude.strings | sort | uniq -c | sort -rn
  grep -o -E "/etc/[a-z0-9_.-]*claude[a-z0-9_./-]*" claude.strings | sort -u
  grep -o -E "[A-Za-z0-9_./ -]{0,40}remote-settings[A-Za-z0-9_./ -]{0,30}" claude.strings | sort -u
  ```

- Result, macOS sources (all three are what 2.1.292 and 2.1.296 already had):
  - the directory `/Library/Application Support/ClaudeCode` (the binary's own function picks it for `macos`; it holds
    `managed-settings.json`, the drop-in directory `managed-settings.d`, `managed-mcp.json` and the managed `CLAUDE.md`;
    the check is on the whole directory, so a file a later build adds there is covered);
  - the managed preferences `/Library/Managed Preferences/<user>/com.anthropic.claudecode.plist` ("per-user managed
    preferences") and `/Library/Managed Preferences/com.anthropic.claudecode.plist` ("device-level managed
    preferences"), read with `/usr/bin/plutil`;
  - the server-managed settings cache `~/.claude/remote-settings.json` (`remote-settings-consent` is a consent record,
    not a source of settings).
  `/etc/claude-code` and `C:\Program Files\ClaudeCode` are the Linux and Windows places; `HKLM`/`HKCU` are the Windows
  registry. A policy helper is configured only inside one of the sources above ("policy helper configuration is read
  from the highest managed settings source only"), so it is covered. `--managed-settings` is a flag VBear never passes.
- Result, new in 2.1.318: the string `policy-limits.json`, a cache next to `remote-settings.json` in the config home
  (its own signature and stamp files, and an endpoint path containing `policy_limits`), with messages such as "the
  cache was written under another credential's identity" and "explicit denials still deny". It is a second
  server-delivered cache. Nothing in the strings says what it can change, only that its verdicts are enforced. It is
  not in the 2.1.296 evidence. The entry therefore **refuses when `~/.claude/policy-limits.json` exists** (any kind of
  file, a link included), the same rule as for `remote-settings.json`, and refuses when its existence cannot be
  established. This is stricter than the older versions, on purpose: no source is known to be harmless.
- Not done: the vendor's documentation pages were not read again (the run had no network); the pages read on
  2026-10-12 are quoted in [claude-code-2.1.296-stream.md](claude-code-2.1.296-stream.md). The same residual risk
  applies as there: in a non-interactive run, server-managed settings that need the user's approval are applied for
  that run only and not cached, so a missing cache does not show that there are none.
- If the Mac already has `~/.claude/policy-limits.json`, a chat on 2.1.318 is refused with that path named; removing the
  entry from the list is a code change that needs this file updated first.

## Chat mode verification

`python3 -m vbear.boundary_check --mode chat --claude <binary>` runs one real session with VBear's own chat code and
judges it from the recorded events, not from the model's words. Its checks, and what a pass writes, are described in
[SECURITY-MODEL.md](../SECURITY-MODEL.md) ("Chats with a role card"). It was **not** run for this file: it spends model
quota and is run by a person (the 「驗證聊天」 button, or the command above). Until it passes on a Mac, no chat starts
there.
