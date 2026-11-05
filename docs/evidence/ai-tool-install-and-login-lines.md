# Install and login lines of the AI tools

Why this file: the start-up page types one line into a terminal for the person (`vbear/ai_tools.py`, `install_command`,
`login_command`, `login_regions`). The rule is that each line is the vendor's own, as its documentation writes it. This
records where each came from, checked on 2026-11-05 against the vendors' public pages and the `--help` of the versions on
the maintainer's Mac (claude 2.1.318, codex-cli 0.163.0, agy 1.5.0, grok 0.2.101, mcode 0.5.2). VBear does not download or
run any of these scripts itself; the five install addresses answered HTTP 200 when only fetched (never run).

| Tool | Install line | Login line | Source |
| --- | --- | --- | --- |
| Claude Code | `curl -fsSL https://claude.ai/install.sh \| bash` | `claude auth login` | code.claude.com/docs/en/setup, /authentication |
| Codex | `curl -fsSL https://chatgpt.com/codex/install.sh \| sh` | `codex login` | learn.chatgpt.com/docs/codex/cli |
| AGY | `curl -fsSL https://antigravity.google/cli/install.sh \| bash` | `agy` (no login subcommand; the first start opens the browser) | antigravity.google/docs/getting-started, /install |
| Grok | `curl -fsSL https://x.ai/cli/install.sh \| bash` | `grok login` | docs.x.ai/build/overview, /build/cli/reference |
| MCODE | `curl -fsSL https://filecdn.minimax.chat/public/install.sh \| bash` | `mcode login --region global` or `mcode login --region cn` | agent.minimax.io/docs/cli/quick-start.md |

## Status checks

- Claude Code: `claude auth status`. Codex: `codex login status`. Both exist in the local `--help`; the vendors' pages do not
  define their exit codes, so VBear counts only exit code 0 as logged in and everything else (including a timeout) as not
  logged in, and keeps no output.
- AGY, Grok and MCODE have no non-interactive status command (the local `--help` has none and the pages list none), so the
  person's "I have logged in" mark is the only evidence.

## Headless calls of 「試一下」

From the research notes (flags confirmed against each tool's local `--help`; none was run for this task, the tests use stand-ins):
Claude Code `-p` with `--safe-mode`, `--setting-sources ""`, `--tools ""`, `--max-budget-usd`, `--output-format json`,
`--no-session-persistence` (the same words the chat and the translations use); Codex `exec` with `--ignore-user-config`,
`--ignore-rules`, `--skip-git-repo-check`, `--ephemeral`, `--sandbox read-only`, `-` for stdin (`--ask-for-approval never` goes before `exec`: it is a top-level option of `codex` and
`codex exec --help` does not list it; `--disable shell_tool`, `--disable mcp` as the translations candidate already used); AGY `-p` with `--output-format text` and
`--disable-slash-commands` (no checked flag for fewer tools; `--sandbox`'s value form is not known); Grok `-p` with
`--output-format plain`, `--max-turns 1`, `--disable-web-search`, `--no-memory`, `--no-plan`, `--no-subagents`, `--cwd`; MCODE
`exec` with `--cwd`, `--timeout`, `--max-steps 1`, `--permission off`, `--output-format text`. Only Claude Code has a budget flag
and reports a cost. These are to be checked once on a real machine (cost under US$0.01 each, answered, no file written).

## Version lines (what marks a tool as installed)

`2.1.318 (Claude Code)`, `codex-cli 0.163.0`, `1.5.0` (AGY), `grok 0.2.101 (5bc4b5dfadcf)`, `0.5.2` (MCODE); the patterns are
`version_pattern` in `vbear/ai_tools.py`.

## Install folders searched

The install scripts put the programs in `~/.local/bin` (Claude Code, Codex, AGY), `~/.grok/bin` and `~/.minimax-code/bin`;
`runtime/daemon.extra_path` lists all of them (task 2).

## Not found

Exit-code meaning of the two status commands; a status command for AGY, Grok and MCODE; which Codex plans may log in; MiniMax's
subscription requirement. The page's one-sentence descriptions say so where it matters.
