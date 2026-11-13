# AGY 1.5.7: what was looked at, what the tables say, and what was not shown (v0.25.5)

AGY updates itself. A Mac whose AGY went to 1.5.7 could not chat, because VBear's AGY chat knew 1.5.3 and 1.5.6 ([agy-1.5.3-chat.md](agy-1.5.3-chat.md), [agy-1.5.6-chat.md](agy-1.5.6-chat.md)). The method of the 1.5.6 file was
repeated on 2026-11-13, side by side with its tables. This file records what a real 1.5.7 was made to show, which table of VBear each fact supports, and what it did **not** show. The writer of the code change ran no AGY: the files named
below were made by the planner and handed over.

**Status: this is evidence for the tables, not a verification.** A version in `agy_chat_protocol.VERSIONS` is a version VBear is willing to start once `python3 -m vbear.boundary_check --mode agy-chat` passed on that Mac for that
very version (recorded per version in `agy-chat-verified.json`). Nothing here, and nothing in the repository, says 1.5.7 passed. 1.5.3 and 1.5.6 having passed (or not) says nothing about 1.5.7. The person presses 「聊天安全檢查」 once on 1.5.7.

## 1. How it was obtained

- The program: `~/.local/bin/agy`, 234,512,352 bytes, SHA-256 `e872cc54b5381f401c798fc947937a0a930876b849bc3fee654996ba4ab236a8`; `agy --version` printed `1.5.7` and nothing else. (1.5.6 was 233,521,200 bytes, SHA-256 `c55b821d5efcfd7ca7fdadbc870d1247cc0ccd31137291fee83fb0e342dc753a`.)
- Static reads: `agy --help`, `agy acp --help` and the strings of the executable that matter for safety (a count of each name, with a few neighbouring words where a name was new).
- One short run of the real program, and only that, the same as for 1.5.6: `HOME` was an empty temporary folder (so **not signed in**), the environment was cleared (`env -i`), and the command was
  `agy acp --gemini-dir <empty temporary folder> --sandbox --disable-telemetry`, the arguments the chat passes. Two messages were sent: `initialize` (answered with `protocolVersion: 1`) and `session/new`
  (answered `Authentication required`, code -32000). **No prompt was sent, nobody was logged in, no plan was used, and nothing was spent.** AGY writes `antigravity-cli/builtin` at the `session/new` step;
  the folder it wrote was then read: the path, SHA-256, size and mode of each file, and the names of everything else. The temporary folders were deleted.
- **No content of any file AGY wrote is quoted or copied into this repository**, only names and hashes. The planner's copies of those files were read by the writer (one of them, the new skill, was searched for the places it names and its packaging
  section read, to see whether it names a place VBear does not already refuse; section 4) and are not part of the repository.

## 2. The flags and the protocol: the same

- `agy --help` and `agy acp --help` of 1.5.7 are **word for word** the outputs recorded for 1.5.6 (`diff` prints nothing for either). So the flags the chat passes (`acp`, `--gemini-dir`, `--sandbox`, `--disable-telemetry`, `--add-dir`)
  are all there, the ones never passed are still never passed (section 2 of the 1.5.6 file), and `--settings` and `--mode` are still only on the main command, not on `acp`.
- The answer to `initialize` has `protocolVersion: 1`, `loadSession: true`, session capabilities `resume`, `close`, `load`, `list` and `additionalDirectories`, the four authentication methods of the 1.5.3 file, and an agent name and
  version (`1.5.7`). The 1.5.6 answer itself was not kept; what the 1.5.3 file records, and what `ChatTracker` reads (`protocolVersion` equal to 1, `resume` among the session capabilities), is what 1.5.7 answered. VBear keeps none of the
  rest. (A test feeds an answer of this shape to the tracker.) `session/new` without a login answers `Authentication required`, as 1.5.6 did.
- So every protocol constant of `VERSIONS["1.5.7"]` is 1.5.3's (the same way 1.5.6's are); only the version, the path table and the hash table are its own.

## 3. The strings (name: count in 1.5.7) and what each does to a table

The counting of 1.5.7 was made by the planner with a slightly different extraction from the one of 1.5.6 (names that sit next to each other in the program come out joined in a different way), so **a count is compared only to say "the name is still there"**.

| Name in the program | Count | What VBear does |
|---|---|---|
| `/etc/antigravity/admin_settings.json`, `admin_settings`, `AdminSettings` | 1, 6, 18 | already in the source list (`etc/antigravity`, the whole folder); same for 1.5.7 |
| `/Library/Application Support/Antigravity` | 1 | already in the 1.5.6 list; **kept for 1.5.7** (the whole folder, an unconfirmed candidate: a Mac without that folder is not affected) |
| `com.google.antigravity` | 10 | already in the source list (the managed-preferences domain, a candidate); same for 1.5.7 |
| `com.google.antigravity.companion`, `.dev`, `.insiders` | 1 each | **not added.** Three longer names that begin with the domain. They sit in the program next to the bundle identifiers of other applications (a notification centre, a browser), which is where an application finds out what is installed; nothing shows that one is a managed-preferences domain of the command-line program. The 1.5.6 count file cannot tell whether they are new in 1.5.7. The source table holds one domain per version, and a change of its shape is not made on this evidence. **Open point**, for whoever decides whether the shape should hold a list of domains |
| `managed-settings`, `policy.json` | not in the extract | not added (nothing names them) |
| `.agents/hooks.json`, `.agents/agents`, `.agents/plugins`, `.agents/plugins.json`, `.agents/rules`, `.agents/skills`, `.agents/skills.json`, `.agents/teamwork`, `.agents/workflows` | 2, 2, 1, 1, 1, 6, 3, 606, 3 | the very same names and counts as 1.5.6; see section 4 |
| `GEMINI.md`, `AGENTS.md`, `hooks.json`, `mcp_config.json` | 55, 62, 41, 30 | already refused (names); unchanged. The small changes of count (`AGENTS.md` 60 to 62, `mcp_config.json` 29 to 30) are the extraction or program text; no new name |
| `session/cancel`, `session/load`, `session/prompt`, `session/request_permission`, `session/resume`, `session/update` | 1 each | the methods VBear writes or reads; `session/load` is still never written |
| `allow_once`, `reject_once`, `allow_always` | 1, 1, 4 | the option kinds; only the first two are ever chosen |
| `BypassSandbox` | 27 | still refused by VBear with no card |
| `ANTIGRAVITY_*`, `GEMINI_*` | see section 5 | not passed: the process gets exactly six variables |

## 4. Hooks and project settings: no new place

The built-in guide `skills/agy-customizations` (whose `docs/hooks.md`, `docs/plugins.md`, `docs/rules.md`, `docs/skills.md`, `docs/json_configs.md`, `docs/mcp_servers.md` and `SKILL.md` have the **same bytes in 1.5.7 as in 1.5.6**) is what section 4
of the 1.5.6 file read for the customization roots (`.agents/`, `.agent/`, `_agents/`, `_agent/`), hooks, plugins and rules. It did not change, and the `.agents/*` names of the program are the same, so VBear's lists
(`workdir_forbidden`, `forbidden_anywhere`, the protected names of the file tools, the twelve places of `home_hooks_state` and `ancestor_hooks_state`) are unchanged and apply to 1.5.7 as they are.

The one new built-in file, `skills/mcp-app-development/SKILL.md` (a document for the model about building MCP servers whose tools show an interface), was searched for every folder and file name of the customization places and its packaging section was read: it names `mcp_config.json` inside a plugin and shows a command of AGY's language
server, and no folder, file name or customization root that the 1.5.6 reading did not already have. It is a plain document (the ending `.md`), not a file that can run.

## 5. The environment

Unchanged. The chat gives AGY exactly six variables (`PATH USER LOGNAME LANG TMPDIR HOME`; `agent_sessions.agy_chat_env`), a whitelist, so no `ANTIGRAVITY_*` or `GEMINI_*` name can reach it. The names in 1.5.7's strings are the ones section 5 of the 1.5.6 file lists (the planner
found no real addition; the `GEMINI_2_5_*` and similar words are model names, not variables). `tests/test_p46_agy_chat_launch.py` and rule 14d hold every version to six variables.

## 6. AGY's own built-in folder: 64 paths, 42 files, 7 of the old ones different, 1 file new

The folder a real 1.5.7 wrote has every file mode `0644` and **64 paths: 42 files and 22 folders**. Against the table of 1.5.6 (62 paths, 41 files):

- **34 files have the same SHA-256** as 1.5.6's table (among them `keep.txt`, the empty file, `plugins/swarm/plugin.json`, the swarm board's `app.js`, `channels.mjs`, `main.mjs`, `index.html`, `narrator_bootstrap.js`, `package.json`, `sidecar.json`, `styles.css`, and the seven files of `skills/agy-customizations`).
- **7 files differ**: `.checksum`, `.manifest`, `plugins/swarm/sidecars/swarm_board/hive.css`, `plugins/swarm/sidecars/swarm_board/hive.js`, `skills/antigravity_guide/references/app.md`, `skills/native_swarm/SKILL.md`, `skills/swarm_narrator/SKILL.md`.
- **1 file is new**, in a new folder: `skills/mcp-app-development/SKILL.md` (and the folder `skills/mcp-app-development`).
- Nothing disappeared.

(`.checksum` is a line of the form `builtin:` and a hash, made by AGY over the folder.) The 42 values are `builtin_sha256` of `VERSIONS["1.5.7"]`. Its `builtin_paths` are 1.5.6's 62 plus the two new ones (the folder and the file); `builtin_runnable` is 1.5.3's, unchanged:
the new file ends in `.md`, no file of 1.5.7 has an ending that is new, and the runnable ones (`hive.js` among the 7 that changed) are pinned like every other file. `skills/native_swarm/SKILL.md` and `skills/swarm_narrator/SKILL.md` have a third value now (1.5.3's,
1.5.6's, 1.5.7's); any one of them passes at that path (ADR 0018), no other does.

**The path table belongs to the version about to start.** `agy_chat_env.builtin_table(version)` reads it per version, so a folder with `skills/mcp-app-development` is refused when 1.5.6 is about to start (the path is not on 1.5.6's table) and accepted when 1.5.7 is; a folder
1.5.6 wrote (without that skill) is accepted for 1.5.7, because a path the table has and the folder lacks is not a fault. Only the hashes are shared among the known versions (a file passes with the value any known version pins at its own path); the paths never are.

The folder outside `builtin` had these names, all of them in `home_created` already: `antigravity-cli`, `brain`, `conversation_summaries.db`, `conversations`, `crashes`, `implicit` (with one `.pb` file named by a UUID), `installation_id`,
`jetski_state.pbtxt`, `log` (with one log file; only its name differs from the 1.5.6 run), and `config` with `.migrated`, `config.json`, `mcp_config.json` and `projects`. Names AGY makes only after a prompt or a command were not produced by this run; nothing is claimed about them for 1.5.7.

## 7. What each table of VBear rests on

| Table | Entry | Evidence | Gap |
|---|---|---|---|
| `agy_chat_protocol.VERSIONS["1.5.7"]` constants (argv, six variables, settings, model, option kinds, session updates, usage fields, `announced_kinds`, `home_created`) | 1.5.3's | sections 2 and 3 (identical helps, the same methods and option kinds), section 6 (the names AGY made) | the shape of signed-in messages, the order of a tool call, the usage fields, and what is made after a command: **not shown**; the chat check shows them, and a message that does not fit is an anomaly or stops the chat |
| `builtin_paths` | 1.5.6's 62 plus `skills/mcp-app-development` and its `SKILL.md` | section 6 | a folder AGY 1.5.7 writes after a long use may hold more; that is refused by name until a run shows it |
| `builtin_runnable` | 1.5.3's | section 6: no new ending | none known |
| `builtin_sha256` | the 42 values of the folder a real 1.5.7 wrote | section 6 | as above |
| `admin_policy.AGY_SOURCES["1.5.7"]` | 1.5.6's: `etc/antigravity`, `Library/Application Support/Antigravity`, domain `com.google.antigravity` | section 3 | the list is a reading of strings, not vendor documentation; the three longer `com.google.antigravity.*` names are an open point |
| work folder, file tools, home hooks | unchanged | section 4 | rules the guide does not state; a change between the look and AGY's search |
| environment | six variables, unchanged | section 5 | none |

## 8. Not shown, on purpose

- Everything that needs a signed-in AGY: the answer of `session/new` (models, modes, config options), `session/set_model`, the permission requests and the options they offer, the tool calls and their order, `usage`, `session/cancel`,
  `session/resume`, whether AGY rewrites an older `builtin` folder when it starts after an update, and what the sandbox does. These are what `boundary_check --mode agy-chat` (and `--shared`) measure on the person's Mac.
- The shared-folder part: the AGY employee still does not use the shared folder (ADR 0012, decision 7); nothing about 1.5.7 changes that.
- Whether the administrator-source list is complete (it is a reading of strings).
- What the new skill does when AGY uses it (it is a document for the model; VBear's permission cards and sandbox are what limit what AGY may do, as for every other built-in skill).
