# AGY 1.5.3, chat mode

**Status: the evidence the design rests on; not yet boundary evidence.** The chat check
`python3 -m vbear.boundary_check --mode agy-chat` is what lets a version chat, and its result is recorded in
`agy-chat-verified.json` on each Mac, never here. Until a version has passed it, no AGY chat starts. Everything below comes from a
short investigation of 2026-11-09 with the local `agy` 1.5.3 (`agy --version` prints `1.5.3` and nothing else), done with a small
ACP client of the investigator's own, in a temporary folder that was deleted afterwards (about US$0.15 of estimated spend; the model
calls ran on the person's Google plan, not on paid credits), plus one zero-cost static read of the installed executable (section 8).
**The investigation's raw messages were not kept.** The fixtures of `tests/fixtures/agy-chat/` are therefore synthetic: they are built
from the facts below and from the public ACP v1 message formats, and each one says so on its first line. The code and its tests run
only a stand-in `agy` (`tests/fake_agy_acp.py`); the real one is run only by the check and by a person.

Facts are marked **measured** (seen on the real 1.5.3), **documented** (the vendor's documentation or changelog, not tried),
**format** (ACP v1's public shape, not seen on this version) or **unconfirmed**. Section 11 lists what the first real run must confirm.

## 1. Why the chat uses `agy acp`, its own settings folder and `--sandbox`

| Interface | Long-lived, many turns | Asks the host before a tool | Result |
|---|---|---|---|
| `agy acp` (ACP v1, one JSON-RPC message per line on stdio) | yes: many `session/prompt` in one process; a new process uses `session/resume` | yes: the agent sends `session/request_permission` and the host answers with one of the offered options | used |
| `agy -p` with `--input-format` / `--output-format stream-json` (headless) | one process per turn | no: the documentation and the changelog say a headless run decides by the settings file's policy | not used: only allow-all or deny-all |

`agy acp --help` lists `--gemini-dir`, `--app-data-dir`, `--sandbox`, `--add-dir`, `--dangerously-skip-permissions`,
`--disable-telemetry`, `--include-default-customizations`, `--process-per-session` and `--login` (**measured**). **`--settings` and
`--mode` exist only on the main command, not on `acp`**: the settings of an ACP process can come only from
`<gemini-dir>/antigravity-cli/settings.json`. The chat passes exactly `acp --gemini-dir <state>/agy-chat-home --sandbox --disable-telemetry`
and, for an employee who has the shared folder, `--add-dir <shared folder>`. `--disable-telemetry` was not used in the investigation
(**unconfirmed**; the chat check shows it starts, or the switch is taken out of the table). None of the other switches is ever passed.

`initialize` is answered with `loadSession: true`, session capabilities that include `resume`, `close`, `load`, `list` and
`additionalDirectories`, a plan-name field and a list of four authentication methods (**measured**; where each sits in the answer is
**format**). VBear keeps none of the plan name or the methods. `session/new` is answered with a model list (13 models, the default one
not the chat's), modes `default`, `accept-edits` and `plan` (ACP has no `auto`), config options for the model, the thinking level
and the mode, and the plan name again (**measured**; the exact shape of the model list is **format**).

## 2. Settings, and asking every time

VBear's own folder holds `antigravity-cli/settings.json`:

```json
{"toolPermission":"request-review","allowNonWorkspaceAccess":false,"enableTerminalSandbox":true,"useG1Credits":false,"permissions":{"allow":[],"ask":[],"deny":[]}}
```

The investigation used the same file without `useG1Credits` (**measured**), together with `--sandbox`. The key `useG1Credits` (paid
credits, off by default) was found by the static read of section 8 as a settings field name; that it belongs to this settings file is
**unconfirmed**, and the chat check must show a normal chat with it, or it is taken out of the table.

With these settings, in a work folder with an outside decoy folder, one turn asked for five things and VBear allowed each:

| Action | Asked? | Result |
|---|---|---|
| File tool creates a file in the work folder | yes (`kind: edit`, with a diff) | created |
| `ls -la` | yes (`kind: execute`) | ran |
| File tool reads a file outside the work folder | yes (`kind: read`) | read |
| `echo ... > <outside folder>/out.txt` | yes | **the sandbox stopped it**: `operation not permitted`, exit code 1, no file |
| File tool creates a file outside the work folder | yes | **created** (`allowNonWorkspaceAccess: false` did not stop an allowed write) |

A read inside the work folder is, by the documentation, allowed without asking ("auto-allowed in workspace"); the investigation did not
try it alone (**documented, unconfirmed**). A command that fails still ends its tool call as `completed`; the exit code is in
`rawOutput.exit_code` (**measured**).

## 3. Permission requests and the options

`session/request_permission` carries `options` of exactly two entries (**measured**):

| optionId | kind |
|---|---|
| `allow` | `allow_once` |
| `deny` | `reject_once` |

There is no "allow always" option in this version. The chat answers only with the option of kind `allow_once` or the one of kind
`reject_once` (by kind, never by position or id), and never with an option of any other kind; a list that does not hold exactly one of
each is refused. The request's `toolCall` has `kind`, `title`, `rawInput`, `locations` and `content` (**measured**); the raw input of a
command has `CommandLine`, that of a file tool has `Path` and `Content`, and `locations` has the path again (**measured**). The
wrapper of the answer (`{"outcome": {"outcome": "selected", "optionId": ...}}`, and `{"outcome": {"outcome": "cancelled"}}`) is
**format**. VBear sees the whole command and the paths before any card is shown.

The answer can only choose an option. **It cannot carry a changed input.** A person's change is therefore a refusal followed, when the
turn ends, by a new message that asks for the changed thing; AGY then asks again. The changelog of 1.5.0 says that a second prompt
sent in the middle of a turn can steer it; that was not tried, and the chat does not use it. A refusal works: the call ended as
`failed`, the file was not created and the model did not retry (**measured**).

## 4. The sandbox: commands yes, file tools no

`--sandbox` is Seatbelt on macOS (the vendor's sandbox page). With every request allowed (**measured**):

- writing outside the work folder from a command: stopped;
- reading outside the work folder from a command (`cat`): stopped (exit code 1, a sandbox error);
- reaching the network from a command (`curl`): stopped (exit code 6).

**The sandbox does not leave itself.** After a command was stopped, the tool output told the model that it could set `BypassSandbox`
to true and run again, which asks the person again. When asked to do so, the model sent a new permission request whose raw input was
`{"BypassSandbox": true, "CommandLine": ...}`. **VBear therefore sees "this one runs outside the sandbox" before a card is built**,
and refuses it itself, with no card, for any value that is not `false`. (Codex, by comparison, reruns outside its sandbox without
asking again.)

The documented writable range of the sandbox is the project folder, the temporary folder and the usual build caches, so more than the
work folder; `/tmp` was not tried (**unconfirmed**). **The file tools are not in the sandbox**: once allowed, they wrote outside
the work folder (section 2). VBear judges their paths itself, as it does for Claude Code: outside the work folder (or the shared
folder the employee has), under `.git`, `.agents`, `.agent`, `.gemini`, `.codex` or `.claude` at any depth, a file named `GEMINI.md`
or `AGENTS.md`, a file with another hard link, or content that does not fit a card: refused with no card. A file tool's path is in
`rawInput.Path` and in `locations`.

## 5. How much of the person's own AGY setup is read

- `--gemini-dir <new folder>` makes AGY create a fresh `config/` (its `config.json` lists only a built-in plugin; its `mcp_config.json`
  is empty) and a fresh `antigravity-cli/` (conversations, logs, built-in skills) there. **The sign-in still works**: it is not under
  the gemini folder. Pointing `HOME` at an empty folder instead gave `Authentication required`: the sign-in follows `HOME` (how it is
  stored was not looked at). The chat therefore keeps the person's real `HOME` and does not ask for a second sign-in.
- **The skills in the person's home folder are still loaded**, with the person's own gemini folder or VBear's, and also with
  `--include-default-customizations=false`. The command list the agent reported shrank with VBear's folder, but what remained still held
  skills that exist only in the person's home folder (the number is not recorded here). The decision of 2026-11-09 is to accept this and
  to say so on the screen. A skill is text for the model, not a permission: every command and file change still asks, and commands
  still run in the sandbox.
- MCP: VBear passes `mcpServers: []` with an empty `mcp_config.json`; no MCP call or notification was seen. That nothing else
  (an import of another tool's settings) loads one was not proven.
- Not verified: whether a `GEMINI.md` or `AGENTS.md` in the home folder is read; whether the permissions of the AGY desktop application,
  which the documentation says the command line merges, still merge with another gemini folder; whether VBear's `settings.json` is read at
  all (the investigation's behaviour is the same as the default `request-review`; the chat check's `settings` step uses
  `"toolPermission": "strict"` in another temporary folder to prove it is read); the full list of administrator policy.

## 6. Many turns, resuming, stopping

- One process can take many `session/prompt` (**measured**). A new process takes `session/resume` and goes on without replaying
  anything (the second turn read 14,686 cached tokens). `session/load` replays earlier tool calls as updates and then remembers them;
  the chat does not use it. The conversation is kept as a database file under the gemini folder
  (`antigravity-cli/conversations/`).
- **After every `session/new`, `session/resume` and `session/load`, `session/set_model {"modelId": "gemini-3.8-flash-high"}` has to be
  sent again** (the answer is `{}`); otherwise the default model of the list is used.
- `session/cancel` is answered at once with `stopReason: "cancelled"` and a `usage` (**measured**). The model was still thinking when it
  was sent, so stopping a command that was already running was not observed (**unconfirmed**). The documentation says that cancelling
  ends tool calls in progress and drops requests that have no answer.

## 7. Usage and what a turn is counted as

`session/prompt` is answered with `usage: {inputTokens, outputTokens, cachedReadTokens, cachedWriteTokens, thoughtTokens,
totalTokens}` for that one turn (not cumulative; also on a cancelled turn). **`totalTokens` = `inputTokens` + `cachedReadTokens` +
`outputTokens`** (thought tokens are inside the output tokens). There is no amount of money, no `usage_update` and no use of the plan,
and nothing at all while a turn runs (**measured**). The first turn of a session is large (a system prompt and the skill list: eighty to
a hundred thousand tokens in the investigation's five turns). The five turns came to about US$0.08 at reference prices; nothing was charged.

VBear counts a turn as `totalTokens` / 1,000,000 x US$1.00, rounded up to the cent, at least US$0.01 (the rule of the Codex chat,
ADR 0005; one function serves both) and shows it as an estimate. When `totalTokens` is not a whole number in range, is missing, or
does not equal the sum of the three, the turn is counted at its cap. Because AGY says nothing during a turn, the per-turn cap can only be
checked before a turn starts, and one turn may cost more than the cap.

## 8. Administrator policy and what a static read of the program shows

On 2026-11-09 the planner ran `strings` on the installed `agy` executable (a regular file of about 200 MB), which executes nothing and
reads none of the person's settings. Names that appear in it:

- administrator settings: `/etc/antigravity/admin_settings.json` in full; also `AdminSettings`, `AdminSettingsPath` and the name
  `com.google.antigravity` (whether it is a macOS managed-preferences domain was not established);
- settings fields (as `json:"..."` names): `toolPermission`, `allowNonWorkspaceAccess`, `enableTerminalSandbox`, `permissions`,
  `permissions_v2`, `useG1Credits` (whether they are in one structure was not established);
- places read: `.gemini/config/` (`config.json`, `mcp_config.json`, `hooks.json`, `skills/`, `workflows/`, `global_workflows/`,
  `plugins/`, `projects/`), `.gemini/GEMINI.md`, `.gemini/settings.json`, `.gemini/antigravity-cli/settings.json`, **`.agents/hooks.json`**,
  `.agents/skills/`, `.agents/skills.json`, `.agents/workflows/`, `.agents/agents/`, `GEMINI.md`, `AGENTS.md`;
- environment variables: `ANTIGRAVITY_GEMINI_DIR`, `ANTIGRAVITY_APP_DATA_DIR`, **`ANTIGRAVITY_PERM_GRANTS`** (it looks like a way to
  grant permissions through the environment; its use is unknown) and others.

What the design takes from it (all of it fail-closed, none of it proven): the chat does not start when `/etc/antigravity` or the managed
preference exists; hooks (commands AGY runs by itself) have a home-folder place (`~/.agents/hooks.json`) and a project place, so the chat
does not start when the first exists (only `lstat`; its content is never read) and when a work folder holds `.agents`, `.agent`,
`.gemini`, `GEMINI.md` or `AGENTS.md`; the process environment is exactly six variables and passes no `ANTIGRAVITY_*`, `GEMINI_*` or
`GOOGLE_*`. The list is a reading of strings, not vendor documentation.

## 9. MCODE 0.5.2: why this version has no chat for it

The same investigation looked at MCODE 0.5.2 (`mcode acp`, ACP v1) and found that it cannot be run the way the chat needs (general
facts only):

- Its "Ask" mode does not ask before writing a file inside the work folder, running `ls`, or reading a file outside the work folder; a
  later process, resuming the session, did not ask before writing outside either. The reason is unknown.
- It has no sandbox: writes outside the work folder succeeded once allowed.
- Its settings and sign-in live in `$HOME/.minimax`; `acp` has no switch for another settings folder, and another `HOME` means signing in
  again. A fresh `HOME` also gets a line added to its shell start-up files.
- Switching the permission mode through ACP is stored as a global setting, so trying it changes the person's own configuration.
- It reports `cost.amount` as 0 whatever the model, and no per-turn token count; only the size of the context.

MCODE keeps ADR 0002's rule (a full-mode terminal only). A new version gets the same checks before anything is reconsidered.

## 10. What was built

*(P46-6 completes this section; P46-1 contributes the first item.)*

1. **P46-1** `vbear/runtime/agy_chat_protocol.py`: the version table (`VERSIONS["1.5.3"]`: argv, environment names, settings, model,
   kinds, option kinds, usage fields, the names that may not be in the settings folder or at the top of a work folder), the lines VBear
   writes, `answer_line` (only "allow once" / "reject once" / cancelled), `judge_file_change` and `judge_read`, the tracker that
   turns what the agent prints into facts (a request becomes a card, a refusal or VBear's own yes; a tool that ran without a yes, a read
   outside the work folder, another mode or another session stops the chat), and the estimate shared with Codex. `tests/fake_agy_acp.py`
   plays the synthetic scripts. Rule 14a-14c of `tests/test_autonomy_guard.py`.

## 11. What the first real run of `--mode agy-chat` must confirm

*(P46-6 fills in the result.)* The code reads every field below as written; a field that is not as written is an anomaly or stops the
chat, never a guess. These are the **unconfirmed** points and the **format** fields on which the synthetic fixtures rest:

- where `initialize` puts the protocol version (`protocolVersion`) and the capabilities (`agentCapabilities.sessionCapabilities.resume`,
  `agentCapabilities.loadSession`);
- that `session/new` answers `sessionId` as a UUID, `modes.currentModeId` as `default` and the models as
  `models.availableModels[].modelId`; that `session/resume` answers without a session id or with the same one;
- that `systemPrompt.append` in `_meta.antigravity` of `session/new` and `session/resume` is applied (the check asks for a random code word at
  the start of the reply);
- the shape of `session/update` (`sessionUpdate`, `content.text` of a message chunk, `toolCallId`, `kind`, `status`, `rawInput`,
  `rawOutput.exit_code`, `locations[].path`, `content` blocks of type `diff` with `path`, `oldText`, `newText`); that the tool call's
  status is `pending` until it runs; that a read inside the work folder is not asked about; that a search names no path;
- the shape of the error answers (`Authentication required` when not signed in; the error when a session to resume is not found);
- that the file tools name the same path in `rawInput.Path` and `locations`, and that a delete or a move uses the same fields;
- that a request to leave the sandbox uses the key `BypassSandbox` in the raw input, as measured, and what a tool of kind `fetch`,
  `think` or `other` looks like (a request, or nothing);
- that the answer wrapper is `{"outcome": {"outcome": "selected", "optionId": ...}}`;
- that `--disable-telemetry` starts and that `useG1Credits` in the settings does not stop a normal chat; that `--add-dir` makes the shared
  folder writable by the sandbox; that `/tmp` is or is not writable; that the six environment variables are enough to start and to stay
  signed in; that AGY creates none of the names that may not be in its settings folder; that no process of its own is left behind;
- that stopping a turn in the middle of a running command ends the command.
