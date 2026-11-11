# AGY 1.5.5: compared with 1.5.3, and not added (v0.22.1)

A Mac whose AGY updated itself to 1.5.5 cannot chat, because VBear's AGY chat knows 1.5.3 only ([agy-1.5.3-chat.md](agy-1.5.3-chat.md)). On 2026-11-11 the installed
`agy` was compared, with static means only (`--version`, `--help`, `acp --help`, `strings`; nothing started, no login, no network, `HOME` set to an empty temporary
folder). The older 1.5.3 file is no longer on the Mac, so the 1.5.3 side is what the evidence above and the tables in `agy_chat_protocol.py` recorded; the file
`agy.<number>.old` that the updater left is 1.5.4 and was used as a second reference.

- Files: 1.5.5, 209824176 bytes, SHA-256 `42b591f206a868dd0b924d5b6b396638a108539367695a5dbe2f7dcfdbf4d6f3`; 1.5.4, 209477856 bytes, SHA-256
  `bfa89f0d8cbf1b6961395cc54ac5a75bc2776bc4f6a5e50dd91d3dd1ba076b03`.
- **The same as recorded for 1.5.3:** `agy --help` and `agy acp --help` list every flag the chat passes (`acp`, `--gemini-dir`, `--sandbox`, `--disable-telemetry`, `--add-dir`) and the
  ones the evidence names (`--app-data-dir`, `--dangerously-skip-permissions`, `--include-default-customizations`, `--process-per-session`, `--login`); the help
  of 1.5.4 and 1.5.5 is the same. The strings the 1.5.3 reading found are all there, with the same counts in 1.5.4 and 1.5.5: `/etc/antigravity/admin_settings.json`,
  `AdminSettings`, `AdminSettingsPath`, `com.google.antigravity`, the settings field names, `.agents/hooks.json`, the ACP method and update names, `allow_once`,
  `reject_once`, `BypassSandbox`, the usage field names. The `ANTIGRAVITY_*`/`GEMINI_*` names differ by one (`ANTIGRAVITY_DISABLE_EMBEDDED_RIPGREP`), which
  the chat's environment never passes. So the administrator-source list would be 1.5.3's.
- **Different: AGY's own built-in content.** The chat check pins the SHA-256 of every file AGY writes under `antigravity-cli/builtin` (`builtin_sha256` of the
  version table) and refuses the folder when a file does not match. These files are embedded in the executable as plain bytes. Reading them out of 1.5.4 reproduces
  the recorded 1.5.3 hash exactly for 12 files, which shows that the embedded bytes are the ones AGY writes. Reading them out of 1.5.5:
  - `skills/native_swarm/SKILL.md` is **different**: the embedded file has SHA-256 `25f6eb1e3b43a5589a776ce6e53b29896ef13bc6449716ee578ea09e95ef197f`; the table has
    `2e8009f09eff39c5e2658bb2e518159f1d403c3fd0548ef871bd225bb0d47b44`. The change is in the text: a link parameter `?tab=graph` became `&tab=graph`, and two lines about `auto_open=false` were added.
  - 11 other `SKILL.md` files (`agy-customizations`, `antigravity_guide`, `automation`, `migrate-agent-settings`, `migrate-workflows`, `permissioned-github`,
    `plugin`, `run-workflow`, `swarm_monitor`, `swarm_narrator`, `ui-plugin-navigation`) are byte for byte the recorded ones.
  - The other 28 files of the table (the documents under `docs` and `references`, `generative_ui/SKILL.md`, the swarm plugin and its board, the two READMEs, the logo,
    the empty `keep.txt`) could not be placed in the executable by this method, in 1.5.4 or in 1.5.5, so nothing is known about them from it. `.checksum` and `.manifest` are
    made by AGY when it writes the folder; their content cannot be read from the executable, and they very probably change with a changed file.
- **Why 1.5.5 was not added.** With one built-in file changed (and `.manifest` and `.checksum` unknown), a folder in which AGY 1.5.5 wrote its built-in files would not match the table
  (this assumes AGY rewrites the folder when its version changes, which a static reading cannot show). The next start would then be refused with
  「聊天用的 AGY 設定資料夾裡有 antigravity-cli/builtin/…，不是 VBear 放的…」, so adding `"1.5.5"` with 1.5.3's table could let a first chat start and make the next one fail, or fail at once.
  A new table can only come from a run of the real 1.5.5 that writes the folder (the hash of every file, nothing of its content, as the fifth real run of 1.5.3 did), and that is a run, not
  a static reading. `AGY_SOURCES`, `agy_chat_protocol.VERSIONS` and the AGY tests are therefore **unchanged** in v0.22.1: AGY 1.5.5 still answers 「不支援」 in VBear.
