# SID Console for Herdr

給 [herdr](https://github.com/herdrdev/herdr) 使用者的本機主控台外掛：把分散在各處的 Skill、Agent 角色與工作中的 Terminal
整理成一般人看得懂的畫面。對應規劃書 P1（互動原型）＋ P2（唯讀技能庫）＋ P3（Agent 關聯）。

本專案是獨立的第三方外掛，與 herdr 官方無關；「herdr」為其原作者的產品名稱，這裡只用來說明相容對象。

- **本機、唯讀**：只讀取你選的來源，不修改任何技能或角色檔案，不執行技能內的腳本。
- **零相依**：只用 Python 3.11+ 標準函式庫，沒有 npm / pip 套件，不連外部服務。
  需要 Python 3.11 以上（用到 `tomllib`）；macOS 系統內建的 `/usr/bin/python3` 是 3.9，會啟動失敗，請改用 Homebrew 等較新的 `python3`。
- **有來源才顯示**：每項資訊標示「作者說明／自動整理／執行觀察／未提供」，查不到就寫未知。

## 使用

```sh
python3 -m sidconsole serve --open   # 啟動並開啟 http://127.0.0.1:7788
python3 -m sidconsole doctor         # 檢查來源與 herdr 連線
python3 -m sidconsole scan           # 重新掃描並輸出摘要
python3 -m unittest discover -s tests   # 前端行為測試另需 node
```

從 herdr 內開啟（會註冊到 herdr 的全域外掛設定）：

```sh
herdr plugin link /path/to/sid-console
herdr plugin action invoke sid.console.open
```

## 畫面

| 頁面 | 內容 |
|---|---|
| 我的工作台 | 等你回覆／待查看的 Terminal、用自然語言找技能、最近專案、有問題的技能 |
| 技能庫 | 卡片／列表、中英文搜尋、依狀態／工具／用途／範圍／我的標籤篩選；詳情含我的註記、同名比較、引用檔、原始 SKILL.md、使用紀錄 |
| Agent 團隊 | 工作中的 Terminal（角色名、本次模型、本次用過的技能、切換）與角色設定（主代理、子代理） |
| 專案 | 依 git 儲存庫歸類：專案 → herdr workspace → 各角色 Terminal |
| 設定 | 掃描來源開關、使用紀錄範圍、進階模式、資料流向說明 |

## 資料從哪裡來

| 資訊 | 來源 | 強度 |
|---|---|---|
| 技能內容 | `SKILL.md` front matter 與章節 | 作者說明／自動整理 |
| Claude 外掛是否生效 | `~/.claude/plugins/installed_plugins.json` + `settings.json` 的 `enabledPlugins` + 外掛 `plugin.json` 的載入路徑 | 設定檔 |
| Codex 技能是否生效 | `~/.codex/config.toml` 的 `skills.config` | 設定檔 |
| 技能上游 | `~/.agents/.skill-lock.json` | 設定檔 |
| 工作中的 Terminal | `herdr agent/workspace/tab list` | 執行觀察 |
| 本次模型、本次用過的技能 | Claude `~/.claude/projects/*/*.jsonl` 的 Skill 呼叫；Codex `~/.codex/sessions` 讀取 SKILL.md 的工具呼叫 | 執行觀察（Codex 為較弱的「讀取過技能檔」） |
| 用途分類 | `sidconsole/categories.py` 關鍵字表 | 自動整理 |

使用紀錄只擷取技能名稱、模型名稱、工作階段 ID、工作目錄與時間；對話內容不會被讀出或保存。可在設定頁關閉。

`/api/live` 會帶出 herdr 回報的 Terminal 標題（`terminal_title_stripped`）；Agent 常會自動把標題設成目前任務摘要，所以畫面上可能看到任務內容的片段。這份資料只在本機 API 中傳遞，不寫入狀態目錄。

## 我的註記

在技能詳情頁可以加上易懂名稱、標籤與備註，搜尋時會一併比對，卡片會顯示你取的名稱並保留原名。

- 只存在 `~/.sid-console/annotations.json`，不會修改任何技能檔。
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
  會觸發 herdr 呼叫的 `/api/live?force=1` 另外需要自訂標頭。
- 嚴格 CSP，技能內容一律以純文字渲染（無 `innerHTML`）。
- 檔案只能依技能 ID 或「已驗證存在於該技能目錄內」的引用檔讀取。`SKILL.md` 本身若是指向來源目錄之外的符號連結，
  掃描與讀取時都不會打開它（來源目錄本身是符號連結時，以實際路徑比對，不受影響）。
- 掃描有界：單檔超過 256KB 不解析、front matter 巢狀超過 32 層停止解析；任一技能解析失敗只會變成該技能的警告，不會中斷整次掃描。
- 憑證遮蔽：front matter 鍵名像機密（`api_key`、`apiKey`、`access_token`、`password`、`auth` 等）整個值遮蔽；
  內文的 `名稱: 值`／`名稱=值`（含 JSON 引號）遮到行尾；另外辨識 `sk-`／`sk-ant-`、GitHub、AWS `AKIA…`、Slack `xox?-`
  與整塊 PEM 私鑰。遮蔽套用在索引、章節、原始 SKILL.md、引用檔與警告文字，寧可多遮（例如整行說明）也不漏。
  只是「描述」機密的名稱不遮：數量或上限（`max_tokens`、`token_count`）、位置或名稱（`token_file`、`api_key_env`、`secret_name`）、
  資料庫鍵（`primary_key`、`sort_key`）；它們的值若本身像 token，仍會被上面的樣式遮住。
- 「切到這個 Terminal」只呼叫 `herdr agent focus`，不會送出任何輸入給 Agent；目標必須是目前 herdr 回報的 pane／terminal ID，
  且不可以 `-` 開頭（`herdr agent focus` 只接受單一參數，沒有 `--` 分隔）。
- 請求內容：`Content-Length` 只接受純數字；超過 64KB 回 413 並關閉連線；整個請求內容必須在 15 秒內送完，
  逐位元組拖延的連線會被切斷。標頭階段只有每次讀取 15 秒的逾時，沒有總時限。
- 設定檔損毀時：不覆寫原檔（先備份為 `config.json.bak`）；掃描範圍改為「全部關閉」而不是預設值，
  拒絕重新掃描（保留先前的索引），並在工作台、技能庫與設定頁顯示警告。
- 啟動器用 `Server` 標頭加上回應格式辨認 7788 上的是不是 SID Console；這只能分辨別的服務，不是身分驗證。
- 狀態目錄權限 `0700`、其中檔案 `0600`（啟動時也會收緊舊版建立的檔案）；暫存檔名唯一，CLI 掃描與伺服器重新掃描同時寫入不會互相覆蓋。

## 狀態目錄

`~/.sid-console/`（可用 `SID_CONSOLE_HOME` 覆寫）：`config.json`、`index.json`、`usage-cache.json`、`annotations.json`、`server.log`。索引超過 24 小時會提示過期；程式更新後舊格式索引會自動重掃。

## 結構

```
sidconsole/
  scan/claude.py codex.py shared.py   來源適配器
  scan/document.py frontmatter.py     SKILL.md 解析（無 PyYAML）
  scan/usage.py                       使用證據
  bridge/herdr.py                     herdr CLI 橋接
  index.py                            靜態索引＋即時視圖
  annotations.py                      我的註記（別名、標籤、備註）
  server.py                           本機 HTTP API
web/                                  介面（原生 HTML/CSS/JS）
tests/                                84 項測試，全部使用合成的 HOME
tests/frontend/                       前端行為測試（node＋合成 DOM，不是瀏覽器測試）
```
