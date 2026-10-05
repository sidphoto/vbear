# SID Console｜Phase R 規劃：獨立 Runtime（脫離 Herdr，macOS 優先）

- 日期：2026-09-25
- 狀態：**R-D1～R-D7 已由使用者核准（2026-09-25，全部採建議）｜R1 契約已凍結，待使用者說「開始」才派工**。本文件不授權 R2 以後的實作。
- 存放：`sidconsole/PHASE-R-PLAN.md`

## 0. 已核准裁決（2026-09-25）

使用者原生訊息「同意」，回覆協調者提出的整組建議，包含：

| 裁決 | 結論 |
|---|---|
| R-D1 | push `472043d`，作為 Herdr 版最後基準點 |
| R-D2 | 保留 Phase D1 契約，排在 R1 之後，可與 R2 並行；D-D3 於 R3 定案後重新裁決 |
| R-D3 | 執行期產品碼維持零第三方相依；打包工具（如 PyInstaller）允許 |
| R-D4 | R2 先做到「瀏覽器關閉不中斷」；「App 結束後仍存活」另行裁決 |
| R-D5 | Gate 10（R3）通過後才移除 Herdr 相容層 — **已完成（2026-10-05，分支 `r4-remove-herdr`；回退點 tag `last-herdr`）** |
| R-D6 | 沿用 routing；R1 STANDARD，R2、R3 DEEP 並須獨立審查 |
| R-D7 | R2 開始前修復 AGY 瀏覽器 QA |
| Gate 編號 | Gate 8～12 對應 R1～R5；Phase D1 Armory 改用 **Gate D1** |
| R1 執行者 | MCODE（MiniMax-M3）寫碼、Claude 唯讀審查 |
| R1 前置 | 先補做 `472043d` 的獨立審查 |

協調者修正：R1 範圍補列 `bridge/terminal.py`、`index.py`、`__main__.py`（見 §5 R1）。
- 適用治理：`~/.codex/rules/PROJECT-GOVERNANCE.md`（governance_version 3.0.0）
- 前一基準：`472043d`（Phase C + Gate 7 修正，本機未 push）

---

## 1. 背景

SID Console 目前依附 Herdr 執行終端機與 Agent：session、pane、Agent 狀態都透過 `herdr terminal session observe/control` 取得。這帶來三個限制：

1. **權限無法強制**。Agent 由 Herdr 啟動，SID 碰不到啟動參數與設定檔，Profile 的 Permissions 只能停在「意圖」。
2. **一般使用者無法安裝**。使用者必須先裝 Herdr，再用指令啟動 SID。
3. **上游依賴**。受 Herdr 版本（目前 0.9.1）與 PUBLIC fork 的 Apache 2.0 §6 商標問題牽制。

使用者已決定：SID Console 改為獨立程式，本身同時提供終端機與一般人可用的介面，第一版只支援 macOS。

## 2. 目標與非目標

### 目標

- SID 自行開啟與管理終端機 session，不需要 Herdr。
- SID 啟動 Agent 時，把 Agent Profile 的權限轉成 Agent 實際會讀取的設定，並在畫面上誠實標示每項權限的套用程度。
- 提供兩種模式：**一般模式**（結構化畫面、按鈕核准）與**進階模式**（完整終端機）。
- 最終產出可雙擊開啟的 macOS `.app`。
- 過程中每個階段結束時，程式都維持可用。

### 非目標（本階段不做）

- Windows、Linux 支援。
- Git／URL 技能匯入（沿用 D-D1 裁決）。
- Policy Compiler 完整版與 Context Budget（Phase E、F）。
- 修改使用者全域的 `~/.claude`、`~/.codex` 設定。R3 的設定一律寫在 SID 自己管理的暫存位置。
- 對外發佈到 App Store。

## 3. 待使用者裁決事項

| 編號 | 問題 | 建議 |
|---|---|---|
| R-D1 | `472043d` 是否先 push，作為「Herdr 版最後基準點」 | 建議先 push，方便日後比對與回退 |
| R-D2 | Phase D1（Armory 唯讀總覽）保留、並行或暫停 | 建議保留契約，排在 R1 之後，可與 R2 並行；D-D3 Load Policy 等 R3 定案後再重新裁決 |
| R-D3 | R5 打包是否接受放寬「零第三方相依」 | 建議區分：**執行期程式碼**維持零相依；**打包工具**（例如 PyInstaller）允許使用，不進入產品程式碼 |
| R-D4 | App 關閉後，Agent session 要不要繼續跑 | 建議 R2 先做到「瀏覽器關閉不中斷」；「整個 App 結束後仍存活」列為選配，另行裁決 |
| R-D5 | Herdr 相容層何時移除 | 建議 Gate 10（R3）通過後才移除 |
| R-D6 | 各階段寫碼者與審查者 | 沿用 `PHASE-C-AGENT-MODEL-ROUTING.md`；R2、R3 涉及程序管理與權限，建議列為 DEEP，必須獨立審查 |
| R-D7 | AGY 瀏覽器 QA 是否在 R 系列開始前修復 | 建議在 R2 前修復；R2 以後的終端機行為靠人工驗證成本很高 |

## 4. 架構概要

```
┌─────────────────────────────────────────────┐
│ 瀏覽器前端 web/（一般模式 / 進階模式）         │
└───────────────┬─────────────────────────────┘
                │ HTTP / WebSocket（僅 127.0.0.1）
┌───────────────▼─────────────────────────────┐
│ sidconsole/server.py                         │
│  ├ Agent Profiles / Tasks / Skills（既有）    │
│  └ Runtime 介面（新）                          │
│       ├ HerdrRuntime  （既有橋接，過渡期）     │
│       └ NativeRuntime （新）                   │
└───────────────┬─────────────────────────────┘
                │ Unix domain socket（0600）
┌───────────────▼─────────────────────────────┐
│ sidconsole-runtimed（新，常駐背景程序）        │
│  ├ PTY 管理（Python 標準函式庫 pty）           │
│  ├ scrollback 環狀緩衝                        │
│  ├ 程序群組管理與清理                          │
│  └ Agent 啟動器（套用 Profile 設定）           │
└───────────────┬─────────────────────────────┘
                ▼
        claude / codex / 其他 CLI Agent
```

### Runtime 介面（R1 定義，實作需對齊）

| 操作 | 說明 |
|---|---|
| `list_sessions()` | 列出所有 session 與 pane |
| `open_session(spec)` | 依規格開啟 session；spec 含工作目錄、指令、環境變數、Profile 參照 |
| `send_input(session_id, data)` | 寫入終端機輸入 |
| `observe(session_id)` | 串流輸出；新連線先收到 scrollback |
| `control(session_id)` / `release(session_id)` | 接管與釋放 |
| `resize(session_id, cols, rows)` | 調整終端機尺寸 |
| `status(session_id)` | 回傳執行狀態；無法判斷時回傳 `unknown` |
| `close(session_id)` | 結束 session 與其程序群組 |

狀態值沿用既有原則：執行狀態（idle／working／exited）不等於任務完成。

## 5. 分階段計畫

### R1｜Runtime 抽象層

- **目標**：定義 Runtime 介面，把 `bridge/herdr.py` 改寫為 `HerdrRuntime`，使用者可見行為完全不變。
- **範圍**：`sidconsole/runtime/`（新）、`sidconsole/bridge/herdr.py`、`sidconsole/bridge/terminal.py`（終端機串流主體）、`sidconsole/server.py`、`sidconsole/index.py`、`sidconsole/__main__.py` 中呼叫 Herdr 的位置、對應測試。（2026-09-25 協調者補列：bridge 以外共 10 處直接呼叫 `herdr.`）
- **不做**：任何原生 PTY 程式碼、UI 變更。
- **交付**：介面定義、`HerdrRuntime`、介面合約測試（之後原生版必須通過同一組測試）。
- **驗收**：
  - 既有 213 tests 全綠，連跑 3 次。
  - 新增介面合約測試通過。
  - Gate 6、Gate 7 冒煙清單重跑通過。
- **Gate**：Gate 8
- **風險等級**：STANDARD

### R2｜原生 PTY Runtime

- **目標**：SID 自行開啟終端機並啟動 Agent，功能對齊 Herdr 版。
- **範圍**：`sidconsole/runtime/native.py`、`sidconsole/runtimed/`（新）、設定切換開關、測試。
- **交付**：
  - `sidconsole-runtimed` 背景程序，透過 `~/.sid-console/runtime.sock`（權限 0600）與 server 溝通。
  - 每個 session 保留固定大小的 scrollback，重連時補送。
  - 關閉 session 時終止整個程序群組，不留孤兒程序。
  - 設定開關可在 Herdr 版與原生版之間切換。
- **驗收**：
  - 原生版通過 R1 的介面合約測試。
  - 開啟、輸入、接管、釋放、重連、調整尺寸、關閉，全部與 Herdr 版行為一致。
  - 關閉瀏覽器後重新開啟，session 與輸出仍在。
  - 關閉 session 後以 `ps` 確認無殘留程序。
  - 從 Finder 啟動時也找得到 `claude`、`codex`（見風險 §8-2）。
- **Gate**：Gate 9
- **風險等級**：DEEP（程序管理、IPC、檔案權限），需獨立審查

### R3｜啟動時套用 Agent Profile

- **目標**：Agent Profile 的權限在啟動時真正生效，並在畫面上誠實標示。
- **範圍**：Agent 啟動器、權限對照表、Profile 啟動預覽 UI、測試。
- **交付**：
  - 每個 session 產生一份專屬設定，存放於 `~/.sid-console/sessions/<id>/`，不修改使用者全域設定。
  - 啟動前顯示「本次將套用的設定」預覽，使用者確認後才啟動。
  - 每項權限顯示套用程度（見 §6）。
- **前置作業**：實作前先做一次技術驗證（spike），以當時安裝的 CLI 版本實測下表機制，更新對照表後再凍結契約。

權限對照表初稿（**全部待驗證**，以 spike 結果為準）：

| Permission Intent | Claude Code 可能機制 | Codex 可能機制 | 預期套用程度 |
|---|---|---|---|
| Read | 權限模式／允許工具清單 | sandbox 唯讀模式 | 強制 |
| Write | 允許或拒絕檔案編輯工具 | sandbox 可寫範圍 | 強制 |
| Test | 允許特定 shell 指令 | 核准模式 | 部分強制 |
| Commit | 拒絕 `git commit` 類指令 | 核准模式 | 部分強制（可被其他指令繞過） |
| Deploy | 拒絕特定部署指令 | 核准模式 | 部分強制 |
| Network | 拒絕網路相關工具與指令 | sandbox 網路設定 | 待驗證 |
| Filesystem | 限制工作目錄範圍 | sandbox 可寫範圍 | 部分強制 |

- **驗收**：
  - 每一列都有實測紀錄（設定、測試指令、結果）。
  - 設為「不允許」的動作實際被擋下，或畫面正確顯示「僅意圖」。
  - 使用者全域 `~/.claude`、`~/.codex` 在測試前後 hash 不變。
- **Gate**：Gate 10
- **風險等級**：DEEP，需獨立審查
- **Gate 10 通過後**：依 R-D5 移除 `HerdrRuntime`（另開一個小任務卡）。

### R4｜一般模式

- **目標**：不懂終端機的人也能使用 Agent。
- **前置作業**：技術驗證（spike），確認 Claude Code 與 Codex 的非互動模式能否輸出結構化事件串流，以及權限請求在非互動模式下如何回傳給 SID。若無法在非互動模式中處理核准，改為「啟動前一次決定權限」的設計，並在規劃中註明。
- **交付**：
  - 聊天加動作清單的畫面：Agent 說了什麼、讀了哪些檔案、改了哪些檔案、跑了哪些指令。
  - 權限請求顯示為「允許／拒絕」按鈕，並以一般用語說明（例如「Agent 想修改 report.md」）。
  - 一般模式與進階模式可以切換，同一個 session 不重複啟動。
  - 權限設定提供簡化版：「只能看／可以改檔案／可以上網／可以發布」四級，進階使用者可展開七項細節。
- **驗收**：由一位無技術背景的人，在不看說明文件的情況下完成一項指定任務（例如「請 Agent 幫我整理這個資料夾的檔名」）。
- **Gate**：Gate 11
- **風險等級**：STANDARD（UI）＋DEEP（核准流程）

### R5｜打包成 macOS App

- **目標**：使用者雙擊即可開啟，不需要安裝 Python、不需要開終端機。
- **交付**：
  - 內含 Python 執行環境的 `.app`。
  - 開啟後自動啟動 server 與 runtimed，並開啟介面（預設瀏覽器或內嵌視窗，另行裁決）。
  - 結束 App 時的行為符合 R-D4 裁決。
  - 第一次開啟時檢查 `claude`、`codex` 是否已安裝，未安裝時以一般用語提示。
- **驗收**：在一台沒有開發環境的 Mac 上，從下載到完成第一個任務。
- **對外發佈另需**：Apple 開發者帳號、程式碼簽章、公證（notarization）。未完成前只能自用或手動允許。
- **Gate**：Gate 12

## 6. 誠信邊界延伸

既有原則「Permission Intent ≠ Enforced Permission」在 R3 之後細分為四種標示，UI 與 API 必須一致：

| 標示 | 意義 |
|---|---|
| 強制 | 已寫入 Agent 會讀取的設定，且 spike 實測有效 |
| 部分強制 | 已寫入設定，但已知可被其他方式繞過；畫面需說明繞過方式 |
| 僅意圖 | 此 Agent 沒有對應機制，SID 只記錄使用者意圖 |
| 未知 | 尚未驗證，或 CLI 版本與驗證時不同 |

CLI 版本改變時，對應權限自動降為「未知」，直到重新驗證。

既有原則維持不變：Installed ≠ Equipped ≠ Loaded、執行狀態 ≠ 任務完成、沒有資料就顯示「未知」。

## 7. 與既有階段的關係

| 項目 | 處理方式 |
|---|---|
| Phase A、B、C 成果 | 全部保留；R1 以介面包住 Herdr 橋接，不重寫 |
| Phase D1 契約 `.local/handoffs/20260924-phase-d1-to-mcode.md` | 依 R-D2 裁決；建議保留，R1 後啟動 |
| D-D3 Load Policy | R3 定案後重新裁決，因為 SID 將能在啟動時決定技能載入 |
| `SID_herdr` PUBLIC fork 與商標問題 | R3 通過、移除 Herdr 相容層後，此問題不再阻擋 SID Console 本身 |
| 產品架構圖 Roadmap | 需更新：新增 Phase R，並修正 A～C 的實際狀態 |

## 8. 風險

1. **Agent 狀態偵測**：Herdr 原本負責判斷 Agent 在工作或閒置。原生版在進階模式只能靠終端機輸出推測，推測不確定時必須顯示「未知」。一般模式（R4）改用結構化事件，準確度較高。
2. **macOS PATH 問題**：從 Finder 或 `.app` 啟動的程式拿不到使用者 shell 的 PATH，常見結果是找不到 `/opt/homebrew/bin` 下的 `claude`。R2 就要處理，不能拖到 R5。
3. **CLI 版本變動**：Claude Code 與 Codex 更新頻繁，權限參數與 JSON 格式可能改變。R3 需記錄驗證時的 CLI 版本，並在版本改變時降級標示。
4. **孤兒程序**：Agent 可能再啟動子程序。關閉 session 必須終止整個程序群組，並有測試覆蓋。
5. **本機 socket 安全**：runtime socket 與 HTTP server 只接受本機連線；socket 權限 0600；API 維持既有寫入防護。
6. **Gate 7 後修正未經獨立審查**：R1 開始前，建議先補做 `472043d` 的獨立審查，避免把未審查的程式碼當作新階段的基準。
7. **工作量**：R2 與 R3 是整個計畫最重的部分，也是產品價值所在。若時間有限，優先順序為 R1 → R2 → R3，R4 與 R5 可延後。

## 9. 需要使用者回覆的事項

1. §3 的 R-D1 至 R-D7 逐項裁決（同意建議，或另行指定）。
2. 確認 Gate 編號：Gate 8（R1）至 Gate 12（R5）。
3. 指定 R1 的寫碼者與審查者。
4. 確認本文件存放位置。

使用者確認後，下一步為撰寫 R1 契約（`.local/handoffs/`），再派工。
