# Memory evidence: Claude Code 2.1.319 and its own memory in a VBear chat

Why this file: VBear keeps the person's memory itself (ADR 0008, `vbear/memory.py`) and does not use Claude Code's own memory
(the automatic memory it can write under the person's own `~/.claude`, and the `CLAUDE.md` files it reads). A chat with a role
card runs with `--safe-mode`, `--setting-sources ""` and `--strict-mcp-config`. This file records what the program's text says
about those two things in safe mode, and why VBear still sets two environment variables.

## What was read, and how

The program text of the version on the maintainer's Mac was read as bytes with `grep`; **nothing was run** (no `claude`, not even
`--version`), no network was used, and no file of the account's configuration or memory was read. These are the three pieces of
the program that matter, copied from that reading (the program is minified; the names `Mh`, `to`, `Pe` and `i` are its own):

1. The test of whether the automatic memory is on. Safe mode answers "off" before any setting is looked at; the environment
   variable and the setting `autoMemoryEnabled` come after:

   ```js
   function Mh(){if(to())return"off";…let e=process.env.CLAUDE_CODE_DISABLE_AUTO_MEMORY;if(Pe(e))return"off";…}
   ```

2. What "safe mode" is: the environment variable `CLAUDE_CODE_SAFE_MODE` or the flag `--safe-mode` on the command line:

   ```js
   function to(){return Pe(process.env.CLAUDE_CODE_SAFE_MODE)||i("--safe-mode")}
   ```

3. What starting in safe mode sets, among other things (the rest is left out here): the project instruction files are switched off:

   ```js
   if(to()){process.env.CLAUDE_CODE_SAFE_MODE="1",process.env.CLAUDE_CODE_DISABLE_CLAUDE_MDS="1",…}
   ```

## What follows, and what does not

- In safe mode (the chat's argv has `--safe-mode`) the automatic memory is off and no `CLAUDE.md` is read. This is **only
  evidence from the program's text**: `system/init` does not report the memory's state, and nobody has watched a chat process
  here. So a real-machine check looks for the one thing that would show it wrong: after a chat, the memory folder Claude Code
  would have made for the chat's work folder does not exist (an existence test of that one path; nothing under
  `~/.claude/projects` is listed or read).
- VBear sets `CLAUDE_CODE_DISABLE_AUTO_MEMORY=1` and `CLAUDE_CODE_DISABLE_CLAUDE_MDS=1` in the environment of every chat
  process (`vbear/runtime/daemon_chat.py`, the Claude Code chat only). They are the names the text above reads. They are a second
  lock on top of safe mode, not a replacement: if a later build renames them, the first lock (safe mode) is still there, and a
  new Claude Code version still has to pass the chat check before VBear starts a chat with it.
- Terminals in full mode, meetings, team meetings and the chief of staff are not touched by this change: full mode uses the
  person's own settings and so the tool's own memory as the person set it; the other three already run in safe mode with no tools.
- Codex is a different program with its own settings: `--disable memories`, `project_doc_max_bytes=0` and
  `history.persistence="none"` (see `docs/evidence/codex-0.163.0-chat.md`). Nothing here is about Codex.

Tests pin the argv and the environment with a fake Claude Code (`tests/test_memory_reuse.py`); they do not show what the real one
does.
