# 0012 AGY 聊天用 `agy acp`、VBear 自己的設定資料夾與 AGY 的沙盒：每個指令與檔案修改都問，要在沙盒外跑一律拒絕，用你自己的 AGY 登入

日期：2026-11-09　狀態：已決定（使用者 2026-11-09 拷問拍板，第 1–9 點；v0.20.0 做完後以第 7 次真機檢查補上「真機結果」，並依真機結果把共用資料夾這版收回，見第 7 點與文末「真機結果」。
實測整理在 `docs/evidence/agy-1.5.3-chat.md`；細節依 ADR 0001–0011 與 GLOSSARY 提出；第 3、5、7、9 點是使用者可以再改的取捨，改的話要連同畫面文字與 `docs/SECURITY-MODEL.md` 一起改）

## 背景

ADR 0001 Q1-5：只有 Codex 或 AGY 的人也要能用聊天；Q1-8：聊天依序補上。v0.13.0 做了 Codex 聊天（ADR 0005），之後的群組、派工、記憶、共用資料夾、例行工作、團隊範本都照「Claude Code 與 Codex 的員工」設計。
AGY（Google Antigravity CLI）到 v0.19.0 只能在終端機用完整模式（ADR 0002）。

2026-11-09 的實測（AGY 1.5.3、MCODE 0.5.2，花費約 US$0.15）：

- `agy acp`（ACP v1，stdio JSON-RPC）可以做到「長駐、多回合、用工具前先問 host、允許或拒絕」。headless `-p` 不能逐次問。
- VBear 自己的 `--gemini-dir` 裡放 `antigravity-cli/settings.json`（`toolPermission: request-review`、`enableTerminalSandbox: true`），加 `--sandbox`：寫檔、執行指令、讀寫工作資料夾外，**每一個都問**。
  權限選項只有「允許一次」「拒絕一次」，沒有「以後都允許」，也不能改內容。
- 沙盒（macOS Seatbelt）擋住允許後的指令寫外面、讀外面、連網，而且**不會自己跳出沙盒**：要在沙盒外跑時，AGY 會再問一次，請求裡寫著 `BypassSandbox: true`，VBear 在出卡片前就看得到。這比 Codex 好（ADR 0005 第 7 點）。
  但**檔案工具不在沙盒裡**：允許後可以寫到工作資料夾外。
- `--gemini-dir` 換掉 AGY 的設定與 MCP 設定，登入照樣能用（登入跟著 HOME 走，換 HOME 就要重新登入）；**但使用者家目錄的技能（`~/.agents/skills`）仍會載入**。
- 續接用 `session/resume`；停止用 `session/cancel`；每個新程序都要再設一次模型。用量只有每回合結束時的 token 數，沒有金額、回合中途沒有用量。
- MCODE 0.5.2 的 Ask 模式不問就寫檔、跑指令、讀外面，沒有沙盒，切模式還會改到使用者的全域設定，花費恆為 0：做不到安全模式聊天。

規劃時另做了一次零花費的靜態讀取（`strings` 本機 `agy` 執行檔，沒有執行）：管理員設定在 `/etc/antigravity/admin_settings.json`；AGY 認得 `.agents/hooks.json`（自動執行的指令）、`ANTIGRAVITY_PERM_GRANTS` 這類環境變數、`useG1Credits`（付費點數）。

## 決定

1. **用 `agy acp`，搭配 VBear 自己的設定資料夾 `<state>/agy-chat-home`（0700）與 `--sandbox`；用你自己的 AGY 登入，不另外登入。**
   argv 固定是 `agy acp --gemini-dir <state>/agy-chat-home --sandbox --disable-telemetry`（打開共用資料夾的員工多 `--add-dir <共用資料夾>`）；
   VBear 每次開程序前把 `antigravity-cli/settings.json` 寫成固定內容（`request-review`、終端機沙盒開、`allowNonWorkspaceAccess` 關、付費點數 `useG1Credits` 關、`permissions` 全空），程序在跑時被改就停。
   環境變數剛好六個（`PATH`、`USER`、`LOGNAME`、`LANG`、`TMPDIR`、真的 `HOME`），不傳任何 `ANTIGRAVITY_*`、`GEMINI_*`、`GOOGLE_*`。
   **使用者家目錄的 AGY 技能仍會被載入：使用者拍板接受**（第 5 點），畫面與 SECURITY-MODEL 寫「AGY 員工會用到你自己裝的 AGY 技能」。
   理由：AGY 的登入跟著 HOME 走，要完全不讀使用者的東西只能另設 HOME、再登入一次（像 Codex 的 `CODEX_HOME`），使用者選了不另外登入；技能是給模型的說明，不是權限。

2. **每個指令、每個檔案修改都問；只送「允許一次」或「拒絕一次」。** VBear 從不選「以後都允許」，不送 `session/set_mode`（`accept-edits` 會讓改檔不問）、`set_config_option`、`session/load`；
   模型固定 `gemini-3.8-flash-high`，每次 `session/new`、`session/resume` 之後都送 `set_model`；`session/new` 的模式必須是 `default`，被換掉就停。
   AGY 沒經 VBear 允許就跑完的指令或檔案修改（例如合併進來的 App 權限、hooks）一出現，聊天就停（違規）。

3. **「改內容再允許」改成「拒絕，這一回合結束後把你改的內容當成下一則訊息送出，AGY 再問你一次」。** ACP 的回答只有選項，不能帶改過的內容；
   AGY 1.5.0 的 changelog 說送另一個 prompt 可以導正進行中的回合，但沒有實測，所以不用。畫面寫明「AGY 會再問你一次」，不能說成「已經照你改的執行」。

4. **沙盒與路徑：**
   - 指令一律在 AGY 的沙盒裡；**`BypassSandbox` 的請求由 VBear 直接拒絕、不出卡片**（使用者拍板第 7 點）。代價：需要網路或寫外面的指令（`npm install`、`git push`）在聊天裡都不能用。
     指令卡上寫「允許後，這個指令在 AGY 的沙盒裡執行：不能連網，只能寫工作資料夾（和暫存資料夾）」。
   - 檔案工具不在沙盒裡，由 VBear 判路徑（同 Claude 聊天）：工作資料夾（或打開的共用資料夾）外、任何深度的 `.git`／`.agents`／`.agent`／`.gemini`／`.codex`／`.claude`、檔名 `GEMINI.md`／`AGENTS.md`、硬連結 → 直接拒絕、不出卡片。
     讀取：工作資料夾內由 AGY 自己允許（VBear 看路徑，外面就停），外面出讀取卡。網路工具一律拒絕。
   - 工作資料夾最上層有 `.agents`、`.agent`、`.gemini`、`GEMINI.md`、`AGENTS.md`，或資料夾裡有指向外面的連結，不啟動（AGY 會把它們當設定與規則讀；連結會讓「工作資料夾內的讀取」讀到外面）。

5. **花費**：沿用 Codex 的估算規則（ADR 0005 第 5 點）：每回合 =（`totalTokens` ÷ 1,000,000）× US$1.00，無條件進位到分，至少 US$0.01，計入每天上限，畫面寫「估計」「不是帳單」「AGY 用的是你的 Google 方案」。
   `totalTokens` 沒有或不符加總時以這回合上限計。**AGY 回合中途不回報用量，所以每回合上限只在開始前檢查，一回合可能超過，照實記**（取捨，見後果）。

6. **版本閘門 `python3 -m vbear.boundary_check --mode agy-chat`。** 每個 AGY 版本都要在這台 Mac 上先通過（用你的 Google 方案，約 15–18 個短回合，不計入每天上限），`agy-chat-verified.json` 記下來才能聊天；
   AGY 自己更新後要再驗證（真機結果見文末）。通過條件包括：系統指示真的帶進去、VBear 的 settings.json 真的被讀（用 `strict` 證明）、每個指令都問、拒絕有效、改內容再問、外面的檔案工具被自動拒絕、
   允許的指令寫不到外面也讀不到外面、`BypassSandbox` 被自動拒絕、連不了網、經由連結讀不到外面、停止、續接、設定資料夾裡沒有多出 hooks 或 MCP；共用資料夾另有一段。

7. **其他功能照 Codex 員工的先例接上 AGY 員工**：群組、派工（含幕僚長提議 AGY 新員工；幕僚長本身仍要 Claude Code）、CEO 是 AGY 卡（對話送給 Claude 整理，寫明）、例行工作、
   整理要記住的事與整理成技能（送給 Anthropic，寫明）、團隊範本（第三個可選的 AI 工具，預設仍是 Claude Code → Codex）、第一位 CEO（最後一順位）。
   **記憶對 AGY 員工預設關，打開要再確認「會送到 Google」**（使用者拍板第 7 點）。
   **共用資料夾這版不開放給 AGY 員工**（協調者依真機結果決定；原本的設計是預設關、打開前確認「會送到 Google」，程式留著，只是 `shared_folder.SUPPORTED_ENGINES` 不含 `agy-chat`）：
   真機看到 AGY 的檔案工具可以寫進共用資料夾（會先問），但在共用資料夾裡用 shell 寫檔被 AGY 的沙盒擋住（`--add-dir` 不會讓沙盒可寫）。兩種行為不一致，員工會卡住，所以先不開。
   畫面與文件一律寫「AGY 員工這版不能用共用資料夾，之後 AGY 新版再檢查」；API 對 AGY 員工打開共用資料夾回 400 `card_tool_unsupported`，說同一句話。
   群組、派工把共用資料夾打勾時，有 AGY 員工就不能建立或確認（同一句話）。要再開放：把 `agy-chat` 加回 `SUPPORTED_ENGINES`，並讓新的 AGY 版本的共用資料夾那段全部通過。

8. **管理員政策與使用者的 hooks**：`/etc/antigravity`（整個資料夾）與受管偏好 `com.google.antigravity` 存在就不啟動（清單來自 strings，不是官方文件）；
   **使用者家目錄有 `~/.agents/hooks.json` 就不啟動 AGY 聊天**（只看存不存在，不讀內容，不替用的人動）：hooks 是 AGY 會自動執行的指令，VBear 問不到也擋不了。

9. **MCODE 這版不做聊天**（使用者拍板第 1–4 點）：維持 ADR 0002 的「只有完整模式」；MCODE 出新版時用 spike 的方法再檢查。

## 考慮過的其他選項

- **AGY 專用的 HOME，另外登入一次 Google**（像 Codex 的 `CODEX_HOME`）：可以完全不讀使用者的技能，但要先做一次登入的實測、用的人要多登入一次，還可能碰到鑰匙圈。使用者選了不另外登入。
- **`toolPermission: "strict"`**（連工作資料夾內的讀取都問）：VBear 能判每一次讀取（像 Claude 聊天），不怕經由連結讀到外面；但 spike 沒有用它跑過一般的聊天，行為不確定。
  這版只在版本檢查用它證明 settings 有被讀；改用它要先用 `--mode agy-chat` 驗證。
- **`BypassSandbox` 出卡片加警告**：需要網路的事能做，但「允許的指令一定在沙盒裡」這個好說明的保證就沒了。不選（使用者拍板第 7 點）。
- **送第二個 prompt 導正進行中的回合（改內容再問）**：比較快，但沒有實測。不選。
- **每回合以上限計費**：最保守，但 AGY 用的是 Google 方案，不是 VBear 的錢；照 Codex 的估算比較接近實際。不選。
- **把 MCODE 和 AGY 一起做**：MCODE 0.5.2 做不到每次都問與沙盒。不選。
- **共用資料夾對 AGY 開放，以版本檢查的共用資料夾段把關**：這是原本的選擇（使用者拍板「記憶與共用資料夾預設關、打開前提醒」）。真機上那一段有兩項沒過（見「真機結果」），
  所以改成這版不開放，程式留著、只拿掉一個名字。

## 後果

- 只用 AGY 的人可以在 VBear 裡聊天、開群組、被派工、排例行工作、套用團隊範本（不能用共用資料夾）；第一次聊天前要按一次「驗證聊天」（Google 方案，不另外花錢），AGY 更新後要再按一次。
- 需要網路或寫工作資料夾外的事，AGY 員工在聊天裡做不到（要做請改用完整模式的終端機，或其他 AI 工具的員工）。
- 「改內容再問」在 AGY 上多一個回合。
- 用的人自己的 AGY 技能會進到聊天；有 `~/.agents/hooks.json` 的人要先移走才能用 AGY 聊天。
- 花費是 VBear 的估算，不是帳單；AGY 不回報方案用量，也不說什麼時候恢復（倒數接續對 AGY 寫「未知」）。
- AGY 自己存的對話副本留在 `<state>/agy-chat-home/antigravity-cli/conversations/`，刪除聊天時不刪（刪除確認寫明）。
- AGY 1.5.3 的執行類與修改類工具呼叫（execute、edit、delete、move）會先以 `in_progress` 宣告、再 `pending`、再要求許可，所以只有完全照這個順序（`in_progress` → `pending` → request_permission → 答覆 →（拒絕時）`in_progress` → `failed`／`cancelled`）才不算違規；多出來的 `in_progress`、順序不對、看不懂的狀態、被允許之前出現任何輸出（文字或 exit code）、沒被問就 `completed`／`failed`、回合結束時還停在宣告狀態，都算違規，被允許的呼叫仍用簽章檢查；這是版本表的欄位 `announced_kinds`，其他種類與其他版本照舊，`in_progress` 沒有被允許就停。
- AGY 執行指令後會建 `antigravity-cli/persistent_terminals`：它在 AGY 自己會建的名稱表裡，但裡面只准表上列的名稱（`cli_closed`，目前沒有），所以裡面出現任何東西都會被點名拒絕，直到真機看過它放什麼；內建項目表逐一列出 AGY 1.5.3 `builtin` 的 62 個路徑，`builtin/.manifest` 只在檢查報告裡拿來對照名稱，不拿來決定放行。會執行的內建檔（`.js`、`.mjs`、`.json`、`.html` 等，版本表 `builtin_runnable`）只有在版本表 `builtin_sha256` 釘了 SHA-256 而且雜湊相符才放行，沒釘的一律拒絕，不只靠名稱（表上已釘 AGY 1.5.3 全部 41 個內建檔案的雜湊）；表上的資料夾名稱（`builtin`、`persistent_terminals`）拼法必須和表完全一致，只有大小寫不同的一律拒絕。
- AGY 自己內建的技能與外掛放在 `antigravity-cli/builtin`，名字長得像要禁止的 skills／plugins，所以不整個放行：版本表 `builtin_paths` 逐一列出 AGY 1.5.3 內建的路徑，只有完全符合的才通過，表上沒有的名字一律拒絕，其他位置的同名項目照舊拒絕。
- 聊天紀錄不新增事件種類：回到 v0.19.0 時 AGY 聊天會被標成有問題（欄位不符）、不能送也不能刪、檔案都留著，但當天的花費照樣算得出來（`tests/test_p46_flow.py` 用 v0.19.0 標籤的程式實際讀過）。
  用 AGY 套用過團隊範本的話，`applies.json` 的 `tool` 在 v0.19.0 是封閉的兩個值，整個套用紀錄會被讀成有問題：v0.19.0 不能再套用、也不能復原任何團隊範本，在 v0.20.0 先復原也不會把那筆紀錄移除。
  其他細節（角色卡、群組、例行工作、記憶開關、`agy-chat-home`、啟動紀錄）見 `docs/SECURITY-MODEL.md`「Going back to v0.19.0」與 CHANGELOG。
- 殘餘風險（寫在 `docs/SECURITY-MODEL.md`「Chats with an AGY role card」）：
  - 用的人自己的 AGY 技能（可能還有 `~/.agents` 底下的工作流程與 agents 定義）會載入；
  - AGY 程序本身（不是它跑的指令）不在沙盒裡、用真的 HOME；VBear 只控制參數、環境、設定資料夾與每個請求的回答；
  - 工作資料夾內的讀取不經 VBear，VBear 看到路徑在外面就停，但可能來不及（版本檢查 `link_read` 證明測過的情況沒有漏）；
  - 沙盒允許寫暫存資料夾與常見的 build cache；系統檔可能讀得到；
  - 讀取卡允許後，讀到的內容會送到 Google（卡片上寫明）；
  - 每回合上限只在回合開始前檢查，一回合可能超過；
  - 管理員政策清單來自 strings，不是官方文件；App 共用的使用者權限會不會合併沒有驗證（以「沒問就完成就停」兜底）；
  - AGY 會自己更新，新版本要重新驗證（換版本就不能聊天，直到通過）；
  - 員工被允許的指令可以讀到 VBear 的存取權杖並呼叫 VBear 的 API（和所有聊天相同；真機上沙盒擋住寫外面、讀外面與連網，但讀 VBear 自己的檔案沒有專門驗證）。

## 真機結果（第 7 次真機檢查，AGY 1.5.3）

前六次真機檢查各抓到一個設計沒料到的事，每一次都改了程式與版本表再跑（過程在證據檔第 12 節）；第 7 次主要檢查全部通過：
15 個回合，VBear 的估算 US$0.57（用的是使用者的 Google 方案，不是錢）；`ask_probe` 的結論是 `asked_and_refused`。

- AGY 真正的順序是：tool_call `in_progress` → `pending` → `request_permission` → 答覆 → `in_progress` → `completed`／`failed`。這就是第 4 項「後果」裡 `announced_kinds` 嚴格順序檢查的依據。
- 按停止 3.1 秒內結束，之後沒有留下程序。AGY 的持久終端機若有子程序離開程序群組，VBear 的設計是交給人工處理，真機上這個設計如預期運作。
- 沙盒擋住寫外面、讀外面與連網。
- 「改內容再問」（拒絕、下一則訊息送改過的內容、AGY 再問一次）有效。
- 內建檔案：41 個檔案的 SHA-256 釘在版本表，資料夾名稱逐字檢查；內建項目表共 62 個路徑（41 個檔案、21 個資料夾）。
- SQLite 的 `conversation_summaries.db` 在續接時會留下 `-journal`、`-shm`、`-wal` 三個旁檔，版本表允許這三個完全相符的名字（第 6 次真機檢查時第二次啟動因此被拒絕）。
- 共用資料夾那一段：`shared_write_card`、`shared_link_refused`、`shared_git_refused`、`shared_records_clean` 通過；`shared_shell_card` 沒過（在共用資料夾裡用 shell 寫檔，沙盒不讓寫，與檔案工具的行為不一致）；
  `shared_home_clean` 沒過，`found` 是 `["path"]`：檢查把一個家目錄路徑的字串當成帳號資料，那是路徑造成的誤判，不是真的洩漏（設定資料夾本身是乾淨的、`settings.json` 沒變）。
  這兩項是第 7 點「這版不開放共用資料夾」的依據；檢查程式的誤判留給 AGY 新版一起處理。
- 原本列為「未確認」的事，主要檢查的對應項目都通過了：系統指示有套用（`system_prompt_applied`）、`strict` 時 AGY 讀的是 VBear 寫的 settings（`strict_settings`）、`--disable-telemetry` 與 `useG1Credits` 不讓 AGY 拒絕啟動（`initialize`）、
  sessionId 是 UUID（`session_id_uuid`）、停止會中斷正在跑的指令（`stop_works`）、每個回合的用量加得起來（`usage_adds_up`）。`useG1Credits` 是不是 settings 的欄位仍然沒有證實。各項見證據檔第 11 節。
