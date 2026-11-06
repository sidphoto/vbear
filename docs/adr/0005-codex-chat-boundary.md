# 0005 Codex 聊天用 app-server、VBear 專用的 Codex 登入資料夾，每個指令都問

日期：2026-11-06　狀態：已決定（使用者授權「細節依決策紀錄決定」，依 ADR 0001–0004 提出；第 3、4 點是使用者可以再改的取捨，改的話要連同畫面文字與 `docs/SECURITY-MODEL.md` 一起改）

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
4. **沙盒用舊式 `workspace-write`**：只能寫員工自己的工作資料夾，排除 `/tmp` 與 `$TMPDIR`，不能連網。
   代價：指令可以讀整台電腦的檔案（作業系統沙盒不擋讀），只靠「每個指令都要用的人按允許」把關，與 Claude 聊天
   （Bash 沙盒也不擋讀、每個 Bash 都問）相同。不選權限設定檔的「全硬碟不可讀」，因為它會讓檔案修改全部失敗；
   等 Codex 修好後，用 `--mode codex-chat` 驗證再換。
   檔案修改另由 VBear 自己檢查路徑：工作資料夾外、或工作資料夾裡的 `.codex`、`.agents`、`.git`，直接拒絕，不給允許選項。
5. **花費**：Codex 不回報金額（實測沒有任何 cost 欄位），只回報 token 數。VBear 依 token 數估算後計入每天上限：
   每回合 =（這回合用掉的 token 總數 ÷ 1,000,000）× US$1.00，無條件進位到分，至少 US$0.01。
   畫面一律寫「估計」與「不是帳單；Codex 用的是你的 ChatGPT 方案」。沒有 token 數可用（停止、逾時、程序結束）時以這回合上限計。
   VBear 每次收到 token 數就核對，到上限就中斷這回合；兩次核對之間可能多出一次模型回應，這是殘餘風險。

## 考慮過的其他選項

- 用用的人自己的 `~/.codex`：不必再登入一次，但用的人的 AGENTS.md、MCP 伺服器、規則、`approval_policy` 都會進來（實測已發生），
  違反「聊天不讀你自己的設定」，而且 MCP 工具呼叫 VBear 無法事先列出。
- 把 `~/.codex` 的登入檔連結或複製到專用資料夾：VBear 不碰登入資料（ADR 0001 Q1-2）；更新 token 時還可能讓用的人自己的 Codex 被登出。
- `codex exec --json` 加 `exec resume`：會讀的設定可以關掉，但 headless 不能問，只能「全部放行（靠沙盒）」或「全部拒絕」，
  違反「聊天每次都問」。
- 權限設定檔、全硬碟不可讀：讀的保護較強，但檔案修改會失敗（實測）。
- 每回合固定以上限計費：最保守，但 US$3 的每天上限只夠 6 回合，對用 ChatGPT 方案、不另外付錢的人不合理。

## 後果

- 用 Codex 聊天前要多登入一次（在 VBear 的開始設定頁完成，不用打指令）。
- 「改內容再允許」在 Codex 上多一步：改完要再允許一次。
- 指令可以讀到工作資料夾以外的檔案，前提是用的人按了允許；允許卡要把完整指令顯示出來，不能截斷（沿用 P36 的整張卡規則）。
- 花費是 VBear 的估算，不是帳單；方案本身的用量（Codex 回報的 5 小時、每週百分比）另外顯示，來源是 Codex。
- Codex 自己保存的對話副本留在 `<state>/codex-chat-home/`，刪除聊天時不會刪掉它（刪除確認要寫明）。
- 依賴 `untrusted` 這個已退役的值，以及 app-server 這個標示為 experimental 的介面：每個 Codex 版本都要先過 `--mode codex-chat`。
- 聊天用哪個引擎，由角色卡的 AI 工具在開聊天時決定（Claude Code 是 `claude-chat`，Codex 是 `codex-chat`），之後不會換；
  卡換了 AI 工具，原來的聊天不能再送訊息（`card_tool_changed`），要開新的。其他工具的卡（Grok、AGY、MCODE、共用）一樣不能聊天
  （`card_tool_unsupported`），之後依序做 Grok、AGY、MCODE。
- 聊天紀錄的 `session_ready` 用中性的欄位 `cli_version` 放 AI 工具的版本；v0.13.0 之前的 Claude 聊天紀錄用 `claude_code_version`，照舊讀得懂。
- 殘餘風險（寫在 `docs/SECURITY-MODEL.md`「Chats with a Codex role card」）：讀不受沙盒限制；花費上限在兩次 token 回報之間可能多一次模型呼叫；
  依賴已退役的 `untrusted`；app-server 是 experimental 介面。
