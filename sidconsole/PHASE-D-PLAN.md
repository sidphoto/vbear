# Phase D｜SID Armory 規劃草案

狀態：**D-D1～D-D5 已由產品負責人核准（2026-09-24，全部採建議）｜範圍凍結為 Phase D1；尚未開工**
前置：Phase C Gate 7 已由使用者人工宣告通過（2026-09-24，見 `.local/runs/20260924-gate7-result.md`）；Phase C 尚未 commit

## 0. 已核准產品裁決（2026-09-24）

產品負責人回覆「D1~5照建議」，以下凍結為 Phase D1 契約：

| 裁決 | 結論 |
|---|---|
| D-D1 | 不做 External（Git/URL）Import；需先有網路存取安全審查，另立階段 |
| D-D2 | Equipped 反向索引每次即時計算，不落地第二份資料 |
| D-D3 | Load Policy 屬 Profile 層級，但涉及 schema breaking change，**延後**，Phase D1 不動 `agent_profiles.json` 格式 |
| D-D4 | Skill Boundary Scanner 獨立為 Phase D3，不納入 D1 |
| D-D5 | 不新增 Inventory Contract 欄位；只可視化現有 `SkillRecord` 欄位 |

Phase D1 範圍即 §5：唯讀 Armory 四態總覽＋Equipped 反向查詢。§6 排除項全數維持。
本文件僅供討論與後續產品裁決，**不得作為開工依據**；動工前需比照 Phase C 走完
「產品裁決 → 契約凍結 → MCODE 實作 → 獨立複審 → 協調者驗證 → Gate 人工驗收」流程。

## 1. 目標

依 `.local/prd/SID-CONSOLE-CONTEXT-GOVERNANCE-PLAN.md` §7–12，把 Skill
管理獨立成「SID Armory」，讓使用者能看懂、管理並（未來）掛載技能，同時
維持全專案最重要的誠信邊界：

> **Installed ≠ Loaded；Equipped ≠ Loaded。**

Phase D 只做**技能安裝狀態管理**，不做 Effective Context 注入、不做
Policy Compiler、不啟動任何 Agent Session。

## 2. 現有基礎（唯讀，可直接複用）

- `sidconsole/model.py` 的 `SkillRecord`：已有 `skill_id`、`scope`、
  `activation`（`ACT_ACTIVE`/`ACT_DISABLED`/`ACT_SUPERSEDED`/
  `ACT_NOT_INSTALLED`/`ACT_ARCHIVED`/`ACT_NOT_LOADED`/`ACT_UNKNOWN`）、
  `origin_package`、`duplicate_of` 等欄位——這組 activation 狀態機
  已經很接近 PRD §7 的 `Available → Installed → Equipped → Loaded`，
  但語意不完全對齊，需要先做**名詞映射**而非重新發明。
- `sidconsole/scan/{claude,codex,shared}.py`：已掃描 Official（plugin
  cache）、Project、Personal（user skills）、Community（`shared.py` 對接
  `~/.agents/skills` 的 `.skill-lock.json`）四種來源，對應 PRD §8 的
  Official/Project/Personal/Community 四類，只缺 **External（Git/URL
  Import）**。
- `sidconsole/annotations.py`：已有使用者自訂別名、標籤、備註的
  fail-closed 儲存模式（`MAX_ALIASES=5`、`MAX_TAGS=12`、
  `MAX_ENTRIES=5000`），Phase D 的 Inventory Contract 可直接沿用
  同一套儲存慣例（0700/0600、flock、原子寫入）。
- `sidconsole/agent_profiles.py`（Phase C 剛完成）：`equipped_skill_ids`
  欄位已經是「Profile 引用哪些 skill_id」的唯讀清單，Phase D 若要讓
  Equipped 狀態反映到 Skill 本身，這是唯一該讀寫串接的既有資料源，
  不應該重複造一份 equipped 清單。

## 3. 語意映射（需要產品裁決）

| PRD §7 狀態 | 現有 `model.py` 概念 | 落差 |
|---|---|---|
| Available | `ACT_NOT_INSTALLED`（marketplace 副本） | 已存在，直接沿用 |
| Installed | `ACT_ACTIVE` / `ACT_DISABLED` / `ACT_SUPERSEDED` | 「已安裝」目前混在多個 activation 值裡，需要衍生一個布林視圖，不建議改動既有 enum（會動到現有測試與 UI 文案） |
| Equipped | `AgentProfile.equipped_skill_ids`（Phase C） | 已存在但只有「Profile → skill_id」單向引用，沒有「skill_id → 有哪些 Profile equip 了它」的反向索引 |
| Loaded | `scan/usage.py` 的執行觀察（`SkillRecord` 的使用紀錄） | 已存在，且已明確標示為 `RUNTIME` 來源，不是本階段的痛點 |

**核心決策**：Phase D 不改 `model.py` 既有 enum，改用一層薄的「Armory 視圖」
（唯讀衍生，不落地新 schema）把 `SkillRecord.activation` + `AgentProfile`
的 equipped 引用組合成 PRD 的四態顯示，避免破壞 Phase A/B/C 已測過的
`activation` 契約。

## 4. 待產品裁決（比照 Phase C 的 C-D1～C-D5 模式）

### D-D1：External（Git/URL Import）是否納入 Phase D 範圍

PRD §8 列了 External 來源，但本機環境刻意零第三方相依、零網路寫入
（README 明載「後端零第三方相依」）。Git clone / URL fetch 需要對外連線，
與現有安全模型（唯讀掃描本機已存在的檔案）性質不同。

**建議**：Phase D **不做** External Import，只做 Official/Project/
Personal/Community 四類既有來源的可視化與管理。Import 留到獨立的
Phase D2 或更後面，需要先補一份網路存取的安全審查。

### D-D2：Installed↔Equipped 反向索引存哪裡

`AgentProfile.equipped_skill_ids` 已經是唯一真實來源。反向索引
（某個 skill 被哪些 Profile equip）是否要落地成獨立檔案，還是每次
API 呼叫時即時掃描所有 profiles 算出來？

**建議**：即時計算，不落地。理由：Profile 數量上限 500（`MAX_PROFILES`），
掃描成本可忽略；落地索引會產生第二份真相來源，需要額外同步邏輯，
違反「Installed ≠ Loaded」這類契約最怕的「兩份資料互相漂移」風險。

### D-D3：Load Policy（Auto/Always/Manual/Disabled）的儲存位置

PRD §10 的四種載入方式，是 Skill 本身的屬性（掃描結果的一部分）還是
Profile 的設定（每個 Profile 對同一 skill 可以有不同 Load Policy）？

**建議**：屬於 Profile 層級，不是 Skill 層級——同一個 skill 被
Profile A equip 可能要 `Auto`，被 Profile B equip 可能要 `Manual`。
存放位置：`AgentProfile.equipped_skill_ids` 從純字串陣列升級為
`{skill_id, load_policy}` 物件陣列。**這是 Schema Breaking Change**，
需要 migration 或版本欄位，必須在動工前明確裁決，且需要 Phase C
的 `agent_profiles.json` 已有真實資料時做好回溯相容。

### D-D4：Skill Boundary Scanner（PRD §12）是否納入 Phase D

掃描 Skill 內容找跨層洩漏（例如技能檔案裡寫死 `Always use pnpm`）。
這需要對已抓取的 skill body 做關鍵字/語意比對，屬於**內容分析**而非
單純狀態管理，複雜度和 Phase D 的其他項目不對稱。

**建議**：獨立成 Phase D3，不與 D1（可視化）/D2（Equipped 管理）
綁在一起，避免範圍蔓延。

### D-D5：Skill Inventory Contract（PRD §9）的欄位是否全部實作

PRD §9 列了 `Content Hash`、`License`、`Estimated Context`、
`Network Requirement`、`Filesystem Requirement` 等欄位，目前
`SkillRecord` 都沒有。這些多數需要解析 skill 內容才能填（例如掃描
腳本判斷 Network Requirement），成本不低。

**建議**：Phase D 先只做 UI 可視化現有欄位（`skill_id`/`name`/
`scope`/`activation`/`origin_package`），新欄位留待有實際需求時
再逐項評估，不要為了填滿契約表格而做臆測性欄位。

## 5. 建議範圍（Phase D1，若上述裁決都採建議值）

1. **唯讀 Armory 總覽頁**：依現有 `SkillRecord` 資料，用 PRD 四態
   語意重新分類顯示（Available/Installed/Equipped/Loaded），沿用
   Phase C 的誠實揭露模式（每個狀態旁註明依據來源）。
2. **Equipped 反向查詢**：某個 skill 詳情頁顯示「目前被哪些
   Agent Profile equip」，唯讀連結到 Phase C 的 Agent Profile 詳情。
3. **不做**：Import、Load Policy 細分、Boundary Scanner、Install/
   Uninstall 操作（掃描到的技能本來就是唯讀來源，Phase D1 不新增
   寫入外部技能目錄的任何操作）。

## 6. 明確排除（Phase D1）

- 修改任何 skill 檔案內容
- Git/URL Import
- Load Policy 落地（等 D-D3 裁決）
- Boundary Scanner（獨立為 D3）
- Effective Context 注入、Policy Compiler（Phase E 範圍）
- 對 `~/.codex`、`~/.claude`、第三方 marketplace cache 的任何寫入

## 7. 執行前置條件

1. ~~Phase C Gate 7 人工驗收通過~~（2026-09-24 完成）
2. Phase C 變更 commit/push（待使用者授權）
3. ~~產品負責人對 D-D1～D-D5 逐項裁決~~（2026-09-24 全部採建議）
4. 依 `PHASE-C-AGENT-MODEL-ROUTING.md` 同一套分工：MCODE 主力 coding，
   Claude 獨立複審，Codex 依 trigger 啟動，AGY 負責瀏覽器 QA
   （本輪 AGY CLI 曾卡住，下次啟動前建議先做一次獨立 smoke test）

**在完成上述四項前置條件之前，不開始任何 Phase D 產品碼撰寫。**
