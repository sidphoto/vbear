# 0005 Codex 聊天用 app-server、VBear 專用的 Codex 登入資料夾，每個指令都問

日期：2026-11-06　狀態：已決定（使用者授權「細節依決策紀錄決定」，依 ADR 0001–0004 提出；第 3、4、7 點是使用者可以再改的取捨，改的話要連同畫面文字與 `docs/SECURITY-MODEL.md` 一起改）

## 背景

v0.13.0 要讓工具是 Codex 的角色卡也能聊天（ADR 0001 Q1-5）。聊天的預設是「每次都問」（P36 拍板 2），
不讀用的人自己的 AI 工具設定（P36：Claude 聊天用 `--setting-sources ""`，「看不到你自己的 Claude 設定，這是代價」）。
P38-0 用本機 Codex 0.163.0 實測（證據整理在 `docs/evidence/codex-0.163.0-chat.md`）：

- 能做到「長駐、多回合、用工具前先問 host、可以允許或拒絕」的只有 `codex app-server`（stdio JSON-RPC）。
  `codex exec` 在 headless 模式強制 `approval_policy=never`（原始碼 rust-v0.163.0 `codex-rs/exec/src/lib.rs`），
  0.163.0 沒有 `mcp-server`、`proto` 子指令。
- `codex app-server` 沒有 `--ignore-user-config`、`--ignore-rules`、`--ephemeral`（本機 `--help` 與實測都拒絕這些參數；
  原始碼 `codex-rs/cli/src/main.rs` 以 `LoaderOverrides::default()` 啟動 app-server）。用的人平常的 `~/.codex` 一定會被讀。
  實測時它載入了用的人自己的 AGENTS.md（`instructionSources` 1 筆，回覆因此變成中文）與 5 個 MCP 伺服器。
- 登入資料跟著 `CODEX_HOME` 走（`codex-rs/login/src/auth/storage.rs`）。全新的 `CODEX_HOME` 就是還沒登入。
- 回覆權限詢問只能選 accept／acceptForSession／decline／cancel（加兩種「以後都允許」的修正規則），**不能改內容**。
- 檔案修改（apply_patch）用 0.163.0 的權限設定檔，把整顆硬碟設成不可讀（`":root"="deny"`）時會失敗（實測 2 次），
  用舊式 `workspace-write` 沙盒才成功。

## 決定

1. **用 `codex app-server`，搭配 VBear 自己的 `CODEX_HOME`**：`<state>/codex-chat-home/`（0700），用的人要另外登入一次。
   開始設定頁多一個「讓聊天用的 Codex 登入」按鈕，在內建終端機送出固定的一行
   `CODEX_HOME=<那個資料夾> codex login -c cli_auth_credentials_store=file`。
   不複製、不連結、不讀用的人 `~/.codex` 裡的登入資料，也不使用用的人的 Codex 設定、規則、AGENTS.md 與 MCP 伺服器。
   這個資料夾不和流程審查用的 `<state>/codex-home` 共用：審查有自己的登入指紋綁定與 512 MiB 監測，聊天紀錄不應該擋住審查。
2. **每個指令都問**：`thread/start` 明確送 `approvalPolicy: "untrusted"`、`approvalsReviewer: "user"`。實測連 `ls -a` 也會問；
   檔案修改在 `untrusted` 下一律問（原始碼 `codex-rs/core/src/safety.rs`）。VBear 不送 acceptForSession、
   acceptWithExecpolicyAmendment、applyNetworkPolicyAmendment，也就是沒有「以後都允許」。
   注意：官方文件說 `untrusted` 已退役，0.163.0 的 app-server 仍接受；之後的版本若拒絕，版本閘門會失敗，聊天不開（fail closed）。
3. **「改內容再允許」改成「拒絕，請 Codex 照你改的再問一次」**：VBear 先回 decline，再用 `turn/steer` 把用的人改好的指令
   或內容當成使用者的話送進同一個回合。Codex 會為新的指令再跳一張卡，用的人看清楚後再按允許（實測：改成
   `echo changed-by-user > shell.txt`，再問一次、允許後檔案內容是改過的）。畫面要寫明「Codex 會再問你一次」，
   不能說成「已經照你改的執行」。
4. **沙盒設定用舊式 `workspace-write`**：設定上只能寫員工自己的工作資料夾，排除 `/tmp` 與 `$TMPDIR`，網路關閉。
   但「用的人按了允許的指令」不一定還在沙盒裡，見第 7 點。
   代價：指令可以讀整台電腦的檔案（作業系統沙盒不擋讀），只靠「每個指令都要用的人按允許」把關，與 Claude 聊天
   （Bash 沙盒也不擋讀、每個 Bash 都問）相同。不選權限設定檔的「全硬碟不可讀」，因為它會讓檔案修改全部失敗；
   等 Codex 修好後，用 `--mode codex-chat` 驗證再換（第 7 點）。
   檔案修改另由 VBear 自己檢查路徑：工作資料夾外、或工作資料夾裡的 `.codex`、`.agents`、`.git`，直接拒絕，不給允許選項。
5. **花費**：Codex 不回報金額（實測沒有任何 cost 欄位），只回報 token 數。VBear 依 token 數估算後計入每天上限：
   每回合 =（這回合用掉的 token 總數 ÷ 1,000,000）× US$1.00，無條件進位到分，至少 US$0.01。
   畫面一律寫「估計」與「不是帳單；Codex 用的是你的 ChatGPT 方案」。沒有 token 數可用（停止、逾時、程序結束）時以這回合上限計。
   VBear 每次收到 token 數就核對，到上限就中斷這回合；兩次核對之間可能多出一次模型回應，這是殘餘風險。

6. **家目錄是 git 資料夾時，多送兩個 `-c`，兩個都要**（發版前真機發現，再用 0.163.0 零花費探測確認；證據在
   `docs/evidence/codex-0.163.0-chat.md` 5a）：`~/.git` 存在時，Codex 把 `~` 當專案根，VBear 換了 `CODEX_HOME` 以後
   `~/.codex` 不再被跳過，於是被當成專案層讀進來；`thread/start` 又會自動把 `~` 寫成 trusted 到聊天用的 `config.toml`，
   讓使用者自己的 MCP 伺服器與技能都載入。`thread/start` 的回應（核准方式、沙盒、指示檔）完全看不出來。
   - `project_root_markers=[]`：專案根就是工作資料夾，不往上找；單獨用時 Codex 仍會替 `~` 寫入 trust。
   - `projects={"<工作資料夾>"={trust_level="untrusted"}}`：工作資料夾有了 trust 設定就不會自動寫入，專案層設定關閉；
     單獨用時技能仍會從停用的專案層載入。必須是**行內表格**：點號寫法會被含點的路徑（`~/.vbear`）切壞，而且 trust 照樣被寫入。
     路徑以 TOML 字串寫出（引號、反斜線跳脫），含控制字元或不是絕對路徑就拒絕啟動。
   - MCP 檢查改成帶 `threadId` 的 `mcpServerStatus/list`（拿到 thread id 之後才送）；不帶時 Codex 只回程序啟動時載入的，
     那時還沒有 trust，永遠是空的。
   - 聊天用資料夾的 `config.toml` 維持「有就拒絕、不自動刪」，訊息改成說明它可能是舊版寫進去的信任設定、要移走的位置。
   - 版本檢查多兩個斷言：thread/start 之後沒有 `config.toml`；每個程序的參數都帶了兩個設定（報告不記路徑）。

7. **允許後可能在沙盒外執行，照現在發布，卡片照實寫明**（發版前真機發現，再讀 0.163.0 原始碼確認；證據在
   `docs/evidence/codex-0.163.0-chat.md` 5b）：`untrusted` 下，用的人允許的指令若被沙盒擋下（輸出含 `operation not permitted`
   之類的字），Codex 會不再問、不用沙盒再跑一次；模型要求升級（`sandbox_permissions` 設成 `require_escalated`）時，允許後
   第一次就不用沙盒。不用沙盒的指令可以寫整台電腦、可以連網。卡片的穩定欄位沒有任何一個說「這次會不用沙盒」，
   回覆也沒有「允許但留在沙盒裡」的選項，所以 VBear 在卡片上分不出來。研究給了三個選項，使用者 2026-11-06 選了第三個：
   - **權限設定檔 `:root`＝`deny`＋`untrusted`**：每個指令都問，允許後還在沙盒裡（不重跑、升級不放寬、網路關閉），
     讀取也限制在工作資料夾。但 `apply_patch` 在這個設定下會失敗（P38-0 實測，原因還沒找到，看起來是 Codex 的問題），
     所以檔案修改全部不能用。**不選**：現在不能改檔，聊天就少了一半用處。
   - **`never`＋舊式沙盒**：沒有任何路可以跑出沙盒，`apply_patch` 在工作資料夾內自動成功。但完全沒有卡片，
     讀取也不問，模型可以讀家目錄的私人檔案、送到 OpenAI，比現在更糟。**不選**。
   - **維持現狀（`untrusted`＋舊式沙盒），卡片與文件照實寫明風險**：**選這個**。理由：可以馬上發布、檔案修改照常、
     每個指令仍然都問；風險交給用的人在卡片上判斷，而不是假裝沙盒擋得住。
   做法：Codex 聊天的**指令卡**（不是檔案卡）在允許按鈕上方寫「允許後，這個指令可能在沙盒外執行：能改到工作資料夾以外的檔案，
   也能連網。只允許你看得懂、確定沒問題的指令。」Claude 聊天的卡片不變。檔案修改照舊：工作資料夾外與 `.codex`、`.agents`、
   `.git` 由 VBear 直接拒絕、沒有卡片。版本檢查的 `outside` 步驟：`apply_patch` 寫外面必須被 VBear 自動拒絕、沒有卡片、
   外面沒有檔案（仍是通過條件，檢查名 `outside_patch_refused`）；允許的 shell 寫外面只記在報告的觀察項目，
   不影響通過，檢查寫出去的檔案當場清掉。
   **什麼時候回頭改**：等 Codex 修好權限設定檔下的 `apply_patch`（或有「允許但留在沙盒裡」的回覆），再改用權限設定檔，
   拿掉卡片上的警告，把 shell 寫外面改回通過條件。到那時要重新用 `--mode codex-chat` 驗證。
   另外要記得：官方文件說 `untrusted` 已退役（第 2 點），選項一與現狀都依賴它。

## 考慮過的其他選項

- 用用的人自己的 `~/.codex`：不必再登入一次，但用的人的 AGENTS.md、MCP 伺服器、規則、`approval_policy` 都會進來（實測已發生），
  違反「聊天不讀你自己的設定」，而且 MCP 工具呼叫 VBear 無法事先列出。
- 把 `~/.codex` 的登入檔連結或複製到專用資料夾：VBear 不碰登入資料（ADR 0001 Q1-2）；更新 token 時還可能讓用的人自己的 Codex 被登出。
- `codex exec --json` 加 `exec resume`：會讀的設定可以關掉，但 headless 不能問，只能「全部放行（靠沙盒）」或「全部拒絕」，
  違反「聊天每次都問」。
- 權限設定檔、全硬碟不可讀：讀的保護較強，但檔案修改會失敗（實測）。第 7 點把它和 `never` 都列為選項，使用者沒有選。
- 每回合固定以上限計費：最保守，但 US$3 的每天上限只夠 6 回合，對用 ChatGPT 方案、不另外付錢的人不合理。

## 後果

- 用 Codex 聊天前要多登入一次（在 VBear 的開始設定頁完成，不用打指令）。
- 「改內容再允許」在 Codex 上多一步：改完要再允許一次。
- 指令可以讀到工作資料夾以外的檔案，前提是用的人按了允許；而且按了允許的指令可能在沙盒外執行，能寫整台電腦、能連網（第 7 點）；允許卡要把完整指令顯示出來，不能截斷（沿用 P36 的整張卡規則）。
- 花費是 VBear 的估算，不是帳單；方案本身的用量（Codex 回報的 5 小時、每週百分比）另外顯示，來源是 Codex。
- Codex 自己保存的對話副本留在 `<state>/codex-chat-home/`，刪除聊天時不會刪掉它（刪除確認要寫明）。
- 依賴 `untrusted` 這個已退役的值，以及 app-server 這個標示為 experimental 的介面：每個 Codex 版本都要先過 `--mode codex-chat`。
- 聊天用哪個引擎，由角色卡的 AI 工具在開聊天時決定（Claude Code 是 `claude-chat`，Codex 是 `codex-chat`），之後不會換；
  卡換了 AI 工具，原來的聊天不能再送訊息（`card_tool_changed`），要開新的。其他工具的卡（Grok、AGY、MCODE、共用）一樣不能聊天
  （`card_tool_unsupported`），之後依序做 Grok、AGY、MCODE。
- 聊天紀錄的 `session_ready` 用中性的欄位 `cli_version` 放 AI 工具的版本；v0.13.0 之前的 Claude 聊天紀錄用 `claude_code_version`，照舊讀得懂。
- 家目錄是 git 資料夾的處理有兩個殘餘風險：系統、裝置管理或雲端的 managed 設定排在 `-c` 之上，可能把兩個設定蓋回去
  （VBear 遇到已知的管理員政策來源就拒絕，但不讀 Codex 合併後的設定來證明）；停用的專案層與 `.agents/skills`
  仍是技能來源（工作資料夾的 `.codex`、`.agents`、`.git` 由 VBear 拒絕檔案修改，Codex 沙盒也預設唯讀，但使用者允許的指令仍可能建立）。
- 殘餘風險（寫在 `docs/SECURITY-MODEL.md`「Chats with a Codex role card」）：讀不受沙盒限制；允許後的指令可能在沙盒外執行；花費上限在兩次 token 回報之間可能多一次模型呼叫；
  依賴已退役的 `untrusted`；app-server 是 experimental 介面。
