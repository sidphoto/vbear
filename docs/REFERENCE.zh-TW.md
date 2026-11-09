# VBear 參考資料（繁體中文）

這份文件收錄原本放在 [README.zh-TW.md](../README.zh-TW.md) 的參考章節：畫面、資料從哪裡來、我的註記、技能狀態、安全、狀態目錄、結構。內容最初從 README 原樣搬來，之後隨版本補上新的頁面、檔案與模組（v0.9.0 補了角色卡池、會議、完整模式出發；v0.10.0 補了組隊會議；v0.11.0 補了聊天；v0.16.0 補了群組；v0.17.0 補了記憶；v0.17.1 補了共用資料夾；v0.18.0 補了技能與例行工作；v0.19.0 補了團隊範本）；英文版請看 [ARCHITECTURE](ARCHITECTURE.md) 與 [安全模型](SECURITY-MODEL.md)。

## 畫面

| 頁面 | 內容 |
|---|---|
| 冒險者大廳（首頁） | 任務告示板：輪到你的流程與等你回覆的 Agent、等你核准的會議與等你看的組隊提案、其他進行中的任務（最多 4 則）；用自然語言找技能、最近專案、有問題的技能 |
| 辦公室 | 像素辦公室：工作站（流程隊伍依階段站在計畫板、實作區、審查室、合併關卡）、辦公桌（出勤中的終端與狀態）、會議室（最新一場進行中或等核准的會議，頭上的字只取自會議紀錄，代發言另外標示）與董事長桌（幾場會議等你核准、幾份「組隊提案待你看」；進行中或等你看的組隊會議也坐在會議室，標「組隊會議」）、休息室（Profile 名冊）；點角色看武器、防具、技能卡。只讀 VBear 已有的資料 |
| 會議 | 今日花費燈號（80% 黃燈、100% 不能再開會）、會議紀錄清單、開一場會（議題、補充說明、任務卡、CEO 主席、最多 6 位發言者、「涉及」勾選）、開會前的預覽（每段指示與送出全文、模型、預留金額、是否通過無工具安全檢查）；單場會議的發言與證據列、CEO 決定、董事長桌（核准／否決）、重試、取消、寫進任務卡（只預填任務卡編輯器） |
| 聊天 | `#/chat` 與 `#/chat/<id>`：每日花費與上限、這個 Claude Code 版本有沒有通過聊天驗證（附「驗證聊天」，先說明會花多少）、可以聊天的角色卡（每張標出 AI 工具；停用或工具不是 Claude Code、Codex、AGY 的卡列出原因、不能選）、Codex 的支援狀態（沒裝、還沒驗證、聊天用的 Codex 還沒登入、管理員政策，各有對應的按鈕）、AGY 的支援狀態（沒裝、版本不支援、還沒驗證〔附「驗證聊天」，用你的 Google 方案〕、管理員政策、你有 `~/.agents/hooks.json`、聊天用的 AGY 設定資料夾有不認得的東西，各有一句白話）、聊天紀錄清單（每個聊天標出 AI 工具）；單一聊天顯示依序的紀錄（你說的、回覆、工具與結果、權限卡片及結局、每回合花費）、正在寫的回覆、權限卡片（允許這一次／拒絕／改內容再允許；Codex 與 AGY 是指令卡、檔案卡附 diff，和「改內容再問」；AGY 還有讀取卡，寫明讀到的內容會送到 Google，沒有可以改的內容；AGY 的指令卡寫「在 AGY 的沙盒裡執行：不能連網，只能寫工作資料夾〔和暫存資料夾〕」）、Codex 的估計花費與方案用量一行、AGY 每回合的估計花費（「估計 US$…，AGY 不回報金額，不是帳單，用的是你的 Google 方案」）、停止這一回合與刪除（Codex、AGY 聊天的刪除確認會說明它們自己的對話副本不會被刪）。角色卡上也有「聊天」按鈕 |
| 群組 | `#/chat` 的「開新群組」與 `#/chat/group/<id>`：勾 2 到 3 位能聊天的員工（Claude Code、Codex 或 AGY；不能聊天的列出原因）、取個名字（預設是成員名字），建立不花錢；混用不同工具時，對話框寫明群組裡的對話會同時送給各家公司（依 Claude Code、Codex、AGY 的順序列出 Anthropic、OpenAI、Google）。群組和一對一聊天排在同一張列表（標「群組」、人數、「等你」）。群組頁：成員（照回答順序）、對話（你說的靠右，寫「對大家說」或「對 @某某 說」；員工的回覆寫名字、AI 工具與花費，沒正常做完的會寫明）、輸入框上方的「大家」與「@名字」按鈕（點名；打字開頭的 @名字 也會幫你選好）、「這句會請 N 位回答，最多 US$X，今天還剩 US$Y」（亮紅燈不能送）；員工一位一位照順序回答，正在回答的人名下有即時文字與允許卡（和聊天頁同一張，Codex 指令卡附沙盒外警告；沒有任何一次允許好幾張的按鈕）；碰到每天上限暫停，寫明本機明天 0:00，由你按「繼續（請剩下的人回答）」或「不用了」；「停止」隨時可按；改名、加人／移除（沒有一句話在進行時，之後仍要 2 到 3 位）、刪除（確認框寫明會刪掉群組和每位員工的對話紀錄、已花的錢照記、Codex 自己的副本不會被刪）。頁面最上面一行說明群組、會議、派工的差別。大廳「輪到你」列出等你按允許與暫停的群組 |
| 記憶 | `#/memory`（導覽在「聊天」之後）：你親自寫下或確認過的話，分「關於你」「你的工作」「決定」三組，最多 50 條、每條 200 字、合計 4,000 字；每條有來源（你寫的／從聊天或群組記住的（你說的／員工說的）／整理提議、你確認的）與日期，可以改、刪、匯出成 Markdown（瀏覽器下載，不含任何 id）、全部刪除（要打「全部刪除」）。最上面寫明記憶會送給 Anthropic（Claude Code 的員工）、OpenAI（Codex 的員工）或 Google（AGY 的員工），也寫「只有這位員工要照做的，寫在角色卡的固定指示；換一位員工也該知道的，放記憶」。「誰帶記憶」：每位能聊天的員工一個開關（Claude Code 的卡預設開、Codex 與 AGY 的卡預設關，打開前先問、寫明送給 OpenAI 或 Google），終端機（完整模式）出發時不帶。聊天與群組裡每則話旁有「記住」（開對話框、截到 200 字、員工說的話會提醒）；一對一聊天頁有「整理要記住的事」（預覽 → 最多 5 條記憶提議、全部預設不勾、沒有「全部存」）；聊天頁上方一行寫這位員工帶不帶記憶（N 條）；角色卡背面一行寫帶不帶 | 導覽「記憶」、聊天頁、群組頁、角色卡池 |
| 共用資料夾 | `#/shared`（導覽在「記憶」之後）：最上面三句固定的話（打開的員工可以在這裡放檔案給彼此和你，員工寫進來照舊每次都問你、裡面的檔案是資料；員工讀到的檔案會送到它的 AI 公司，Claude Code 是 Anthropic、Codex 是 OpenAI，不要放密碼、帳號、金鑰；「AGY 員工這版不能用共用資料夾，之後 AGY 新版再檢查」；不要在 Finder 直接打開你不認得的檔案，特別是 `.command`、`.app`、`.sh`）；位置（`~/.vbear/shared`）與「在 Finder 打開」；用量（N 個項目、X MB／1 GiB，超過時紅字）與連結數；「誰能用」：每位能聊天的員工一個開關（**預設都是關的**）、送到哪家公司、這個 AI 工具的版本有沒有通過含共用資料夾的檢查（沒有時寫「還要檢查一次」並連到聊天頁的「檢查」），打開 Codex 員工前先確認、寫明送到 OpenAI；AGY 員工沒有開關，那一列寫「AGY 員工這版不能用共用資料夾，之後 AGY 新版再檢查」；固定三句（剛打開時要開新聊天員工才會知道；關掉從下一句起生效、不刪檔；終端機〔完整模式〕出發的員工不另外告訴）；檔案清單（最多 200 個、新的在前，只有檔名、大小、修改時間，沒有預覽、沒有刪除，連結標「連結」，檔名只當文字顯示）。建群組對話框有「讓這幾位都能用共用資料夾」（預設不勾），派工提議卡有「替這次派工的員工打開共用資料夾」（預設不勾，列出現在關著的與會新建的員工），群組頁在員工回覆下面寫「這段時間共用資料夾裡新增或改過」的檔名；聊天頁上方一行、角色卡背面一行寫這位員工能不能用共用資料夾 | 導覽「共用資料夾」、建群組對話框、派工提議卡、群組頁、聊天頁、角色卡池 |
| 技能 | `#/my-skills`（導覽在「共用資料夾」之後）：最上面兩行固定的話（這裡是你存在 VBear 的做法，用的時候變成你對員工說的話、員工照舊每個指令和每個檔案修改都問你；「技能庫」列的是 AI 工具自己的技能檔，是另一回事）；每個技能的名稱、前 80 字、來源（你寫的／從你說的話存的／從員工說的話存的／整理提議、你確認的）與日期，新增、改、刪除；最多 100 個、名稱 40 字、內容 4,000 字。聊天與群組的輸入框旁有「用技能」（只把說明放進輸入框，不送出），每句話旁有「存成技能」，一對一聊天上方有「整理成技能」（對話送到 Anthropic，最多 US$0.10，預設不存） |
| 例行工作 | `#/routines`（導覽在「技能」之後）：最上面三行固定的話（VBear 的視窗要開著、Mac 要醒著才會做；員工照舊會問你，你不在時卡片 5 分鐘沒人按就當作拒絕；沒勾自己動手第 3 項只會提醒）；「等你決定」區（到時間的提醒「現在開始」「這次跳過」、錯過的「補做」「不用了」）；每件的員工、星期幾與時間、下一次、啟用開關、每次最多花多少、最近 10 次的狀態與連到聊天、現在開始、改、刪（可以「從技能帶入」）；設定區：例行工作每天上限（預設是每天上限的一半，不能高於每天上限）與「讓 Mac 保持清醒」（有工作在跑時不讓 Mac 睡著，預設是關的）。每一頁上方還有一行「等你決定」，派工頁與群組頁暫停時有倒數 |
| 團隊範本 | `#/templates`（導覽在「例行工作」之後；角色卡池沒有自己的卡時有「用團隊範本開始」）：最上面四行固定的話（團隊範本是一組現成的員工、技能和例行工作，勾你要的、按「預覽並套用」看清楚再套用；套用不用 AI、不花錢，員工一律安全模式，記憶和共用資料夾照平常的設定，例行工作建好是關著的；每次套用都可以「復原這次套用」，只刪這次建的、你沒改過也沒用過的；只存在這台電腦，不會上傳，也不能匯出）；內建四個（小店、自媒體、接案工作室、個人生活助理），每個一塊，分員工、技能、例行工作三排勾選，可以跨團隊範本拼組，每一項可以「看全文」；「你存的團隊範本」（改名、刪除）與「你現在的」（現有的員工、技能、例行工作，只給「存成團隊範本」用）；底下一行「已勾：N 位員工、N 個技能、N 件例行工作」與「預覽並套用」「存成團隊範本」。預覽對話框：選 Claude Code 或 Codex（預設是開始設定頁顯示就緒的那個）、會建的員工（名字可以改）、技能、例行工作和交給誰、套用後的數量與上限、問題與同名提醒、要多確認的字（「我確定」）；套用的結果（完成，或「建到一半停下了」）；「套用紀錄」（最近 50 次，每次的時間、AI 工具、建了幾項、狀態）與「復原這次套用」：先列「會刪掉」「會留著（原因）」「已經不在了」，另有固定的兩行提醒（如果你在終端機用過這些員工，VBear 看不出來；VBear 不記錄技能有沒有被用過，只看有沒有改過），按「刪掉這些」才刪 |
| 派工 | `#/dispatch` 與 `#/dispatch/<id>`：每一份派工的狀態、每一步交給誰、花了多少、停止、繼續（說明會跳過沒做完的那一步）、撤回 VBear 建的員工、刪除；暫停時寫明是哪一步、哪個 AI 工具、每天上限、什麼時候恢復（不知道寫「未知」）。CEO 的聊天頁有「請幕僚長安排」（對話框先寫明內容送到 Claude Code、最多花多少、今天還剩多少）和提議卡（改字、刪步驟、換人、「你改過」、確認派工、不採用） |
| AI 自己做了什麼 | `#/actions`：幕僚長和派工做過的每一件事，以及是誰決定的（你、自己動手第 1、2、3、5 項、VBear）；也列出例行工作的開始與補做、派工的自己接續；已經送出的訊息收不回來；可以停止進行中的派工、撤回 VBear 建的員工。設定頁「自己動手」那一節有連結 |
| 組隊會議 | 從任務卡的「請 CEO 組隊」進入（`#/staffing?task=`）：VBear 依固定規則建議的發言者與理由、組隊會議前的預覽（每段送出全文、模型與思考強度、預留金額、清單少了多少）；單份組隊紀錄（`#/staffing/<id>`）的座位與發言、CEO 的組隊提案（代號一律換成卡與技能現在的名稱，找不到就寫「找不到」）、改成你要的樣子（草稿，只存在這個瀏覽器）、照草稿採用（啟用 → 建新卡 → 插技能 → 帶到隊伍 → 帶去開會 → 記下，每一步都要你自己按）、董事長桌、重試、取消、刪除 |
| 終端工作台 | 統一三欄版面（左側角色、中間真實 Terminal、右側 Task Card 與 G/P/A/T 治理骨架）、專注模式、可收合側欄 |
| 技能庫 | 卡片／列表、中英文搜尋、依狀態／工具／用途／範圍／我的標籤篩選；詳情含我的註記、同名比較、引用檔、原始 SKILL.md、使用紀錄 |
| 角色卡池 | 我的角色卡（正反兩面、起手牌組、建立角色卡精靈：第 2 步選職位、寫職位指示、選出發方式並看邊界，第 3 步插技能卡）、開啟中的終端（VBear runtime 管理的 Claude／Codex／AGY，角色名、本次模型、本次用過的技能、開啟終端）與角色設定（主代理、子代理）；這頁以前叫「Agent 團隊」 |
| 專案 | 依 git 儲存庫歸類：專案 → 各角色 Terminal |
| 流程 | 多 Agent 合作的任務卡：角色與模型家族、推導出的階段、審查輪次、時間軸、手動記錄事件 |
| 設定 | 掃描來源開關、使用紀錄範圍、進階模式、資料流向說明 |

## 資料從哪裡來

| 資訊 | 來源 | 強度 |
|---|---|---|
| 技能內容 | `SKILL.md` front matter 與章節 | 作者說明／自動整理 |
| Claude 外掛是否生效 | `~/.claude/plugins/installed_plugins.json` + `settings.json` 的 `enabledPlugins` + 外掛 `plugin.json` 的載入路徑 | 設定檔 |
| Codex 技能是否生效 | `~/.codex/config.toml` 的 `skills.config` | 設定檔 |
| 技能上游 | `~/.agents/.skill-lock.json` | 設定檔 |
| 工作中的 Terminal | VBear runtime 的 session 清單 | 執行觀察 |
| 工作中／等你回覆 | Profile 啟動的 Claude Code 自己設定的終端標題（只保留開頭符號，不保存標題文字；只有版本有實測紀錄或在本機驗證過時採用，其他顯示「狀態未知」） | 執行觀察（Agent 自己回報） |
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
  名稱像機密、冒號後面沒有值的行（例如 `tokens:`），底下縮排更深的行（清單、換行後的值、巢狀 mapping）也一併遮蔽，直到縮排相同或更淺的下一行為止；同一行只有註解、開頭括號、區塊標記或標籤時也一樣。
- Profile 管理的 Claude 啟動：先 `POST /api/native/agent-previews` 取得預覽（七項權限的實際套用程度與證據），確認後
  `POST /api/native/agent-launches` 才啟動；預覽單次使用、5 分鐘過期，設定或 Profile 變動回 409。不接受 argv、環境變數、設定或憑證。
  Bash 工具的寫入由 Claude 沙盒限制在工作目錄與該 session 的暫存區；讀取不隔離；使用者在終端以 `!` 直接執行的指令不經沙盒。
  工作目錄套用和資料夾選擇器同一份「不能當成專案」的清單：家目錄本身，以及 `~/.ssh`、`~/.gnupg`、`~/.aws`、`~/.config`、
  `~/.vbear`、`~/.claude`、`~/.codex`、`~/.gemini`、`~/Library` 和它們底下的位置（含狀態目錄）都會被拒絕；名稱不分大小寫，
  符號連結先解析成實際路徑再比對，會包含這些位置的工作目錄也不行。拒絕發生在檢查資料夾是否存在之前，位置存不存在訊息都一樣，
  錯誤碼是 `invalid_workdir`；預覽會顯示為不可啟動的原因，啟動前會再檢查一次。因此放在 `~/Library`（例如 iCloud Drive）或 `~/.config`
  底下的資料夾不能當受管啟動的工作目錄。
- 完整模式出發（角色卡的 `launch_mode` 是 `full`）：VBear 不加沙盒、`--safe-mode`、設定檔、工具清單與暫存區，什麼都不擋；工具用你自己的設定、技能、
  `CLAUDE.md`、MCP 與網路。指令由伺服器組成，是一串引數、不經 shell（`claude [--model X] [--append-system-prompt …]`、`codex [-m X]`、`agy [--model X]`），
  runtime 只透過 `open_full` 接受 `agent_sessions.full_argv` 組得出來的形狀。仍然要先預覽、按確認；預覽單次使用、5 分鐘過期，卡片或程式檔變了就作廢（`cli_drift`）。
  資料夾規則和安全模式相同。沒有 `launch_mode` 的卡一律是安全模式。詳見 [安全模型](SECURITY-MODEL.md#full-mode-launches)。
- 會議：每次發言都是完全沒有工具的 Claude Code headless 呼叫（argv 沿用翻譯的 `translation_argv`），每次都即時檢查 init 只有 `StructuredOutput`、沒有 MCP，
  不符就殺掉整個 process group、結果不採用、撤銷這個版本的通過紀錄。送出前的預覽列出全文；送出的是任務卡欄位，不含資料夾路徑。會議只寫 `meetings/`，
  不寫任務卡、流程或專案資料夾；重大與否每次讀取時依固定規則 R1–R8 推導，模型只能升級。詳見 [安全模型](SECURITY-MODEL.md#meetings-tool-less-headless-speech)。
- 聊天：和一張已啟用、工具是 Claude Code、Codex 或 AGY 的角色卡一對一聊天（API 層自己檢查，停用或其他工具的卡會回原因；聊天的引擎由卡的工具在開聊天時決定，之後卡換了工具，這個聊天就不能再送訊息，要開新的）。runtime 的 daemon 擁有聊天程序並是唯一寫紀錄的一方；每張卡最多一個程序、全部最多三個，閒置 10 分鐘關閉、每回合最長 10 分鐘。
  只帶這張卡自己寫的指示（一個 `--append-system-prompt`），不帶職位預設文字；VBear 還沒有在真機上確認 Claude Code 真的套用，也沒確認續接時改過的指示會不會生效。
  Bash、Edit、Write 一律出權限卡片（允許這一次、拒絕、改內容再允許），沒有「以後都允許」；卡片 5 分鐘過期視為拒絕，按下允許時 VBear 會再檢查一次。
  每回合上限 `chat_limits.per_turn_usd`（預設 US$0.50，0.01 到 5），和會議、組隊會議共用 `meeting_limits.daily_usd`；沒回報花費的回合按上限算。
  Claude Code 版本要先通過 `python3 -m vbear.boundary_check --mode chat`（約 6 次 Haiku 小呼叫，用你自己的登入）才能聊天；2.1.318 與 2.1.319 另外把 `~/.claude/policy-limits.json` 當成管理員政策，存在就不能聊天。聊天會自動選 Claude Code 版本資料夾裡通過聊天驗證、其次是 VBear 有聊天常數的最新版，再其次才是 PATH 上的 `claude`；會議與幕僚長用 PATH 上的，所以三者可能是不同版本。
  Codex 聊天（引擎 `codex-chat`）：每個指令和每次改檔都問（連只讀檔的也問）；「改內容再問」是先拒絕、再請 Codex 照你改的重新問一次；沙盒不擋讀，而且允許後的指令可能在沙盒外執行（能寫整台電腦、能連網；指令卡上寫明）；花費是 VBear 依 token 數的估計（每 100 萬 token 計 US$1.00，不是帳單），算進每天上限；聊天用的 Codex 另外登入（開始設定頁），版本要先通過 `python3 -m vbear.boundary_check --mode codex-chat`（頁面上的「驗證聊天」）。
  AGY 聊天（引擎 `agy-chat`，v0.20.0，ADR 0012）：執行 `agy acp`（ACP v1，stdio 上的 JSON-RPC），用 VBear 自己的設定資料夾 `<state>/agy-chat-home`、AGY 自己的沙盒（`--sandbox`）和你自己的 AGY 登入（不另外登入）；VBear 每次開程序前把 `antigravity-cli/settings.json` 寫成固定內容（每個都問、沙盒開、不用付費點數），程序的環境剛好六個變數。每個指令、每次改檔、工作資料夾外的讀取都問，只送「允許一次」或「拒絕一次」；要在沙盒外執行的請求由 VBear 直接拒絕、不出卡片；檔案工具不在沙盒裡，由 VBear 判路徑（資料夾外、`.git`、`.agents`、`.gemini` 等直接拒絕）。「改內容再問」是先拒絕、這一回合結束後把你改的內容當下一則訊息送出，AGY 再問一次。花費是 VBear 依 token 數的估計（US$1.00 / 100 萬 token，不是帳單；用你的 Google 方案）。AGY 版本要先通過 `python3 -m vbear.boundary_check --mode agy-chat`（約 15 次短呼叫）；有 `/etc/antigravity` 管理員政策或 `~/.agents/hooks.json` 就不能聊天；你自己裝的 AGY 技能會被 AGY 讀到。AGY 員工這版不能用共用資料夾。聊天紀錄沒有新增事件種類。詳見 [安全模型](SECURITY-MODEL.md#chats-with-an-agy-role-card-engine-agy-chat-v020)、[ADR 0012](adr/0012-agy-chat-boundary.md) 與 [證據檔](evidence/agy-1.5.3-chat.md)。
  詳見 [安全模型](SECURITY-MODEL.md#chats-with-a-role-card) 與 [Codex 聊天](SECURITY-MODEL.md#chats-with-a-codex-role-card-engine-codex-chat-v013)。
  幕僚長與派工：幕僚長把你和 CEO 的對話送到 Anthropic（透過你的 Claude Code，每次最多 US$0.30，算進每天上限）；派工只透過聊天送訊息，不回答權限卡片，每個指令和改檔仍然問你；上一步的回覆當資料交給下一步，這是惡意文字帶偏下一位員工的一條路；員工被允許的指令讀得到 VBear 的存取權杖。VBear 只保證自己的幕僚長與派工程式不改上限、不啟動終端機或完整模式、不裝技能。詳見 [幕僚長與派工](SECURITY-MODEL.md#chief-of-staff-and-dispatch-v015)。
  群組：只有你說話才會有員工回答（員工回覆裡的 @ 不會叫到別人），被叫到的員工照順序一位一位回答；每位員工是自己的一個聊天，所以每個指令和改檔都問你、每回合上限與每天上限照聊天的規則，群組不替你回答任何權限卡片（`vbear/group*.py` 受守門測試管，不得呼叫 `answer`、不改上限、不啟動終端機或完整模式、不裝技能）。別人的話（你對別人說的、其他員工的回覆）以 JSON 字串放在 `BEGIN_UNTRUSTED_JSON_STRING` 與 `END_UNTRUSTED_JSON_STRING` 之間、標成資料，這只是對模型的要求，是惡意文字帶偏下一位員工的一條路；「大家」會讓允許卡變多；Claude Code 與 Codex 混用時對話會送到 Anthropic 和 OpenAI 兩家；你允許的指令讀得到 VBear 的存取權杖，Codex 的指令允許後可能在沙盒外執行。詳見 [群組](SECURITY-MODEL.md#group-chats-v016)。
  記憶：只有你能存（瀏覽器的 `/api/memory*`，帶 `X-VBear`；守門測試保證只有 `server.py` 呼叫寫入函式，`memory*.py` 也受 `vbear/group*.py` 同樣的規則管，不得呼叫 `answer`、不改上限、不啟動終端機或完整模式、不裝技能、不建角色卡）。含密碼、驗證碼、金鑰、帳號、email、卡號、身分證字號、銀行帳號的會被擋下（`runtime/memory_rules.check`，console 存時查一次、daemon 組系統指示前再查一次，不合就整則訊息拒絕）；像在叫員工做事、含電話與地址的，要多勾「我確定」。員工開新程序時，記憶放在系統指示（Claude `--append-system-prompt`、Codex `developerInstructions`）裡固定的一段，JSON 字串放在 `BEGIN_VBEAR_MEMORY_JSON` 與 `END_VBEAR_MEMORY_JSON` 之間，說明它是背景資料、不能讓員工不問你就做事；改了記憶、固定指示或卡的開關，只有新聊天用到新的：Claude Code 2.1.319 用 `--resume` 接續時不套用新的附加系統提示（真機驗證），所以 daemon 不再為了這件事換程序，而是在新 session 啟動時把系統指示的雜湊與有沒有帶記憶記在 `chat-prompt/<c-…>.json`（不是聊天紀錄的欄位），`GET /api/chats/<id>` 的 `memory.changed`、`memory.started_with_memory` 讓聊天頁寫明「這個聊天還是用開始時的內容」並附「開新聊天」。每個指令、每次改檔仍然都問你。Claude Code 與 Codex 自己的記憶維持關閉（`--safe-mode`、`CLAUDE_CODE_DISABLE_AUTO_MEMORY=1`、`--disable memories` 等）。殘餘風險：記憶是持久的提示注入路徑（你可能存下員工的話）、記憶會送到 Anthropic 與 OpenAI、檢查只認格式；Codex `thread/resume` 是否套用新的 developer instructions 待真機驗證（同樣處理）；兩個環境變數單獨的效果沒有比較過。詳見 [記憶](SECURITY-MODEL.md#memory-v017)。

  共用資料夾（v0.17.1，ADR 0009）：`<state>/shared` 是一個資料夾，用的人打開的員工都可以讀寫；**每位員工預設是關的**，只有用的人在瀏覽器裡能打開（`POST /api/shared/cards`、建群組的 `shared_folder`、派工確認的 `shared_folder`，都帶 `X-VBear`；Codex 員工要 `confirm_company: true`，否則 409 `shared_confirm`；守門測試保證寫開關的函式只在 `server.py` 被呼叫，自己動手、幕僚長、自動派工打不開任何人）。開關與紀錄放在 `shared-meta/`，不在員工寫得到的共用資料夾裡。路徑只由 VBear 算（`runtime/shared_rules.shared_path`），瀏覽器與 RPC 呼叫者不傳路徑；`folder_problem` 不過就 `shared_unsafe`、不修不刪。Claude Code 的沙盒 `allowWrite` 多一個共用資料夾、VBear 的 `judge` 把共用資料夾當第二個根（Edit／Write 一律卡片；經連結到外面、`.claude`／`.codex`／`.agents`／`.git`〔任何深度〕、硬連結數大於 1 一律拒絕、沒有卡片），Codex 的 `-c sandbox_workspace_write.writable_roots`、`turn/start` 的 `writableRoots`、`thread/start` 的回答（不是剛好那一個就停）與 `judge_file_change` 同樣處理；不用 `--add-dir`，`--permission-prompt-tool stdio`、`permissions.ask: ["Bash"]`、Codex 的 `untrusted` 都沒動。沙盒跟著現在的開關（關掉從下一句起生效），員工知道什麼跟著聊天開始時（剛打開要開新聊天）；關著時 argv、設定、系統指示與指紋和 v0.17.0 逐位元相同。VBear 不讀檔案內容、不刪檔，只用 `os.scandir`／`lstat`；檔名不進日誌；容量 1 GiB／1 萬個項目，只在開新程序時查（`shared_full`）。群組與派工把「前一位回答期間新增或改過的檔名」（最多 50 個，當資料，包在 `BEGIN_UNTRUSTED_JSON_STRING`／`END_UNTRUSTED_JSON_STRING` 之間）交給下一位，清單存在 `shared-meta/changes/`，不加進群組、派工、聊天紀錄的欄位。每個 AI 工具版本要先通過含共用資料夾的聊天檢查（報告的 `shared: passed`），打開的員工才能聊天（`shared_unverified`）。殘餘風險：一位員工寫的檔案是另一位的輸入（提示注入）、讀到的檔案送到該員工的 AI 公司（混用時跨公司）、硬連結與連結、Codex 允許後可能在沙盒外、你在 Finder 打開員工放的可執行檔、容量只在開新程序時查；**Codex 員工使用共用資料夾沒有在真機上驗證**（只用假的 app-server 與零花費的沙盒探測）。詳見 [共用資料夾](SECURITY-MODEL.md#shared-folder-v0171)。
  技能與例行工作（v0.18.0，ADR 0010）：只有你能存技能（瀏覽器的 `/api/my-skills*`）、只有你能建立、修改、啟用、刪除例行工作（`POST /api/routines` 等，帶 `X-VBear`）；守門測試（規則 8 到 12）保證只有 `server.py` 呼叫寫入函式，`skillbook*.py`、`routine*.py`、`auto_continue.py` 不得寫 `config.json`、不得啟動終端機或完整模式或任何程式、不得裝技能或建改角色卡、不得呼叫 `answer`。技能不進系統指示、不寫成任何 AI 工具的技能檔，「用技能」只把說明放進輸入框，由你送出；名稱與內容用記憶的同一組規則檢查（`memory_rules.check_text`）。例行工作每次新開一個一對一聊天、做一個回合，走聊天的規則（每個指令與檔案修改都問、卡片 5 分鐘過期當作拒絕、每回合上限、每天上限），同一個時間最多開始一次；沒勾自己動手第 3 項只提醒，勾了才自己開始；例行工作自己的每天上限預設是每天上限的一半。VBear 關著或 Mac 睡著時什麼都不做，不裝常駐的東西，醒來只補最近一次（12 小時內、每次醒來最多 3 件才自己補）。「讓 Mac 保持清醒」預設是關的，打開後 VBear 在有工作時執行固定的 `/usr/bin/caffeinate -i -w <pid>`。自己動手第 5 項讓暫停的派工到了恢復時間自己按「繼續」（每次暫停 1 次、每份 3 次、每天 5 次）。已知缺口：聊天背景程序算「今天花了多少」時不含「整理成技能」（最多多給 US$0.10）。Codex 員工的例行工作、Mac 真的睡著、半夜的自動接續、`caffeinate` 真的擋住睡眠，都沒有在真機上驗證。見 [SECURITY-MODEL.md](SECURITY-MODEL.md#skills-and-routines-v018)。
  團隊範本（v0.19.0，ADR 0011）：只有你能預覽、套用、復原、存（瀏覽器的 `/api/templates*`，帶 `X-VBear`，欄位封閉）；套用 `POST /api/templates/apply` 先檢查全部（檔案讀得懂、上限：角色卡 500、技能 100、例行工作 20，一次套用與一個團隊範本最多 12 位員工、24 個技能、12 件例行工作）再一個一個建，只經原本的寫入函式（員工與 `POST /api/agent-profiles` 共用 `_save_card`，技能 `skillbook.add`，例行工作 `routines.create`），檢查一條不少。員工一律 `launch_mode: "safe"`、`equipped_skill_ids: []`、不會是完整模式；例行工作一律 `enabled: false`（關著）；不碰記憶、共用資料夾、`config.json`、自己動手，也不用 AI、不花錢。守門測試（規則 13a 到 13e）保證團隊範本的模組不得 import 聊天、會議、網路，別的被掃描的模組不得 import 團隊範本的模組，寫入函式只在 `server.py`；規則 13b 沒有為套用開例外（寫入都在 `server.py`，`templates_apply.py` 只記紀錄）。復原這次套用先預覽（什麼都不寫）、再按「刪掉這些」：伺服器再算一次，只刪這次套用建的、指紋相同（沒改過）、沒有聊天或群組、派工、會議、任務提到、記憶或共用資料夾開關沒改過、沒有留下來的例行工作交給他的員工，沒改過、沒跑過的例行工作，沒改過的技能；讀不到、太大、太多、是連結的一律留著；順序是例行工作、技能、員工。**VBear 看不出來你有沒有在終端機用過團隊範本的員工**（終端機出發不留角色卡的 id），也沒有技能「用過」的紀錄，所以預覽固定多一行提醒，由你確定再刪。存成自己的團隊範本只存名字、職位、你寫的固定指示和 Claude 的模型別名，不帶 AI 工具、啟動模式、技能卡、記憶、共用資料夾、聊天；完整模式的員工可以存，但不帶啟動模式，套用一律是安全模式。已知限制：團隊範本建的 Codex 員工、例行工作真的到時間執行，都沒有在真機上驗證；模型會不會照內建的固定指示做沒有紀錄。見 [SECURITY-MODEL.md](SECURITY-MODEL.md#team-templates-v019)。
- 組隊會議：用會議的引擎和同一個 worker（會議和組隊會議不會同時跑），同樣是沒有工具的呼叫、同樣即時檢查 init，同樣只用低／中思考強度與時鐘；
  卡和技能用代號（`C1`、`S1`…）送出，不送 id，也不送任務卡的資料夾路徑。花費上限：發言者每次 `meeting_limits.per_call_usd`、CEO 每次
  `staffing_limits.proposal_call_usd`、每份 `staffing_limits.total_usd`，和會議共用每天的上限。提案只是建議：VBear 不建卡、不插技能、不排隊伍；
  採用的每一步都走原本就有的端點、要你自己按，隊伍先放在任務卡的畫面上，按「建立隊伍」或「儲存隊伍」才寫進 `flows.json`。組隊會議只寫 `staffing/`。
  詳見 [安全模型](SECURITY-MODEL.md#staffing-meetings-組隊會議)。
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
    - **結果綁定 commit、結案理由、交接與處理狀態**（做法參考 OpenRig，見 [docs/evidence/openrig-learnings.md](evidence/openrig-learnings.md)）：
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

`~/.vbear/`（可用 `VBEAR_HOME` 覆寫）：`config.json`（含會議上限 `meeting_limits`、組隊會議上限 `staffing_limits`、會議速度 `meeting_speed`）、`index.json`、`usage-cache.json`、`annotations.json`、`tasks.json`、`flows.json`、`agent_profiles.json`、`server.log`、
VBear runtime 的 `runtime.sock`／`runtimed.lock`／`runtimed.log`，以及 Profile 管理 session 的 `sessions/<launch-id>/`（session 暫存區在 `/private/tmp/sc-<隨機>/`）。
翻譯與會議：`translations.json`、`role-translations.json`、`translation-boundaries.json`（依版本記錄通過無工具安全檢查的 Claude Code，翻譯與會議共用）、`translation-worker.lock`／`translation-worker.blocked`，
幕僚長的提議：`chief/`；派工：`dispatch/`（`d-` 加十二位十六進位）與 `dispatch-runner.lock`。群組：`groups/g-<十二位十六進位>/`（`group.json` 與 `log.jsonl`；員工的回覆不另存，從成員的聊天讀）與 `group-runner.lock`。記憶：`memory/`（`memory.json`、`log.jsonl` 只記動作不記內容、`suggest/ms-<十二位十六進位>.json` 整理提議）。共用資料夾：`shared/`（員工可寫的那一個資料夾，0700）與 `shared-meta/`（員工寫不到：`settings.json` 哪幾位打開、`log.jsonl` 開關紀錄，沒有檔名、`changes/<g-…|d-…>.jsonl` 群組與派工交接的檔名清單、`pending/<d-…>.json` 派工確認時勾了沒有）。聊天：`chats/<c-十六位十六進位>/`（`chat.json` 與 `events.jsonl`）、`chat-work/`（每張角色卡一個工作資料夾）、`chat-spend/`（刪掉的聊天留下的三天花費）、`chat-prompt/`（每個聊天開始時系統指示的雜湊，刪聊天時一起刪）與 `claude-chat-verified.json`（通過聊天驗證的版本）；Codex 聊天另有 `codex-chat-home/`（聊天用的 Codex 登入與它自己存的對話副本，刪除聊天不會刪）與 `codex-chat-verified.json`；`config.json` 另有 `chat_limits`。
技能：`skillbook/`（`skills.json`、`log.jsonl` 只記動作與 id、`suggest/ks-<12 位十六進位>.json`）。例行工作：`routines/`（`routines.json`、`settings.json`、`runs.jsonl`、`heartbeat.json`、`auto-continue.jsonl`、`log.jsonl`）與 `routine-runner.lock`。團隊範本：`templates/`（`mine.json` 你存的團隊範本、`applies.json` 最近 50 次套用的紀錄與 `log.jsonl`；只有 id、指紋、狀態、時間與數量，沒有名稱與內容）。
以及 `meetings/`（每場會議一個 `m-<12 位十六進位>.json`）、`staffing/`（每份組隊紀錄一個 `s-<12 位十六進位>.json`）與 `meeting-worker.lock`／`meeting-worker.blocked`（會議與組隊會議共用）。索引超過 24 小時會提示過期；程式更新後舊格式索引會自動重掃。

## 結構

```
vbear/
  scan/claude.py codex.py shared.py   來源適配器
  scan/document.py frontmatter.py     SKILL.md 解析（無 PyYAML）
  scan/usage.py                       使用證據
  runtime/daemon.py native.py         VBear runtime 背景程序與用戶端（PTY session）
  runtime/agent_sessions.py proctrack.py  Profile 管理 session 的設定／暫存區／清理，與後代程序追蹤
  runtime/cli_versions.py             Agent CLI 版本檢查
  agent_launch.py                     啟動前預覽與確認、七項權限標籤、完整模式出發的預覽
  agent_profiles.py                   角色卡（職位、職位指示、出發方式；本機儲存）
  position_guide.py                   職位的預設指示、邊界、推薦技能分類與建議資料夾
  headless_cli.py                     無工具 headless 呼叫的共用執行器（翻譯與會議）
  translations.py                     技能與職業名稱翻譯、無工具安全檢查
  meetings.py meeting_rules.py        會議紀錄、輸出檢查、prompt、花費；重大規則表 R1–R8
  meeting_runner.py                   會議的預覽、一次一個呼叫的 worker、重試與取消
  chat_service.py                     聊天：伺服器端的服務與拒絕說明（紀錄與花費在 runtime/chat_store.py）
  groups.py group_runner.py           群組：紀錄與驗證、員工收到的訊息、一輪的狀態；console 執行緒一位一位照順序問（守門測試涵蓋 group*.py）
  memory.py memory_suggest.py         記憶：`memory.json`、上限、來源、匯出；整理提議的格式與紀錄（只有 console 的 `/api/memory*` 路由能存，守門測試涵蓋 memory*.py）
  memory_suggest_runner.py            整理要記住的事：一次沒有工具的 Claude Code 呼叫，最多 US$0.10，不存任何一條
  runtime/memory_rules.py             一條記憶能不能存（console 與 daemon 共用）、組成員工收到的那一段、系統指示的雜湊
  shared_folder.py shared_changes.py  共用資料夾：開關與紀錄（只有 `server.py` 的路由能寫）、頁面的檔案清單、群組與派工交接的檔名清單（守門測試涵蓋 shared*.py）
  runtime/shared_rules.py             共用資料夾的位置檢查、用量、快照與比對、寫入的規則、員工收到的那一段（console 與 daemon 共用）
  skillbook.py skillbook_suggest.py   技能：`skills.json`、上限、來源、文字檢查；整理成技能的格式與紀錄（只有 `server.py` 的 `/api/my-skills*` 路由能寫，整理的程式不 import `skillbook`）
  skillbook_suggest_runner.py         整理成技能：一次沒有工具的 Claude Code 呼叫，最多 US$0.10，花費種類 `skill_suggest`，不存任何技能
  routine_rules.py routines.py        例行工作：欄位與時間（本機時間、夏令時間）、紀錄 `routines.json`／`runs.jsonl`／`settings.json`／`heartbeat.json`（只有 `server.py` 的路由能寫）
  routine_runner.py                   例行工作的執行緒：每 15 秒看一次，提醒或自己開始、醒來補做、一次一件、上限與燈號、`send_for_routine`、`routine-runner.lock`
  auto_continue.py countdown.py       倒數的文字；第 5 項：暫停的派工到了恢復時間自己按「繼續」（`resume_dispatch(…, by="vbear")`），上限與紀錄 `auto-continue.jsonl`
  keep_awake.py                       「讓 Mac 保持清醒」：固定 argv 的 `/usr/bin/caffeinate`，只由 `serve()` 交給 console，其他建法的 console 不啟動任何東西
  templates.py templates_builtin.py   團隊範本：封閉的格式與上限、勾選與拼組（`plan`）、預覽、做出給寫入函式的內容（純函式）；內建四個（小店、自媒體、接案工作室、個人生活助理，逐字）
  templates_apply.py                  團隊範本的套用紀錄 `applies.json`／`log.jsonl`、指紋、中斷後的 `recover()`、「提到他」的搜尋、復原的規則 `undo_plan`（只記紀錄與算規則，不呼叫任何寫入函式；寫入都在 `server.py`）
  templates_mine.py                   你存的團隊範本 `mine.json`（只有 `server.py` 的 `/api/templates/mine*` 路由能寫；不帶 AI 工具、啟動模式、記憶、共用資料夾）
  chat_check.py claude_verify.py      聊天驗證（boundary_check --mode chat）與它的啟動、狀態
  codex_chat_check.py                 Codex 聊天的版本閘門（boundary_check --mode codex-chat，約 14 次呼叫、總估計不超過 US$0.30）
  board_engine.py                     會議的引擎：一回合一個無工具呼叫、花費、思考強度與時鐘（會議與組隊會議共用）
  skill_fit.py                        哪張技能可以插在哪張卡（和網頁同一套相容規則，讓伺服器檢查組隊提案）
  staffing.py staffing_runner.py      組隊會議：清單與代號、建議的發言者、輸出檢查、紀錄；預覽、執行、重試、董事長紀錄
  index.py                            靜態索引＋即時視圖
  annotations.py                      我的註記（別名、標籤、備註）
  tasks.py                            任務卡（Task Card MVP、狀態證明、結果綁定 commit、結案理由、交接、本機儲存）
  flows.py                            流程看板（角色、事件紀錄、階段推導、審查與 commit 綁定；只記錄不執行）
  jsonstore.py                        私有 JSON 儲存（0600、原子寫入、跨程序鎖、損毀時封鎖）
  git_head.py                         不執行 git，直接讀 .git 檔案取得目前的 commit
  activity.py                         Agent 狀態判斷（工作中／等你回覆／未知）與判斷依據
  runtime/osc_title.py                受管 Claude 的終端標題分類（不保存標題文字）
  server.py                           本機 HTTP API
web/                                  介面（原生 HTML/CSS/JS）
tests/                                Python 單元測試，全部使用合成的 HOME；實際筆數以 `python3 -m unittest discover -s tests` 執行結果為準，不在此處寫死固定數字
tests/frontend/                       前端行為測試（node＋合成 DOM，不是瀏覽器測試）
```
