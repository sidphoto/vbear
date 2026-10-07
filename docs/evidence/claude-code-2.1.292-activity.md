# Activity evidence: Claude Code 2.1.292

Recorded on 2026-10-07 for VBear's activity taxonomy ([`vbear/activity.py`](../../vbear/activity.py)). It is the
evidence behind the `claude-title` rung being authoritative for this version, and the reason other signals are not
used.

- Binary: Claude Code **2.1.292**, native build, macOS arm64.
- Launch: VBear's managed argv (`claude_argv()`: `--safe-mode --settings <file> --permission-mode acceptEdits
  --tools Bash --disallowedTools Edit,Write --strict-mcp-config`) and sandbox settings (`claude_settings()`), plus
  `--model haiku` and `--session-id <uuid>`. The environment was the daemon's (`PATH`, `TERM`, `LANG`, `HOME`, `USER`,
  `LOGNAME`, `CLAUDE_CODE_TMPDIR`, `DISABLE_AUTOUPDATER=1`).
- Driver: a PTY harness outside the repository. It typed short prompts and recorded every output chunk with a
  timestamp, every OSC sequence and every bare BEL. Three sessions: two prompts with one 6-second Bash command, and
  two runs trying to raise a permission prompt.

## Terminal title (OSC 0)

| Moment | Title |
|---|---|
| Before the startup trust dialog is answered | none set |
| Idle at the prompt | `✳ Claude Code` |
| Prompt sent; thinking; replying | `◐ Claude Code`, then `◐ <task summary>` |
| Working, including while a 6 s Bash command ran | alternates `◐` and `◑`, one frame every 0.96 s |
| Turn finished | `✳ <task summary>` |
| `/exit` | empty title |

The title's first character is the only part VBear keeps. The rest is a summary of the current task and is never
stored or returned.

## Other signals looked at

- **Hooks:** six events configured through `--settings` (SessionStart, UserPromptSubmit, PreToolUse, PostToolUse,
  Notification, Stop) produced no call at all across two prompts and a Bash command. `--safe-mode` disables settings
  hooks, as its `--help` says. VBear keeps `--safe-mode`, so hooks are not an evidence source.
- **Output rate:** 400–1,300 bytes/s while working (spinner and status line), 0 bytes/s while waiting. Consistent
  with the title, but it carries no meaning of its own; not used.
- **Transcript:** with `--session-id`, `~/.claude/projects/<cwd>/<id>.jsonl` gets a user entry when a turn starts,
  `tool_use`/`tool_result` entries in between, and `system`/`turn_duration` when it ends. Written by Claude Code
  outside the sandbox's write area, so a sandboxed command cannot forge it. Not used yet: it would add
  `--session-id` to the launch argv, a launch-boundary change of its own.
- **Permission prompts:** not reproduced. With the managed sandbox settings, `echo` and `touch` inside the work
  directory ran without a prompt, also with `--permission-mode default`. So it is not recorded whether a dialog
  changes the title. VBear calls the `✳` state "waiting" (for your input or your decision) and does not claim which
  of the two it is.

## What VBear derives

| Title state | Activity | Note |
|---|---|---|
| `◐` or `◑`, a frame within the last 5 s | working | |
| `◐` or `◑`, no frame for more than 5 s | unknown | the spinner stopped |
| `✳` | waiting | no time limit: Claude does not re-send it |
| no title yet | unknown | possibly the startup trust dialog |
| empty, or any other first character | unknown | |

For any other Claude Code version, the same evidence is recorded as **trial**: shown, never consulted, so the state
reads unknown. Adding a version to `VERIFIED` in `vbear/activity.py` needs a record like this one.
