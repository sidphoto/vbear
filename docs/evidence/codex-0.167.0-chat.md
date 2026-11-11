# Chat evidence: Codex 0.167.0

Why this file: a Mac that Codex updated itself to 0.167.0 could not chat (the screen said that 0.167.0 has no administrator-policy source list), because VBear
knew 0.160.0 and 0.163.0 only ([codex-0.163.0-chat.md](codex-0.163.0-chat.md)). What follows was compared on 2026-11-11 (v0.22.1), side by side with the
installed 0.163.0, **without logging in, without a chat, without a connection and without reading anything of the person's `~/.codex`**. What was run:
`--version`, `--help` of the commands VBear runs, `strings`, `codex features list` and `codex app-server generate-json-schema --out <folder>`. Every one of
them ran with `HOME` and `CODEX_HOME` set to an empty temporary folder. `generate-json-schema` writes the protocol's JSON Schema into that folder; it starts no
app server, makes no connection and needs no login (the evidence of 0.163.0 used the same command). No `app-server` was started, and no `codex login`,
`codex exec` or `codex sandbox` was run.

## 1. Binaries and the commands VBear runs

- `codex --version`: `codex-cli 0.167.0` and `codex-cli 0.163.0`. Both are the vendor installer's standalone releases, `bin/codex`:
  - 0.163.0, 249952688 bytes, SHA-256 `8813367285524ac798dd96d1b071aea30d58708c7226fd236cd275cf1cfdee31`;
  - 0.167.0, 270815376 bytes, SHA-256 `030316ecfbb41f4e7946e584b0063ef333b7a36cd312ba349f2f6869e39b62cc`.
- `--help` of `codex login`, `codex login status`, `codex exec`, `codex mcp` and `codex app-server generate-json-schema`: **identical**.
  `codex --help` differs in two lines (the text of `agents`, and a new experimental command `migrate-nfs-db`); VBear runs neither.
- `codex app-server --help` differs only by **four new options**: `--startup-sign-out`, `--print-startup-config`, `--startup-client-info`
  and `--cloud-skills-snapshot`. Every option VBear passes (`--listen stdio://`, `-c key=value`, `--disable <feature>`) and every other option is unchanged.
  VBear passes none of the four new ones.
- The twelve `-c key=value` settings of the chat, and the fixed login lines, were also given to `codex features list` of both versions (it loads the
  configuration and prints the features): both accepted them (exit code 0).

## 2. Administrator sources

The method of the Claude Code 2.1.318 file, on `strings -a` of both binaries. Both name **the same places**:

- the system layer `/etc/codex/config.toml`, `/etc/codex/requirements.toml` and `/etc/codex/managed_config.toml` (so the folder `/etc/codex`);
- the managed preferences domain `com.openai.codex` (`config_toml_base64`, `requirements_toml_base64` and the legacy `managed_config.toml` from it; the same
  layer names, "MDM", "system", "enterprise-managed", "legacy managed_config.toml", in both);
- the cloud bundle cache `cloud-config-bundle-cache.json`, which lives under `CODEX_HOME` (VBear's chat uses its own `CODEX_HOME`, as for 0.163.0).

The list of path-like strings (`/etc`, `/Library`, `~/`, `.codex/`, `.agents/`, and the like) is the same in both: 99 entries each, and the entries that
differ are only where a neighbouring string was glued on by the compiler. There is no new system or managed place. What is new in 0.167.0 is
text about managed requirements (for example "Managed configuration sign-in is required", "may only be configured in local managed requirements"), which
belong to the places above. So `admin_policy.CODEX_SOURCES["0.167.0"]` is the 0.160.0 / 0.163.0 list: the folder `/etc/codex` and the domain `com.openai.codex`.

## 3. Features VBear disables

`codex features list` of both versions (stage and effective state): the 20 features the chat disables (`apps`, `plugins`, `remote_plugin`, `hooks`,
`shell_snapshot`, `browser_use`, `browser_use_external`, `computer_use`, `image_generation`, `memories`, `multi_agent`, `skill_mcp_dependency_install`,
`tool_suggest`, `view_image`, `in_app_browser`, `goals`, `realtime_conversation`, `sleep_tool`, `workspace_dependencies`, `worktrees`) are all still known, and
`--disable` of each is accepted (an unknown name is refused with `Unknown feature flag`; these are not).

**Two of them changed stage: `realtime_conversation` and `worktrees` went from `stable` to `removed`.** A removed feature has no switch any more; the list shows its
effective state as true. `--disable` of them still exits with 0 and no longer changes anything. What the strings show about them: `worktrees` is the TUI's
"task-tools" server and the `--worktree` option of the terminal program (`create_worktree`, `list_worktrees`; in 0.163.0 the same text said the feature had to be
enabled with `--enable worktrees`), and `realtime_conversation` is driven by the client's `thread/realtime/*` requests. VBear's chat runs `app-server` (not the TUI)
and never sends a realtime request, so neither is something the model can reach through VBear's chat; **but VBear can no longer turn them off, and this is a
change in a setting VBear passes**. The chat check is what shows whether a chat still behaves as the settings say.

Features that are new or became stable and enabled by default in 0.167.0 (so on, and not disabled by VBear): `bedrock_setup_wizard`, `deferred_tool_world_state`,
`incremental_tools`, `mcp_oauth_refresh_coordination`, `plugin_discovery_prefetch`, `prediction_preserve_parent_tools`, `reasoning_effort_override`. None of them is a
tool, a login, a plugin or a network surface that `strings` shows to be new; `plugin_discovery_prefetch` belongs to plugins, which stay disabled. This is a reading of
names, not a proof.

## 4. The app-server protocol

`codex app-server generate-json-schema --out <folder>` of both versions (the non-experimental output; VBear sends `experimentalApi: false`), compared
as data (the JSON of `codex_app_server_protocol.v2.schemas.json` and `codex_app_server_protocol.schemas.json`, definition by definition):

- **Requests the client sends:** 0.167.0 adds one (`feedback/save`) and removes none. `initialize`, `initialized`, `thread/start`, `thread/resume`, `thread/delete`,
  `turn/start`, `turn/steer`, `turn/interrupt` and `mcpServerStatus/list` have the same params; the only things added to any of them are optional.
- **Requests the server sends:** the same list, none added or removed (`item/commandExecution/requestApproval`, `item/fileChange/requestApproval` and the ones
  VBear refuses are all there, with the same names).
- **Notifications:** one new method (`thread/section/changed`, a sidebar grouping that a client causes by editing a section) and none removed. VBear treats a
  notification it does not know as an anomaly, not as a violation.
- **Definitions:** none removed; 14 added (account session types, `FeedbackSave*`, `ModelProviderError`, `OtelRequirements` and related, `ThreadSectionChangedNotification`,
  `ApplicationStorageRequirements`, `ImageGenerationInputImage`). Fields added to existing ones: `InitializeCapabilities.requiredHumanApproval`,
  `AdditionalContextEntry.name`, `HooksListParams.threadId`, `NetworkRequirements.reviewDomains`, `ProcessExitedNotification.outputDrainTimedOut`,
  `ThreadUsage.nativeUsageUsdMicros`, `McpServerStatus.toolListMeta`, `HookMetadata.environmentId`, `ConfigRequirements.otel`, `ApplicationRequirements.storage`, `Account`
  (a `gcp` type, `workspaceName`), `HookEventName` (`preModelRequest`, `postModelRequest`), `PlanType`, `CodexErrorInfo` (`modelNotFound`, `policyCapacityUnavailable`). None
  of these is in a message VBear reads or writes in a chat. Changed shapes: `ThreadItem` `imageGeneration` (`result` is no longer required, `inputImages` and `generationId`
  added; VBear stops a chat on any item kind that is not in its allowed list, which does not include it), `UserInput` `audio` and `ContentItem` `input_audio` (a chat sends only text),
  `ReviewDelivery` lost the value `detached` (VBear uses no review request).
- **Approvals:** `CommandExecutionApprovalKind` has a new value, `humanCommand` ("a managed checkpoint requiring a fresh human decision... Requires the
  `requiredHumanApproval` initialize capability"). VBear's `initialize` carries `capabilities: {"experimentalApi": false}` only, so this kind is not asked for; and if one came, VBear
  answers any kind that is not `command` with a decline card (`_command_request`). The decision values (`accept`, `decline`, `cancel` and the others) did not change.
- No list of `required` members changed in any definition other than the `imageGeneration` and `audio` shapes above.

## 5. Not done, and what is still open

- No real recording of 0.167.0 was made: the fixtures of `tests/fixtures/codex-chat` are 0.163.0's, so `ccp.VERSIONS["0.167.0"]` is `0.163.0`'s constants with another
  version string. That the model's behaviour, the order of messages, the files Codex makes in `CODEX_HOME` and the answers to `turn/steer` or `thread/delete` are
  the same is **assumed**, and is what `boundary_check --mode codex-chat` shows on a real Mac.
- The vendor's documentation was not read (no network); `strings` shows names, not behaviour.
- 0.167.0 is **not** in `CODEX_CHAT_VERIFIED_VERSIONS` or any verified list: it chats only after `python3 -m vbear.boundary_check --mode codex-chat` (the
  「聊天安全檢查」 button) passed on the Mac for that version. Codex's review (`codex_constants`) was not touched and still knows 0.160.0 only.
