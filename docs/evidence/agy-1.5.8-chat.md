# AGY 1.5.8: what was looked at, what the tables say, and what was not shown (v0.25.6)

AGY updates itself. A few hours after v0.25.5 was released, the AGY on the same Mac went to 1.5.8, and VBear's AGY chat knew 1.5.3, 1.5.6 and 1.5.7 ([agy-1.5.3-chat.md](agy-1.5.3-chat.md), [agy-1.5.6-chat.md](agy-1.5.6-chat.md),
[agy-1.5.7-chat.md](agy-1.5.7-chat.md)). The method of the 1.5.7 file was repeated on 2026-11-13, side by side with its tables. This file records what a real 1.5.8 was made to show, which table of VBear each fact supports, and what it did **not** show.
The writer of the code change ran no AGY: the files named below were made by the planner and handed over.

**Status: this is evidence for the tables, not a verification.** A version in `agy_chat_protocol.VERSIONS` is a version VBear is willing to start once `python3 -m vbear.boundary_check --mode agy-chat` passed on that Mac for that
very version (recorded per version in `agy-chat-verified.json`). Nothing here, and nothing in the repository, says 1.5.8 passed. 1.5.3, 1.5.6 and 1.5.7 having passed (or not) says nothing about 1.5.8. The person presses 「聊天安全檢查」 once on 1.5.8.

## 1. How it was obtained

- The program: `~/.local/bin/agy`, 235,205,648 bytes, SHA-256 `b127126993e1c5b7e0b1ef80fa9bbe6955ddb85a5d76a3310b6096acc7eb000a`; `agy --version` printed `1.5.8` and nothing else. (1.5.7 was 234,512,352 bytes, SHA-256 `e872cc54b5381f401c798fc947937a0a930876b849bc3fee654996ba4ab236a8`;
  the copy of 1.5.7 used for the side-by-side counting was the one AGY left behind when it replaced itself.)
- Static reads: `agy --help`, `agy acp --help`, and the strings of both executables (`strings -a`; a count of each name that matters for safety, and the symbol names of the administrator-control package that were new).
- One short run of the real program, and only that, the same as for 1.5.7: `HOME` was an empty temporary folder (so **not signed in**), the environment was cleared (`env -i`), and the command was
  `agy acp --gemini-dir <empty temporary folder> --sandbox --disable-telemetry`, the arguments the chat passes. Two messages were sent: `initialize` (answered with `protocolVersion: 1`) and `session/new`
  (answered `Authentication required`, code -32000). **No prompt was sent, nobody was logged in, no plan was used, and nothing was spent.** AGY writes `antigravity-cli/builtin` at the `session/new` step;
  the folder it wrote was then read: the path, SHA-256, size and mode of each file, and the names of everything else. The temporary folders were deleted.
- **No content of any file AGY wrote is quoted or copied into this repository**, only names and hashes. The planner's copies of those files were read by the writer only for the one file whose bytes changed apart from the checksum (`skills/mcp-app-development/SKILL.md`,
  compared with the copy of 1.5.7, to see whether it names a place VBear does not already refuse; section 4) and are not part of the repository.

## 2. The flags and the protocol: the same

- `agy --help` and `agy acp --help` of 1.5.8 are **byte for byte** the outputs recorded for 1.5.7 (and so word for word 1.5.6's; `cmp` finds no difference in either). So the flags the chat passes (`acp`, `--gemini-dir`, `--sandbox`, `--disable-telemetry`, `--add-dir`)
  are all there, the ones never passed are still never passed (section 2 of the 1.5.6 file), and `--settings` and `--mode` are still only on the main command, not on `acp`.
- The answer to `initialize` is **the same as 1.5.7's, field for field, except `agentInfo.version`** (`1.5.8`; it appears in two places of the answer): `protocolVersion: 1`, `loadSession: true`, session capabilities `resume`, `close`, `load`, `list` and
  `additionalDirectories`, the four authentication methods, an `auth` capability with `logout`. What `ChatTracker` reads (`protocolVersion` equal to 1, `resume` among the session capabilities) is what 1.5.8 answered; VBear keeps none of the rest.
  (A test feeds an answer of this shape to the tracker.) `session/new` without a login answers `Authentication required`, as 1.5.7 did.
- So every protocol constant of `VERSIONS["1.5.8"]` is 1.5.7's, which are 1.5.3's; only the version and the hash table are its own (the path table is 1.5.7's, section 6).

## 3. The strings, the administrator places, and what 1.5.8 added to them

Two countings were made. The first is the one of the 1.5.7 file (an extraction that joins names that sit next to each other in the program in its own way); it was repeated for 1.5.8 and differs from 1.5.7's in exactly three lines. The second is a plain `strings -a` of
both executables, side by side, made for the administrator-control question only. **A count is compared only to say "the name is still there" or "it is a different number"**; neither counting can prove a list complete.

| Name in the program | 1.5.7 | 1.5.8 | What VBear does |
|---|---|---|---|
| `/etc/antigravity/admin_settings.json` | 1 | 1 | already in the source list (`etc/antigravity`, the whole folder); same for 1.5.8 |
| `admin_settings.json` (second counting) | 6 | 6 | the same |
| `/Library/Application Support/Antigravity` | 1 | 1 | already in the 1.5.6 list; **kept for 1.5.8** (the whole folder, an unconfirmed candidate: a Mac without that folder is not affected) |
| `com.google.antigravity` (first counting: 10; second counting: 14) | same | same | already in the source list (the managed-preferences domain, a candidate); same for 1.5.8 |
| `com.google.antigravity.companion`, `.dev`, `.insiders` | 1 each | 1 each | **still not added.** The same three longer names as in 1.5.7, next to the bundle identifiers of other applications; nothing shows that one is a managed-preferences domain of the command-line program. The source table holds one domain per version. **Open point** of the 1.5.7 file, unchanged |
| `Managed Preferences`, `CFPreferences` | 0 | 0 | nothing names them |
| `managed-settings`, `policy.json` | not in the extract | not in the extract | not added (nothing names them) |
| `AdminSettings` | 18 | 26 | see below |
| `MDM` | 12 | 15 | see below |
| `FetchAdminControls` | 263 | 265 | see below |
| `authControls` (a JSON field name) | 0 | 6 | see below |
| `GEMINI_INTERNAL_BYOM` | 1 | 2 | a name in the program's text of the same kind as the other `GEMINI_*` words; not passed to the process (section 5) |
| `mcp_config.json` | 30 | 31 | already refused (name); no new name |
| `.agents/hooks.json`, `.agents/agents`, `.agents/plugins`, `.agents/plugins.json`, `.agents/rules`, `.agents/skills`, `.agents/skills.json`, `.agents/teamwork`, `.agents/workflows` | 2, 2, 1, 1, 1, 6, 3, 606, 3 | the same names and counts | see section 4 |
| `GEMINI.md`, `AGENTS.md`, `hooks.json` | 55, 62, 41 | the same | already refused (names); unchanged |
| `session/cancel`, `session/load`, `session/prompt`, `session/request_permission`, `session/resume`, `session/update` | 1 each | the same | the methods VBear writes or reads; `session/load` is still never written |
| `allow_once`, `reject_once`, `allow_always` | 1, 1, 4 | the same | the option kinds; only the first two are ever chosen |
| `BypassSandbox` | 27 | 27 | still refused by VBear with no card |
| `ANTIGRAVITY_*`, `GEMINI_*` | see section 5 | no real addition | not passed: the process gets exactly six variables |

**What grew is what an administrator can control, not where it is read from.** The names that are new in 1.5.8 are symbol names of Google's administrator-controls package and one JSON section: an `authControls` section whose fields are `disableConsumerLogin`, `wifProvider`,
`gcpProjectId`, `gcpLocation` and `licenseType`; a switch that turns web fetching off; a switch that turns remote control off; a ceiling that an administrator can put on the permission preset (`applyPermissionPresetCeiling`); an error kind for an MDM failure; and a log line saying
the controls are applied "under Permissions V2". The path `/Library/Application Support/Antigravity/admin_settings.json` is now followed in the program's text by `authControls.licenseType`, which reads as: the new fields are read from **the same file**. Removed from the
program's text: `GetMcpAllowlist`, `IsMcpEnabled`, `TieredModelConfig.ToProto`.

Reading, and what follows for the table:

- There is **no new file path, no new managed-preferences domain and no new `ANTIGRAVITY_*` variable.** The sources are the same two folders, the same domain, and the controls the server hands over (`FetchAdminControls`, which is in 1.5.7 too, 263 times).
  So `AGY_SOURCES["1.5.8"]` is 1.5.7's list, which is 1.5.6's.
- VBear refuses the AGY chat when any listed local source exists, **whatever it holds**. A new field inside an existing source therefore needs no new entry: the file's presence already stops the chat, and VBear never reads the file's content to decide.
- **The residual that was already there is unchanged in kind.** The controls fetched from Google's servers for a signed-in account (`FetchAdminControls`) are not a place on this Mac's disk, so the administrator-source check cannot see them; this was true for 1.5.7 and is named in SECURITY-MODEL.
  1.5.8 can be told more things by them (the new switches and the ceiling), and VBear cannot know which. What VBear's own settings file asks of AGY (`toolPermission: request-review`, the terminal sandbox on, no non-workspace access) is a request that a server-side
  ceiling could only make stricter or refuse; a ceiling that **loosened** it is not something any text seen says AGY does, and not something this evidence could show.
- **Not verified:** that the strings list is complete (a name can be assembled at run time), what any of the new switches does when set, and how the permission-preset ceiling interacts with `toolPermission: request-review`. Only a signed-in run under an administrator's controls would show it.

## 4. Hooks and project settings: no new place

The built-in guide `skills/agy-customizations` (its `SKILL.md` and its six `docs/*.md` files) has the **same bytes in 1.5.8 as in 1.5.7**, which are the same as in 1.5.6, and the `.agents/*` names and counts of the program are the same. So VBear's lists (`workdir_forbidden`,
`forbidden_anywhere`, the protected names of the file tools, the twelve places of `home_hooks_state` and `ancestor_hooks_state`) are unchanged and apply to 1.5.8 as they are.

One built-in file has new bytes apart from the checksum: `skills/mcp-app-development/SKILL.md` (the document for the model about building MCP servers whose tools show an interface, new in 1.5.7). The writer compared it with the 1.5.7 copy. The changes are wording
("sandboxed" became "isolated" in a few sentences, and a section heading with it) and **one paragraph that is new: how to ship the server as a plugin**, under `~/.gemini/config/plugins/<name>/`, with a `plugin.json`, an `mcp_config.json`, a `bin/` folder for the server and an
`assets/` folder, and the variables `${PLUGIN_ROOT}` and `${PLUGIN_DATA}` for paths inside the plugin. Every one of these is already refused or never created by VBear: `config/plugins` is in `home_forbidden` of the chat folder (a plugin folder there stops the chat), a non-empty
`config/mcp_config.json` stops the chat, and the work folder and the home hook looks are unchanged. The file is a plain document (the ending `.md`), not a file that can run.

## 5. The environment

Unchanged. The chat gives AGY exactly six variables (`PATH USER LOGNAME LANG TMPDIR HOME`; `agent_sessions.agy_chat_env`), a whitelist, so no `ANTIGRAVITY_*` or `GEMINI_*` name can reach it. The names in 1.5.8's strings are the ones 1.5.7's strings have, with one more occurrence of
`GEMINI_INTERNAL_BYOM` (an internal name of the program's own text; it is not a variable VBear passes). `tests/test_p46_agy_chat_launch.py` and rule 14d hold every version to six variables.

## 6. AGY's own built-in folder: the same 64 paths, 42 files, 2 of them with new bytes

The folder a real 1.5.8 wrote has every file mode `0644` and **64 paths: 42 files and 22 folders**. Against the table of 1.5.7 (the same 64 paths, 42 files):

- **40 files have the same SHA-256** as 1.5.7's table (among them `keep.txt`, the empty file, `.manifest`, `plugins/swarm/plugin.json`, the swarm board's files including `hive.js` and `hive.css`, the seven files of `skills/agy-customizations`, and every other skill).
- **2 files differ**: `.checksum` (a line of the form `builtin:` and a hash, made by AGY over the folder, so it changes when any file does) and `skills/mcp-app-development/SKILL.md` (section 4).
- **Nothing was added, nothing disappeared, no mode changed, no new folder appeared.** The same 42 names, the same sizes and modes (apart from the two files above), and AGY's own `.manifest` (a list of 40 file names) is byte for byte 1.5.7's.

The 42 values are `builtin_sha256` of `VERSIONS["1.5.8"]`. Its `builtin_paths` are 1.5.7's (the same object's value: 64 paths); `builtin_runnable` is 1.5.3's, unchanged: the changed skill file ends in `.md`, no file of 1.5.8 has an ending that is new, and the runnable ones
(`hive.js`) have the bytes of 1.5.7 and are pinned like every other file. `skills/mcp-app-development/SKILL.md` and `.checksum` have a second value now (1.5.7's, 1.5.8's); either one passes at that path (ADR 0018), no other does.

**The path table belongs to the version about to start.** `agy_chat_env.builtin_table(version)` reads it per version, so a folder with `skills/mcp-app-development` is still refused when 1.5.6 is about to start and accepted when 1.5.7 or 1.5.8 is. A folder 1.5.7 wrote is
accepted for 1.5.8 and the reverse, because the paths are the same and the hashes are shared among the known versions at one path. Only the hashes are shared; the paths never are.

The folder outside `builtin` had these names, all of them in `home_created` already: `antigravity-cli`, `brain`, `conversation_summaries.db`, `conversations`, `crashes`, `implicit` (with one `.pb` file named by a UUID), `installation_id`,
`jetski_state.pbtxt`, `log` (with one log file), and `config` with `.migrated`, `config.json`, `mcp_config.json` and `projects`. Names AGY makes only after a prompt or a command were not produced by this run; nothing is claimed about them for 1.5.8.

## 7. What each table of VBear rests on

| Table | Entry | Evidence | Gap |
|---|---|---|---|
| `agy_chat_protocol.VERSIONS["1.5.8"]` constants (argv, six variables, settings, model, option kinds, session updates, usage fields, `announced_kinds`, `home_created`) | 1.5.7's (1.5.3's) | sections 2 and 3 (identical helps, the same methods and option kinds), section 6 (the names AGY made) | the shape of signed-in messages, the order of a tool call, the usage fields, and what is made after a command: **not shown**; the chat check shows them, and a message that does not fit is an anomaly or stops the chat |
| `builtin_paths` | 1.5.7's 64 | section 6 | a folder AGY 1.5.8 writes after a long use may hold more; that is refused by name until a run shows it |
| `builtin_runnable` | 1.5.3's | section 6: no new ending | none known |
| `builtin_sha256` | the 42 values of the folder a real 1.5.8 wrote | section 6 | as above |
| `admin_policy.AGY_SOURCES["1.5.8"]` | 1.5.6's, as 1.5.7's: `etc/antigravity`, `Library/Application Support/Antigravity`, domain `com.google.antigravity` | section 3 | the list is a reading of strings, not vendor documentation; the three longer `com.google.antigravity.*` names are an open point; the controls fetched from the server are not a place on disk |
| work folder, file tools, home hooks | unchanged | section 4 | rules the guide does not state; a change between the look and AGY's search |
| environment | six variables, unchanged | section 5 | none |

## 8. Not shown, on purpose

- Everything that needs a signed-in AGY: the answer of `session/new` (models, modes, config options), `session/set_model`, the permission requests and the options they offer, the tool calls and their order, `usage`, `session/cancel`,
  `session/resume`, whether AGY rewrites an older `builtin` folder when it starts after an update, and what the sandbox does. These are what `boundary_check --mode agy-chat` (and `--shared`) measure on the person's Mac.
- What the controls an administrator can set (section 3) do when they are set, by a file on this Mac or from the server: nothing in the repository, and nothing seen, tests them.
- The shared-folder part: the AGY employee still does not use the shared folder (ADR 0012, decision 7); nothing about 1.5.8 changes that.
- Whether the administrator-source list is complete (it is a reading of strings).
- What the changed skill does when AGY uses it (it is a document for the model; VBear's permission cards and sandbox are what limit what AGY may do, as for every other built-in skill).
