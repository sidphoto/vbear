# VBear

本機主控台：把分散在各處的 Skill、Agent 角色與工作中的 Terminal 整理成一般人看得懂的畫面，並以內建的
VBear runtime 啟動與管理 Agent 終端（Profile 管理的 Claude 啟動含啟動前預覽、確認與如實的權限標示）。

[English](README.md) · [架構](docs/ARCHITECTURE.md) · [安全模型](docs/SECURITY-MODEL.md) · [參與貢獻](.github/CONTRIBUTING.md) · [回報資安問題](SECURITY.md)

> **目前狀態：早期版本（v0.2）**，只在 macOS 上由作者本人日常使用與測試。開始使用前請先看下方「已知限制」。
>
> VBear 的名字來自台灣黑熊和牠胸前的 V 字：先看清楚，再放行。
>
> v0.1.0 以前叫「SID Console」，最早依附 Herdr 執行終端（「SID Console for Herdr」）。第一次啟動時會自動把舊的 `~/.sid-console` 搬到 `~/.vbear`。Herdr 相容層已移除，最後一個支援 Herdr 的版本標記為 git tag `last-herdr`。
> 舊設定的 `runtime_kind: herdr` 會在啟動時自動改為 native，並提示一次。

## 已知限制

- **讀取不隔離**：受管的 Claude session 仍可讀取你帳號能讀的所有檔案，只限制寫入與網路。
- **`!` 指令不經沙盒**：在 Claude Code 裡以 `!` 自己輸入的指令不受沙盒限制；預覽畫面有標示。
- **無法阻擋 commit**：工作目錄的 `.git` 可寫，啟動前必須勾選知悉。
- 目前只有一種啟動設定（只開放 Bash、停用 Edit/Write、不連網）；唯讀、可連網與 Codex 受管啟動尚未提供。
- 「工作中／等你回覆」只對 Profile 啟動、且版本有實測紀錄的 Claude Code（目前是 2.1.292）判斷，依據是 Claude 自己設定的終端標題；分不出是等你輸入還是等你確認。其他 Terminal、其他版本與 Codex 顯示「狀態未知」。
- 任務卡的版本綁定只比對 commit：核准之後未提交的修改，不會讓結果失效。
- **以你的帳號執行的程式可以操作 VBear**：其他網站和其他使用者帳號會被擋下，因為每次呼叫 API 都要帶一組
  每次啟動都會更換的通行證，通行證存在只有你能讀的檔案裡。但以你的帳號執行的程式，也讀得到這個檔案。
- **沒有遙測**：VBear 不對外連線，也沒有帳號或雲端服務。

## 特色

- **內建終端機**：在「終端機」頁選一個家目錄內的資料夾，就能開你的登入 shell 直接打字，多個終端機以分頁切換。
  這是以你的帳號執行的一般終端機，**不受沙盒限制**，畫面上會標示。
- **本機執行、外部技能與角色來源唯讀**：只讀取你選的外部工具來源，不修改任何技能或角色檔案，不執行技能內的腳本（VBear 本身之設定、註記與終端操作除外）。終端工作台（Terminal Workbench）提供本機 Agent pane 畫面串流與受控輸入通道（見下文），其餘外部來源相關功能維持唯讀。
- **後端零第三方相依、前端單一本機 Vendored 依賴**：後端僅使用 Python 3.13+ 標準函式庫（零 pip 套件、零雲端服務）。前端介面零 npm 建置步驟，唯一依賴為本機打包之 MIT 開源套件 `@xterm/xterm` 與 `@xterm/addon-fit`（置於 `web/vendor/xterm/`，鎖定版本並由單元測試持續驗證固定之 SHA-256 完整性雜湊，嚴格拒絕 CDN 外部載入，維持嚴格 CSP `script-src 'self'`）。
  需要 Python 3.13 以上（Agent CLI 版本檢查需要 `os.waitid`，macOS 從 3.13 才提供）；macOS 系統內建的 `/usr/bin/python3` 是 3.9，會啟動失敗，請改用 Homebrew 等較新的 `python3`。
- **有來源才顯示**：每項資訊標示「作者說明／自動整理／執行觀察／未提供」，查不到就寫未知。

## 安裝與使用

### 下載 App（建議）

1. 從 [最新版本](https://github.com/sidphoto/vbear/releases/latest) 下載 `VBear-<版本>-arm64.dmg`，打開後把 **VBear** 拖進「應用程式」。
   需要 Apple 晶片（M1 以後）的 Mac、macOS 13 以上；App 已內含 Python，不必另外安裝。
2. **第一次打開**：App 目前沒有 Apple 開發者簽章，macOS 第一次會拒絕開啟。請到「系統設定 → 隱私權與安全性」，
   往下找到 VBear，按「強制打開」。只需要做一次。

也可以用 Homebrew：`brew install --cask sidphoto/tap/vbear`

結束 App 會關掉視窗和伺服器；你開的終端機會繼續執行，下次打開 VBear 時還在。

### 從原始碼執行

需要 macOS、Python 3.13 以上；Profile 啟動另需 Claude Code。尚未驗證的版本也能啟動，但權限標示會是「未驗證」，啟動前要勾選知悉；啟動對話框的「驗證這個版本」會用你的 Claude 帳號做 2 次小型模型呼叫來驗證（約 1–3 分鐘），通過後這個版本在你的 Mac 上就算已驗證。不需要安裝任何套件。

```sh
git clone https://github.com/sidphoto/vbear.git && cd vbear
python3 -m vbear serve --open   # 啟動並開啟 http://127.0.0.1:7788
python3 -m vbear launch         # 背景啟動（若尚未執行）並開啟瀏覽器
python3 -m vbear doctor         # 檢查來源與 VBear runtime 連線
python3 -m vbear scan           # 重新掃描並輸出摘要
```

Agent 終端由 `vbear runtimed`（VBear runtime 背景程序）執行；主控台需要時會自動啟動它，主控台關閉後它會繼續執行，
已開啟的 Terminal 不會因此中斷。

## 畫面

| 頁面 | 內容 |
|---|---|
| 我的工作台 | 等你回覆／待查看的 Terminal、用自然語言找技能、最近專案、有問題的技能 |
| 終端工作台 | 統一三欄版面（左側角色、中間真實 Terminal、右側 Task Card 與 G/P/A/T 治理骨架）、專注模式、可收合側欄 |
| 技能庫 | 卡片／列表、中英文搜尋、依狀態／工具／用途／範圍／我的標籤篩選；詳情含我的註記、同名比較、引用檔、原始 SKILL.md、使用紀錄 |
| Agent 團隊 | 工作中的 Terminal（VBear runtime 管理的 Claude／Codex，角色名、本次模型、本次用過的技能、開啟終端）與角色設定（主代理、子代理） |
| 專案 | 依 git 儲存庫歸類：專案 → 各角色 Terminal |
| 設定 | 掃描來源開關、使用紀錄範圍、進階模式、資料流向說明 |

## 資料從哪裡來

| 資訊 | 來源 | 強度 |
|---|---|---|
| 技能內容 | `SKILL.md` front matter 與章節 | 作者說明／自動整理 |
| Claude 外掛是否生效 | `~/.claude/plugins/installed_plugins.json` + `settings.json` 的 `enabledPlugins` + 外掛 `plugin.json` 的載入路徑 | 設定檔 |
| Codex 技能是否生效 | `~/.codex/config.toml` 的 `skills.config` | 設定檔 |
| 技能上游 | `~/.agents/.skill-lock.json` | 設定檔 |
| 工作中的 Terminal | VBear runtime 的 session 清單 | 執行觀察 |
| 工作中／等你回覆 | Profile 啟動的 Claude Code 自己設定的終端標題（只保留開頭符號，不保存標題文字；只有版本有實測紀錄時採用，其他顯示「狀態未知」） | 執行觀察（Agent 自己回報） |
| 本次模型、本次用過的技能 | Claude `~/.claude/projects/*/*.jsonl` 的 Skill 呼叫；Codex `~/.codex/sessions` 讀取 SKILL.md 的工具呼叫 | 執行觀察（Codex 為較弱的「讀取過技能檔」） |
| 用途分類 | `vbear/categories.py` 關鍵字表 | 自動整理 |

使用紀錄只擷取技能名稱、模型名稱、工作階段 ID、工作目錄與時間；對話內容不會被讀出或保存。可在設定頁關閉。

`/api/live` 只帶出 Terminal 的指令名稱、工作目錄與狀態；這份資料只在本機 API 中傳遞，不寫入狀態目錄。

## 我的註記

在技能詳情頁可以加上易懂名稱、標籤與備註，搜尋時會一併比對，卡片會顯示你取的名稱並保留原名。

- 只存在 `~/.vbear/annotations.json`，不會修改任何技能檔。
- 以「工具＋呼叫名稱」為鍵（例如 `claude:vercel:vercel-firewall`）：外掛升級後註記仍在；Claude 與 Codex 的同名技能各自獨立。
- 畫面上標示為「我的註記」，和作者說明、自動整理分開。

## 技能狀態

| 狀態 | 意思 |
|---|---|
| 可使用 | 位於工具的載入範圍，且沒有被停用 |
| 已停用 | 已安裝，但設定中關閉 |
| 舊版快取 | 舊版本的快取副本，目前安裝的是較新版本 |
| 附帶・不載入 | 隨外掛附帶，但不在外掛的技能載入路徑 |
| 未安裝 | 外掛市集中的來源副本 |
| 無法確認 | 沒有設定檔能證明它是否被載入；或技能檔沒有被讀取（超過 256KB、或連到技能目錄之外），無法確認能否正常載入 |

## 安全

- 只綁定 `127.0.0.1`；Host 標頭必須是本機位址（防 DNS rebinding）。
- 寫入類請求需要自訂標頭與同源 Origin（防 CSRF）；只接受白名單設定鍵，並檢查值：
  `language` 只接受 `zh-TW`；`project_roots` 必須是絕對路徑（可用 `~`），不接受 `/`、家目錄或其上層；
  註記只能加在目前索引中存在的技能，總數上限 5000 筆。
- 讀取 API 若帶 `Sec-Fetch-Site` 且不是 `same-origin`／`none` 一律拒絕（其他網站、同機其他埠的頁面都讀不到）；
  會強制查詢 VBear runtime 的 `/api/live?force=1` 另外需要自訂標頭。
- 嚴格 CSP，技能內容一律以純文字渲染（無 `innerHTML`）。
- 檔案只能依技能 ID 或「已驗證存在於該技能目錄內」的引用檔讀取。`SKILL.md` 本身若是指向來源目錄之外的符號連結，
  掃描與讀取時都不會打開它（來源目錄本身是符號連結時，以實際路徑比對，不受影響）。
- 掃描有界：單檔超過 256KB 不解析、front matter 巢狀超過 32 層停止解析；任一技能解析失敗只會變成該技能的警告，不會中斷整次掃描。
- 憑證遮蔽：front matter 鍵名像機密（`api_key`、`apiKey`、`access_token`、`password`、`auth` 等）整個值遮蔽；
  內文的 `名稱: 值`／`名稱=值`（含 JSON 引號）遮到行尾；另外辨識 `sk-`／`sk-ant-`、GitHub、AWS `AKIA…`、Slack `xox?-`
  與整塊 PEM 私鑰。遮蔽套用在索引、章節、原始 SKILL.md、引用檔與警告文字，寧可多遮（例如整行說明）也不漏。
  資料庫鍵（`primary_key`、`sort_key`）不遮。只是「描述」機密的名稱（`max_tokens`、`token_file`、`api_key_env`、`secret_name`）
  只有在值明顯無害時才顯示：數字、路徑、網址（不含查詢字串）、`ENV_VAR` 名稱或布林值；其他值一律遮蔽（例如 `secret_file: hunter2`）。
- Profile 管理的 Claude 啟動：先 `POST /api/native/agent-previews` 取得預覽（七項權限的實際套用程度與證據），確認後
  `POST /api/native/agent-launches` 才啟動；預覽單次使用、5 分鐘過期，設定或 Profile 變動回 409。不接受 argv、環境變數、設定或憑證。
  Bash 工具的寫入由 Claude 沙盒限制在工作目錄與該 session 的暫存區；讀取不隔離；使用者在終端以 `!` 直接執行的指令不經沙盒。
- **終端工作台（Terminal Workbench）安全模型與資料流向**：
  - **資料流向與本機邊界**：終端畫面走本機 SSE 串流 (`GET /api/term/<pane>/stream`)，輸出僅於記憶體中轉送，不落地儲存，絕不上傳外部或雲端。
  - **端點防護與 Fetch-SSE**：瀏覽器不使用原生 `EventSource`（因其無法攜帶自訂標頭），改由原生 `fetch()` 串流。端點防護精確區分：串流讀取 (`GET /api/term/<pane>/stream`) 透過 Host 檢驗、強制 `X-VBear: 1` 自訂標頭及 Fetch Metadata (`Sec-Fetch-Site`) 阻擋跨站讀取；操作與輸入寫入 (`POST /api/term/<pane>/...`) 則透過 Host 檢驗、`X-VBear: 1` 標頭及同源 `Origin` 檢驗完整防禦 CSRF。
  - **觀看／接管／釋放／放棄操作生命週期**：
    - 預設為「觀看模式 (Observe)」：僅轉送畫面，不接收網頁鍵盤輸入，不送出任何輸入給 Agent。
    - 「接管操作 (Takeover)」：使用者於畫面上確認接管風險後，透過 `POST /api/term/<pane>/control` 取得輸入控制權與隨機的不透明 generation token，方可透過 `POST /api/term/<pane>/input` 送出鍵盤輸入（客戶端限速批次傳送，單次上限小於伺服端 4096 位元組限制，連線中斷或錯誤不重放歷史輸入）。
    - 「釋放控制 (Release)」：使用者主動釋放輸入通道，退回僅觀看模式。
    - 「放棄與客戶端離開 (Abandon)」：當客戶端在接管中途卸載或跳頁時，發出帶 token 的 abandon 請求停止該頁的連線；若已被更新的操作接替，後端比對 token 不符即原子性 no-op，絕不誤停新的連線。
    - 「關閉 Session」：結束 Terminal 內的程式；Profile 管理的 session 會在所有程序確認結束後清除其暫存區與設定，否則保留待檢查。
  - **單一控制者**：同一時間只有一個分頁能接管；其他分頁接管時，原控制者會自動改回僅觀看。UI 與確認對話框均有說明。
  - **CSP 策略與 style-src 'unsafe-inline' 權衡說明**：
    - `script-src 'self'`：嚴格禁止任何 CDN、任何 inline script 與 `eval`。
    - `style-src 'self' 'unsafe-inline'`：xterm.js 5.5.0 核心需要動態插入 `<style>` 元素（`_injectCss`）以及在 row 元素動態設定 inline style（`element.setAttribute('style', ...)`）以呈現 ANSI 24 位元真彩色 (Truecolor)。若限制為純 `'self'`，瀏覽器會阻擋真彩色並退回黑白預設色。由於 VBear 前端完全無使用者可控之 HTML/CSS injection sink（所有動態內容皆經 safe DOM APIs / textContent 或 xterm 位元組解碼），開放 `style-src 'unsafe-inline'` 是受控且必要的安全權衡。
  - **同 Pane 重新連線與全畫面重繪 (Same-Pane Continuity)**：
    - 串流在重連或初次連線時先送出 `full: true` 的重播畫面（最近一段輸出），其中可能含視窗清除與游標定位，但不一定包含 DECSET 1049 (`\x1b[?1049h`)。
    - 前端不呼叫破壞性的 `term.reset()`，而是由 `handleTerminalFrame` 執行 `scrollToBottom()` 後直接寫入 decoded ANSI 位元組，以保留 Pane 正在執行的 Alternate Buffer 狀態並避免重連畫面黏在 Normal Buffer。
    - 串流只重播最近一段輸出，不是完整歷史。因此網頁終端使用 `scrollback: 0` 並明示「開啟時只重播最近一段輸出，不提供完整的回捲歷史」。
  - **xterm.js 安全配置**：配置 `linkHandler: null` 明確禁用自動連結識別與開啟、配置 `windowOptions: {}` 禁止視窗操控序列；套件使用 xterm core 5.5.0 本機打包，未載入任何剪貼簿插件（無 OSC 52 剪貼簿寫入整合）與連結插件；前端 DOM 一律經由純文字節點與 safe DOM APIs 操作，嚴格杜絕 `innerHTML` 注入風險。
  - **三欄工作台、任務卡 (Task Card) 與 G/P/A/T 治理基礎**：
    - **統一三欄版面與專注模式**：左欄 Agent / Role / Skills 列表與切換、中欄真實 Terminal、右欄 Task Card 與 G/P/A/T 資訊；支援兩側獨立收合與一鍵「專注模式」（收合兩側、Esc 退出）。切換顯示中之 Agent 焦點**絕不重啟該既有 session**；離開分頁時自動中止串流以防止孤兒行程。若切換當下正處於接管操作模式，前端會送出**帶 token 的 abandon**（而非無條件的 release）：只有在該 token 仍與伺服器目前的 session 相符時才會停止，避免在快速切換或多分頁競速下，誤將別處剛完成的新接管操作奪回為僅觀看模式。
    - **任務卡本機儲存與狀態證明**：儲存於 `~/.vbear/tasks.json`（0600 原子寫入、目錄 0700），跨執行緒與**跨行程**（`flock` 檔案鎖，涵蓋整個讀-改-寫區間）保護，讀取路徑遇到損毀 JSON、結構不符 schema 之項目、或任何非「檔案不存在」之讀取錯誤（權限、符號連結、硬連結等）一律**拒絕靜默降級為空集合**並隔離原檔待人工復原，避免後續寫入誤將真實資料覆寫遺失。固定 Goal/Scope/Out of Scope/Deliverables/Acceptance Criteria/Evidence 六核心欄位與步驟/成品追蹤。狀態證明（Status Provenance）明確分離 Agent 回報完成、自動化測試通過與介面核准三維度；本主控台**沒有任何具身份驗證能力的驗證者**，因此絕不推導或顯示治理層級的「已驗證 (Verified)」狀態——`provenance.verified` 恆為 `false`，僅有誠實命名的 `provenance.verification_asserted`（`status` 對應 `verification_asserted`）代表「測試與核准兩欄皆已透過此網頁/API 自我回報為通過」的**自我聲稱**，並非正式驗證；`status`/`verification_asserted` 欄位**無法**由用戶端直接偽造，僅能由實際通過測試與核准後推導產生。誠實揭露：本主控台無使用者身份驗證，三欄皆為透過此網頁/API 自行填寫之自我回報值（含「核准」欄位在內），並非經密碼學或帳號驗證之真實人類審查記錄；每一欄位記錄最後變更時間（`set_at`）供稽核。
    - **追蹤關聯與未來規則邊界**：任務卡與 Session 關聯**僅為本機追蹤記錄，絕非 Context 注入**；變更 Task Card 並欲作為 Effective Context 套用時，**必須開啟全新 Agent Session**。
    - **結果綁定 commit、結案理由、交接與處理狀態**（做法參考 OpenRig，見 [docs/evidence/openrig-learnings.md](docs/evidence/openrig-learnings.md)）：
      - 任務卡可以設定工作目錄。測試設成通過、或核准時，伺服器讀取該目錄當時的 commit 一併記錄（用戶端無法指定）；之後每次讀取都會比對，commit 改變就顯示「結果對應的版本已變更」，不再算聲稱驗證通過。讀取 commit 時**不執行 `git`**，直接讀 `.git` 內的檔案，因為 repo 設定能讓 git 執行任意程式，而受管 Agent 可能寫得到 `.git`。
      - 把 Agent 回報狀態標成「已回報完成」或「阻塞」時，必須選擇結案理由（完成沒有後續、交給下一位、被取代、取消、拒絕；卡在某人或某事、已上報），需要對象的理由必須填對象。規則在資料層強制，舊資料照常讀取並標示「缺少結案理由」。
      - 「交接給…」在同一次寫入裡把原卡標成「已交接」並建立接手的新卡：沿用目標、範圍、驗收條件與工作目錄，狀態證明從頭開始，並記錄交接鏈。交接鏈無法從一般 API 修改。
      - 「處理狀態」（尚未認領、處理中、停在等你、中斷、阻塞中、已結案、未知）由關聯的 Terminal 即時推算，不存檔、也不接受用戶端設定。
    - **G/P/A/T 唯讀介面骨架**：展示 Global 底線與 Project 契約骨架。本階段無 Policy Compiler、無自動注入、不掃描不修改 `~/.codex`。
- 請求內容：`Content-Length` 只接受純數字；超過 64KB 回 413 並關閉連線；整個請求內容必須在 15 秒內送完，
  逐位元組拖延的連線會被切斷。標頭階段只有每次讀取 15 秒的逾時，沒有總時限。
- 設定檔損毀時：不覆寫原檔（先備份為 `config.json.bak`）；掃描範圍改為「全部關閉」而不是預設值，
  拒絕重新掃描（保留先前的索引），並在工作台、技能庫與設定頁顯示警告。
- 啟動器用 `Server` 標頭加上回應格式辨認 7788 上的是不是 VBear；這只能分辨別的服務，不是身分驗證。
- 狀態目錄權限 `0700`、其中檔案 `0600`（啟動時也會收緊舊版建立的檔案）；暫存檔名唯一，CLI 掃描與伺服器重新掃描同時寫入不會互相覆蓋。

## 狀態目錄

`~/.vbear/`（可用 `VBEAR_HOME` 覆寫）：`config.json`、`index.json`、`usage-cache.json`、`annotations.json`、`tasks.json`、`agent_profiles.json`、`server.log`、
VBear runtime 的 `runtime.sock`／`runtimed.lock`／`runtimed.log`，以及 Profile 管理 session 的 `sessions/<launch-id>/`（session 暫存區在 `/private/tmp/sc-<隨機>/`）。索引超過 24 小時會提示過期；程式更新後舊格式索引會自動重掃。

## 結構

```
vbear/
  scan/claude.py codex.py shared.py   來源適配器
  scan/document.py frontmatter.py     SKILL.md 解析（無 PyYAML）
  scan/usage.py                       使用證據
  runtime/daemon.py native.py         VBear runtime 背景程序與用戶端（PTY session）
  runtime/agent_sessions.py proctrack.py  Profile 管理 session 的設定／暫存區／清理，與後代程序追蹤
  runtime/cli_versions.py             Agent CLI 版本檢查
  agent_launch.py                     啟動前預覽與確認、七項權限標籤
  index.py                            靜態索引＋即時視圖
  annotations.py                      我的註記（別名、標籤、備註）
  tasks.py                            任務卡（Task Card MVP、狀態證明、結果綁定 commit、結案理由、交接、本機儲存）
  git_head.py                         不執行 git，直接讀 .git 檔案取得目前的 commit
  activity.py                         Agent 狀態判斷（工作中／等你回覆／未知）與判斷依據
  runtime/osc_title.py                受管 Claude 的終端標題分類（不保存標題文字）
  server.py                           本機 HTTP API
web/                                  介面（原生 HTML/CSS/JS）
tests/                                Python 單元測試，全部使用合成的 HOME；實際筆數以 `python3 -m unittest discover -s tests` 執行結果為準，不在此處寫死固定數字
tests/frontend/                       前端行為測試（node＋合成 DOM，不是瀏覽器測試）
```

## 授權

[MIT](LICENSE)。內附的 xterm.js 與 fit addon（`web/vendor/xterm/`）為其作者的 MIT 授權，見 `web/vendor/xterm/LICENSE`。

## 社群與支援

- 問題與想法：[GitHub Discussions](https://github.com/sidphoto/vbear/discussions)
- 錯誤回報與功能需求：[GitHub Issues](https://github.com/sidphoto/vbear/issues)
- 資安問題請**不要**開公開 issue，見 [SECURITY.md](SECURITY.md)。

中文或英文皆可。開發方式見 [CONTRIBUTING](.github/CONTRIBUTING.md)。
