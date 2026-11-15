# AGY 1.5.9: what was looked at, what the tables say, and what was not shown (v0.26.1)

AGY updates itself. The AGY on the same Mac went to 1.5.9 (its file on the Mac is dated 2026-11-14), and VBear's AGY chat knew 1.5.3, 1.5.6, 1.5.7 and 1.5.8 ([agy-1.5.3-chat.md](agy-1.5.3-chat.md), [agy-1.5.6-chat.md](agy-1.5.6-chat.md), [agy-1.5.7-chat.md](agy-1.5.7-chat.md),
[agy-1.5.8-chat.md](agy-1.5.8-chat.md)). The method of the 1.5.8 file was repeated on 2026-11-15. This file records what a real 1.5.9 was made to show, which table of VBear each fact supports, and what it did **not** show.
**Unlike the 1.5.8 file, this one was written without a copy of 1.5.8 to put next to the new program**: the older program and the outputs recorded for it were not kept, so everything that the 1.5.8 file calls "byte for byte the same" is, here, compared only with the **text of that file and the tables of VBear**, not with a second run. Each place where that limits a claim says so.

**Status: this is evidence for the tables, not a verification.** A version in `agy_chat_protocol.VERSIONS` is a version VBear is willing to start once `python3 -m vbear.boundary_check --mode agy-chat` passed on that Mac for that
very version (recorded per version in `agy-chat-verified.json`). Nothing here, and nothing in the repository, says 1.5.9 passed. 1.5.3, 1.5.6, 1.5.7 and 1.5.8 having passed (or not) says nothing about 1.5.9. The person presses 「聊天安全檢查」 once on 1.5.9.
Until that pass, the kept copy of v0.26.0 (ADR 0021) is not available for 1.5.9 either: a copy is made only when the check passes on it.

## 1. How it was obtained

- The program: `~/.local/bin/agy`, 223,424,816 bytes, SHA-256 `fad3628ad91fe8613a72f074a1c5fde7cd816517788a5b9be96703f7d256741a`; `agy --version` printed `1.5.9` and nothing else.
  (1.5.8 was 235,205,648 bytes, SHA-256 `b127126993e1c5b7e0b1ef80fa9bbe6955ddb85a5d76a3310b6096acc7eb000a`, from the 1.5.8 file. **The program is about 12 MB smaller than 1.5.8's.** Why was not looked into; it is a fact noted here, not an explanation.)
- Static reads: `agy --help`, `agy acp --help`, and `strings -a` of the executable (the count of each name that matters for safety, as occurrences, `grep -o`).
- One short run of the real program, and only that, the same as for 1.5.8: `HOME` was an empty temporary folder (so **not signed in**), the environment was cleared (`env -i`, with `PATH USER LOGNAME LANG TMPDIR HOME` only), and the command was
  `agy acp --gemini-dir <empty temporary folder> --sandbox --disable-telemetry`, the arguments the chat passes. Two messages were sent: `initialize` (answered with `protocolVersion: 1`) and `session/new`
  (answered `Authentication required`, code -32000). **No prompt was sent, nobody was logged in, no plan was used, and nothing was spent.** AGY writes `antigravity-cli/builtin` before the `session/new` answer;
  the folder it wrote was then read: the path, SHA-256, size and mode of each file, and the names of everything else.
  (A first attempt of the same command failed before AGY started, because the shell had no `timeout` program; it ran nothing and wrote nothing. The run above is the second, with a 30-second alarm from `perl`.)
- **No content of any file AGY wrote is quoted or copied into this repository**, only names and hashes. The writer of the code change read two things of the new built-in folder, and wrote down only what they are: the new skill file `skills/swarm_pane/SKILL.md` (section 4)
  and, as text, the two changed `.js` files of `swarm_board` (section 4). They are not part of the repository, and the temporary folders are outside it.

## 2. The flags and the protocol

- **Not compared byte for byte with 1.5.8's helps.** No copy of 1.5.8's `agy --help` or `agy acp --help` was kept, so the sentence "the helps are byte for byte the same" cannot be written for 1.5.9. What was checked is what the chat depends on: `agy acp --help` of 1.5.9 lists
  `--add-dir`, `--gemini-dir`, `--sandbox` and `--disable-telemetry`, each once, and the real run above accepted the arguments the chat passes. It also lists the other flags the 1.5.6 file names (`--agent`, `--app-data-dir`, `--cli_dir_name`, `--cli_log_file`, `--cloud_code_endpoint`, `--dangerously-skip-permissions`, `--ide-mcp-port`, `--include-default-customizations`, `--log-file`, `--login`, `--override_user_agent_name`,
  `--process-per-session`, `--stdio`, `--use_stubby_auth`, `--worker`, `--is_google3_workspace`, `--is_google_internal`, and underscore spellings of some of them); no flag name in the 1.5.9 `acp` help is missing from that list, which was checked by reading, not by a second run of 1.5.8. VBear passes none of them. `--settings` and `--mode` are still only on the main command, not on `acp` (the main help lists both; the `acp` help lists neither).
- The answer to `initialize`: `protocolVersion: 1`, `loadSession: true` (and a second spelling, `load_session`), prompt capabilities for images and embedded context (not audio), session capabilities `resume`, `close`, `load`, `list` and `additionalDirectories` (also under a second spelling, `session_capabilities`), the four authentication
  methods (`oauth-personal`, `oauth-business`, `gemini-api-key`, `agent-platform`), an `auth` capability with `logout`, `agentInfo.name` `Antigravity ACP Server`, `agentInfo.version` `1.5.9`, **and a `_meta.antigravity` object with `tier: true` and `systemPrompt.append: true`.**
  The 1.5.8 file does not mention a `_meta` object in its answer and no copy of that answer was kept, so **whether `_meta` is new in 1.5.9 cannot be said.** What `ChatTracker` reads (`protocolVersion` equal to 1, `resume` among the session capabilities) is what 1.5.9 answered; VBear keeps none of the rest
  (a test feeds an answer of exactly this shape to the tracker). The `systemPrompt.append` word is the one VBear's own `_meta.antigravity.systemPrompt.append` in `session/new` already uses; nothing about it changed in VBear.
  `session/new` without a login answers `Authentication required`, as 1.5.8 did.
- So every protocol constant of `VERSIONS["1.5.9"]` is 1.5.8's (which are 1.5.3's), because nothing seen contradicts it; only the version, the path table and the hash table are its own.

## 3. The strings, the administrator places, and what 1.5.9 shows of them

One counting was made: `strings -a` of the program, and for each name the number of occurrences (`grep -aoF`). **The 1.5.8 file counted in two ways that are not recorded in enough detail to repeat exactly, so a count is compared only to say "the name is still there" or "the number is the same"; a different number
is shown, not interpreted.** (An earlier line count of this same output gave smaller numbers for a few names, because one line holds several; the numbers below are occurrences.)

| Name in the program | 1.5.8 (its file) | 1.5.9 | What VBear does |
|---|---|---|---|
| `/etc/antigravity/admin_settings.json` | 1 | 1 | already in the source list (`etc/antigravity`, the whole folder) |
| `admin_settings.json` | 6 | 6 | the same |
| `/Library/Application Support/Antigravity` | 1 | 1 | already in the 1.5.6 list; **kept for 1.5.9** (the whole folder, an unconfirmed candidate) |
| `com.google.antigravity` | 14 (second counting) | 14 | already in the source list (the managed-preferences domain, a candidate) |
| `com.google.antigravity.companion`, `.dev`, `.insiders` | 1 each | 1 each | **still not added.** The same open point as in the 1.5.7 and 1.5.8 files |
| `Managed Preferences`, `CFPreferences`, `managed-settings`, `policy.json` | 0 | 0 | nothing names them |
| `AdminSettings` | 26 | 28 | the name of Google's administrator-controls package, two more times; see below |
| `MDM` | 15 | 15 | the same |
| `FetchAdminControls` | 265 | 265 | the same: the controls the server hands over, not a place on this Mac |
| `authControls` | 6 | 6 | the same. Its fields in the text: `gcpLocation`, `gcpProjectId`, `licenseType`, `wifProvider` (and the same sections as 1.5.8's file names) |
| `models.list` | not recorded | 5 | **new in what this file names.** One of the five follows `/etc/antigravity/admin_settings.json` in the program's text, so it reads as a field of the same file; see below |
| `GEMINI_INTERNAL_BYOM` | 2 | 3 | a name in the program's text of the same kind as the other `GEMINI_*` words; not passed to the process (section 5) |
| `mcp_config.json` | 31 | 32 | already refused (name); no new name |
| `.agents/hooks.json`, `.agents/agents`, `.agents/plugins.json`, `.agents/plugins` (counts the previous one too), `.agents/rules`, `.agents/skills.json`, `.agents/skills` (counts the previous one too), `.agents/teamwork`, `.agents/workflows` | 2, 2, 1, 2, 1, 3, 9, 606, 3 (from the 1.5.8 file: 2, 2, 1, 1, 1, 6, 3, 606, 3 with the shorter names counted apart) | 2, 2, 1, 2, 1, 3, 9, 606, 3 | the same names and, taking the two overlapping pairs into account, the same counts; see section 4 |
| `GEMINI.md`, `AGENTS.md`, `hooks.json` | 55, 62, 41 | 56, 63, 45 | already refused (names); the numbers differ by a method that is not recorded, the names are there |
| `session/cancel`, `session/load`, `session/prompt`, `session/resume` | 1 each | 1 each | the methods VBear writes or reads; `session/load` is still never written |
| `session/request_permission`, `session/update` | 1 each | 2 each | the same methods; nothing new is read or written because of the second occurrence |
| `allow_once`, `reject_once`, `allow_always` | 1, 1, 4 | 1, 1, 4 | the option kinds; only the first two are ever chosen |
| `BypassSandbox` | 27 | 27 | still refused by VBear with no card |
| `ANTIGRAVITY_*` (distinct names) | see the 1.5.8 file | 59 distinct names in the text | **not passed:** the process gets exactly six variables (section 5). Which of them are new was not counted |

**No new file path, no new managed-preferences domain and no new administrator place was found**, and the sources are the same two folders, the same domain and the controls the server hands over (`FetchAdminControls`). So `AGY_SOURCES["1.5.9"]` is 1.5.8's list, which is 1.5.6's.
VBear refuses the AGY chat when any listed local source exists, **whatever it holds**; a field named inside an existing source (`models.list` of `admin_settings.json`) therefore needs no new entry: the presence of the file already stops the chat, and VBear never reads its content to decide.

- **An earlier line count must not be repeated.** In a first counting of the same output by lines (`grep -c`), `BypassSandbox` came out 22 and `allow_always` 3. That counted lines, not occurrences; the occurrences are 27 and 4 as above, the same as 1.5.8's. **No rule was loosened because of any count.**
- **The residual that was already there is unchanged in kind.** The controls fetched from Google's servers for a signed-in account (`FetchAdminControls`) are not a place on this Mac's disk, so the administrator-source check cannot see them. This is named in SECURITY-MODEL.
- **Not verified:** that the strings list is complete (a name can be assembled at run time), what `models.list` or any of the `authControls` fields do when set, and whether a server-side control can loosen what VBear's own settings file asks of AGY (`toolPermission: request-review`, the terminal sandbox on, no non-workspace access).
  Only a signed-in run under an administrator's controls would show it.

## 4. Hooks and project settings: no new place; the new skill and the two changed scripts

The `.agents/*` names and counts of the program are the same as the 1.5.8 file records (the table above), so VBear's lists (`workdir_forbidden`, `forbidden_anywhere`, the protected names of the file tools, the twelve places of `home_hooks_state` and `ancestor_hooks_state`) are unchanged and apply to 1.5.9 as they are.
The six built-in guide files `skills/agy-customizations/docs/*.md` and its `SKILL.md` have the **same SHA-256 as the table of 1.5.8** (section 6), so there is no new statement in that guide to read.

Three built-in files have something to say apart from their hash:

- **`skills/swarm_pane/SKILL.md` is new** (1,987 bytes, mode 0644, a `.md`, not a file that can run). Its text is a document for the model (it describes what the coordinator of a swarm writes so that the Swarm UI's Overview can show the goal, the groups of work and a screenshot timeline). The places it names are `<appData>/brain/<conversation id>/.system_generated/swarm/plan.json`
  and a folder under the worker's own `<appData>/brain/<conversation id>/`. `brain` is AGY's own folder and is already in the `home_created` table of VBear; nothing in the file names `.agents`, `config/plugins`, `config/mcp_config.json`, a hook or a rule. It is on 1.5.9's path table only, so a 1.5.8 start still refuses it.
- **`plugins/swarm/sidecars/swarm_board/hive.js` and `app.js` have new bytes** (73,016 and 92,955 bytes). They are files that can run (`.js`, in `builtin_runnable`), so they pass only by their hash, as before. **No copy of 1.5.8's two files was kept, so no difference between them was seen; only that the SHA-256 differs from the table of 1.5.8.**
  What was read are the new files as text, with a count of words that matter for a script that runs in a browser page of the swarm board: `app.js` has `fetch` (called on the sidecar's own paths such as `/narrator_bootstrap.js`, through `window.sidecar.fetch` when it exists), `localStorage` (3), `postMessage` (2),
  `innerHTML` (30) and one `window.open(a.target, '_blank', 'noopener,noreferrer')`; `hive.js` has `innerHTML` (3) and the SVG namespace address and no `fetch`, `XMLHttpRequest`, `WebSocket`, `EventSource` or `sendBeacon`; neither names a process, a file system or a shell. This is a reading of words, **not an analysis, and not a comparison with 1.5.8's scripts.**
  These scripts are served by AGY's swarm-board sidecar, which a chat of VBear does not start (no swarm is asked for; the chat asks for no plugin and `config/plugins` is refused), so what they would do is not shown to be reachable from VBear's chat.
- **`skills/native_swarm/SKILL.md` has new bytes** (a `.md`). Only the hash is known to differ; its text was not compared.

## 5. The environment

Unchanged. The chat gives AGY exactly six variables (`PATH USER LOGNAME LANG TMPDIR HOME`; `agent_sessions.agy_chat_env`), a whitelist, so no `ANTIGRAVITY_*` or `GEMINI_*` name can reach it. The strings of 1.5.9 name 59 distinct `ANTIGRAVITY_*` words; they were not compared with 1.5.8's because the whitelist makes the comparison unnecessary.
`tests/test_p46_agy_chat_launch.py` and rule 14d hold every version to six variables.

## 6. AGY's own built-in folder: 66 paths, 43 files, 6 of them new or with new bytes

The folder a real 1.5.9 wrote has every built-in file in mode `0644` and **66 paths: 43 files and 23 folders**. (Other files of the folder, written by AGY outside `builtin`, have mode `0600`: `config/config.json` and `antigravity-cli/jetski_state.pbtxt`; they are not part of this table.) Against the table of 1.5.8 (64 paths, 42 files, 22 folders):

- **37 files have the same SHA-256** as 1.5.8's table (among them `keep.txt`, `plugins/swarm/plugin.json`, the other files of the swarm board including `hive.css`, `main.mjs`, `channels.mjs` and `narrator_bootstrap.js`, the seven files of `skills/agy-customizations`, and `skills/mcp-app-development/SKILL.md`).
- **5 files differ**: `.checksum` (a line of the form `builtin:` and a hash, made by AGY over the folder, so it changes when any file does), `.manifest`, `plugins/swarm/sidecars/swarm_board/app.js`, `plugins/swarm/sidecars/swarm_board/hive.js` and `skills/native_swarm/SKILL.md`.
- **1 file is new**: `skills/swarm_pane/SKILL.md`, with its folder `skills/swarm_pane`. Nothing disappeared, no mode changed, and no other folder appeared.
- **`.manifest` (AGY's own list of names, 41 now, 40 in 1.5.8) was checked against the table:** the 41 names are the 43 files minus `.checksum` and `.manifest`, which is what 1.5.8's list was against its 42, plus the new skill file, and **the 1.5.9 list with its one new line removed has exactly the SHA-256 of 1.5.8's `.manifest`** (`03f89b56579e2bf4a01bb6041369a93c2366c9ca97d2d4b5529458518d472250`).
  So the change of `.manifest` is that one line and nothing else.

The 43 values are `builtin_sha256` of `VERSIONS["1.5.9"]`. Its `builtin_paths` are 1.5.8's with the two new paths (66, the folder before its file, in the order of the table); `builtin_runnable` is 1.5.3's, unchanged: the new file is a `.md`, no file of 1.5.9 has an ending that is new, and the changed runnable files (`app.js`, `hive.js`) are pinned by hash like every other file.
`skills/native_swarm/SKILL.md`, `.checksum`, `.manifest`, `app.js` and `hive.js` have a new value now, and each of their older values still passes at that path (ADR 0018); no other path takes them.

**The path table belongs to the version about to start.** `agy_chat_env.builtin_table(version)` reads it per version, so a folder with `skills/swarm_pane` is refused when 1.5.8 (or an older version) is about to start and accepted when 1.5.9 is; a folder 1.5.8 wrote is accepted for 1.5.9, because it is a subset of the paths and the hashes are shared at each path. Only the hashes are shared; the paths never are.

The folder outside `builtin` had these names, all of them in `home_created` already: `antigravity-cli` (with `brain`, `conversation_summaries.db`, `conversations`, `crashes`, `implicit` with one `.pb` file named by a UUID, `installation_id`, `jetski_state.pbtxt`, `log` with one log file) and `config` with `.migrated`, `config.json`, `mcp_config.json` and `projects`.
Names AGY makes only after a prompt or a command were not produced by this run; nothing is claimed about them for 1.5.9.

## 7. What each table of VBear rests on

| Table | Entry | Evidence | Gap |
|---|---|---|---|
| `agy_chat_protocol.VERSIONS["1.5.9"]` constants (argv, six variables, settings, model, option kinds, session updates, usage fields, `announced_kinds`, `home_created`) | 1.5.8's (1.5.3's) | section 2 (the flags the chat passes, the answer to `initialize`), section 3 (the same methods and option kinds), section 6 (the names AGY made) | **no byte-for-byte comparison with 1.5.8's helps or `initialize` answer** (none kept); `_meta.antigravity` in the answer may be new; the shape of signed-in messages, the order of a tool call, the usage fields, and what is made after a command: **not shown**; the chat check shows them, and a message that does not fit is an anomaly or stops the chat |
| `builtin_paths` | 1.5.8's 64 and `skills/swarm_pane`, `skills/swarm_pane/SKILL.md` | section 6 | a folder AGY 1.5.9 writes after a long use may hold more; that is refused by name until a run shows it |
| `builtin_runnable` | 1.5.3's | section 6: no new ending | none known |
| `builtin_sha256` | the 43 values of the folder a real 1.5.9 wrote | section 6 | the contents of `app.js`, `hive.js` and `native_swarm/SKILL.md` were not compared with 1.5.8's; the hash is what is pinned |
| `admin_policy.AGY_SOURCES["1.5.9"]` | 1.5.6's, as 1.5.7's and 1.5.8's: `etc/antigravity`, `Library/Application Support/Antigravity`, domain `com.google.antigravity` | section 3 | the list is a reading of strings, not vendor documentation; the three longer `com.google.antigravity.*` names are an open point; the controls fetched from the server are not a place on disk |
| work folder, file tools, home hooks | unchanged | section 4 | rules the guide does not state; a change between the look and AGY's search |
| environment | six variables, unchanged | section 5 | none |

## 8. Not shown, on purpose

- Everything that needs a signed-in AGY: the answer of `session/new` (models, modes, config options), `session/set_model`, the permission requests and the options they offer, the tool calls and their order, `usage`, `session/cancel`,
  `session/resume`, whether AGY rewrites an older `builtin` folder when it starts after an update, and what the sandbox does. These are what `boundary_check --mode agy-chat` (and `--shared`) measure on the person's Mac.
- That `agy` 1.5.9, as a single smaller program, behaves like 1.5.8 in anything but the three observations above (flags the chat passes, the answer to `initialize`, the folder it wrote). Why it is 12 MB smaller is not known.
- Whether the kept copy of v0.26.0 (a copy of the AGY that passed the check) works for 1.5.9: a copy is made only when the check passes on the person's Mac, and no real AGY was copied by this work.
