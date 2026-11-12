# AGY 1.5.6: what was looked at, what the tables say, and what was not shown (v0.25.2)

AGY updates itself. A Mac whose AGY went to 1.5.6 could not chat, because VBear's AGY chat knew 1.5.3 only ([agy-1.5.3-chat.md](agy-1.5.3-chat.md)). v0.22.1 compared 1.5.5 with static means and did **not** add it
([agy-1.5.5-not-added.md](agy-1.5.5-not-added.md)): the folder check pins the SHA-256 of every file AGY writes under `antigravity-cli/builtin`, and that needs a real AGY that has written the folder.
This file records what a real 1.5.6 was made to show on 2026-11-12, which table of VBear each fact supports, and what it did **not** show.

**Status: this is evidence for the tables, not a verification.** A version in `agy_chat_protocol.VERSIONS` is a version VBear is willing to start once `python3 -m vbear.boundary_check --mode agy-chat` passed on that Mac for that
very version (recorded per version in `agy-chat-verified.json`). Nothing here, and nothing in the repository, says 1.5.6 passed. The person presses 「聊天安全檢查」 once on 1.5.6.

## 1. How it was obtained

- The program: `~/.local/bin/agy`, 233,521,200 bytes, SHA-256 `c55b821d5efcfd7ca7fdadbc870d1247cc0ccd31137291fee83fb0e342dc753a`; `agy --version` printed `1.5.6` and nothing else.
- Static reads: `agy --help`, `agy acp --help` and the strings of the executable that matter for safety (a count of each name, no context).
- One short run of the real program, and only that: `HOME` was an empty temporary folder (so **not signed in**), the environment was cleared (`env -i`), and the command was
  `agy acp --gemini-dir <empty temporary folder> --sandbox --disable-telemetry`, the arguments the chat passes. Two messages were sent: `initialize` (answered with `protocolVersion: 1`) and `session/new`
  (answered `Authentication required`). **No prompt was sent, nobody was logged in, no plan was used, and nothing was spent.** AGY writes `antigravity-cli/builtin` at the `session/new` step (after `initialize` alone it is not there yet);
  the folder it wrote was then read: the path, SHA-256, size and mode of each file, and the names of everything else. The temporary folders were deleted.
- This is the same kind of look as the fifth real run of 1.5.3 (the hash of each file, nothing of its content). **No content of any file AGY wrote is quoted or copied into this repository**, only names and hashes.

## 2. The flags: the same

`agy acp --help` of 1.5.6 lists every flag the chat passes (`acp`, `--gemini-dir`, `--sandbox`, `--disable-telemetry`, `--add-dir`) and the ones the 1.5.3 evidence names as never passed (`--app-data-dir`,
`--dangerously-skip-permissions`, `--include-default-customizations`, `--process-per-session`, `--login`). `--settings` and `--mode` are still only on the main command, not on `acp`.
The help lists more flags than section 1 of the 1.5.3 evidence names (`--agent`, `--cli_dir_name`, `--cli_log_file`, `--cloud_code_endpoint`, `--ide-mcp-port`, `--log-file`, `--override_user_agent_name`, `--use_stubby_auth`, `--worker`,
`--is_google3_workspace`, `--is_google_internal`, `--stdio`, and underscore spellings of some of the others). That evidence names the flags it needed, not the whole help, so **"new in 1.5.6" cannot be claimed**; what matters is that
the chat passes none of them: the command line is one table (`acp --gemini-dir <state>/agy-chat-home --sandbox --disable-telemetry`, plus `--add-dir`) and rule 14b of `tests/test_autonomy_guard.py` keeps the switches that skip
permissions, sign in, move the app data or load default customizations out of every file that builds it. An underscore spelling is the same flag as its dashed one and is not passed either.

## 3. The strings (name: count in 1.5.6) and what each does to a table

| Name in the program | Count | What VBear does |
|---|---|---|
| `/etc/antigravity` (the 1.5.3 reading found `/etc/antigravity/admin_settings.json`), `admin_settings`, `AdminSettings` | 1, 7, 18 | already in the source list; same for 1.5.6 |
| `com.google.antigravity` | 6 | already in the source list (the managed-preferences domain, a candidate); same for 1.5.6 |
| **`/Library/Application Support/Antigravity`** | 1 | **Added to the 1.5.6 source list** (`Library/Application Support/Antigravity`, the whole folder). The 1.5.3 reading met this fragment too and left it out as unexplained (a test of `admin_policy` says so); the strings cannot show whether it is an administrator place. A new version is not allowed to be looser than the evidence leaves room for, and a Mac without that folder (this one) is not affected, so for 1.5.6 it refuses. 1.5.3's list is unchanged |
| `managed-settings`, `policy.json` | not in the extract | not added (nothing names them); the 1.5.3 list never had them |
| `.agents/hooks.json` | 2 | project and home hooks place; see section 4 |
| `.agents/agents`, `.agents/plugins`, `.agents/plugins.json`, `.agents/rules`, `.agents/skills`, `.agents/skills.json`, `.agents/workflows` | 2, 1, 1, 1, 6, 3, 3 | see section 4 |
| `.agents/teamwork` | 606 | a place AGY writes team state into (the swarm feature); inside `.agents`, which VBear already refuses at the top of a work folder and for file tools at any depth |
| `GEMINI.md`, `AGENTS.md`, `hooks.json`, `mcp_config.json` | 55, 60, 41, 29 | already refused (names); unchanged |
| `session/cancel`, `session/load`, `session/prompt`, `session/request_permission`, `session/resume`, `session/update` | 1 each | the methods VBear writes or reads; `session/load` is still never written |
| `allow_once`, `reject_once`, `allow_always` | 1, 1, 4 | the option kinds; only the first two are ever chosen |
| `BypassSandbox` | 27 | still refused by VBear with no card |
| `ANTIGRAVITY_*`, `GEMINI_*` (many) | see section 5 | not passed: the process gets exactly six variables |

The names `session/new`, `session/set_model`, `session/set_mode` and `session/set_config_option` are not in the extract; the extract is a count of chosen names, not the program's whole table, so their absence says nothing, and
what a signed-in 1.5.6 does with `session/set_model` is for the chat check.

## 4. Hooks and project settings

What AGY reads as customizations is described by AGY's own built-in guide (`skills/agy-customizations`, whose `SKILL.md` and plugin/rules/skills documents are the very same bytes in 1.5.3 and 1.5.6; only the hooks document differs).
Its statements, read in the files of the folder a real 1.5.6 wrote:

- a **customization root** is `.agents/`, `.agent/`, `_agents/` or `_agent/`, and AGY walks from the working directory up to the repository root looking for them; hooks are `hooks.json` in a root (said by the 1.5.6 hooks document, the one document that differs from 1.5.3's; the 1.5.3 one was not read), plugins are folders under
  `plugins/` of a root (a plugin may carry `hooks.json` and `mcp_config.json`, whose servers AGY launches) or are listed in `plugins.json`; rules are `GEMINI.md` / `AGENTS.md` in any directory on the way and `.agents/rules`;
- globally the same things live in `~/.gemini/config/` (replaced by `--gemini-dir`, which the chat sets to its own folder), and VBear already refuses `hooks.json`, `skills`, `workflows`, `global_workflows`, `plugins` and
  every name it does not know in that folder.

Against VBear's lists (before v0.25.2): the work folder refused `.agents`, `.agent`, `.gemini`, `GEMINI.md`, `AGENTS.md` at its top; file tools refused the same names (and `.git`, `.codex`, `.claude`) at any depth; the home folder was
checked for `~/.agents/hooks.json` only. The two spellings `_agents` and `_agent` were not on any list, and neither were the hooks and plugins places in the other roots of the home folder. The root names and the plugin places are in documents that are byte for byte the same in
1.5.3 and 1.5.6 (`SKILL.md`, `plugins.md`), so they are a gap of the earlier table, not something 1.5.6 brought; it is closed now for every version (the lists only grow):

- `workdir_forbidden`, `forbidden_anywhere` and the file tools' protected names gain `_agents` and `_agent`;
- the home check (`home_hooks_state`) now looks, by `lstat` and never opening anything, at `hooks.json`, `plugins.json` and `plugins` in each of `~/.agents`, `~/.agent`, `~/_agents`, `~/_agent`.

Not covered, and said so: customization roots in folders **between** the work folder and `/` other than the home folder (`<state>/chat-work`, the state folder itself): they are VBear's own 0700 folders and nothing but VBear and
the AGY process writes there; and `rules`, `skills`, `workflows` and `agents` in the home folder, which are text for the model and have been accepted since ADR 0012 (`~/.agents/teamwork`, swarm state, is not looked at either).

## 5. The environment

The chat gives AGY exactly six variables (`PATH USER LOGNAME LANG TMPDIR HOME`, each from the daemon's own environment; `agent_sessions.agy_chat_env`), so it is a whitelist and a variable the program reads cannot reach it. The 1.5.6
strings name, among others, `ANTIGRAVITY_GEMINI_DIR`, `ANTIGRAVITY_APP_DATA_DIR`, `ANTIGRAVITY_CONFIG_REL_DIR`, `ANTIGRAVITY_PLUGIN_SHIM_DIR`, `ANTIGRAVITY_EXECUTABLE_DATA_DIR`, `ANTIGRAVITY_NODE_PATH`,
`ANTIGRAVITY_PERM_GRANTS`, `ANTIGRAVITY_LS_ADDRESS`, `ANTIGRAVITY_CSRF_TOKEN`, `ANTIGRAVITY_SIDECAR_*`, `ANTIGRAVITY_DISABLE_EMBEDDED_RIPGREP`, `GEMINI_API_KEY` and `GEMINI_BASE_URL`; the names that could move `--gemini-dir`
or the settings (`ANTIGRAVITY_GEMINI_DIR`, `ANTIGRAVITY_APP_DATA_DIR`, `ANTIGRAVITY_CONFIG_REL_DIR`) and the keys are among them. Whether a name does change the folder was not tried (that would need a run with the variable set); it does not matter,
because none is passed: `tests/test_p46_agy_chat_launch.py` (`ANTIGRAVITY_*` and `GEMINI_*` names of this very list in the daemon's environment) and rule 14d hold every version to six variables. `agy --version` is run with a
separate small whitelist (`cli_versions._probe_environment`) and that is tested with the same names.

## 6. AGY's own built-in folder: 62 paths, 41 files, 15 of them different

The folder a real 1.5.6 wrote has the same 62 paths (41 files and 21 folders) as the table of 1.5.3, every file mode `0644`, and no new or missing path. The SHA-256 of 26 files is the same as in 1.5.3's table (among them `keep.txt`, the empty
file, `.manifest`, `plugins/swarm/plugin.json`, the swarm board's `channels.mjs`, `narrator_bootstrap.js`, `package.json`, and the other 20 documents and skills of the list below). 15 differ:

`.checksum`, `plugins/swarm/assets/logo.svg`, `plugins/swarm/sidecars/swarm_board/README.md`, `.../app.js`, `.../hive.css`, `.../hive.js`, `.../index.html`, `.../main.mjs`, `.../sidecar.json`, `.../styles.css`,
`skills/agy-customizations/docs/hooks.md`, `skills/generative_ui/SKILL.md`, `skills/native_swarm/SKILL.md`, `skills/native_swarm/logo.svg`, `skills/swarm_narrator/SKILL.md`.

(`.checksum` is a line of the form `builtin:` and a SHA-256, made by AGY over the folder.) The 41 values are `builtin_sha256` of `VERSIONS["1.5.6"]`; `builtin_paths` and `builtin_runnable` are 1.5.3's (no file of 1.5.6 has an ending that is new).
Five of the 15 files can run (`main.mjs`, `app.js`, `hive.js`, `sidecar.json`, `index.html`) and they are pinned like every other file: a file of that kind passes only with a hash a table pins at its path.
v0.22.1 found `skills/native_swarm/SKILL.md` different in the program of 1.5.5 (SHA-256 `25f6eb1e...`, [agy-1.5.5-not-added.md](agy-1.5.5-not-added.md)); the file of 1.5.6 is different from both 1.5.3's and that one (`61f7913f...`), so 1.5.5's table is not 1.5.6's, and a table of 1.5.5 was never made because no 1.5.5 executable is left to write the folder: **1.5.5 stays not added.**

The folder outside `builtin` had these names, all of them in `home_created` already: `antigravity-cli`, `brain`, `conversation_summaries.db`, `conversations`, `crashes`, `implicit` (with one `.pb` file named by a UUID), `installation_id`,
`jetski_state.pbtxt`, `log` (with one log file), and `config` with `.migrated`, `config.json`, `mcp_config.json` and `projects`. Names AGY makes only after a prompt or a command (`annotations`, `bin`, `cache`,
`jetbox_summaries_proto.pb`, `persistent_terminals`, the SQLite side files) were not produced by this run; nothing is claimed about them for 1.5.6.

## 7. What each table of VBear rests on

| Table | Entry | Evidence | Gap |
|---|---|---|---|
| `agy_chat_protocol.VERSIONS["1.5.6"]` constants (argv, six variables, settings, model, option kinds, session updates, usage fields, `announced_kinds`, `home_created`) | 1.5.3's | section 2 (flags), section 3 (methods, option kinds), section 6 (the names AGY made) | the shape of signed-in messages, the order of a tool call, the usage fields, and what is made after a command: **not shown**; the chat check shows them, and a message that does not fit is an anomaly or stops the chat |
| `builtin_paths`, `builtin_runnable` | 1.5.3's | section 6: the same 62 paths, no new ending | none known |
| `builtin_sha256` | the 41 values of the folder a real 1.5.6 wrote | section 6 | a folder AGY 1.5.6 writes after a long use may hold more; that is refused by name until a run shows it |
| `admin_policy.AGY_SOURCES["1.5.6"]` | `etc/antigravity`, `Library/Application Support/Antigravity`, domain `com.google.antigravity` | section 3 | the list is a reading of strings, not vendor documentation, as for 1.5.3 |
| work folder, file tools, home hooks | `_agents`, `_agent` and the home places added for every version | section 4 | roots between the work folder and `/` other than the home folder |
| environment | six variables, unchanged | section 5 | none |

## 8. Not shown, on purpose

- Everything that needs a signed-in AGY: the answer of `session/new` (models, modes, config options), `session/set_model`, the permission requests and the options they offer, the tool calls and their order, `usage`, `session/cancel`,
  `session/resume`, whether AGY rewrites an older `builtin` folder when it starts after an update, and what the sandbox does. These are what `boundary_check --mode agy-chat` (and `--shared`) measure on the person's Mac.
- The shared-folder part: the AGY employee still does not use the shared folder (ADR 0012, decision 7); nothing about 1.5.6 changes that.
- Whether the administrator-source list is complete (it is a reading of strings).
- Whether a first start after AGY's own update finds the old built-in files rewritten. VBear accepts either (ADR 0018), which is why it does not need to know.
