# Phase C｜Agent Builder 實作計畫

狀態：**Decision Draft｜等待五項產品裁決後才能開始 coding**

基準：`main` / `26384c9` 之後

前置：Phase B 完成；Gate 6 已由使用者裁決 PASS；GitHub Issue #1 已關閉

Agent／model routing 的權威規則：[`PHASE-C-AGENT-MODEL-ROUTING.md`](PHASE-C-AGENT-MODEL-ROUTING.md)

## 1. 目標

讓使用者在 SID Console 內建立可重用的 Agent Profile，清楚分開四個維度：

1. **Profession**：工作方式／職業模板
2. **Model**：使用的工具與模型設定
3. **Skill Loadout**：此 Profile 裝備哪些技能
4. **Permissions**：期望允許或禁止的操作

Phase C 只建立和管理設定，不啟動 Agent、不編譯 Effective Context，也不宣稱設定已經影響執行中的 session。

## 2. 語意契約

### 2.1 名詞

| 名詞 | 意義 |
|---|---|
| `AgentRole` | 從 Claude／Codex 等來源掃描出的既有角色或 CLI 設定；唯讀來源資料 |
| `AgentProfile` | 使用者在 SID Console 組裝並儲存的設定；Phase C 新增 |
| Profession | AgentProfile 引用的工作方式模板 |
| Equipped | 技能 ID 已列入 Profile 的 loadout |
| Loaded | 技能內容已進入某次 session 的 Effective Context；Phase C 不產生此狀態 |
| Permission Intent | 使用者期望的權限設定；Phase C 尚未強制執行 |

### 2.2 必守不變量

- Profession、Model、Skills、Permissions 四者獨立，不互相推導。
- `equipped_skill_ids` 只能顯示為「已裝備」，不得顯示「已載入」。
- Permission Intent 必須顯示「設定意圖，尚未強制執行」。
- 儲存 AgentProfile 不得啟動、重啟、停止或注入任何 Agent Session。
- 不修改 `~/.codex`、第三方技能檔或掃描來源。
- 不把 Task↔Session 的 tracking-only 關聯升級為 Context 注入。
- 不用 `herdr agent prompt` 傳遞治理內容。
- 不存在於目前 catalog 的 Profession／Skill 引用必須標示 unresolved，不得靜默刪除或換成別項。

## 3. 開工前五項產品裁決

Claude 唯讀審查判定這五項會直接決定 schema。下表列出建議預設值；使用者必須逐項核准或修改。

| ID | 決策 | 建議預設 |
|---|---|---|
| C-D1 | Profession 來源 | 直接使用現有掃描出的 `AgentRole` 作為唯讀 catalog；不在 repo 另造種子模板 |
| C-D2 | 名詞區分 | API／schema 使用 `agent_profile`；既有掃描資料保留 `agent_role`；UI 使用「Agent 設定」與「Profession 模板」 |
| C-D3 | Skill Loadout 邊界 | Phase C 只保存現有 `skill_id` 引用與 Equipped 狀態；不預鋪 Phase D Available／Installed／Loaded 狀態機 |
| C-D4 | Permissions v1 | 固定 `read`、`write`、`test`、`deploy` 四鍵；值為 `allow`／`deny`／`unspecified`；全部標示為 intent-only |
| C-D5 | Task Card 關聯 | Phase C 不新增 AgentProfile↔Task 關聯；留到 Phase E 在 Effective Context 契約下設計並做版本遷移 |

未完成 C-D1～C-D5 前，不建立 `agent_profiles.json`，避免先寫死錯誤 schema 再依賴人工修復。

## 4. 建議資料契約（等待 C-D1～C-D5 核准）

儲存檔：`~/.sid-console/agent_profiles.json`

權限：目錄 `0700`、檔案 `0600`

格式：

```json
{
  "schema_version": 1,
  "profiles": {
    "profile-example": {
      "id": "profile-example",
      "name": "Forge",
      "profession_role_id": "codex:backend-engineer",
      "model": {
        "tool": "codex",
        "model_id": ""
      },
      "equipped_skill_ids": [
        "codex:python",
        "codex:security"
      ],
      "permission_intents": {
        "read": "allow",
        "write": "allow",
        "test": "allow",
        "deploy": "deny"
      },
      "enabled": true,
      "created_at": 0,
      "updated_at": 0
    }
  }
}
```

### 4.1 驗證規則

- Profile 上限：先採 500；需以常數集中管理。
- ID：沿用 Task Card 的安全字元集合與長度限制，伺服器產生，不接受建立時自訂。
- Name：必填純文字，長度上限 200。
- `profession_role_id`：字串或 `null`；引用失效時保留原值並標示 unresolved。
- `model.tool`：只接受 catalog 提供的工具 ID；`model_id` 是設定值，不代表執行環境已安裝或可用。
- `equipped_skill_ids`：去重、有界；只接受建立／更新當下 catalog 已知的 skill ID。來源後續消失時保留並標示 unresolved。
- Permission keys 與值使用嚴格白名單；unknown key/value 拒絕。
- `created_at` 不可由 client 修改；`updated_at` 由 server 產生。
- Unknown top-level/profile fields 拒絕，避免未實作欄位被誤認為有效。

### 4.2 儲存安全

新增 `sidconsole/agent_profiles.py`，沿用 `tasks.py` 的安全模式，不直接共用其私有函式：

- thread lock + cross-process `flock`
- bounded JSON depth／size
- atomic temp write + file fsync + `os.replace` + directory fsync
- symlink／hardlink／permission 異常 fail closed
- corrupt marker 先寫、再 quarantine；任何失敗不得靜默回空集合
- 啟動時收緊舊檔權限

若日後要抽共同 storage helper，另開獨立重構，不和 Phase C 功能混在同一提交。

## 5. API 邊界

### 5.1 讀取

- `GET /api/agent-profiles`
- `GET /api/agent-profiles/<id>`
- `GET /api/agent-builder/catalog`

Catalog 回傳三種唯讀來源：

- `professions`：既有 `AgentRole`
- `models`：工具／模型設定選項及其來源強度
- `skills`：目前索引中的 `SkillRecord`

Catalog 只描述 SID Console 看見的資料；不得把「有設定」寫成「執行時可用」。

### 5.2 寫入

- `POST /api/agent-profiles`
- `POST /api/agent-profiles/<id>`
- `POST /api/agent-profiles/<id>/delete`

沿用現有寫入防護：

- Host 驗證
- `X-SID-Console: 1`
- 同源 Origin
- Fetch Metadata
- body 大小與讀取期限
- 嚴格 schema／unknown field rejection

### 5.3 禁止的端點

Phase C 不新增：

- `/start`
- `/launch`
- `/inject`
- `/compile`
- `/apply-permissions`
- 任何修改 Herdr、`~/.codex` 或第三方檔案的端點

## 6. UI 範圍

將工作台右欄 `[A] 角色裝備` 從唯讀骨架升級為 Agent Builder：

1. Profile 列表與搜尋
2. 建立／編輯／複製／停用／刪除
3. Profession 選擇器
4. Tool／Model 設定
5. Skill Loadout 多選
6. Permission Intent 四鍵設定
7. Summary Preview

### 6.1 誠實揭露

固定顯示：

- 「已裝備不等於已載入；本階段不會把技能注入 Agent Context。」
- 「權限為設定意圖，尚未對 Agent CLI 強制執行。」
- 「儲存或切換 Profile 不會啟動、重啟或修改現有 Session。」
- unresolved 引用顯示原 ID、來源消失原因與修復入口，不靜默隱藏。

### 6.2 可及性與 RWD

- dialog 使用既有 `withModalA11y`
- focus trap、Esc 關閉、焦點還原、背景 inert
- 列表與編輯器可鍵盤操作
- 240px 右欄不得水平溢出；長 ID／模型名／技能名允許換行
- 刪除需二次確認；複製產生新 ID

## 7. 實作切片與依賴順序

### C0｜產品裁決與契約凍結

- 使用者裁決 C-D1～C-D5
- 更新本文件為 `APPROVED`
- 固定 schema v1、enum、上限與 out-of-scope

**Gate C0：** 五項決策均有人工紀錄；尚未寫產品碼。

### C1｜Storage 與模型

- `sidconsole/agent_profiles.py`
- schema validation／normalize
- fail-closed persistence
- 完整 storage／filesystem safety 測試

**Gate C1：** corruption、競態、權限與原子寫入測試全綠。

### C2｜Catalog 與 API

- catalog 組裝
- CRUD routes
- API security／validation tests
- unresolved reference 行為

**Gate C2：** 無任何 endpoint 能啟動 Herdr 或寫外部來源。

### C3｜Agent Builder UI

- `[A]` tab 介面
- CRUD dialogs
- selectors、preview、truthfulness copy
- synthetic DOM behavior tests

**Gate C3：** Equipped／Loaded 與 intent／enforced 用語測試鎖定。

### C4｜整合與回歸

- Python 全套
- terminal／workbench／role-skills 全套
- fault injection
- responsive browser probe
- storage permission check

### C5｜獨立審查

依 `PHASE-C-AGENT-MODEL-ROUTING.md` 動態路由，不固定每個 Agent 永遠使用最高模型：

- MCODE 是唯一產品碼 writer，先做 self-review；self-review 不算獨立審查。
- Claude 是獨立 reviewer。一般工作用 STANDARD／Sonnet；資料完整性、並行、權限或 migration 用 DEEP／Opus。
- Codex 只在 routing governance 的 trigger 成立時做針對性 adversarial review，不重複 Claude 全量審查。
- AGY 僅在 UI／瀏覽器行為相關時執行 STANDARD 或 DEEP QA。
- 協調者只寫治理／文件／報告，不修改產品 runtime code。
- findings 由協調者分類後交回 MCODE；review agents 不直接修碼。
- findings 收斂後再進人工 Gate 7。

## 8. 最小測試矩陣

### Storage

- create／read／update／delete／duplicate／disable
- ID 唯一性與大量建立
- unknown／missing／wrong-type／oversize fields
- enum、陣列去重與上限
- corrupt JSON／wrong root／malformed entry
- symlink／hardlink／permission denied
- temp collision、atomic replace、directory fsync failure
- thread + process concurrency
- `0700`／`0600`

### API

- CRUD happy path
- CSRF／Origin／custom header／Fetch Metadata
- oversized／slow body
- unknown ID／hostile ID
- unavailable catalog references
- storage blocked 時回 503，不回空集合

### UI

- 四維度各自編輯，不互相推導
- Equipped 文字不得出現 Loaded
- Permission Intent 不得出現「已強制」
- CRUD dialog accessibility
- route cleanup、重複 mount、焦點還原
- 240px 窄欄無 overflow
- 任一 CRUD 操作都不呼叫 terminal／control／input API

### 無副作用

在 CRUD 前後量測：

- `herdr terminal session` 數量不變
- pane 數量不變
- `~/.codex` mtime 不變
- 技能／角色來源檔 mtime 不變

自動測試不得為了驗證而真的修改這些來源；人工 Gate 7 才做本機觀測。

## 9. Gate 7｜Agent Builder 人工驗收

1. 建立 Profile 並重整，資料仍存在。
2. 選 Profession、Model、Skills、Permissions，摘要與儲存值一致。
3. UI 清楚顯示 Equipped ≠ Loaded。
4. UI 清楚顯示 Permission Intent ≠ Enforced Permission。
5. 來源消失後 unresolved 引用仍可見，不丟資料。
6. 編輯、複製、停用、刪除流程正常。
7. 窄欄、鍵盤、dialog focus／Esc／inert 正常。
8. CRUD 前後沒有新 Agent Session、pane 或外部檔案變更。
9. Phase B 工作台、Task Card、Terminal 冒煙回歸通過。

Gate 7 仍是人工閘門，代理不得自行宣告完成。

## 10. 明確排除

- Effective Context／Policy Compiler／Context Preview
- 啟動或重啟 Agent
- Profile 套用到既有 session
- Skill install／Git import／Load Policy／Marketplace
- Permissions 強制執行
- AgentProfile↔Task 關聯
- 修改 Global／Project policy
- 修改 `~/.codex`、第三方 Skill 或 Agent 檔案
- 自動部署
- Context Budget／Context Doctor

## 11. 執行與 model routing

完整規則以 `PHASE-C-AGENT-MODEL-ROUTING.md` 為準。Phase C 各切片的初始 routing 建議如下；每次派工仍須記錄 executor、provider、model、tier、thinking/reasoning、intent、writer status 與 acceptance criteria。

| 切片 | 風險 | 初始 routing |
|---|---|---|
| C0 決策／契約 | 產品 schema | Coordinator；不寫 runtime code |
| C1 Storage | 並行、資料完整性、corruption | MCODE DEEP → Claude DEEP／Opus → Codex DEEP（trigger：concurrency + data integrity） |
| C2 Catalog／API | API 防護、資料契約 | MCODE STANDARD → Claude DEEP／Opus；若 authorization finding 未解再啟動 Codex |
| C3 UI | 一般多檔 UI、誠實語意 | MCODE STANDARD → Claude STANDARD／Sonnet → AGY STANDARD |
| C4 整合／回歸 | 長上下文、跨層回歸 | MCODE DEEP self-review → Claude STANDARD 或 DEEP（依 findings）→ AGY STANDARD |
| Critical finding | 安全／資料風險未解或模型意見重大分歧 | ESCALATION；須符合 routing governance 的 Tier 4 條件 |

單一 writer 規則：MCODE 取得 ownership 後才可改產品碼；MCODE 釋放前，Coordinator、Claude、Codex、AGY 均不得修改產品 runtime code。

### Runtime 前置驗證

來源 routing 文件 §18 宣告 MCODE executable 與 API READY；但本 session 於 SID Console worktree 兩次執行 `mcode-orca inspect`，治理 preflight 通過後都在 wrapper 最後一行得到 `command not found: mcode`（exit 127），且 `command -v mcode` 無結果。

因此目前 runtime 判定為：

```text
mcode-orca wrapper       READY
mcode executable         NOT FOUND（本 session native evidence）
Phase C product coding   BLOCKED
```

開始 coding 前必須重新完成 `mcode --version`、inspect-mode 真實 turn，以及 writer lock acquire/release smoke test。文件宣告不能取代執行期證據。

## 12. 規劃審查紀錄

- 使用者提供 `PHASE-C-AGENT-MODEL-ROUTING.md` v1.0，狀態 Active；已在不改變內容語意的前提下正規化 Markdown 換行後納入 repo。
- MCODE：規劃階段啟動失敗，底層 executable 未找到；未開始審查、未改檔。
- Claude：規劃階段唯讀審查完成；因 C-D1～C-D5 尚未裁決，verdict 為 **FAIL / not implementation-ready**。
- 下一步：產品負責人裁決 C-D1～C-D5，並修復／重新驗證 MCODE runtime。
