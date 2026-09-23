# SID Console 開發交接

更新日期：2026-09-22

## 1. 目前狀態

- 分支：`main`
- 最新功能修正：`0eddf9c fix terminal history disclosure and narrow layout`
- 遠端：`origin/main` 已包含 `26384c9`
- 本機服務：`http://127.0.0.1:7788`
- 交接時服務使用 `0eddf9c` 的產品碼，HTTP 與靜態資產檢查正常
- GitHub Gate 6 追蹤入口：<https://github.com/sidphoto/sid-console/issues/1>（已關閉）
- 下一階段計畫：[`PHASE-C-PLAN.md`](PHASE-C-PLAN.md)
- Phase C Agent／model routing：[`PHASE-C-AGENT-MODEL-ROUTING.md`](PHASE-C-AGENT-MODEL-ROUTING.md)

SID Console 的 Phase B1–B5 已完成。Gate 6 已由使用者於 2026-09-22 正式裁決 **PASS**；Issue #1 已補上最終證據並關閉。下一階段為 Phase C｜Agent Builder；C-D1～C-D5 已全部採建議預設並凍結，現在只等待 MCODE runtime smoke test。

## 2. 主要提交

| Commit | 內容 |
|---|---|
| `81de75c` | Phase B1–B4：三欄工作台、Task Card、Status Provenance、G/P/A/T 骨架 |
| `d287af0` | B5：支援 agent-less pane、修正退化終端尺寸與平行快照 |
| `0eddf9c` | 修正窄寬 Status Provenance 溢出；誠實揭露網頁終端不提供歷史回捲 |

## 3. Gate 6 結果摘要

### 已通過

- A1、A2：基本終端顯示與操作
- B1–B3：IME 與輸入邊界
- C1–C3：vim、htop、清屏與 alternate-screen 行為
- D1–D4：側欄、專注模式、尺寸與跨重整持久化
- E3：位於底部時跟隨新輸出
- F1–F5：觀看／接管、pane 切換、清理與關閉分頁生命週期
- G1–G7：分頁、焦點、inert、對話框、任務卡、誠實措辭與 tracking-only
- H1：橋接斷線提示與重新連線

### VOID

- E1、E2：Herdr 串流不提供 scrollback 所需的換行或捲動語意，因此兩項前提不存在，不能記為 PASS 或 FAIL。

### 證據強度

- M：可由 DOM、HTTP、process argv、pane read 或檔案內容量測
- H：需要人類判讀畫面，例如 alternate-screen 重繪是否正確

完整人工驗收紀錄與歷史缺陷索引在 GitHub Issue #1。本機的細節紀錄位於 `.local/runs/` 與 `.local/reviews/`，這兩個目錄刻意不進版控。

## 4. 重要設計邊界

### 4.1 Gate 6 是人工閘門

任何代理只能整理證據，不得自行宣告 Gate 6 通過或關閉 Issue #1。

### 4.2 Task 與 Session 僅為 tracking-only

任務卡與 pane/session 的關聯只供本機追蹤，不是 Context 注入。若任務內容要成為 Effective Context，必須開啟新的 Agent Session。

### 4.3 Status Provenance 不等於正式驗證

SID Console 沒有使用者身份驗證能力：

- `provenance.verified` 恆為 `false`
- `verification_asserted` 只代表測試與介面核准欄位都由未驗證的操作者自行填為通過
- UI 必須使用「聲稱驗證通過」，不得顯示治理層級的「已驗證 / Verified」

### 4.4 接管權不得隱式傳遞

- 預設為 observe
- takeover 需要使用者確認
- 斷線重連、切換 pane 或開啟新 pane 後都回到 observe
- 導航離開時使用 token-guarded `abandon`，避免舊 view 誤殺另一分頁的新 session
- 關閉分頁只清橋接，不關底層 pane

### 4.5 網頁終端只同步目前畫面

Herdr 的 terminal frame 使用絕對游標定位重畫可視網格，實測沒有換行或捲動控制序列。xterm 無法從這種串流建立真實歷史：

- live xterm 使用 `scrollback: 0`
- 獨立終端與工作台都顯示「不提供回捲歷史」
- 需要較早內容時，使用 Herdr 原生視窗
- 不要把 `herdr pane read` 快照直接混入 live xterm；快照與 emulator 狀態沒有可靠合併語意，會造成重複內容或 alternate-screen 衝突
- `tests/frontend/terminal.cjs` Category 10 只證明 full frame 不破壞預先存在的 synthetic xterm 狀態，不代表 live Herdr 可產生 scrollback

若未來要支援網頁歷史，應先讓 Herdr 協定提供可驗證的捲動語意，或設計獨立的唯讀歷史面板；不要偽裝成 xterm scrollback。

## 5. 最近修正：窄寬 RWD

Status Provenance 在窄右欄曾出現 select、badge 與說明文字溢出。`0eddf9c` 做了以下修正：

- `.wb-provenance-box`、header、row 與直接子元素允許收縮
- header/row 可換行
- select 限制 `max-width: 100%`
- 長 badge 可換行
- 真瀏覽器將右欄縮至 240、180、140、120px，均確認 `scrollWidth === clientWidth`

回歸測試位於 `tests/frontend/workbench.cjs` Category 18。

## 6. 驗證基準

交接前最後一輪結果：

- `python3 -m unittest discover -s tests -v`：154 tests OK
- `node tests/frontend/terminal.cjs`：11/11 categories PASS
- `node tests/frontend/workbench.cjs`：18/18 categories PASS
- `node tests/frontend/role_skills.cjs`：5/5 PASS
- `node --check web/app.js`：PASS
- `git diff --check`：PASS

README 不固定宣稱測試筆數；以上數字只代表 2026-09-22 的交接快照。

## 7. 後續工作

1. 修復 MCODE 執行環境；routing 文件宣告 READY，但本 session 的 native evidence 是 `mcode-orca inspect` 最後回 `command not found: mcode`（exit 127）。
2. 完成 `mcode --version`、inspect-mode 真實 turn 與 writer-lock acquire/release smoke test。
3. 依 `PHASE-C-AGENT-MODEL-ROUTING.md` 執行固定角色、動態 model tier：MCODE 唯一產品碼 writer；Claude 獨立複審；Codex 依 trigger 啟動；AGY 負責適用的瀏覽器 QA；協調者只寫治理／文件／報告。
4. 若要開發網頁歷史，先寫產品規格並確認 Herdr 協定，不要直接 hydrate xterm。
5. 補強 Category 11 尺寸測試：鎖定精確 fallback `80×24`，不要只驗證退化值未送出。
6. 將 Category 11d 從 regex/source assertion 改成注入 fake API/FitAddon，直接斷言 resize payload。
7. 改善 agent-less pane 的 UI 可發現性。目前可用直接網址進入，但左欄只列 agent sessions。

## 8. 已清理項目

- F3 測試用的 `w4:p2` 已關閉；工作區恢復為原本單一 pane
- `/tmp/gate6.txt` 已刪除
- AGY 唯讀審查因額度耗盡而停止，其 terminal 已關閉
- 瀏覽器量測產生的 observe session 已終止
- 交接時沒有 `herdr terminal session` 孤兒行程

## 9. 操作限制

- 維持單一 writer
- 遠端 push、重啟服務、建立／關閉 pane 等受控操作需要使用者明確授權
- 不修改 `~/.codex`
- 不碰其他倉庫或既有 Herdr agent panes
- 不把 pane 內容、家目錄絕對路徑、憑證或本機私密資料寫入 GitHub
