# Research: a per-launch CODEX_HOME for Codex 0.160.0

Recorded on 2026-10-07. A research note, not boundary evidence: **Codex launches stay refused**
(`CODEX_INTERACTIVE_FLAGS_SUPPORTED = False`, pinned 0.159.2). It answers one question: could a managed Codex
session get its own empty `CODEX_HOME`, so that the user's global configuration is simply not there to load?

OpenRig passes an explicit `CODEX_HOME` to every Codex seat (`codex-runtime-adapter.ts`); that is where the idea came
from. OpenRig itself passes the daemon's own home through, so it does not isolate anything.

- Binary: codex-cli **0.160.0**, macOS arm64 (`codex doctor` reports 0.160.1 is out).
- No model was called. Probes that start the TUI used an empty home, so Codex could not authenticate, and were
  killed after 5 s. Credentials were not read, copied or linked: only the existence of `~/.codex/auth.json` was
  checked.
- Probes: a PTY driver for the TUI, a JSON-RPC driver for `codex app-server` (`initialize`, `config/read`,
  `configRequirements/read`, `hooks/list`, `skills/list`, `plugin/installed`), `codex mcp list --json` and
  `codex debug prompt-input` (empty homes only, since it could run the user's hooks). Every output was filtered to
  names and counts before it was printed.

## 1. The interactive command still rejects the exec-only flags

`--ignore-user-config`, `--ignore-rules`, `--ephemeral` and `--skip-git-repo-check` all fail with
`error: unexpected argument '<flag>' found`. They exist only under `codex exec`. **`codex_argv()` passes all four**,
so it would be refused as written even if Codex launches were enabled. Without them (and with `--no-daemon`) the
same argv reaches the sign-in screen.

Without `--no-daemon`, a fresh home spent the whole 5 s copying the Codex package (318 MB) into
`$CODEX_HOME/packages/app-server-daemon/`. The background daemon's socket path is a hash of `CODEX_HOME`, so a
separate home gets its own daemon rather than the user's.

## 2. What an empty CODEX_HOME still loads

| | Default home | Empty home |
|---|---|---|
| User config layer | `~/.codex/config.toml` | the empty temp `config.toml` |
| MCP servers | 11 | 0 |
| Plugins | 17 configured, plus 25 enabled from remote marketplaces | 0 |
| Hooks | 14 (9 from `~/.codex/hooks.json`, 5 from plugins) | 0 |
| Global `AGENTS.md` instructions | in the prompt | absent (an `AGENTS.md` placed in the temp home did appear) |
| Rules (`default.rules`) | loaded | absent (a rule placed in the temp home did appear) |
| Skills | 129 | 32: 5 system, 1 from the repository, **26 from `~/.agents/skills`** |
| Managed requirements | none | none |

Layers that still apply with an empty home:

- **`$HOME/.agents/skills`.** `--enable skip_host_skill_discovery` did not remove them. Overriding `HOME` did, and
  so did disabling them one by one with `-c 'skills.config=[...]'`.
- **The project.** While the project is untrusted, its config, hooks and rules are disabled, but its `AGENTS.md` and
  skills still reach the prompt. Once trusted, its MCP servers and rules load too.
- **The login-shell snapshot.** `codex debug prompt-input` created `shell_snapshots/`: Codex runs the user's login
  shell to capture its environment.
- **System and managed layers** (`/etc/codex/`, managed preferences) would apply if installed. None exist on this
  Mac.
- After signing in, account-level remote plugins and connectors may come back (not tested).

## 3. Credentials

An empty home has none: `codex login status` says "Not logged in" (also with fake key variables set), and
`codex doctor` points at `$CODEX_HOME/auth.json`. The user's config uses a custom provider with
`requires_openai_auth = true`, so a per-launch config would need a copy of that provider block. Options, none
tested:

1. Sign in per launch (browser, device code or API key), with `-c cli_auth_credentials_store="ephemeral"` so
   nothing is written.
2. One dedicated VBear home, signed in once, with per-launch session state cleaned.
3. Copying or linking `auth.json`: not recommended. ChatGPT refresh tokens rotate, so two homes sharing one would
   break each other.

## 4. What Codex writes into a fresh home

Five seconds of the TUI with `--no-daemon` wrote 66 MB: `config.toml`, `installation_id`, `version.json`, five
SQLite databases, the bundled system skills, and a network clone of the curated plugin marketplace. With
`--disable plugins --disable remote_plugin --disable apps --disable hooks --disable shell_snapshot
-c check_for_update_on_startup=false` it still reached sign-in, wrote 2.9 MB and made no clone.

## Conclusion

A per-launch `CODEX_HOME` removes most of the user's global configuration (MCP servers, plugins, user hooks, global
instructions, rules, profiles) on 0.160.0. It is not yet a launch path:

- `codex_argv()` must drop the four exec-only flags and add `--no-daemon`.
- `~/.agents/skills` and the project's `AGENTS.md` and skills still load, so the preview would have to say so or
  VBear would have to remove them (a `HOME` override or a skills deny list).
- Authentication has no tested option.
- Still unverified: the OS sandbox's negative tests outside `/tmp` (the probe's scratch directory was under
  `/private/tmp`, which confounded it), whether the TUI honours `-c sandbox_workspace_write.*`, the trust prompt,
  and cleanup of the `codex-code-mode-host` child process. Codex does not protect `CODEX_HOME` on its own: a home
  inside the writable work directory was writable, so it would have to live outside every writable root.

The probe scripts and their filtered outputs are kept outside the repository, in
`_sandbox/20261007-164809/a4-codex/` of the working tree where they were run.
