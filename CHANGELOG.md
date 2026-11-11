# Changelog

## v0.25.0 — the first run on one page

A new person used to go home page → start-up page → create-CEO page → chat. Now the first run is done on the home page: pick one AI, get it ready, press one button, and you are talking with your CEO. The words for "this AI tool cannot be used" are plain now. This release only changes what the screen shows; it adds no new request and changes nothing on the server.

- **One page for the first run.** With no employee yet, the home page says 「先選一家你有在用的 AI」 and shows the start-up page's own cards (nothing preselected, nothing marked as recommended, the order never changes by state). Pick one and its steps open in place: install, log in, and the one button 「試一下，並做聊天安全檢查」, which still says what it will use and costs first, and does nothing until you press 「確認，開始」. When that AI can chat, a name box and 「建立 CEO，開始聊」 appear; the button makes the CEO (the same card, in the same "ask me about everything" mode, as the create-CEO page) and opens the conversation, the opening sentence only put in the box. 「每件事先問我」 stays on the page, and for AGY so does the sentence that the talk goes to Google. The daily spending limit is a closed fold at the bottom, and the foot of the page links to 「到開始設定看全部 AI 工具」. Every step is your own press: nothing is picked, checked or created for you.
- **New people are no longer sent to the start-up page.** The home page used to send anyone who had not finished the start-up there. Now they stay on the home page and do the first run. Only the app window's first-time page (第一次打開 VBear, shown once) can still come first; its buttons (「我知道了，開始」 and 「略過」) go back to the home page. When you press 「建立 CEO，開始聊」 and the CEO is made, VBear marks the start-up as done (the same one request the start-up page's own button sends; if it fails you still get into the conversation). The start-up page, the create-CEO page and the first-time page still open from their addresses and work as before.
- **"Cannot use it" in plain words.** When an AI tool has updated itself to a version VBear does not know yet, the screen says 「你的 Claude Code 是 x 版，VBear 還不認得這一版，所以先不能用它聊天。等 VBear 出新版就能用。」 (the version only when the server told it; never looked up or guessed; no advice to go back to an older version). The server's own sentence stays whole under 「技術細節」. A tool that is not ready says which step is missing (not installed, not logged in, no safety check yet, an administrator's settings, a version it does not know, or that it could not be read) on the home page, on the create-CEO page and where a chat is prepared. After you pick an AI on the start-up page, the first line 「目前還沒有就緒的 AI 工具…」 goes away.
- **Three small fixes.** In settings 「用量與上限」 is above 「通知」. The 「存成團隊範本」 box has the site's input look, its content scrolls and its buttons stay at the bottom (and wrap on a narrow screen); the team-template preview no longer shows a strip of content under its bottom bar.
- **Tests and guard rules.** Rule 19a: on the home page the chat safety check is only sent by the confirm area's button (the same road as 16a); 19b: the CEO is only made inside the click of 「建立 CEO，開始聊」, and `setup_done` is written once after the card is made, never on load, pick or redraw; 19c: the plain sentence about an unknown version holds no version number that did not come from the server. Rules 15 to 18 are not changed and pass; 15b (no new `/api/` path, no changed route or event) passes unchanged. `tests/frontend/p52_first_run.cjs`, `p52_words.cjs`, `p52_small.cjs` and `tests/test_p52_docs.py` are new. The old three steps (`homeFirstSteps`) are gone.
- **Two things the review of v0.23.0 asked for.** The small message at the bottom of the screen (the toast) now shows above the phone drawer, the dialogs and the skill tip instead of under them. Guard rule 17 is stronger and only grew: 17a also reads `homeAskGrow` (which the example fill calls), 17b checks that `drawNavRecent` is only called from the chat list read and the page change, and 17c checks that no keydown on `document` or `window` can send from the home box. Each has a bad sample that must fire.
- **A first look by eye, and what it found.** For the first time the pages were photographed (with made-up data, by `tools/shots_stub.py`: a stub console on 127.0.0.1 that refuses every write, and a headless Chrome; 1280x800 light and dark and 400x800) and looked at. Six things were wrong and are fixed, on the screen only: on a phone the bar at the top was 82 to 200px high instead of 57px (two grid rows shared the free height); the open phone drawer hid the brand and had no clear way out, so now the bar stays above it and its button says 「關閉」; the box showed two rings when it had the focus, now one; a message of yours was twice as high as its words and a reply had an empty band under it (the hidden name-and-time line and the hidden 「記住」 buttons kept their room, now they sit over the gap between messages and are still reached by keyboard and shown on hover or focus); the arrow of a fold line was tiny and the line did not look like it opens; a plain drop-down was the browser's square one. `tests/frontend/p54_look.cjs` keeps these.
- **Money.** Nothing here costs anything by itself. The chat safety check, when you press 「確認，開始」, uses your own plan as before, and the page says so first.
- **Not tried on a real Mac / known limits.** The look was checked by reading the CSS and by the tests, not by eye in a browser (the first-run block in the new home column, the narrow-screen team-template box, the app window's first-time page). The tool state on the home page is read every 5 seconds but the chat state follows the home page's 30-second chat read, so it can be up to about 30 seconds behind until you press 「重新檢查」. `setup_done` stays false for someone who never makes a CEO here and never leaves the start-up page; the home page no longer depends on it.
- **Going back to v0.24.0.** Nothing to convert: no data file, setting or browser key changed (`vbear-setup-pick` is still read).

## v0.24.0 — a chat that reads like text

The chat page used to be a pile of boxes: every reply, every line you said, every tool the employee used and every turn's bill had its own frame. Now the page is the conversation. This release only changes what the screen shows; it adds no new request and changes nothing on the server.

- **Words, not boxes.** What the employee says has no frame or fill, with only the name over it. What you say is a soft grey bubble on the right. The time of each message is in the page and shows when you point at it or tab to it (and always, in small print, on a screen with no mouse). The column is centred, 720px at most.
- **The work is one line.** Tool uses, their results, what VBear allowed by itself, what a turn cost and the employee coming and going that follow one another are one closed line, for example 「用了 3 次工具・自動允許 1 次・細節」; open it and every original line is there, with its own amount. The line itself never shows an amount. A failed tool result is counted on the line (「1 筆失敗」).
- **Nothing that needs you is folded.** A card that asks you, what you decided, a refusal, an error, a message VBear does not recognise, the words said, and a turn that was stopped, hit a limit or went wrong (or a process that ended for a reason the page does not know) are always in the open. Folding is only how it looks: no record is dropped, drawn later or renamed (each keeps its `data-seq` and `data-chat`), and a fold you opened stays open when new lines arrive.
- **The box is the home page's box, and you can change whom you talk to.** The words above, whom you talk to at the left (the small button shows the employee's name), stop and send at the right. Press the name and a list opens: employees who can chat are the options; those who cannot are below in grey with one sentence why, and a press goes to the page that prepares them. On the home page a pick only changes whom 送出 sends to; on a chat page it goes to that employee's chat and carries the words you had not sent, which that page sends only when you press its 送出. Opening the list and picking from it make no request at all. Cmd/Ctrl + Enter still sends and Enter alone still does not (and now an IME's Enter does not either).
- **A one-row head.** The name, the state word and 「⋯」 in one row. The line 「職位・AI 工具・每件事先問你・對話會送到哪一家公司」 stays, a size smaller and grey, because it says where your words go. The page that prepares a chat and the list of chats use the same column; the list is plain rows (name, last time, a dot when a card waits for you), with the same words and links.
- **Tests and guard rules.** Rule 18a: a fold holds only the six quiet kinds and never a card, a decision, a refusal, an error, an odd message or the words said; 18b: changing whom you talk to sends and writes nothing and reads no chat list; 18c: only Cmd/Ctrl + Enter sends from the chat box; 18d: the line over a fold has no amount. Rules 15, 16 and 17 are not changed and pass; 15b (no new `/api/` path, no changed route or event) passes unchanged. `tests/frontend/p51_chat.cjs`, `p51_who.cjs`, `p51_head.cjs` and `tests/test_p51_docs.py` are new.
- **Money.** Nothing here costs anything.
- **Not tried on a real Mac / known limits.** The look was checked by reading the CSS and by the tests, not by eye in a browser: the pop-up list opens upwards from the chat box and was not looked at on a phone-width window. The list of employees comes from the chat list read when the page opened, so it can be a little old, and there is no button when that read failed. An employee with no chat yet is reached through the page that opens one (the pick itself creates nothing).
- **Going back to v0.23.0.** Nothing to convert: no data file, setting or browser key changed.

## v0.23.0 — a greeting and one box

Open VBear and you see one line, 「今天想做什麼？」, and a box. Type, press Cmd/Ctrl + Enter, and you are talking with your CEO. Everything else (your employees, the timed jobs, the settings) stepped back to the left bar. This release only changes what the screen shows; it adds no new request and changes nothing on the server.

- **The home page is a greeting and a box.** What waits for your decision is a small pill, 「有 N 件事等你決定」, that opens the list right where it is; when nothing waits (and VBear is sure it has read everything) the pill is not there, and while the data is still coming it says 「載入中」, never "nothing". The box is a big rounded one with the 送出 button at its corner; it grows as you type, Enter alone still does not send, and the cursor is in it when the page opens (not on a phone or tablet, where the keyboard would cover the page).
- **Three example sentences for the very first time.** 「幫我整理今天的待辦」, 「幫我寫一篇貼文」 and 「每天早上給我一份摘要」 only put the words in the box for you to change; nothing is sent, nothing costs anything, until you press 送出.
- **Your employees are small faces with names**, with a 「＋」 at the end to add one. 「今天」 is one grey line. Someone with no employee yet still sees the three steps.
- **The left bar is a record of conversations.** 新對話 (the old 首頁 item: back to the box), 最近 (the employees you talked with lately, up to 8, newest first, a dot when a card of theirs waits for you), then 員工, 工作 and 設定 a size smaller at the foot, and the advanced items below as before. 最近 uses only the chat list the home page already read: it makes no request of its own and has no timer (the chat list makes the server ask each AI tool for its version, so reading it more often is not free). On a phone the bar is a drawer behind a 選單 button.
- **Neutral colours, fewer frames.** Black, white and grey instead of cream and green; green is kept for the main buttons and the page you are on. Buttons are round pills, cards keep their frame but lose the shadow, the home page has no boxes inside boxes. The status colours (green, amber, red, blue), the office and the cards of the game did not change. Text contrast is at least as high as before in both light and dark.
- **Tests and guard rules.** Rule 17a: the example sentences send nothing; 17b: 最近 does not read the chat list and sets no timer; 17c: only Cmd/Ctrl + Enter sends from the home box. Rule 15b (no new `/api/` path, no changed route or event) passes unchanged. `tests/frontend/p50_home.cjs`, `p50_nav.cjs`, `p50_theme.cjs` and `tests/test_p50_docs.py` are new.
- **Money.** Nothing here costs anything.
- **Not tried on a real Mac / known limits.** The look was checked by reading the colours and by the tests, not by eye in a browser; the contrast numbers are computed from the colour values. The 最近 list is empty until the home page has read the chat list once (the page does not guess). The example sentence replaces what is already in the box without asking.
- **Going back to v0.22.1.** Nothing to convert: no data file, setting or browser key changed.

## v0.22.1 — Claude Code 2.1.322 and Codex 0.167.0

The AI tools update themselves, and a Mac that had updated could no longer chat: the screen said, for example, 「Codex 0.167.0 沒有管理員政策來源清單，不能啟動」. This small release teaches VBear two of the three new versions. **It is not a new feature, and it does not make a version trusted.**

- **Claude Code 2.1.322 and Codex 0.167.0 can start a chat.** Each now has chat constants and an administrator-source list (`chat_protocol.VERSIONS`, `codex_chat_protocol.VERSIONS`, `admin_policy.CLAUDE_SOURCES`, `admin_policy.CODEX_SOURCES`). They are the previous version's, because the comparison found nothing that differs: Claude Code's `--help` is identical to 2.1.319's and its program names the same administrator places; Codex's `--help` for every command VBear runs is identical to 0.163.0's, its program names the same places (`/etc/codex`, `com.openai.codex`), and its app-server protocol (printed by `codex app-server generate-json-schema`, no login) adds to 0.163.0's and changes nothing a VBear chat sends or reads. Evidence, method and date: `docs/evidence/claude-code-2.1.322-chat.md`, `docs/evidence/codex-0.167.0-chat.md`.
- **You still press 「聊天安全檢查」 once for each.** Neither version is in any verified list; a chat starts only after the chat check passed on your Mac for that very version. Nothing about that rule changed, and nothing in the comparison replaces the check.
- **Codex 0.167.0: two switches are gone.** `realtime_conversation` and `worktrees` are now "removed" features in Codex (on for good), so VBear's `--disable` for them is accepted and does nothing. They belong to Codex's terminal program and to requests a client sends, which a VBear chat never does. This is written down in `docs/SECURITY-MODEL.md` ("New versions of the AI tools (v0.22.1)") as a residual risk.
- **AGY 1.5.5 is not added.** AGY's `--help`, administrator-source strings and protocol names are the same as recorded for 1.5.3, but one of AGY's own built-in skill files (`native_swarm/SKILL.md`) is different, and VBear pins the hash of every built-in file (and two more files AGY generates cannot be read from the program). A folder written by 1.5.5 would be refused, so adding the version by copying 1.5.3's table would not give a working chat. It needs a run of the real 1.5.5 to record the new table. `docs/evidence/agy-1.5.5-not-added.md` has the difference. AGY chats stay on 1.5.3 only.
- **Start-up boundary.** `vbear/admin_policy.py`, `vbear/runtime/chat_protocol.py` and `vbear/runtime/codex_chat_protocol.py` each gained one entry (nothing else in how a chat starts). No route, setting, limit, kind of chat event or `localStorage` key changed. Tests: `tests/test_admin_policy.py`, `tests/test_chat_protocol.py`, `tests/test_codex_chat_protocol.py`.
- **Money.** Nothing here costs anything. The chat check, when you press it, uses your own plan as before.
- **Known limits.** (1) No real stream of 2.1.322 or 0.167.0 was recorded; the fixtures are the earlier versions', and the comparison reads names, not behaviour (the files Codex makes in its own folder, the order of its messages, and what Codex 0.167.0's new default-on features do are only shown by the chat check). (2) Claude Code's installed 2.1.321 was not compared. (3) Not tried on a real Mac in this release.

## v0.22.0 — easier to pick up, part 2 (好上手 2)

Part 1 made the screens plain. Part 2 is about **the first ten minutes and about not missing something that waits for you**. The start-up page now asks **one question first, 「先選一家你要用的 AI」**, and opens only the AI you pick, with one checklist and **one button** that does the try and the chat safety check together (after you confirm). The home page **draws its frame first** and never says "nothing waits for you" before it has read anything. A permission card in a chat that waits for your press is now part of 等你決定, in the number in the page title, and, if you switch it on, in a **Mac notification that carries only the number**. And deleting a meeting or a proposal **no longer makes today's spending smaller** (#86). Nothing the server may do was widened: no API route, setting key or kind of chat event was added, and none of the files that start or check an AI tool was changed.

**What you will see.**
- **Start-up page: pick one AI first.** Three big cards in a fixed order, Anthropic Claude (Claude Code), OpenAI ChatGPT (Codex) and Google Gemini (AGY), each with one line about the account it uses and the state of this Mac. xAI Grok is a grey line 「之後支援」, not a button; MCODE is not on a card. Nothing is preselected, nothing is marked 「建議」, nothing is reordered by state. Pressing 「選這個」 opens that AI's old row (install, log in, 「我登入好了」, the Codex chat login) and a **checklist** 「檢查能不能用」 (installed, logged in, chat login for Codex, answers, chat safety check; each is 通過, 沒過, 還沒做, 進行中 or 讀不到, and a failed one says what to do in plain words with the original sentence behind 「技術細節」). 「換一家」 goes back to the three cards. The other tools are in a closed 「其他 AI 工具（之後隨時可以加）」. The last button is 「下一步：建立 CEO」 (it was 「開始使用」). The page draws its frame first and each card fills when its state is read. The pick is kept only in this browser (`localStorage` key `vbear-setup-pick`), written only when you press 「選這個」.
- **One button, asked first.** 「試一下，並做聊天安全檢查」 opens a confirm area that says what each of the two parts does and what it costs (the try counts in the daily limit; the chat safety check uses your own plan, with the vendor's full cost text), and that the safety check runs in the background. Only 「確認，開始」 sends anything (`POST /api/setup/tools/<id>/try {"confirmed": true}`, then, if this version has not passed yet, `POST /api/chat-support/verify`); 「取消」 sends nothing. You can go on to create the CEO while it runs; the prepare page of a chat knows a running safety check, reads its progress, and opens the chat by itself when it passes (the opening words are put in the box; nothing is sent). A tool an administrator setting blocks has no button: the checklist says why and offers 「換一家」.
- **The CEO is made on the AI you picked.** The create-CEO page asks `GET /api/first-ceo?tool=<id>` (any other value is a 400); if that tool is not ready it says 「你選的 X 還沒準備好，回開始設定把它準備好，或換一家。」 and **does not swap in another one**. The page is lighter: 「每件事先問我」 and, for AGY, the sentence that the talk goes to Google stay in view; the rest is in a closed 「詳細資訊」. In the first conversation with the CEO there are a few **opening choices** (they only put words in the box; nothing is sent), and when the CEO's last reply looks like a plan (you spoke at least twice and the reply has three or more list lines) a line asks 「計畫整理好了嗎？」 with 「請幕僚長安排」 (the same preview as the 「⋯」 item; nothing that costs money is sent before you confirm in it) and 「先不用」.
- **Home draws its frame first.** Each of the three blocks says 「載入中…」 until its own data arrives; after 3 seconds a line lists only what is still being read; after 60 seconds it says 「讀不到…」. Before the data is there the page never says 「沒有要你決定的事」 and never shows 0. The logo is retried once, then the letters 「VB」 are shown instead of a broken picture.
- **Chat cards in 等你決定, in the title and on the Dock.** A chat that has a permission card waiting is a row of its own (it opens that chat). The tab title is `VBear` or `(N) VBear` (digits only; no number when a read was incomplete, for example when the background program is not running). The Mac app sets the Dock number and the window title from `{count, notify}`, which the page hands over through `window.webkit.messageHandlers.vbearWaiting`. The home page re-reads its other sources every 5 seconds but reads the chat list (`GET /api/chats`) **at most every 30 seconds**.
- **A Mac notification, off by default.** Settings has a 「通知」 block with one switch (`vbear-notify` in `localStorage`, only `"on"` means on). It asks the Mac for permission **only when you press the switch**; the content is fixed, 「VBear」 and 「有 N 件事等你決定」, and nothing else; it is posted only when a complete read counted more than the last one and the app is not in front. A refused or unavailable permission leaves the switch off and says so. In a browser the browser's own notification is used the same way. The app opens no connection (no `URLSession`, `URLRequest` or `Process`), asks the system once (`requestAuthorization`, alert only) and posts under one fixed identifier.
- **Deleting no longer lowers today's spending (#86).** When a meeting, a staffing, chief-of-staff, memory-suggestion or skill-suggestion record is deleted, what it spent is first kept in `<state>/spend-keep/<kind>-<id>.json` (folder 0700, files 0600) for two days, so 「今天已花多少」 and the daily limit still count it. A kept file that is bad or unknown makes today's spending unknown and the spending is stopped (fail closed). A record that is queued or running cannot be deleted (409 `running`). (A deleted chat already kept its cost in `chat-spend/`; that did not change.)
- **Small fixes.** 「連不上 VBear 的伺服器…」 in plain words with a next step (`Failed to fetch`, `Load failed`, …); the translation state and the data-flow list in plain words; the template preview has the name box, 「沒有指定職位」, the models' own labels and a bar fixed at the bottom; one check-box size (18 px); the settings summary says 「已到上限」 only when the lamp is red.

**The tasks.**
- **P48-1 — the start-up page: pick one, one button, the checklist, guard rules 16a and 16b.** `tests/frontend/p48_setup.cjs`.
- **P48-2 — home frame first, the waiting model with chat cards, the title number, the logo fallback, the 30-second chat read; guard rules 16c and 16d.** `homeWaitingRows()`, `tests/frontend/p48_home.cjs`.
- **P48-3 — the lighter create-CEO page on the picked AI (`?tool=`), opening choices, the chief-of-staff hint, a running safety check in the prepare page; guard rule 16g.** `vbear/first_ceo.py` (`plan(..., wanted=None)`), `tests/frontend/p48_chat.cjs`, `WantedToolTests` in `tests/test_p38_first_ceo.py`; guard 15b's list of `/api/` paths gained `/api/first-ceo?tool=` and nothing else.
- **P48-4 — the app side of the waiting count and the notification switch; guard rule 16e.** `macos/VBear/main.swift`, `macos/smoke_test.sh`, `macos/test_waiting_bridge.sh`, `tests/frontend/p48_notify.cjs`, `tests/test_p48_notify_static.py`.
- **P48-5 — deleting a record no longer lowers today's spending (Codex); guard rule 16f.** `vbear/spend_keep.py` and one line in each of `chief.py`, `meetings.py`, `memory_suggest.py`, `skillbook_suggest.py`, `staffing.py`; `tests/test_p48_spend_keep.py`, `DeletingNeverLowersTheDay` in `tests/test_autonomy_guard.py`.
- **P48-6 — small leftovers and a regression test.** `tests/frontend/p48_sweep.cjs`; R8 regression tests in `tests/test_qa_p47.py` (`tools/qa_p47.py` itself did not change).
- **P48-7 — documents, ADR 0014, the real-machine walk.** ADR 0014 is final (and ADR 0001's Q1-4 says what changed); `docs/SECURITY-MODEL.md` has 「Easy start 2 (v0.22)」; both READMEs, `docs/ARCHITECTURE.md`, `docs/REFERENCE.zh-TW.md` and `GLOSSARY.md`; `tools/qa_p48.py` with `tests/test_qa_p48.py`; `tests/test_p48_docs.py`; the version number.

**What did not change (safety).** No server route (API), setting key, kind of chat event or `localStorage` key beyond the two new ones was added (`vbear-setup-pick` and `vbear-notify`; the new `GET /api/first-ceo` query `tool` is a parameter of an existing route). `git diff v0.21.0 -- vbear/` is `chief.py`, `first_ceo.py`, `meetings.py`, `memory_suggest.py`, `server.py` (one line for the `tool` query and its 400), `skillbook_suggest.py`, `staffing.py`, the new `spend_keep.py` and the version number; none of `agent_launch.py`, `runtime/*`, `chat_service.py`, `*_verify.py`, `chat_check.py`, `cli_versions.py` or `admin_policy.py` was touched. The chat safety check is still done **once per version on each Mac**, is still announced with its cost first and asked for by a press, is not carried to another version and is not remembered in the browser. The page logs nobody in and decides nothing for anyone. The guard rules 1 to 15 are as they were (15b's list gained one path); rule 16 was added: **16a** the safety check is asked for by a press with its full cost first and not carried across versions; **16b** the picker logs nobody in, preselects nothing and writes the pick only on 「選這個」; **16c** home says 載入中 and never "nothing waits" or a number before the data is there; **16d** a waiting chat card is a row of its own, the title is a number only, the app gets only `count` and `notify`, and the chat list is read at most every 30 seconds; **16e** the notification is local, count-only, off by default and asked for only by the switch; **16f** deleting never lowers the day's spending; **16g** an opening choice and the hint only put words in the box or ask for a preview.

**Money.** Nothing in this release costs anything new. The checklist's button spends only after 「確認，開始」, in the same way as before (the try counts in the daily limit; the safety check uses your own plan); the create-CEO page, the opening choices and the hint send nothing that costs money by themselves. #86 can only make the day's spending larger or unknown, never smaller. The real-machine walk costs US$0 with `--no-ai` and at most US$0.30 with `--haiku`.

**Known limits.** (1) `GET /api/chats` makes the console run the three AI tools' `--version` on every call, with no cache (a cold start takes 2 to 7 seconds), and the start-up page, the home page and the chat pages read it; so chat-card numbers and notifications can be up to 30 seconds late on the home page. A cache of 5 to 10 seconds for the version probe on the server is the suggested fix for the next version; it is in a boundary file and was not done here. (2) `request_queue_size` was not changed: with 12 or more simultaneous connections some can be reset on the default queue of 5 (measured); a browser's 6 connections are fine; a one-line change to 64 exists. (3) From `serve` to a port that answers takes 2.4 to 10 seconds; the front end cannot fix that. (4) The logo's single retry: in some browsers an SVG's `naturalWidth` is 0, which only costs one extra `/logo.svg?r=1`. (5) 「換一家」 does not clear the stored pick, and the create-CEO page reads the stored pick. (6) The notification switch does not notice that the Mac's permission was revoked in System Settings (the app checks the authorization before it posts, so nothing is posted). (7) An unsigned or ad-hoc signed app may not be given the notification permission; the page says so. (8) The result of 「會回話（試一下）」 is only shown in the page that is open. (9) The title and the Dock show no number when a read was incomplete (for example no background program). (10) The progress of a running safety check is read on the page's existing 5-second tick, not every 3 seconds. (11) The CEO is found by the position `planner`, not by `first_ceo_id`; the chief-of-staff hint is a literal rule (three list lines, two sends) and is hidden when the record was cut. (12) Rules 16a and 16b are checked on small samples (judge functions run on bad logs and bad sources), not by changing `web/app.js`. (13) Spend keeping: an unknown stray file in `spend-keep/` makes the day unknown; two versions writing at once are not covered; the skill suggestions' spending is not in the chat side's daily cap (as before); `chief.spend_kind` depends on the order of its checks; if the delete fails after the keep was written the cost may be counted twice, which is the careful way round. (14) The sticky bar of the template preview and the new layouts were not seen in a real browser. (15) The full Python test run takes about 33 to 42 minutes on the development Mac. (16) `tools/qa_p48.py` and `tools/qa_p47.py` are checks to run by hand, not part of the app.

- **On a real Mac:** on 2026-11-11 (Claude Code 2.1.322, which VBear cannot chat with yet; a fresh temporary home folder, so no AI tool was signed in) `tools/qa_p48.py --no-ai` was run on v0.21.0 and v0.22.0. On a cold start the home page now shows its frame in 0.14 to 0.22 seconds, with 「載入中…」 in the three blocks that are still waiting, where v0.21.0 showed nothing for 0.5 to 0.9 seconds; both finish when the AI tools' versions have been read (0.5 to 0.8 seconds, once 4.3 seconds). The start-up page shows its heading in 0.14 to 0.24 seconds instead of 1.4. It shows three cards with nothing chosen and Grok as a grey line; choosing Claude opened only its checklist, with 「換一家」. The create-CEO page, with Claude chosen and not ready, said so and offered nothing to create. No page said nothing waits and then showed a row; the title was `VBear`; the notification switch was off, pressing it sent nothing, and the headless Chrome's refusal was shown in plain words with the switch left off. Setting a US$5 limit and a routine for 8 every morning took the same steps as v0.21.0; finding the limit took one more scroll, because the settings page is longer. **Not tried on a real machine:** with no AI tool signed in, the walk stopped before creating a CEO in both versions, so the CEO page's details, the openings and the chief-of-staff hint were not seen; the Claude Code chat on the development Mac is also refused by an administrator setting, so `--haiku` was not run; the permission window of the Mac notification, the number on the Dock and a notification really appearing were not tried and have to be tried by you after upgrading. The check script `tools/qa_p48.py` itself has two known mistakes, left for the next version: when the home page is not the first task it only changes the part after `#`, so that task measured the wrong page (its one FAIL is the script's, not VBear's), and its phone walk looks for the picker after a tool was already chosen. Claude cost US$0.
- **Going back to v0.21.0.** Nothing is migrated: v0.22.0 added no setting, no kind of chat event and no API path. Read from the v0.21.0 code; what could not be read is marked 待確認. (1) The `<state>/spend-keep/` folder is not read by v0.21.0: the cost of a meeting or proposal deleted on the same day is not counted again (the old behaviour), and the leftover files are harmless; from the next day on there is no difference. (2) The browser keys `vbear-setup-pick` and `vbear-notify` are not read. (3) The start-up page goes back to one row per tool, and the try and the chat check are two buttons again. (4) The records of the chat safety check have the same format, so a version that passed under v0.22.0 passes under v0.21.0 too. (5) The create-CEO page of v0.21.0 does not send `?tool=` and picks by its own order. (6) The Mac's notification permission stays granted, but the v0.21.0 app posts nothing and has no Dock number. (7) The queue length was not changed.

## v0.21.0 — easier to pick up (好上手 1)

VBear should be something a person who has never opened a terminal can pick up and use. This release changes **what the screen says and where things are**, and nothing the server does. The menu has **four items** instead of nineteen: **首頁** (home), **員工** (employees), **工作** (work) and **設定** (settings). The engineering pages (指令視窗, 工作台, 流程, 專案資料夾, AI 工具的外掛清單, 員工詳細資料) are behind **進階模式** in the settings; it only adds them to the menu and shows paths and diagnostics, it changes no permission, and every old address still opens. The home page shows what waits for your decision, your employees (press a face to chat), what is on today, and a box 「想做什麼？跟 CEO 說」. A new person sees three steps: get an AI tool ready, create a CEO, say the first sentence; 「建立 CEO，開始聊」 opens the chat with him, the opening sentence already in the box (you press 送出 yourself). The chat page is only the conversation and a box fixed at the bottom; the rarely used things are in a 「⋯」 menu. The whole screen uses **one set of company words** (員工, 分配工作, 定時工作, 常用做法, 花費上限, 保護範圍（沙盒）…; the game words stay on the office page), the error sentences are in plain words, and the permission cards say 「想修改檔案」 instead of `Edit`. The daily spending limit moved to **設定 → 用量與上限** (closed until you open it, and you can type your own amount from US$0.01 to US$50); **every limit is still checked and enforced exactly as before**, and when one stops something the screen says so in plain words and has a button to the settings. Six tasks (P47-1 to P47-6), built on v0.20.0; ADR 0013 gives the reasons.

**What you will see.**
- **Four menu items and an advanced part.** 首頁, 員工, 工作, 設定; with 進階模式 on, a part 進階 with the six engineering pages. On a phone-width window the four items sit in one row at the top. Old addresses (`#/team`, `#/terminals`, `#/skills`, …) draw as before; an advanced page opened with the mode off has one line saying where to switch it on. The brand line says 「你的 AI 員工」.
- **Home.** 等你決定 (everything that waits for you, the same in both modes), 我的員工, 今天, and the box. Pressing 送出 sends one message to the CEO, the same request as the chat page's 送出; if the CEO is answering, a card waits, or the chat cannot start, nothing is sent and your words are put in the chat's box. There is no amount of money in the new home blocks. In advanced mode the old home (新手第一局, the task board, finding skills, recent projects) is below, in 進階, called as it was, so its cards can still show amounts.
- **員工 and 工作.** `#/employees`: a small card for each employee (chat, 設定, 刪除 with its confirmation), 新增員工, 用團隊範本一次加好幾位, and the shared things (memory, the shared folder, a new group, the conversations, the office). `#/work`: a list of links with one sentence each (對話紀錄, 分配工作, 定時工作, 會議, 常用做法, 「AI 自己做了什麼」).
- **Settings.** The normal mode shows AI 工具, 自己動手, 顯示, 使用紀錄 (the privacy switch stays), 資料流向 and 用量與上限; skill translation, 新手第一局, the scan sources and the diagnostics are in advanced mode. 「用量與上限」 holds today's use, the limit (US$1, US$3, US$10 or your own amount) and a note that the plan's own limit is a different thing; it saves only when you press 儲存. `#/settings?open=limits` opens it. The start-up page's daily limit is a closed part (「每天最多花 US$3（預設，可以不用動）」) with the same editor, and it now says the truth about where to change it later.
- **Routines.** A new routine is **every day and on** (it was Monday to Friday and off). With 自己動手 item 3 off, on only means VBear reminds you at the time; with item 3 on, saving it as on first asks, in the words of the 開啟 button. A routine made by a team template is still made off. The money of routines is in a closed 「用量與上限（定時工作）」, still with its own limit.
- **The chat page.** Name and 「⋯」 on the first line; then one line (position・AI tool・「每件事先問你」・the company the chat goes to), and 「詳細資訊」 (the limits, the notes of the AI tool, the plan's use, memory, the shared folder; 「估計」, 「不是帳單」 and 「用的是你的方案」 are all still there). The 「⋯」 menu: 請幕僚長安排 (CEO only), 整理要記住的事, 整理成常用做法, 所有分配工作, 「AI 自己做了什麼」 and 刪除這個對話; each opens the same preview or confirmation box as the button it replaced, with the cost and where it is sent. The buttons under a message (記住, 存成常用做法) appear on hover or focus, and every message can be reached with Tab. The box is fixed at the bottom with 送出 and 用常用做法; 停止這一回合 only while a turn runs. An employee's words carry the employee's name. A turn's cost is behind a small 「詳細資訊」; 「員工上線」 no longer shows an amount.
- **A chat that cannot start yet** (`#/chat?profile=<id>`) says one reason and has one action (start the chat, do the safety check, sign in to the AI tool, …); when the check you started passes, the chat opens by itself. Nothing opens a chat the AI tool cannot hold: 「建立 CEO，開始聊」, the home box and an employee's face first read whether the tool can chat (checked for chat, no administrator's policy, signed in) and otherwise lead to this page, your words kept; a send the server refuses for that reason is told in plain words (an administrator's policy is said as that, not as something to verify) with a way to this page; the home page's first step and the create-CEO page say 「已就緒」 only when a chat can start. The check still asks first what it uses, what it costs and how long it takes.
- **Permission cards in plain words.** 「{員工}想修改檔案」, 「想執行指令」, 「想建立或覆蓋檔案」; the fields are 「原本的內容」 and 「改成」; the tool's English name and the raw fields are in a closed 「技術細節」 at the foot. The buttons are the same (允許這一次, 改內容再允許／再問, 拒絕), there is no "allow from now on", and every warning is kept word for word, only 沙盒 is written 保護範圍（沙盒） the first time.
- **Plain error sentences.** The background program not running, the AI tool's version that could not be checked, 「manual_review」, the orphan translations and a stop by the day's limit are said in plain words with a next step; the server's original sentence is kept whole behind 「技術細節」, and a sentence the screen does not know is shown as it came. The server's sentences were not changed.
- **The contradictions are gone.** The create-CEO page no longer says dispatch is missing (it says what 請幕僚長安排 does), the team templates page no longer asks for a CEO when you have one (P47-5), the chat page says 「CEO」 and not `planner`, and 自己動手 item 3 is titled 「定時工作到時間可以自己開始」 like its explanation.

**The tasks.**
- **P47-1 — the table of words, plain errors, the four menu items, advanced mode, guard rules 15a and 15b.** `WORDS` and `PLAIN_ERRORS` in `web/app.js` with `plainWords()`, `plainNotice()` and `limitReachedNotice()`; `NAV_PARENT`, `syncAdvancedNav()`; new entries in `GLOSSARY.md`.
- **P47-2 — home, 員工, 工作, guard rule 15c.** `viewHome` with its blocks, `openChatWith()`, `viewEmployees`, `viewWork`; `tests/frontend/p47_home.cjs`.
- **P47-3 — settings, the start-up page, routines (Codex).** `dailyLimitEditor`, 「用量與上限」, the routine form's defaults and the confirmation, the money of routines folded, `vbear/autonomy.py` wording; `tests/frontend/p47_settings.cjs` (guard rule 15d).
- **P47-4 — the chat page, permission cards, direct start of the CEO chat, guard rule 15e.** The head, 「詳細資訊」, 「⋯」, the fixed box, the prepare page, the cards, the three "desks" that now only show a result; `vbear/first_ceo.py` wording; `tests/frontend/p47_chat.cjs`.
- **P47-5 — the words of the rest of the screen, `GLOSSARY.md`.** The remaining pages of the normal mode use the table of words; an advanced page changes only its menu name and its title.
- **P47-6 — documents, ADR 0013, the real-machine walk.** ADR 0013 is final (and ADR 0001's Q4 says where the daily limit is now); `docs/SECURITY-MODEL.md` has 「Plain navigation (v0.21)」; both READMEs, `docs/ARCHITECTURE.md`, `docs/REFERENCE.zh-TW.md`; the quotes of the documents follow the words of the screen (the sandbox warning, 「VBear 依分配工作送出」) and the tests that compare them were changed with them, keeping what they check. `tools/qa_p47.py` is the real-machine walk: it starts a headless Chrome of its own over `--remote-debugging-pipe` (no TCP port), walks the same five tasks on v0.20.0 and v0.21.0 on one port in turn (the first sentence to the CEO, a daily limit of US$5, a routine for every morning at 8, reading and refusing a 「修改檔案」 card, and what a person sees when the day's limit stops them), counts the steps, the stuck steps, the characters to read first and where the chat box sits on a 390-pixel-wide phone, and prints a before/after table (`--compare`). `--no-ai` spends nothing; `--haiku` uses Claude Code on Haiku under a hard cap of US$0.30 for both versions together, checked before every step that spends (an amount that is not known is never counted as zero: the step is not done); it runs on port 7802 only (never 7788 or 7789) and refuses `~/.vbear` and anything under it; `--compare` fails when a run has a FAIL or an after task did not finish. `tests/test_qa_p47.py` tests its pure functions and an in-memory page (it starts no browser); `tests/test_p47_docs.py` keeps the documents and the code saying the same.

**What did not change (safety).** No server route (API), setting, data file, kind of chat event or `localStorage` key was added (the page has two new addresses, `#/employees` and `#/work`, and the version number changed), and `git diff v0.20.0 -- vbear/` is only Chinese wording in `vbear/autonomy.py` and `vbear/first_ceo.py`. The guard rules 1 to 14 are as they were; rule 15 was added: **15a** advanced mode is a display and no Python reads it, **15b** the page asks the server nothing new and the data does not change, **15c** the home page sends nothing by itself, **15d** the spending limit and a routine are changed only by the person's press, **15e** the lighter chat page keeps every confirmation and warning and says in plain words, with a way to raise it, when a limit stops a message. Advanced mode is not a permission: an employee still asks about every command and every file change. Folding the spending away did not weaken a limit: the per-turn limit, the daily limit, the routines' own limit and the red-lamp stop are the server's, and **the AI still cannot raise a limit**.

**Money.** Nothing in this release costs anything new. The home page's box, the chat page and the routines spend only as they did, under the same limits, and only on the person's own press (送出, 現在開始, or a routine that item 3 lets start). The real-machine walk costs US$0 with `--no-ai` and at most US$0.30 with `--haiku`.

**Known limits.** (1) The advanced pages keep their old words inside (任務卡, 出發, 終端機…); only their menu names and titles were changed. (2) The old words were swept out of 17 normal pages and the first step of the employee wizard by a test, and out of the team-template preview (including the server's sentences, said in the page's words); the Codex and AGY chats, groups, the details of a dispatch, the wizard's other steps and the kinds of cards are covered by the tests of their own pages, not by that sweep, and a word inside a sentence the server writes elsewhere (for example in a note of an AI tool) stays as the server wrote it. (3) The real-machine walk counts steps; whether the plain sentences really read well is for a person to say. (4) `tools/qa_p47.py`, the check script (it is not part of the app), had its time limits reviewed in eight rounds; the last change (the guard on a new connection is kept while a cut-off call's thread still runs) was not reviewed again before this release.

- **On a real Mac:** on 2026-11-10 (Claude Code 2.1.319, whose chat was refused by an administrator setting) `tools/qa_p47.py --no-ai` passed on v0.20.0 and v0.21.0. v0.21.0 took no more steps on any task and got stuck 0 times instead of 20. The first chat now leads to a page with one plain reason and one action, instead of a chat box that cannot be used, and a page that cannot read the chat state says so and offers "read again". Setting a US$5 limit, which v0.20.0 could not do, took 7 steps. **Not tried on a real machine:** the `--haiku` part was refused by the same administrator setting, so sending a turn and seeing the answer, the permission cards and a send really stopped by the limit were not exercised on that Mac (the front-end tests cover them); Claude cost US$0.
- **Going back to v0.20.0.** Nothing is migrated: v0.21.0 added no setting, no data file and no kind of chat event, and no key of the browser's `localStorage` (the chat list no longer remembers 「我知道了」, so it uses one key less). Read from the v0.20.0 code (and the first two checked on a v0.20.0 console): (1) `advanced_mode` is a key v0.20.0 already has; on, it only shows paths and diagnostics there. (2) A daily limit you typed (for example US$5) is read by v0.20.0: the start-up page says 「目前的每天上限是 US$5，不是這三個之一」 (the server has always accepted 0.01 to 50). (3) A routine made every day and on is an ordinary routine in v0.20.0; with item 3 off it reminds as before. (4) The menu is the 19 items again, the game words are back, and the amounts are where they were; `#/employees` and `#/work` say 「找不到這個頁面」, `#/settings?open=limits` is the plain settings page, and the chat page has no 「⋯」. (5) The conversations, employees, memory, the shared folder, groups and team templates are the same files and are read as before. (6) What was read but not run (待確認): none that the code leaves open.

## v0.20.0 — AGY employees can chat

A role card whose AI tool is **AGY** (Google's Antigravity CLI) can now **chat**, which until v0.19.0 only Claude Code and Codex cards could. Everything that was built around chats follows: **groups** (with Claude Code and Codex employees, two or three together), **dispatch**, the **chief of staff and the CEO** (an AGY CEO's conversation goes to Claude Code to be arranged, and the page says so), **routines**, **memory** (off for an AGY card until you say yes to Google), **整理要記住的事 and 整理成技能** (the chat also goes to Anthropic, and the page says so), **team templates** (AGY is the third tool you can apply a template with) and the **first-CEO** choice (AGY last). **The one thing AGY employees cannot use is the shared folder in this version:** the pages, a group and a dispatch say 「AGY 員工這版不能用共用資料夾，之後 AGY 新版再檢查」. Six tasks (P46-1 to P46-6), built on v0.19.0; ADR 0012 gives the reasons.

**How it works.** The chat runs `agy acp` (ACP v1, JSON-RPC over stdio) inside AGY's own sandbox, with a settings folder of VBear's (`<state>/agy-chat-home`) and **your own AGY login** (no second login, and your own AGY settings are not read or changed). Every command and every file change is asked on a permission card; only "allow once" or "refuse once" is ever sent, there is no "allow every time". A request to leave the sandbox is **refused by VBear with no card**. The file tools are not in AGY's sandbox, so VBear itself refuses a path outside the work folder, anything in `.git`, `.agents`, `.gemini` and the like, and a link out. 改內容再問 refuses the original, and when that turn ends sends your changed text as the next message so AGY asks again (it costs one more turn; the page says "AGY 會再問你一次", never that it ran your change).

**What an AGY employee can and cannot do.**
- Can: talk; ask to run a command (it runs in AGY's sandbox after you allow it); ask to change, add, delete or move a file in its work folder (with a diff); ask to read a file outside the work folder (a read card, which says the content goes to Google); be in a group, a dispatch, a routine and a team template; take memory along once you switch it on and say yes to Google.
- Cannot: use the **shared folder** (this version); reach the network or write outside the work folder (and the temporary folder) or read outside it from a command (the sandbox stops them, so `npm install` and `git push` do not work in a chat; use a full-mode terminal); run outside the sandbox (refused, no card); change a file outside its folder or under `.git` and the like (refused by VBear).
- **AGY employees use the AGY skills you installed yourself.** AGY reads the skills under `~/.agents/skills` whatever settings folder it is given (the investigation showed it), you accepted it, and a skill is words for the model and not a permission. The screens say 「AGY 員工會用到你自己裝的 AGY 技能」.
- The chat does not start if your Mac has an administrator policy for AGY (`/etc/antigravity`, or the managed preferences `com.google.antigravity`; the list comes from reading the program's strings, not from the vendor) or you have `~/.agents/hooks.json` (commands AGY runs by itself; VBear only checks that it exists and never reads it). AGY updates itself: a new version must pass 驗證聊天 on your Mac before it chats.

**Money.** AGY says how many tokens a turn used, only at the end of the turn, and never an amount. VBear **estimates** each turn (tokens divided by a million, times US$1.00, up to the cent, at least US$0.01), shows it as 「估計」, 「不是帳單」, 「用的是你的 Google 方案」 and counts it in the daily limit. **The cost is an estimate:** the per-turn limit can only be checked before a turn starts, so one turn may cost more than it, and the record says what it counted. 驗證聊天 runs about fifteen short turns on your Google plan and is not billed apart.

- **The protocol, a fake AGY and the evidence (P46-1).** `vbear/runtime/agy_chat_protocol.py` (pure functions: the version table of AGY 1.5.3, the lines VBear writes, `answer_line`, `judge_file_change`, `judge_read`, and the tracker that turns what AGY prints into facts and stops the chat when something ran that VBear had not allowed), `tests/fake_agy_acp.py` (plays synthetic scripts over stdio; `tests/fixtures/agy-chat/` says on its first line that it is not a recording) and `docs/evidence/agy-1.5.3-chat.md`. Guard rules 14a to 14c: only "allow once" and "reject once" are ever chosen, the argument list and the settings are one fixed table, `BypassSandbox` is refused with no card. Nothing was added to the chat record: **no new kind of event**.
- **The settings folder, the binary, the version record and the administrator policy (P46-2).** `vbear/runtime/agy_chat_env.py` (writes `antigravity-cli/settings.json` before every process: ask every time, terminal sandbox on, no paid credits, no permissions; refuses what VBear never writes there; the exactly-six-variable environment; the `lstat` look at `~/.agents/hooks.json`; the work-folder check), `admin_policy.check_agy` / `AGY_SOURCES`, and the AGY records in `vbear/runtime/cli_versions.py`. `AGY_CHAT_VERIFIED_VERSIONS` is empty, as Codex's is: **no version is verified by the repository itself**; each Mac keeps its own `agy-chat-verified.json`.
- **The daemon runs AGY chats (P46-3).** The third row of `chat_engines.TABLE` (`agy-chat`), the launch record (`agent_sessions.prepare_agy_chat_launch`), `runtime/agy_chat_session.py` (`AgyChatProcess`: handshake, `session/new` or `session/resume`, `session/set_model` for every process, cards, 改內容再問, stopping, the settings checked again after every turn) and `_agy_send` in `daemon_chat.py`; the error codes `agy_version`, `agy_home`, `agy_hooks`, `agy_workdir`. Rules 14d, 14g, 14h (the environment is six variables, the person's own AGY folders are left alone, only known messages are written).
- **The version check (P46-4).** `python3 -m vbear.boundary_check --mode agy-chat [--shared]` (`vbear/agy_chat_check.py`) and the button 「驗證聊天」 (`POST /api/chat-support/verify {"engine": "agy"}`, `vbear/agy_verify.py`); `GET /api/chat-support` carries an `agy` block. The check proves, with the person's own AGY: the system prompt is applied, VBear's settings are the ones read, every command is asked (even `ls -a`), a refusal works, 改內容再問 works, the file tools outside are refused, allowed commands cannot write outside, read outside or reach the network, `BypassSandbox` is refused, a link does not give a read of the outside, resuming keeps the conversation, stopping ends the turn and leaves nothing running, nothing forbidden appears in the settings folder, the usage adds up.
- **The screens and the other features (P46-5).** Cards in plain words for commands, file changes and reads; the estimate line; memory, groups, dispatch, the chief of staff and CEO, the suggestions, routines, team templates and the first-CEO choice with AGY; rules 14e and 14f.
- **Documents, the shared folder decision, the walk and the real-machine check (P46-6).** ADR 0012 is final, `docs/SECURITY-MODEL.md` has "Chats with an AGY role card" with its residual risks and "Going back to v0.19.0", the evidence file has its sections 8 to 12, both READMEs, `docs/ARCHITECTURE.md`, `docs/REFERENCE.zh-TW.md` and `GLOSSARY.md` say AGY chats. `tests/test_p46_flow.py` walks one AGY employee over HTTP (card, support, the check, allow, refuse, change and ask again, memory with the yes to Google, the shared folder refused, a group, a routine, a team template with AGY and its undo, delete) and runs the v0.19.0 code over what v0.20.0 wrote. `tools/qa_p46.py` is the real-machine check through the HTTP API (port 7801; it refuses ports 7788 and 7789, `~/.vbear` and anything under it, and a state folder under `/tmp`; Claude runs on Haiku with a hard cap of US$0.30 checked before each Claude stage) and `tests/test_qa_p46.py` runs it against a fake console. `tests/test_p46_docs.py` keeps the documents and the code saying the same.
- **The shared folder is not opened to AGY employees (decision of this release).** The real check of AGY 1.5.3 found that its **file tools can write into the shared folder (after asking), but a shell command cannot** (`--add-dir` does not make AGY's sandbox writable); an employee would try one, then the other, and get stuck. So `shared_folder.SUPPORTED_ENGINES` is `("claude-chat", "codex-chat")`: switching an AGY card on is 400 `card_tool_unsupported` with the sentence above, with or without the yes to Google; a group or a dispatch with the shared box ticked and an AGY employee in it cannot be made or confirmed; the shared page shows the AGY employees with no switch and says why. The part for Google stays in the code, and rule 14f holds both the refusal and the confirmation that returns if `agy-chat` is listed again. These existing tests were changed for it: the two shared tests of rule 14f in `tests/test_autonomy_guard.py`, `SharedFolderForAgyTests` in `tests/test_p46_features.py`, and the shared, group and dispatch tests of `tests/frontend/agy_chat.cjs`.
- **A false positive of the check, recorded.** On the seventh real run the shared part's `shared_home_clean` step failed with `found: ["path"]`: a home-folder path string was judged to be account data. It is a false positive of the check, not a leak (the settings folder was clean, `settings.json` unchanged). It is left for the next AGY version, together with the shared folder.
- **What the real check found (AGY 1.5.3).** The check was run on a real Mac seven times; each of the first six failed on something the synthetic fixtures could not have shown, and each was fixed in the version table (`docs/evidence/agy-1.5.3-chat.md`, section 12): the names AGY makes in its own settings folder (an allow-table and a recursive check), three kinds of message the protocol did not know, **AGY announcing a command or edit as `in_progress` before it asks** (only that exact order is allowed), its 62 built-in paths and **41 built-in files pinned by SHA-256**, the closed `persistent_terminals` folder, and the SQLite side files `-journal`, `-shm` and `-wal` as three exact names.
- **On a real Mac:** with AGY 1.5.3 the version check (`--mode agy-chat`) passed its main part on the seventh run: 15 turns, an estimated US$0.57 on the Google plan (nothing charged), every main check passed (the unasked tool probe: asked and refused); stopping ended the turn in 3.1 seconds and left nothing running. The shared-folder part did not pass (the two points above). On 2026-11-10 (AGY 1.5.3, Claude Code 2.1.319) the console's own check passed again (15 turns, an estimated US$0.55) and `tools/qa_p46.py` passed every stage on its own console: 45 ok, 0 warn, 0 FAIL; 13 AGY turns, an estimated US$0.37 on the Google plan; Claude about US$0.01 (at most US$0.16). That run found two mistakes in the script itself (it read `/api/chat-support` one level too shallow, and it read the chats' record kinds after deleting the chats); both are fixed in this version.
- **Going back to v0.19.0.** Nothing is migrated: v0.20.0 added no setting and no kind of chat event. Read from the v0.19.0 code (and for the first items run in `tests/test_p46_flow.py`); what could not be read is marked 待確認. (1) An AGY chat is read as 「欄位不符」: it is shown with a problem, cannot be sent to or deleted, and its files stay; **the day's spending is still counted** from the events. (2) An AGY role card cannot chat (`card_tool_unsupported`): a new group refuses an AGY member, a new routine for an AGY employee is refused, and a send of a group, routine or dispatch to one goes through the chat service, which refuses it; what an existing group, routine or dispatch then records is 待確認. The card itself is kept. (3) Memory and shared-folder switches hold only card ids; whether a card that cannot chat leaves the switch file readable was read, not run (待確認). (4) `<state>/agy-chat-home/` (with AGY's own copies of the conversations), `agy-chat-verified.json` and the launch records of `agy-chat` under `<state>/sessions/` stay and are not read; how v0.19.0's daemon, at start, treats an unknown engine in a launch record is 待確認; `config.json` has no new key. (5) **A team template applied with AGY locks all team templates in v0.19.0:** `applies.json` keeps the tool of each apply, `tool` is a closed set of two in v0.19.0, so the whole file is read as unreadable, and v0.19.0 can neither apply nor undo a template. Undoing in v0.20.0 first does **not** remove the record, so it stays unreadable. The cards the apply made are ordinary role cards. (6) Upgrading to v0.20.0 again restores everything.

## v0.19.0 — team templates

A **團隊範本** (team template) is a ready-made set of employees (role cards), skills and routines. Built in are four: 小店 (a small shop), 自媒體 (a creator), 接案工作室 (a freelance studio) and 個人生活助理 (a personal assistant), 12 employees, 12 skills and 6 routines in all, written in the program.
On the new 團隊範本 page (`#/templates`) you tick what you want, also from several team templates at once, look at the preview, choose **one AI tool** (Claude Code or Codex) for all the new employees and press 「套用」; VBear then makes them one by one **the way you make them by hand**.
**An apply uses no AI and costs US$0**, makes every employee in the safe mode (never full mode, no skill card), makes every routine **switched off** (you switch it on on the routines page), and does not touch `config.json`, the memory, the shared folder, a chat or the 自己動手 ticks.
Every apply can be taken back with 「復原這次套用」: VBear lists what it would delete and what it would keep and why, and you press 「刪掉這些」; it deletes only what that apply made and you did not change or use, and leaves everything that was there before untouched.
What you have set up yourself can be saved as a team template of your own (at most 20); it stays on this computer, is never uploaded and cannot be exported. Four tasks (P45-1 to P45-4), built on v0.18.0:

- **The format, the four built-in ones, ticking and the preview (P45-1).** `vbear/templates.py` (the closed format: an employee has a name, a position, standing instructions and a Claude model alias; a skill a name and its words; a routine a name, its words, days, times and which employee; no tool, mode, skill card, switch, memory, shared folder or id; the limits, written again and compared with the code of `agent_profiles`, `skillbook` and `routine_rules` by a test; the pure `plan()` that mixes ticks from several team templates;
  `card_body`, `skill_body` and `routine_body` that make the bodies the ordinary write functions take: `launch_mode` is the literal `"safe"`, `equipped_skill_ids` the literal `[]`, `enabled` the literal `False`) and `vbear/templates_builtin.py` (the four, word for word; every text is judged by `memory_rules.check_text` with no warning). `GET /api/templates` and `POST /api/templates/preview` (the routes under `/api/templates`; the preview writes nothing; the whole state folder is compared before and after).
  Guard rules 13a to 13c in `tests/test_autonomy_guard.py`. `GLOSSARY.md` gets 團隊範本 and 復原這次套用, and 技能 now says not to call it a team template.
- **Apply and 復原這次套用 (P45-2).** `vbear/templates_apply.py` keeps `<state>/templates/applies.json` (the last 50 applies; every item is an id, its template and key, a fingerprint, a state and a time, **never a name or a word**) and `log.jsonl`, and the pure rules: the fingerprint (`profile_digest` for an employee, a hash of the whole record for a skill and a routine),
  `card_mentions`, `undo_plan` and `recover()`. The route `POST /api/templates/apply` in `vbear/server.py` checks everything first (the files can be read, the limits of 500 employees, 100 skills and 20 routines, a routine has an employee who can chat, a second yes for words that need one) and then makes the employees with `_save_card` (the same piece of code as `POST /api/agent-profiles`, now a function of its own, behaviour unchanged),
  the skills with `skillbook.add` and the routines with `routines.create`, writing each item down before and after; if something stops it, the apply stops there (409 `template_partial`), says what was made and can be undone. An apply that the console left in the middle is marked interrupted by `recover()` when the console starts, and what it cannot be sure of is never deleted.
  `POST /api/templates/applies/<id>/undo-preview` writes nothing; `POST …/undo` works the plan out again and deletes only what the person's list names **and** may still be deleted, routines first, then skills, then employees, each with the ordinary delete function (`routines.delete`, `skillbook.delete`, `agent_profiles.delete_profile`).
  An employee is kept when he was changed (name, instructions, model, switched off), has a chat or a work folder, is in a group, a dispatch, a meeting or a task, has his memory or shared-folder switch changed, or a routine that stays still goes to him; a routine when it was changed or switched on or has any run; a skill when it was changed; and **everything is kept when a record cannot be read** (a file over 4 MiB, more than 20,000 files, a link, a folder that cannot be opened).
  **What the undo cannot see:** VBear cannot see whether you used an employee of a team template in a terminal (the full mode leaves no record of the card, and the safe mode's record in `<state>/sessions/` has no card id, which `tests/test_templates_undo.py` pins), so the preview of 復原這次套用 always has one more line (whenever it would delete an employee), 「如果你在終端機用過這些員工，VBear 看不出來；確定再刪。」, and you decide before you press 「刪掉這些」.
  VBear does not record that a skill was used (using one only puts its words in the box), so the undo looks only at whether it was changed, and the preview says so. Guard rule 13d.
- **Your own team templates (P45-3).** `vbear/templates_mine.py` keeps `<state>/templates/mine.json` (a closed format; a file with one field more or less is left alone and the four built-in ones still work). `POST /api/templates/mine` saves a copy of what you ticked in a team template or of what you have now, `…/mine/<id>` renames it and `…/mine/<id>/delete` deletes only the template.
  An employee is saved with a name, a position, the instructions you wrote on the card and a Claude model alias; **not** the tool, the mode, skill cards, the profession, permissions, whether it is switched off, memory, shared-folder switch, chats or id. A routine is saved with its words, days, times and which employee (if that employee was saved too) and **never switched on**. Every text is judged again by `memory_rules.check_text` (a key is refused with 400 and the answer does not repeat it; something that sounds like an order to act without asking needs `confirm_warning`).
  For an employee who starts in the full mode this means that **a full-mode employee can be saved, without a launch mode: an apply is always the safe mode**, and the dialog and the answer say so. No route exports, imports, uploads or downloads a team template. Guard rule 13e.
- **Documents, the walk, the real-machine check (P45-4).** `docs/adr/0011-team-templates.md` is final, `docs/SECURITY-MODEL.md` has "Team templates (v0.19)" with its residual risks and what going back does, both READMEs, `docs/ARCHITECTURE.md`, `docs/REFERENCE.zh-TW.md` and `GLOSSARY.md`. `tests/test_templates_flow.py` walks it once over HTTP (look, mix two team templates, preview, apply, talk to one employee, change a skill and a routine,
  the preview of the undo, the undo, save your own, apply it, undo it) and shows `config.json`, the memory and the shared folder's switches are the same bytes at the end. `tools/qa_p45.py` is the real-machine check through the HTTP API (stages `setup`, `browse`, `preview`, `apply`, `chat`, `change`, `undo-preview`, `undo`, `mine`, `reapply`, `final`; it needs `--state`, refuses `~/.vbear` and the ports 7788 and 7789, prints nothing a model wrote);
  `tests/test_qa_p45.py` runs it against a fake console. `tests/test_p45_docs.py` keeps the documents and the code saying the same.
- **The guard test, and rule 13b has no exception for the apply.** `tests/test_autonomy_guard.py` has rules 13a to 13e: the team template modules are scanned like the chief of staff's; no other scanned module imports them; they import no chat, meeting, network or scan module and call no write function of the cards; every `enabled` in them is `False`; their routes are named only in `vbear/server.py`; the record of the applies and the person's own templates are written only by `vbear/server.py` and their own module.
  The plan said to open an exception for `templates_apply`; none was needed and none was made, so there is no exception to rule 13b: **every write is in `vbear/server.py`** (where the write functions have always been called from), and `templates_apply.py` only keeps the record and the rules, so the rule is exactly as strict as before, with a test that the same call put into any template module is still caught.
- **Money.** An apply, a preview, an undo and a save cost US$0 and send nothing to an AI company. Talking to a new employee afterwards is an ordinary chat under the per-turn and the daily limits; routines made by a team template do nothing until you switch them on, and then they follow v0.18.0 (a reminder, or 「自己動手」 item 3).
  Numbers: one team template and one apply hold at most 12 employees, 24 skills and 12 routines; you can keep 20 of your own; the last 50 applies can be undone; the old limits (500 role cards, 100 skills, 20 routines) are checked first and an apply that would go over is not made at all.
- **A flaky test fixed (cause found).** `test_memory_suggest` `test_two_at_once_are_refused` failed once with 「記憶提議的紀錄有多個連結」 on a busy machine. The record is saved by replacing the file whole; a reader that opened the file just before the replace holds the old, complete file whose link count is 0, and the check was "not 1". It is now "more than 1" (a real second name is still refused), in `memory_suggest.py` and in `skillbook_suggest.py`, which has the same shape,
  with `tests/test_suggest_read_race.py` (the replace happens between the open and the look at the link count, and a real hard link is still refused). The same `!= 1` is in other stores (`meetings.py`, `dispatch.py`, `chief.py`, `staffing.py`, `groups.py`, `translations.py`); they were not changed in this release.
- **On a real Mac:** with Claude Code 2.1.319 and Haiku on 2026-11-08, `tools/qa_p45.py` passed (37 ok, 0 warn, 0 FAIL), about US$0.007 in all. The four built-in team templates were listed; a preview picked from two of them wrote no file; after the apply every employee was in safe mode with Claude Code and no skill card, the routines were off, and the ledger and the chats were unchanged; one employee answered one turn (US$0.0014); the undo preview kept the employee that had chatted and the skill and routine that had been changed, and the undo deleted only the rest; an own team template was saved, applied and undone, renamed and deleted (deleting it touched no employee, skill or routine); the undo preview carried the terminal line; `config.json`, the memory and the shared folder settings were byte-identical before and after (they did not exist in this scratch state, so only "absent stays absent" was seen). **Not tried on a real machine:** Codex employees were NOT tried on a real machine (the scratch state has no Codex login for chat; a fake app-server and the unit tests cover it); the routines of a team template really running at their time was NOT tried (they are made switched off, and routines themselves were tried in v0.18.0);
  whether a model follows the standing instructions and the skills of the four built-in team templates has no record (待真機驗證).
- **Going back to v0.18.0.** This was read from the code and was not run (what could not be read is marked 待確認). `<state>/templates/` (`mine.json`, `applies.json`, `log.jsonl`) stays and v0.18.0 does not read it (no code of v0.18.0 names that folder); the 團隊範本 page is gone, and **an apply cannot be undone from v0.18.0**: delete what an apply made one by one on the role card page, the 技能 page and the 例行工作 page. Nothing is deleted.
  What an apply made is in the formats v0.18.0 has: role cards with the fields v0.18.0 knows (`launch_mode` is `safe`, no `enabled` key), skills with `source` `{how: "typed"}` (no new value of `how`) and routines with their six fields, switched off; there is no new field in any record of a chat, a dispatch, a group, a skill or a routine, `config.json` has no new key and `vbear/runtime/` is unchanged, so they work as the ones you made yourself.
  Coming back to v0.19.0 the record is still there and 復原這次套用 works: what you changed, talked to, ran or switched on while in v0.18.0 is kept (the fingerprint, the chat record or the run record shows it) and what you deleted is listed as 「已經不在了」. An apply that was cut off in the middle stays `applying`, which v0.18.0 does not read, and `recover()` marks it interrupted at the next start of v0.19.0.
  Whether the macOS app's own checks of the state folder mention the unknown `templates` folder is 待確認.

## v0.18.0 — skills and routines

Three things you can set up once and VBear then offers or does for you, and a countdown on the work that stopped at a limit. A **技能** (skill) is a way of doing a job that you saved in VBear (a name and up to 4,000 characters):
the 「用技能」 button on a chat or a group puts its words in the box, you read them and press send, so what goes out is your own message. A **例行工作** (routine) hands one employee a job on the days and at the times you chose
(up to three a day), each time as a new one-to-one chat. **By default VBear only reminds you when it is time and you press 「現在開始」**; it starts by itself only when you tick 「自己動手」 item 3. A paused dispatch counts down
to the time the limit is over and then asks you to press 「繼續」; it presses it by itself only with item 5. Nothing is added to the record of a chat, a dispatch or a group (no new field), and **every command and every file change
is still a permission card, which counts as refused after 5 minutes if nobody is at the Mac**. Six tasks (P44-1 to P44-6), built on v0.17.1:

- **Skills: save, use, save from a line (P44-1).** `vbear/skillbook.py` keeps `<state>/skillbook/skills.json` (0600; at most 100 skills; the name 1 to 40 characters, the text 1 to 4,000) and `log.jsonl` (the action and the skill's id, never a name or a word).
  `/api/my-skills` (GET, add, edit, delete; the person's browser only, `X-VBear`, closed bodies). The name and the text are judged by the rules of memory through the one new function in the runtime, `memory_rules.check_text` (a key, a password, an account, a
  card is refused with 400; something that sounds like an order to act without asking, a phone number or an address asks for `confirm_warning`, 409); `memory_rules.check` is unchanged. 「存成技能」 sits beside each line of a chat and a group (an employee's line
  needs the tick 「我確定」, because once saved it becomes something you say to the employee); 「用技能」 sits by the box. A skill is never in the system prompt, never on a role card and never written as a file of an AI tool: a chat that used a
  skill has the same `argv`, the same first message and the same `prompt_sha` as one where the same words were typed. A `skills.json` that cannot be read is left alone and the page says so. 「技能」 is not 「技能庫」, which lists the AI tools' own skill files.
- **Routines: the backbone and item 3 (P44-2).** `vbear/routine_rules.py` (the fields, the local-time slots with the clock-change days handled, the limits, the fixed line), `vbear/routines.py` (`routines.json`, `settings.json`, `runs.jsonl`, `log.jsonl` in `<state>/routines/`),
  `vbear/routine_runner.py` (one pass every 15 seconds, `routine-runner.lock`) and `ChatService.send_for_routine` (it takes only a chat a routine opened, no route of the browser reaches it, and it adds no `origin`). At most 20 routines, ten of them on. A routine is one employee
  who can chat, a text, days and one to three times at least an hour apart. **Only the person makes, changes, switches on, switches off or deletes one** (`/api/routines`); the chief of staff cannot propose one and nothing an employee says makes one. At the time, with item 3 off
  (the default) a reminder shows over every page with 「現在開始」 and 「這次跳過」 and nothing is sent; with it on the routine starts by itself and 「AI 自己做了什麼」 says 「自己動手第 3 項」. One time of one routine starts at most once (a restart, a clock set back or a catch-up
  cannot do it twice), one routine runs at a time, an employee who is busy is asked again for 12 minutes and then skipped, a run that may or may not have been sent is `uncertain` and **never sent again by itself**. The routines have their own daily limit in `settings.json`
  (not in `config.json`), **half of the daily limit unless you change it, and never higher than it**; a routine is not started once the day's lamp is red or the routines' own limit is spent, and it is skipped, not counted down or continued. The line over every page comes from `/api/waiting`.
  Item 3 of 「自己動手」 works (`autonomy` has exactly four booleans now). A new chat for each run, titled 「例行工作：<name> <MM/DD HH:MM>」 in the list.
- **Waking up, and keeping the Mac awake (P44-3).** VBear does nothing when it is closed or the Mac sleeps, installs nothing that runs then (no LaunchAgent, login item or crontab) and schedules no wake-up. `heartbeat.json` is written about once a minute; two looks more than 90 seconds
  apart, or a heartbeat older than that at start, mean the times in between were missed (counted from the later of when the routine was switched on and the last heartbeat, seven days back at most; no heartbeat file counts nothing). Each routine is offered only its **latest** missed time with
  a count, 「補做」 or 「不用了」 (`/api/routines/missed/<id>`); with item 3 on and that time younger than 12 hours VBear catches it up itself, at most three routines per wake-up and one at a time; the listed ones are put away at the routine's next time or after 24 hours.
  The switch 「有工作在跑時不讓 Mac 睡著」 (default off, `settings.json`) makes VBear run **`/usr/bin/caffeinate -i -w <the console's pid>`** while a routine or a dispatch is working, 30 seconds after the last work it ends it: `vbear/keep_awake.py`, a constant argv with no shell, handed to the console by `serve()` only
  (`Console.keep_awake_command`; every other console, including the tests', starts nothing). It is the one program VBear starts that is not an AI tool. A closed lid still sleeps.
- **Countdown and item 5 (P44-4).** A dispatch paused for the daily limit (until midnight on this Mac) or for an AI tool's plan limit (the time the tool says; **Claude Code does not say, so no countdown and no automatic continuation**; Codex does) shows 「還有 H 小時 M 分可以繼續」 on the dispatch page, the group page and the line over every page.
  Two minutes after the time, if the lamp is not red, the line says 「派工『X』可以繼續了」 with 「繼續」. With 「自己動手」 item 5 on `vbear/auto_continue.py` presses it as `vbear` (`resume_dispatch(…, by="vbear")`, the event is `continued` by `vbear`, which v0.17.1 reads; the "item 5" is
  written in `<state>/routines/auto-continue.jsonl`): once per pause, three per dispatch, five a day in all, not again if the dispatch stops for the same reason within 10 minutes, not when the time went by 12 hours ago, and the step the limit cut off is not done again. A group only counts down and never continues by itself. The words of the dispatch's pause did not change.
- **A skill from a conversation, and a routine from a skill (P44-5).** 「整理成技能」 on a one-to-one chat: the meetings' tool-less engine (the same as 「整理要記住的事」) reads the newest messages and proposes at most one skill (a name, the words, a note); **the conversation goes to Anthropic**, the preview says so and how many messages, it costs at most US$0.10 and
  is counted in the day (`skill_suggest` is in the ledger's `includes`), a Codex-only Mac is told it needs Claude Code, and nothing is saved until you change it and press 「存」 (the module never imports `skillbook`). A routine's form has 「從技能帶入」, which copies the skill's words as they are now (a later change of the skill does not change the routine).
- **Documents, the walk, the real-machine check (P44-6).** `docs/adr/0010-skills-and-routines.md` is final (the person decided on 2026-11-08: the routines' daily limit is half of the daily limit), `docs/SECURITY-MODEL.md` has "Skills and routines (v0.18)" with its residual risks and what going back does and the countdown is in "Chief of staff and dispatch",
  both READMEs, `docs/ARCHITECTURE.md`, `docs/REFERENCE.zh-TW.md` and `GLOSSARY.md` (技能, 整理成技能, 例行工作, 醒來補做, 倒數接續, 讓 Mac 保持清醒, 派工, 群組, 自己動手). `tests/test_skills_routines_flow.py` walks it once over HTTP with a fake clock and a fake chat service:
  a skill saved and used, a routine made, the reminder and 「現在開始」, item 3 on and the routine starting by itself, a closed VBear and the catch-up, a paused dispatch and item 5; `config.json` changes only where the settings page's route writes `autonomy`. `tools/qa_p44.py` is the real-machine check through the HTTP API (stages `setup`, `skill`, `suggest`,
  `remind`, `auto`, `awake`, `wake1`, `wake2`, `countdown`, `final`; it needs `--state` and `--cards`, refuses `~/.vbear` and the ports 7788 and 7789, prints nothing a model wrote, and its only other reads are `config.json`, the two `log.jsonl` files and the `caffeinate` lines of `pmset -g assertions`);
  `tests/test_qa_p44.py` runs it against a fake console and a fake `pmset`. The guard test has rules 8 to 12 (only the browser's routes write a skill or a routine; item 3 and item 5 are each read in one place; `caffeinate` is named only in `keep_awake.py`).
  **A flaky test fixed:** `test_one_memory_from_the_first_line_to_clearing_it` looked for the four digits of a made-up phone number in the raw JSON lines of a record, and a time such as `…358.309124` held them by chance; it now compares only the words of each line, and still fails if the number is in a message or a log line.
- **Money.** A run is one chat turn: the per-turn limit (US$0.50 unless changed), then the routines' own daily limit (half of the daily limit), then the daily limit, which still caps everything. The page shows 「每次最多 US$…」 beside each routine and what the routines spent today. Catching up and continuing add no kind of spending; 「整理成技能」 is at most US$0.10 a time.
  Codex employees' runs are estimated from tokens, as in a chat.
- **A known gap in the day's money.** The chat process in the runtime (`_chat_day_spent` in `vbear/runtime/daemon_chat.py`) adds up the day's spending from a fixed list (the chief of staff, memory suggestions, the meetings), and it **does not include** what 「整理成技能」 spent: the guard rules forbid the runtime to know about skills, and this release does not
  change the launch boundary. So the per-turn check of a chat can allow up to US$0.10 more for each 「整理成技能」 you ran that day than the daily limit says. The other direction is covered: 「整理成技能」 itself checks the day including the chats, and the ledger (`GET /api/meetings/ledger`) counts it. To be settled in a later release.
- **On a real Mac:** with Claude Code 2.1.319 and Haiku on 2026-11-08, `tools/qa_p44.py` passed in its three parts (the last 19 ok, 0 FAIL), about US$0.03–0.035 in all. A sent skill was followed; a skill with a key was refused and one that reads like an order asked once more; 整理成技能 cost US$0.015 under its US$0.10 cap (the model offered no draft that time, so saving a suggested skill was not seen); a routine waited for 現在開始 with item 3 off and started by itself within a minute with item 3 on, once per time; with VBear closed for 4 minutes and opened again the missed times were found, offered once each with item 3 off and caught up once by itself with item 3 on; the countdown was shown and a group did not go on by itself; `caffeinate -w <console>` was there only while a card waited and gone within 45 seconds of the turn's end; `config.json` differed only in `autonomy` (two keys to four, all false). Two mistakes of the check script (not of VBear) were fixed after the run. **Not tried on a real machine:** Codex employees were NOT tried on a real machine (the scratch state has no Codex login for chat); a Mac that really sleeps was NOT tried (it cannot be woken
  from a script; a closed VBear stands in for it, and the detection is the same: the wall clock jumps); the automatic continuation after midnight was NOT tried (it needs midnight; a fake clock covers it); `caffeinate` really holding off sleep was NOT tried (the argv and the lifetime are tested, what macOS does with it is not).
  Whether a model follows a skill, and obeys the one fixed sentence that opens a routine's message, has no record (待真機驗證).
- **Going back to v0.17.1.** This was read from the code and was not run (what could not be read is marked 待確認). `<state>/skillbook/` and `<state>/routines/` (with `runs.jsonl`, `settings.json`, `heartbeat.json` and `auto-continue.jsonl`) and `routine-runner.lock` stay and are not read: **routines no longer run and
  nothing is caught up**, and the skills are not offered. Nothing is deleted. A `caffeinate` that was running ends when the v0.18.0 console ends (`-w`); how a v0.18.0 process that is still running when you go back ends is 待確認. `config.json`'s `autonomy` has four keys; v0.17.1 reads only `create_cards` and `dispatch`, so the two
  new ones do no harm, and saving the settings page in v0.17.1 writes the two back only (items 3 and 5 are off when you come back, which is the safe side). The chats a routine opened are ordinary one-to-one chats (no new field in the record; the title 「例行工作：…」 is gone). What you sent with 「用技能」 is an ordinary message. The automatic continuation is a `continued` by `vbear` in the dispatch record, which v0.17.1 knows,
  and 「AI 自己做了什麼」 shows it as 「VBear」, not 「自己動手第 5 項」 (v0.17.1 does not read `auto-continue.jsonl`); a paused dispatch or group waits for your press, as it did. The memory function added to the runtime does not touch v0.17.1. What 「整理成技能」 spent is in its own folder, which v0.17.1's ledger does not read (tested with v0.17.1's code), so
  **on the day you go back its spending is not in v0.17.1's daily total** (at most US$0.10 per run). The ledger does not become unreadable.

## v0.17.1 — the shared folder

The 共用資料夾 page shows one folder, `~/.vbear/shared`, that the employees you switch on can read and write, so one employee can hand a file to another (a
writer drafts, an accountant checks) or to you, and 「在 Finder 打開」 opens it so you can drop your own files in. **Every employee is off until you switch them on**: on that page,
with the tick 「讓這幾位都能用共用資料夾」 when you make a group, or with 「替這次派工的員工打開共用資料夾」 when you confirm a dispatch; switching a Codex employee on asks first, because what it reads goes to OpenAI. Nothing else
can: not an employee, not the chief of staff, not an automatic dispatch. An employee that has the folder is told that its files are data, and **every command and every file change, including a write
into the folder, is still a permission card**. VBear never reads or deletes a file in it and writes no file name to a log. A group and a dispatch hand the next employee the *names* of the files that appeared
meanwhile, as data. Five tasks (P43-1 to P43-5), built on v0.17.0 with P42-6:

- **The backbone: a Claude Code employee writes, another reads (P43-1, `3b84f29`…`fb9fc2a`).** `vbear/runtime/shared_rules.py` (the path VBear alone computes, `folder_problem`/`shared_unsafe`, `usage`,
  `write_problem`, the paragraph between `BEGIN_VBEAR_SHARED_JSON` and `END_VBEAR_SHARED_JSON`), `vbear/shared_folder.py` (`<state>/shared-meta/settings.json` and `log.jsonl`, outside the folder employees write
  in; every card off by default), `GET /api/shared`, `POST /api/shared/cards`, `POST /api/shared/reveal` (Finder through a command `serve()` hands the console; tests use a fake that records the argv).
  `chat_send` takes `shared: true` only (the daemon computes the path; `false` or another type is 400). Claude Code: the folder is a second `sandbox.filesystem.allowWrite` entry, VBear's `judge`
  makes it a second root (a Write or Edit inside is a card; outside it, through a link, in `.claude`/`.codex`/`.agents`/`.git` at any depth or onto a file with more than one hard link it is refused with no card;
  the work folder's `.claude` rule is now any depth too), an idle process whose folder differs is replaced (`restarting`, so **switching off takes hold at the next message**), the system prompt gets one
  more paragraph (so **an employee knows of the folder only if the chat began after it was switched on**), `prompt_sha` is v0.17.0's value byte for byte with the folder off, a chat's added prompt may be 9,000 characters (full mode keeps 2,000),
  1 GiB or 10,000 entries is `shared_full` (checked when a process starts). The 共用資料夾 page and its place in the nav. `--add-dir`, `additionalDirectories: []`, `--permission-prompt-tool stdio` and the `system/init` check
  are untouched. `tests/test_autonomy_guard.py` scans `shared*.py` and `runtime/shared*.py` and fails the build when any module but `server.py` reaches `set_card` or the store.
- **Codex and the version check (P43-2, `a6196af`…`90f0453`, `1bd2222`).** Codex gets the folder as `-c sandbox_workspace_write.writable_roots=[…]`, `turn/start`'s `writableRoots`, a `thread/start`
  answer that must list exactly that root (anything else stops the chat), and `judge_file_change` with the same rules; switching a Codex card on needs `confirm_company: true` (409 `shared_confirm`).
  Both chat checks (`--mode chat`, `--mode codex-chat`) gain a shared-folder part and the report gains `shared: passed|failed` and `shared_steps`; an employee who has the folder on is refused with
  `shared_unverified` on a version that has not passed it (the console says it first, the daemon again), and an employee who has it off chats as before. `docs/evidence/codex-0.163.0-shared.md` quotes the one
  zero-cost `codex sandbox` probe (the root works; a write through a link to the outside and into `.git`/`.codex`/`.agents` is refused; a link can be made and a file deleted inside it).
- **The hand-over of names, and the ticks (P43-3, `1982171`…`5058ff8`).** `shared_rules.snapshot`/`changes` and `vbear/shared_changes.py`: before and after each employee's answer (each dispatch step) the
  folder is listed with `os.scandir` and `lstat`; the new or changed names (at most 50, each at most 200 characters, a name with a control or format character is replaced by 「（檔名含特殊字元）」)
  go to the next employee as one JSON string between `BEGIN_UNTRUSTED_JSON_STRING` and `END_UNTRUSTED_JSON_STRING` (an employee who has the folder off is told only that there are new files). The lists are in
  `<state>/shared-meta/changes/` and in no group, dispatch or chat record (no new field; v0.17.0's checks read them). `POST /api/groups` and `POST /api/dispatch/<id>/confirm` take `shared_folder` and
  `confirm_company` (a refusal comes before anything is made; the dispatch's new employees are opened by a callback only when `pending/<d-…>.json` says the person ticked; a confirmation that fails takes the tick back);
  the chief of staff's list of employees says which can use the folder (with everyone off it is v0.17.0's byte for byte; the proposal format is unchanged); the group page shows the names under a reply.
- **The page in full (P43-4, `2d5ad39`).** Usage, links and the over-limit line, the file list (names as text, no preview, no delete), the question before a Codex card goes on, the fixed sentences (including that a
  full-mode terminal is not told), a line on the role card and at the top of a chat, a mark on a group's member, and the P42-6 notice about a changed chat now names the folder.
  **Merge decision (P43-5):** the chat page had two 「檢查」 offers for a version not checked with the folder (P43-2's note and a button in P43-4's line); only P43-2's note
  (`data-chat="shared-check"`) is kept, it also appears when a send is refused with `shared_unverified`, and the unused second check (`sharedStartCheck` and its hook) is deleted; the tests say exactly one
  place asks for the check with `shared: true`.
- **Documents, the walk, the real-machine check, CI (P43-5).** `docs/adr/0009-shared-folder.md` is final (the person decided on 2026-11-07: off by default; `<state>/shared` with 「在 Finder 打開」; Codex not verified on a real machine),
  `docs/SECURITY-MODEL.md` has "Shared folder (v0.17.1)" with its residual risks and what going back does, and both READMEs, `docs/ARCHITECTURE.md`, `docs/REFERENCE.zh-TW.md` and `GLOSSARY.md` (共用資料夾, 群組, 派工) say what it is.
  `tests/test_shared_flow.py` walks the whole thing once over HTTP: two employees switched on (the Codex one only with `confirm_company`), a group made with the tick, a file named to the second member and shown on the page,
  the second switched off and told only that there are files, a dispatch confirmed with the tick, and the Finder button (a fake) asking for the one folder; `config.json` is byte for byte the same and no
  file name is in `shared-meta`'s logs. `tools/qa_p43.py` is the real-machine check through the HTTP API (stages `setup`, `write`, `read`, `off`, `link`, `inject`, `group`, `full` and the zero-cost
  `codex-sandbox`; it needs `--state` and `--cards`, refuses `~/.vbear` and the ports 7788 and 7789, never presses the Finder button and prints nothing a model wrote); `tests/test_qa_p43.py` runs it against a fake console and a fake `codex`.
  **CI:** the Python 3.14 job was cut at its 20-minute limit in v0.17.0 (the backend had passed; the frontend tests were killed); `ci.yml`'s `timeout-minutes` is 35, and `release.yml`'s job, which runs the same tests and then the build, is 50 (was 30).
- **Money.** The folder itself costs nothing; a chat that has it gets one more paragraph of system prompt (at most 1,000 characters). The chat check's shared part is about three more Haiku calls for Claude Code (a few cents on your own login, not in the day's ledger) and
  a few more short calls on your ChatGPT plan for Codex. Comparing names costs nothing.
- **On a real Mac:** with Claude Code 2.1.319 and Haiku on 2026-11-08, the chat check passed with its shared part (six steps), and `tools/qa_p43.py` ran every stage: 57 ok, 0 warn, 0 FAIL, about US$0.025 in all. A write to the folder asked on a card and another employee read it; an employee switched off could not write (Write refused by VBear, Bash stopped by the sandbox); a write through a link out of the folder and a write to `.git` were refused; an instruction planted in a file was treated as data; the next group member was handed the file name; a folder over 1 GiB refused a new chat at no cost; `config.json` was byte-identical before and after. The zero-cost `codex sandbox` part ran with no sign-in. Not seen: whether a Bash card the person allows can write `.git` deeper than the top of the folder (the model would not try; the sandbox denies only the top four folders, added after this run). **Codex employees using the shared folder were NOT tried on a real machine** (your decision): they were tested
  only against the fake app-server and by the zero-cost `codex sandbox` probe above; in particular whether a real `thread/start` answer lists the configured root is unknown, and the design stops the chat if it does not, so the worst case
  is a Codex version that cannot pass the check with the folder. When you switch a Codex employee on, press 「檢查」 once (it uses your ChatGPT plan). How a real model treats a file as data, and whether a sentence in a file can steer it,
  has no record (待真機驗證).
- **Going back to v0.17.0.** This was read from the code and was not run (what could not be read is marked 待確認). v0.17.0 does not know the folder: `<state>/shared/` and `<state>/shared-meta/` stay and are not read, no employee is told of it,
  no writable root or `allowWrite` entry is added, and VBear's `judge`/`judge_file_change` refuse a write outside the work folder, so an employee can no longer write there (it can still be asked to read it, which is a card). Chat, group and dispatch
  records have no new field and read as before; groups and dispatches no longer hand on names; `config.json` has no new key. A chat that began with the folder on has a `chat-prompt` fingerprint that includes the folder's paragraph, so v0.17.0's
  chat page says it differs from its start (which is true). The chat-check reports have two more keys (`shared`, `shared_steps`); v0.17.0 reads `mode`, `passed` and the version, and that it accepts the extra keys is read from the code, not run (待確認).
  Nothing in the folder is deleted. A v0.17.1 process still running when you go back (待確認 how it ends).

## v0.17.0 — memory

The 記憶 page keeps a few lines you wrote or confirmed (about you, your work, decisions you made), one book for every employee, and each
employee whose card takes memory along is told them when a chat starts, so you do not repeat yourself in every chat. **A change reaches only a
new chat**: Claude Code keeps the system prompt a chat was started with (found on a real machine), so the chat page says when the memory or the
employee's fixed instructions are not what the chat works with, and offers 「開新聊天」. Only you
can save a line: on the page, with 記住 beside a sentence of a chat or a group, or by ticking a 記憶提議 after 整理要記住的事 (VBear proposes,
you tick, you save). An employee saying 「我記住了」 saves nothing. A password, key, account, email or card number is refused; a line that
reads like an order, or holds a phone number or an address, needs 「我確定」. A Claude Code card takes memory along by default and a Codex card only
after you switch it on (it goes to OpenAI); full-mode terminals never get it. Memory never lets an employee skip a question: every command
and every file change is still asked of you. The shared folder of the roadmap's v0.17.0 is not in this version; it is v0.17.1. Seven tasks
(P42-0 to P42-6):

- **Tests leave nothing running (P42-0, `a5fb9e1`).** The tests that put a console in front of the case's daemon did not set
  `VBEAR_RUNTIME_AUTOSTART=0`, so the console started a `vbear runtimed` of its own that nobody stopped. The cases now set it, every case
  registers `tests/leftover.py` (it reads `ps` and reports, then stops, a runtimed or a fake CLI under the case's folder) before it starts
  anything, and `tests/test_leftover.py` shows the check fails on a daemon left running. No product code changed.
- **The backbone (P42-1, `2c48f17`…`d794cf3`).** `vbear/memory.py` (`<state>/memory/memory.json`, `log.jsonl` that never holds a word of a line,
  50 lines, 200 characters each, 4,000 in all) and `vbear/runtime/memory_rules.py`, the one pure `check` (refused: `bad_text`, `secret_password`,
  `secret_key`, `secret_account`, `secret_payment`; needs 「我確定」: `looks_like_order`, `personal`) that the console runs when a line is saved
  and the daemon runs again on every line before it builds the system prompt, refusing the whole message (`memory_refused`) rather than leaving a
  line out. `chat_send` takes a `memory` field (a closed shape of at most 50 `{kind, text}`); the daemon appends one fixed paragraph (VBear's
  words and the lines as one JSON string between `BEGIN_VBEAR_MEMORY_JSON` and `END_VBEAR_MEMORY_JSON`, encoded twice, at most 6,000 characters)
  to Claude's `--append-system-prompt` and Codex's `developerInstructions`, after the card's own instructions; a chat's added prompt may now be
  8,000 characters (a full-mode launch keeps its 2,000). `GET/POST /api/memory`, `DELETE /api/memory/<id>`; 409 `memory_confirm`
  (`confirm_warning: true`), 400 `memory_refused`, 409 `memory_full`; a file that cannot be read means chats go on **without** memory and say so.
  The memory page (list, add, delete) and its place in the nav. Sent for chats, dispatch steps and group answers alike; the chat record has no
  new field (`KINDS` is unchanged) and the daemon's log has one line per new process with the count (`chat process memory entries=<N|none>`).
- **The edges (P42-2, `2299367`…`afa86c1`).** `PATCH /api/memory/<id>`, `POST /api/memory/clear` (`{confirm: "全部刪除"}`),
  `GET /api/memory/export` (Markdown, no chat, group or line id), `POST /api/memory/cards {profile_id, on, confirm_company?}` (switching a Codex card on
  takes `confirm_company: true`), `source` on a line (`chat`, `group` or `suggested`; the place must exist). (As first built, the daemon kept a hash
  of the system prompt a chat process started with and replaced the process when a message's hash differed, to use a change at the next message;
  **that did not work on a real machine and is gone, see P42-6**.) A Claude Code chat process gets
  `CLAUDE_CODE_DISABLE_AUTO_MEMORY=1` and `CLAUDE_CODE_DISABLE_CLAUDE_MDS=1` (only the chat's, not terminals or meetings) on top of `--safe-mode`,
  `--setting-sources ""` and `--strict-mcp-config`; tests pin the argv of both tools (Codex: `--disable memories`, `project_doc_max_bytes=0`,
  `history.persistence="none"`). `GET /api/chats/<id>` carries `memory: {on, count, readable}` (P42-6 adds `changed` and `started_with_memory`). `tests/test_autonomy_guard.py` scans `memory*.py` and
  `runtime/memory_rules.py` and fails the build when any module but `server.py` reaches what writes the memory. `PATCH` now has a handler (memory
  lines only), so `tests/test_console.py` checks that a PATCH with a token elsewhere is 404 and still checks the token and `X-VBear` first.
  `docs/evidence/claude-code-2.1.319-memory.md` quotes the three places of the installed program that the two variables rest on.
- **記住 and the full memory page (P42-3, `96f9334`).** A small 記住 beside each of your sentences and each employee reply in a chat and each
  sentence in a group opens a box with the sentence (cut to 200 characters and said so; an employee's sentence is marked), the kind (關於你, 你的工作 or 決定), and
  the refusal or the 「我確定」 box; only 存 saves, with `source`. The memory page has the sources in words, dates, 改, 刪, 全部刪除 (type the word), export
  through a `Blob` (nothing leaves the browser), the usage, and 誰帶記憶 (a switch per card; a Codex card asks first and says OpenAI; a card that cannot chat says
  why; and that terminals get none). A chat page says in one line whether this employee has the memory (N lines), and the back of a role card says so too.
- **整理要記住的事 (P42-4, `6ccf5e5`…`608e3e6`).** `vbear/memory_suggest.py` and `memory_suggest_runner.py`, shaped like the chief of staff's: a preview
  that costs nothing (what is read, at most US$0.10, what is left today, that the conversation goes to Anthropic), then one tool-less Claude Code
  call (sonnet, low effort, no retry) on the newest messages of a one-to-one chat; the answer is `{items: [{kind, text, why}]}` of at most five, with
  `additionalProperties: false` (anything else voids it). Every item goes through `check`; a refused one cannot be ticked, every line starts unticked,
  there is no 「save all」, and the run saves nothing (`memory.json` is byte for byte the same; the page sends one `POST /api/memory` per ticked line).
  `POST /api/memory/suggest/preview {chat_id}`, `POST /api/memory/suggest {preview_id}` (the page confirms what the preview showed; a changed chat or memory
  makes it `stale_preview`), `GET …[/<id>]`, `POST …/<id>/saved|dismiss|cancel`, `DELETE`. Needs Claude Code (「這個功能目前需要 Claude Code」 otherwise); not in groups.
- **Documents, the walk, and the real-machine check (P42-5).** `docs/SECURITY-MODEL.md` has "Memory (v0.17)" with its residual risks,
  `docs/adr/0008-memory.md` is final, both READMEs, `docs/ARCHITECTURE.md`, `docs/REFERENCE.zh-TW.md` and `GLOSSARY.md` (記憶, 記住, 記憶提議, 固定指示)
  say what it is. `tests/test_memory_flow.py` walks one memory over the real routes, a real daemon and the fake Claude Code (a phone number
  needing 「我確定」, a password refused, a new chat carrying the lines, the suggestion saving nothing, a line saved from it as `suggested`, an edit
  that does not reach the chat already started (the page says so) but reaches a new chat, a card off and on, a Codex card needing the word about OpenAI, the export, clearing; `config.json` the same
  at the end). `tools/qa_p42.py` is the real-machine check through the HTTP API (it needs `--state` and `--cards`, refuses `~/.vbear` and the ports 7788 and
  7789, and prints nothing a model wrote or any word of memory). Merge fixes found here: the chat page showed two lines about the memory (P42-2's and
  P42-3's); the unused second one is gone and the test now asserts one. The ledger's `includes` now lists `memory_suggest` (the money was already
  counted; the five tests that pinned the list follow).
- **A change reaches a new chat only; the old chat says so (P42-6).** The first real-machine run of `tools/qa_p42.py` found that **Claude Code 2.1.319
  does not apply a new `--append-system-prompt` when it resumes a session**: VBear put the new memory in the command line of the resumed process and
  the model still answered with the old line (the program keeps the prompt the session was started with). So the promise "a change is used by the next
  message" is gone, and so is the code behind it: the daemon no longer closes a live process, answers `restarting` and resumes because a message's memory or
  instructions differ (that only cost more and changed nothing; a card's fixed instructions edited after a chat started are likewise used by a new chat).
  Instead, when a chat's **new** session starts, the daemon keeps a fingerprint of its system prompt and whether it carried the memory in
  `<state>/chat-prompt/<chat id>.json` (0600, VBear's own state, **not a chat-record field**: `KINDS` is unchanged; no word of the memory or the
  instructions is in it; it goes when the chat is deleted). `GET /api/chats/<id>` compares it with the current memory and the card's instructions and
  says `memory.changed` and `memory.started_with_memory`; the chat page then says 「你改過記憶（或這位員工的固定指示），這個聊天還是用開始時的內容。要用新的，請開新聊天。」
  with a 開新聊天 button for the same employee (and, when the card is now switched off, that 「這個聊天開始時已經帶著記憶，已送出的內容收不回來」). A chat from before this
  version, or one a group opened, shows nothing. The new session of a resumed chat still gets the current memory on its command line (a later Claude Code
  may use it; the page's sentence is then more careful than it needs to be). **Codex is treated the same**: whether `thread/resume` applies new developer
  instructions was not verified. The fake Claude Code (`tests/fake_chat_cli.py`) now keeps a session's prompt and ignores the one of a resumed process, as
  the real one does, and records the prompt it works with (`system_prompt`). Also found: the 整理要記住的事 dialog needs the tool-less check that the chief of
  staff and the meetings use, and with it not done said only 「請先檢查」; the dialog now has the same 檢查 button (`POST /api/meetings/verify`, asked
  first, then the preview again). `tools/qa_p42.py`'s edit stage checks the new behavior (the old chat says it is changed and starts no process; a new chat answers
  with the new name) and its suggest stage does the check when the preview asks for it.
- **Money.** Memory costs nothing of its own, but every new chat has a longer system prompt (up to about 6,000 characters), and a chat that is resumed
  after its process ended is resumed with it, which reads the earlier conversation again; both fall in the turn's limit and the day. A suggestion costs at
  most US$0.10, counted in the day.
- **On a real Mac** (Claude Code 2.1.319, two Haiku employees, `tools/qa_p42.py`: 47 ok, 1 warn, 0 FAIL; about US$0.08 over two runs): a new
  chat answers from the memory; after the memory changed, an older chat says so, starts no new process and still answers from what it
  started with, and a new chat of the same employee answers from the new memory; a card switched off sends no memory in a new chat; an
  order-like line saved with 「我確定」 still left every command to an allow card; Claude Code made no memory folder or CLAUDE.md for a
  chat's work folder; `config.json` was unchanged. **Not run on a real machine for this change:** whether a model answers from
  the memory in every case; whether the two environment variables are honoured and Claude Code made no memory folder for a chat's work folder (they rest on the
  installed program's text, not on a run; the first real run saw both); how a model treats a line that reads like an order; whether a Codex `thread/resume`
  applies new developer instructions (not tried: the page says the same of Codex); and **Codex employees
  carrying memory, which only the fake app-server has seen**. The look of the pages (the box, the inline edit, the download in a strict CSP) was tried only on a
  synthetic page. No code or test ran a real AI tool.
- **Going back to v0.16.0.** This was read from the code and was not run. v0.16.0 does not know memory: `<state>/memory/` is left alone and
  unread, the 記憶 page and every 記住 are gone, no employee is given a memory paragraph, and nothing in `config.json` has to be undone (v0.17.0 adds no
  key). The chat records have no new field, so every chat reads as before; `<state>/chat-prompt/` is left alone and unread. A card's fixed instructions go back to
  being used only by the next new chat (as in v0.17.0 itself). The 整理 records in `<state>/memory/suggest/` are not read, so what they cost today is not in the day's spending any more (at most US$0.10
  each). A chat that already carried the lines keeps them in the tool's own copy of the conversation and in the live process, and what a
  resumed Claude Code or Codex conversation does with them was not run (待確認).

## v0.16.0 — group chat

In the 聊天 page, 開新群組 makes a group of two or three employees (Claude Code or Codex) that you talk to together, like a LINE
group. You say something to 「大家」 or name some of them with the @ buttons (點名); the employees asked answer one after the other, in the
order of the group, and each is given what was said since it last spoke, marked as data. Only your sentence starts an answer (an
employee's reply never calls another, even with an @ in it), every command and every file change is still asked of you on a
permission card under that employee's name, and nothing goes on by itself after a pause. Four tasks (P41-1 to P41-4); `vbear/runtime/`
is the same as in v0.15.0:

- **The backbone (P41-1, `6ce187e`).** `vbear/groups.py` (`<state>/groups/g-<12 hex>/`: `group.json`, 0600, 64 KiB, and
  `log.jsonl`, append-only, each line synced, 8 MiB; a log that does not read back makes that group read-only) and
  `vbear/group_runner.py` (a thread started by `serve()`, one pass every 2 seconds, `group-runner.lock`; shaped like the dispatch
  runner, no code shared with it). Making a group opens one chat per member with `ChatService.create` (nothing started, nothing spent);
  an answer is one turn of that chat, sent with the new `ChatService.send_for_group` (the same send as a person's, no `origin`, only to a
  chat a group opened). The message is the group's fixed words the first time, then what was said since this employee last spoke as one
  JSON string between `BEGIN_UNTRUSTED_JSON_STRING` and `END_UNTRUSTED_JSON_STRING` after a fixed sentence that it is data (6 KiB for an item, 12 KiB
  in all, 30 KiB for the message), then your words outside the markers. `GET/POST /api/groups`, `GET /api/groups/<id>?after=`,
  `POST /api/groups/<id>/messages` (202; 409 `round_open` while a round is on, 409 `red` on a red lamp). A group's chats are not in
  `GET /api/chats` and `POST /api/chats/<id>/messages` refuses them (`group_member_chat`). `tests/test_autonomy_guard.py` scans
  `vbear/group*.py` too and, new, fails on any call of `answer` (never answers a permission card), with small made-up sources that
  prove each rule fires.
- **Naming, members, and the controls of a round (P41-2, `a3a5d03`).** `to` can be a list of members (asked in the group's order,
  not the order named). `POST /api/groups/<id>/members {add, remove}` (between rounds; two or three remain; someone who comes back
  keeps her chat unless the card's AI tool changed), `POST …/rename`, `DELETE /api/groups/<id>` (between rounds; the chats go first, a busy
  chat refuses everything; what was spent stays counted), `POST …/stop|continue|drop` (body `{}`). A pause with the reason
  (`daily_limit` with 「明天 0:00」, `spend_unknown`, `uncertain` after a restart, `violation`) and a skip of one employee (`plan_limit` with the
  time the tool named or 「未知」, `busy` after three minutes, the chat's code for a card it will not run) in plain words; after a restart a
  turn that may or may not have been sent is looked up in its chat and never sent twice by itself. `GET /api/groups/<id>` carries
  `round`, `current`, `cost` and `can`.
- **The group page (P41-3, `c8af814`).** `#/chat/group/<id>`: the @ buttons (「大家」 and naming exclude each other; an @name at the
  start of the sentence picks the button), the line 「這句會請 N 位回答，最多 US$X，今天還剩 US$Y」 (no sending on a red lamp), the words being
  written, the allow card under the employee who asks (the chat page's own card; a Codex command card keeps its warning that the command may
  run outside the sandbox; no 「allow all」 of any kind), 停止, 繼續（請剩下的人回答）, 不用了, rename, adding and removing, deleting (the
  confirmation says that the chats are deleted, what was spent stays counted and Codex's own copies are not), the line that tells groups,
  meetings and dispatches apart, the lobby's 輪到你 for a group that waits for you or is paused, the 「群組」 and 「等你」 marks in the
  chat list, and, on the chat page of a group's chat opened by an old link, 「這是群組裡的對話」 with a link and no input. `GET /api/chats/<id>`
  also carries `group` (`{id, name}` or `null`).
- **Documents, the walk, and the real-machine check (P41-4).** `docs/SECURITY-MODEL.md` has "Group chats (v0.16)" with its residual
  risks: another employee's words are the next employee's input (a prompt-injection path), 「大家」 makes more cards, with Claude Code and Codex
  in one group the conversation goes to Anthropic and to OpenAI, and an allowed command can reach VBear's access token and API and a Codex
  command may run outside its sandbox. `docs/adr/0007-group-chat.md`, both READMEs, `docs/ARCHITECTURE.md`, `docs/REFERENCE.zh-TW.md` and
  `GLOSSARY.md` (群組, 點名) say what it is. `tests/test_group_flow.py` walks one group through the real HTTP routes over a fake daemon
  (making it, everyone, naming, a fake allow card answered by the person, the daily limit and 繼續, 不用了, 停止, members, rename,
  deleting) and reads every field the page reads; `tools/qa_p41.py` is the real-machine check through the HTTP API (it needs `--state`,
  refuses `~/.vbear` and the ports 7788 and 7789, prints nothing a model wrote). Fixed: after a rename the path at the top of the group
  page showed the old name until the page was opened again.
- **Money.** Each answer is a chat turn under the chat's per-turn limit and the daily limit, counted in the day by the chats; the group has
  no limit of its own. The page says before you send how many will answer and the most it can cost; when the daily limit is reached in
  the middle of a round the round pauses, says the limit and that the day is counted afresh at 0:00 local time tomorrow, and only your
  繼續 or 不用了 goes on. An employee whose plan limit is reached is left out of that sentence and the next one is asked.
- **Not run on a real machine for this change:** how a real model treats the other employees' words between the markers, how a Codex
  employee behaves in a group (the temporary state of the check has no Codex chat login, so only Claude Code employees are tried), whether
  停止 really ends the turn of the employee who was writing, and a Claude plan limit (it is not told apart from another error in a chat's
  record, so such a reply is shown as not finished normally, with no resume time). On a real Mac with Claude Code 2.1.319 and two Haiku
  employees, `tools/qa_p41.py` passed (48 ok, 1 warn, 0 FAIL; about US$0.11). An extra check put a command into the first
  employee's reply: the second employee saw it only inside the markers, asked for no tool, and no file appeared. A stopped turn
  that reports no cost is counted at the per-turn limit, as before. Codex employees in a group were not run on a real Mac. No code or test ran a real AI tool.
- **Going back to v0.15.0.** v0.15.0 does not know groups. `<state>/groups/` and `group-runner.lock` are left alone and unread, the 群組 rows
  are gone and nothing in `config.json` has to be undone (v0.16.0 adds no key). The chat records have no new field (no `origin`), so
  v0.15.0 reads every chat a group opened, one per member and the ones of members taken out too, as an ordinary chat: it is listed, holds the
  group's fixed words and the other employees' words (as data) inside its messages, can be sent to and deleted there, and the
  day's ledger counts what it spent as for any chat. Do not go back while a round is on or paused: its turn goes on in the chat and nothing
  takes the reply into the group. If you open the group again in v0.16.0, a reply whose chat you deleted in v0.15.0 reads 「讀不到這則回覆」;
  what a later round does with a member whose chat is gone, and with turns you added to a group's chat in v0.15.0, was not run (待確認).
  This was read from the code and was not run.

## v0.15.0 — the chief of staff

On the CEO's chat page, 請幕僚長安排 lets VBear's chief of staff read your recent conversation with the CEO and propose who
does what. You read and change the proposal on a card, press 確認派工 once, and VBear makes the new employees and sends the steps to
your employees, one chat per step. It never answers a permission card (every command and every file change is still asked of
you), never changes a limit, never starts a terminal or full mode and never installs a skill, and the whole run can be stopped
and read in 「AI 自己做了什麼」. Six tasks (P40-1 to P40-6; v0.14 was never released, so this version follows v0.13.0):

- **The chief of staff's one call (P40-1).** `vbear/chief.py` (pure: which messages are read, the list of employees as codes
  C1.., the answer's schema with `additionalProperties: false` and no field for a limit, mode, skill, URL or path, and
  `validate_plan` with its three layers: a badly formed answer is void, what is off the list is removed with a note, a plan
  with nothing left is void as `empty_plan`) and `vbear/chief_runner.py` (a board of one turn on the meetings' engine
  `board_engine.HeadlessBoard`: tool-less, `sonnet`, effort low, `min(US$0.30, what is left of the day)`, 120 seconds, the init
  event must list only `StructuredOutput`). `GET /api/chief/preview?chat_id=`, `POST /api/chief`, `GET /api/chief`,
  `GET /api/chief/<id>`, `POST /api/chief/<id>/retry` and `/cancel`. Its records are `<state>/chief/` and count in the day's
  ledger (`GET /api/meetings/ledger` lists `chief` in `includes`). The record keeps counts, sizes and SHA-256 sums, not the
  conversation.
- **自己動手, two items (P40-2).** `vbear/autonomy.py`, `GET/POST /api/settings/autonomy` and a section of the settings page.
  Item 1 lets the chief of staff make new employees by itself; item 2 lets it start a clean proposal by itself. Both are off by
  default, each asks a plain question before it is turned on, and nothing but that POST changes them. The other three items
  of ADR 0003 come later (v0.18.0). `tests/test_autonomy_guard.py` reads the source of `vbear/chief*.py`, `vbear/dispatch*.py`
  and `vbear/autonomy.py` and fails on an import or call that changes a limit, starts a terminal or full mode, or installs a skill.
- **The dispatch record and its confirmation (P40-3).** `vbear/dispatch.py`, `<state>/dispatch/d-<12 hex>.json`: states
  proposed, confirming, running, paused, done, stopped, dismissed; append-only events, each saying who decided
  (`by`: `you`, `auto1`, `auto2`, `vbear`). Confirming checks the plan again, only more strictly, then makes the new employees (safe
  mode, no skill, the fixed instruction text of the position) and a task card. `POST /api/dispatch/<id>/confirm|dismiss|stop|
  continue|withdraw-card|delete`, `GET /api/dispatch`, `GET /api/dispatch/<id>`, `GET /api/actions`. A message a dispatch
  sends is marked `origin = {dispatch, step}` in the chat record (`chat_store`, an optional field of `user_message`).
- **The runner (P40-4).** `vbear/dispatch_runner.py`, a thread started by `serve()`: one step at a time, each in a new chat,
  sent with `ChatService.send_for_dispatch`; a step goes out only after the one before ended normally, with that step's last
  reply handed on between `BEGIN_UNTRUSTED_JSON_STRING` and `END_UNTRUSTED_JSON_STRING` (at most 8 KiB, said to be data). It pauses and
  says why (the daily limit, a Codex plan limit, a busy chat, a step it cannot account for after a restart, a turn that ended in an error), 繼續 and 停止 are
  the person's. 繼續 skips a step that was sent and did not end normally. The step events name the step in the field `step`.
- **The pages (P40-5).** The CEO chat page gains 請幕僚長安排 and its dialog (what is read, where it goes, the most it can cost,
  what is left today, a note); the proposal card (edit the words, delete a step, swap the employee, change a new employee, 「你改過」
  marks, the most it can cost, 確認派工, 不採用); `#/dispatch` and `#/dispatch/<id>` (every step's state, 停止, 繼續 with a sentence
  that it skips the step that did not finish, taking back an employee VBear made, deleting); `#/actions` 「AI 自己做了什麼」
  (every action and who decided; a link from the settings page's 自己動手 section); the lobby's 輪到你 lists a proposal to confirm and
  a dispatch that is paused; a chat message sent by a dispatch says 「VBear 依派工送出」. Plain words for `empty_plan` and the other
  codes; a Codex CEO card says that the conversation goes to Claude Code; a Mac with Codex only reads 「幕僚長目前需要 Claude Code」.
  `GET /api/dispatch/<id>` also carries `tools` (the AI tools a new employee may name) and the actions carry the `profile_id` of a card a
  dispatch made. `tools/qa_p40.py` is the real-machine check through the HTTP API (it needs `--state`).
- **Fixes from the real-machine check (P40-6).** Claude Code 2.1.319 can chat: it has chat constants and an administrator-source
  list (its `--help` is identical to 2.1.318's and its binary names the same places; evidence in `docs/evidence/claude-code-2.1.318-chat.md`),
  but it is **not** yet verified and chats only after `boundary_check --mode chat` passes on your Mac. A chat now also picks, among
  the versions in Claude Code's own `versions` folder, the newest that passed the chat check, else the newest VBear has constants for,
  else PATH's; a version without constants is told in words which versions work. A new employee taken back before you confirm is
  now refused at 確認派工 (it used to start and then pause). Smaller: 「你按的」 in the actions list beside a withdrawal, stop,
  continue and dismissal; the chief of staff no longer writes how VBear will go about it, and the card says what really happens to
  the new employees; `tools/qa_p40.py` got its own fixes and `--from <dispatch id>`.
- **Documents.** `docs/SECURITY-MODEL.md` has "Chief of staff and dispatch" with its residual risks: the previous step's reply
  handed to the next step is a prompt-injection path, and an employee's allowed commands can read VBear's access token and call
  VBear's API, so VBear guarantees only that its own chief of staff and dispatch code do not do the three forbidden things.
  `docs/adr/0006-chief-of-staff-dispatch.md` records the decisions; both READMEs, `docs/ARCHITECTURE.md`,
  `docs/REFERENCE.zh-TW.md` and `GLOSSARY.md` (派工, 提議卡, AI 自己做了什麼; 幕僚長 and CEO updated) say what it is.
- **Money.** The chief of staff's call is counted in the day. A step is a chat turn under the chat's per-turn limit and the daily
  limit; the proposal card says the most it can cost (steps × the per-turn limit) and what is left today before you confirm. When
  the daily limit is reached the dispatch pauses, and 繼續 is yours; nothing counts down or goes on by itself in this version.
- **Not run on a real machine for this change:** that a real Claude Code fills the schema, that a closed chat stops being busy at
  once, that the second employee treats the handed-on reply as data, and the `resets_at` unit of a Codex plan limit. A Claude plan
  limit is not told apart from another error in a chat's record, so its pause carries no resume time. No code or test ran a real AI tool.
- **Going back to v0.13.0.** v0.13.0 does not know the dispatch. A chat message that a dispatch sent has an `origin` field that
  v0.13.0 does not accept in a `user_message`, so v0.13.0 reads that record as damaged: it lists the chat with a problem, cannot send to
  it and cannot delete it, and, as for the chats of v0.13.0 read by v0.12.0, it counts what it cannot read as spend it does not
  know, so on the day such a chat was written it refuses to start any meeting, staffing meeting or chat (`spend_unknown`) until you
  move that chat's folder out of `<state>/chats/`. Delete or move the chats of dispatched steps before going back. `<state>/chief/` and
  `<state>/dispatch/` are left alone and unread, and v0.13.0 does not count the chief of staff's calls in the day, so
  on a day you asked for proposals its ledger shows less than was spent. The employees and task cards a dispatch made are plain cards and stay. The
  config key `autonomy` stays in `config.json`, unread (v0.13.0 keeps keys it does not know). This was read from the v0.13.0 code and was not run.

## v0.13.0 — Codex chat

A role card whose AI tool is Codex can be chatted with, as one whose tool is Claude Code already could. Every command and every
file change is asked first, none is ever allowed from now on, and the cost is an estimate on your ChatGPT plan. A Codex
version chats only after it has passed `python3 -m vbear.boundary_check --mode codex-chat` on your Mac. Six tasks (P38-1 to
P38-6):

- **Protocol and a stand-in Codex (P38-1).** `vbear/runtime/codex_chat_protocol.py` holds, for Codex 0.163.0, every line VBear
  writes to `codex app-server` (it never writes `acceptForSession`, an execpolicy or network amendment, or `cancel`), the
  notices and requests it understands, what it counts as a violation, and the estimate of money from tokens. The ten short
  turns recorded with the real 0.163.0 are kept, scrubbed, in `tests/fixtures/codex-chat/`, and `tests/fake_codex_app_server.py`
  replays them, so no test runs the real `codex`.
- **A Codex login of the chat's own (P38-2).** `codex app-server` cannot be told to ignore your own `~/.codex` (your
  `AGENTS.md` and MCP servers were read in the recorded run), so the chat uses `<state>/codex-chat-home` and you log in to it once
  more. The start-up page's Codex row gains 讓聊天用的 Codex 登入, which types one fixed line into a terminal
  (`CODEX_HOME=<that folder> codex login -c cli_auth_credentials_store=file`; the page sends a tool and an action, never a
  command). The state is the exit code of `codex login status` alone. VBear refuses the folder when it holds a `config.toml`,
  `rules/` or `AGENTS.md`, has a link on its path, or passes 512 MiB. The Codex that runs is the pinned one under
  `~/.codex/packages/standalone/releases/`, never one from `PATH`; `codex-chat-verified.json` lists the versions that passed;
  the administrator-policy sources of 0.163.0 are the 0.160.0 list (`/etc/codex`, the managed preferences domain
  `com.openai.codex`). `docs/evidence/codex-0.163.0-chat.md` keeps what all this rests on.
- **The daemon runs Codex chats (P38-3).** A new engine `codex-chat` (`runtime/codex_chat_session.py`): one `codex app-server`
  per role card, at most three chats in all with the Claude ones, an environment of exactly seven variables, `untrusted` approval
  with reviewer `user`, and asks for the legacy `workspace-write` sandbox (the card's folder as its only writable place, network off, no `/tmp`; an allowed command may still run outside it, see below). A command
  is a card with its whole text; a file change is a card with each file's path, kind and diff, unless a path is outside the folder
  or under `.codex`, `.agents` or `.git`, which is declined without a card. A changed command is not "allow, changed": VBear
  declines it and sends `turn/steer`, and Codex asks again in a card of its own. Anything that shows VBear's settings are not
  in force stops the chat (an extra MCP server, another thread, a command completed without a yes, a changed policy). The chat
  record is version 2 (`chat.json` gains `engine`; version 1 files read as `claude-chat`) with the records `session_bound`,
  `usage`, `plan_usage` and `card_edit_sent`, and a turn's end gains `estimate` and `tokens`.
- **The version check (P38-4).** `python3 -m vbear.boundary_check --mode codex-chat` runs one real chat through VBear's own
  Codex code in a temporary state folder, with seven messages (text; `ls -a` must make a card, and a denied `rm`; a changed
  command; a file change; `apply_patch` outside the folder; stop; `thread/resume`), about fourteen short model calls on your ChatGPT
  plan and at most US$0.30 by VBear's own counting, not added to the day's ledger. A pass writes `codex-chat-verified.json` and a
  0600 report that is read back every time. The report holds no Codex home, user agent, plan kind, credits or e-mail-like text.
- **The console and the page (P38-5).** `POST /api/chats` reads the role card's tool and fixes the chat's engine for good; a
  card whose tool is Grok, AGY, MCODE or shared is refused with `card_tool_unsupported` (this replaces `card_not_claude`), and
  a card whose tool changed after the chat began gets `card_tool_changed` and nothing starts. `GET /api/chat-support` keeps
  Claude Code's keys and carries a `codex` object (not installed, not verified, administrator policy, folder refused, version
  unreadable, not logged in, ready); `POST /api/chat-support/verify` takes `{"engine": "codex"}`
  (`vbear/codex_verify.py`; no engine still means Claude Code). The chat page names each chat's AI tool, shows the notice of the
  chosen card's tool, and for Codex draws the command card (command, folder, what Codex says it does), the file card (path,
  what is done, diff, as text), 改內容再問 (VBear refuses the original and Codex asks again, so you allow once more), each
  reply's cost as 「估計 US$0.02」 with the token count and 「不是帳單」, one line of the ChatGPT plan's use as Codex reports it
  (and the reset time only when a limit was reached), and a deletion note saying Codex's own copy of the conversation in
  `codex-chat-home/sessions` is not deleted. `session_ready` records the CLI's version in `cli_version` (Claude chats keep
  `claude_code_version`; both read). The chat note on the page now says chats work with Claude Code or Codex. New sentences
  for `card_tool_unsupported`, `card_tool_changed` and `codex_version`; `not_logged_in` and `codex_home` have theirs.
  **Money:** Codex reports tokens, not money. A turn is estimated as tokens ÷ 1,000,000 × US$1.00, rounded up to the cent, at
  least US$0.01 (VBear's accounting rule, not a price), and counted in the same `meeting_limits.daily_usd`; a turn cut off
  without a count costs its cap. Two token reports can be a model call apart, so a turn can pass its cap by about one call.
  **Reading is not limited:** the sandbox does not limit reads, so a command you allow can read the whole machine; the
  permission profile that would stop reads made file changes fail on the recorded version.
  Documents: `docs/SECURITY-MODEL.md` has "Chats with a Codex role card" with its residual risks, `docs/adr/0005-codex-chat-boundary.md`
  records the decisions, and both READMEs, `docs/ARCHITECTURE.md` and `docs/REFERENCE.zh-TW.md` say what Codex chat is.
- **A home folder that is a git repository.** Found before release: Codex took `~` for the project root, read the person's own
  MCP servers and skills as a project's, and wrote that trust itself. A Codex chat now starts with `project_root_markers=[]` and
  the work folder's trust set to `untrusted` (both `-c`, the second an inline table), asks `mcpServerStatus/list` with the
  thread's `threadId`, and the version check asserts both were sent and that no `config.toml` appears; a `config.toml` already in
  the chat folder is refused with a plain reason, never deleted (`docs/evidence/codex-0.163.0-chat.md`).
- **An allowed command can run outside the sandbox.** Found on a real Mac, then read in the Codex source: under `untrusted`, when
  the sandbox stops a command you allowed, Codex runs it again without the sandbox and does not ask again, and a command the model
  asked to run outside the sandbox (`require_escalated`) does so the first time you allow it. Such a command can write anywhere
  your account can write and can reach the network, and the card cannot tell which it will be. So a Codex command card now says,
  above 允許這一次: 「允許後，這個指令可能在沙盒外執行：能改到工作資料夾以外的檔案，也能連網。只允許你看得懂、確定沒問題的指令。」
  A Claude chat's card and a Codex file card are unchanged; VBear still declines a file change outside the work folder or under
  `.codex`, `.agents`, `.git` by itself, with no card. The version check's `outside` step now requires only that `apply_patch`
  outside the folder is declined with no card and leaves no file (`outside_patch_refused`); whether the allowed shell write got
  out is only noted in the report and the file is removed. You chose this over the permission profile (every command asked and
  kept in the sandbox, but `apply_patch` fails in it) and over `never` (no cards, reads unasked); VBear will move to the profile
  when Codex fixes `apply_patch` there (`docs/adr/0005-codex-chat-boundary.md`, decision 7; `docs/evidence/codex-0.163.0-chat.md`, 5b).
- **Packaging copies stay out of Spotlight and Launchpad (P38-6).** `macos/build.sh` keeps every `VBear.app` it leaves on disk
  in a folder whose name ends in `.noindex` (`build/app.noindex`, `build/dmg.noindex`, `dist/app.noindex`); the DMG stays
  `dist/VBear-<version>-arm64.dmg`. The release workflow's smoke check reads the new path. It deletes only the old copies inside
  the repository.
- **The first CEO (P38-8).** After all your AI tools were logged in, pressing 開始使用 left a person with an empty lobby and no
  idea what to do (and with 「輪到 p」 and a card for a deleted task at the front of it). Now, when there is no role card you can
  chat with, 開始使用 leads to `#/ceo`, 建立你的 CEO: a card named CEO (position CEO, safe mode, a short plain description you can
  change) on the ready Claude Code, else the ready Codex; one press makes it and opens a chat with it, with the opening sentence
  「你好，請先問我三個問題，了解我想做什麼。」 only put in the box (you can change it; only your own press of 送出 sends it, so
  nothing is spent by the step). `GET /api/first-ceo` (`vbear/first_ceo.py`) tells the page whether the step is needed, which
  tool the card takes (a tool that is only marked as logged in, such as AGY or Grok, is never chosen; with no ready tool it says
  to go back to 開始設定) and the words to fill in; the card itself is made by the ordinary `POST /api/agent-profiles`. The
  config key `first_ceo_id` makes the lobby offer 跟你的 CEO 聊聊 once (until pressed, put away, or you have already talked
  with that card); while there is no card, the lobby offers 建立你的 CEO. A CEO is a plain role card: it chats and turns your idea
  into a plan; it cannot create employees or hand out work (the chief of staff, v0.15, will). In the lobby, flows whose task card
  is deleted or unreadable are folded away under 「其他進行中的任務」 (closed until you open it), and a role named with one or
  two letters or digits reads 「輪到規劃者」, 「輪到執行者」, 「輪到審查者」 instead of 「輪到 p」.
- **Not run on a real machine for this change:** the real Codex was never run by the code or its tests; whether `turn/steer` is
  accepted without the experimental API, whether Codex ends when its stdin closes, what `turn/interrupt` answers, and that a
  login writes nothing into the chat folder are for the first real `--mode codex-chat` (see section 7 of the evidence file).
- **Going back to v0.12.0.** v0.12.0 does not know Codex chats or the version 2 chat file. Every chat made by v0.13.0, a Claude
  chat included, has a `chat.json` that v0.12.0 reads as damaged: it lists the chat with a problem, cannot send to it and cannot
  delete it, and the files stay. A Codex chat's record also holds kinds v0.12.0 does not know (`session_bound`, `usage`,
  `plan_usage`, `card_edit_sent`), and v0.12.0 counts a record it cannot read whole as spend it does not know, so on the day such
  a chat was written it refuses to start any meeting, staffing meeting or chat (`spend_unknown`) until you move the chat's folder
  out of `<state>/chats/`. Chats made by v0.12.0 itself read as before in v0.13.0. Move or delete the Codex chats before going back.
  `codex-chat-home/` and `codex-chat-verified.json` are left alone and unread, and a role card with the Codex tool reads as
  before (v0.12.0 refuses to chat with it). v0.13.0 adds no config key. The launch records of Codex chats under `sessions/` are
  an engine v0.12.0 does not know; how it treats them was not checked. This was read from the v0.12.0 code and was not run.

## v0.12.0 — the start-up page

The start-up page: a new person is taken through installing and signing in to an AI
tool, picking a daily limit and trying the tool once, before anything else.

- **A start-up page (`#/setup`, 開始設定) and a left-menu entry.** It lists the AI tools side by side (Claude Code, Codex,
  Antigravity (AGY), Grok; MCODE only while it is switched on) with where each stands: 還沒安裝, 還沒登入 or 就緒. 安裝 and 登入 open a
  terminal inside VBear and type the tool maker's own install or login line into it; the line comes only from the list in
  `vbear/ai_tools.py` (the page sends a tool and an action, never a command), and the person sees it and the shell runs it.
  MCODE's login has two buttons, one per region. Claude Code and Codex are checked with their own status command and only
  the exit code is used (0 means signed in; the output is not captured, stored or served); AGY, Grok and MCODE have no such
  command, so the person presses 我登入好了, and the page says VBear cannot confirm it. The mark is kept in `setup_marks.json`
  (tool id and time only). Nothing reads any tool's own login folder. The page reads the tools again every 5 seconds (a look
  is kept for 30 seconds, and a forced recheck, a mark, a terminal or a try makes the next look fresh). The runtime daemon
  has one new operation, `open_setup`, which takes only a tool, an action, a region and a terminal size.
- **First time, and upgrading.** New config keys `setup_done` and `setup_notice` (both false by default, written through
  `/api/config`, booleans only). The home page sends a person who has not finished and has no ready tool to `#/setup`;
  someone who already has a ready tool when they upgrade is counted as done and told once. If the server cannot say, nobody
  is forced anywhere.
- **A first-time page (`#/welcome`, 第一次打開 VBear), app window only.** Shown once, before the start-up page, and it can be
  skipped. It says what to do when the Mac stops an app that is not signed with an Apple Developer ID: System Settings,
  隱私權與安全性, press 強制打開 (the same as the README's Open Anyway steps). Its picture is an illustration the page draws
  itself, not a screenshot, so nothing from anyone's real settings is in it, and it says so. Whether it is the app window is
  judged by the folder chooser the app window gives the page (a browser does not have it), so a browser never gets the
  page. New config key `welcome_seen` (false by default, boolean only) is set when it is read or skipped.
- **Grok and MCODE as employees.** Grok (xAI's Grok Build) and MCODE (MiniMax Code) can be put on role cards and started in
  full mode (`grok [-m X]`, `mcode [-m X]`); neither has a safe mode, and the instructions go in only through 貼上職位指示.
  MCODE is hidden: the config key `show_mcode` (false by default) is switched on by 「顯示 MCODE」 in the settings. While it is
  off, MCODE is not offered anywhere, cannot be given to a card and is left out of the staffing proposal's tool list; a card
  that already uses it is kept and says why it cannot be chosen. VBear now also looks for the tools in `~/.grok/bin` and
  `~/.minimax-code/bin` after `~/.local/bin`. xAI and MiniMax are two more makers, each its own family for the independent
  review rule.
- **Full mode needs a tick on 我了解, and new cards start in safe mode.** A full-mode launch is refused with
  `full_mode_not_acknowledged` (409) unless the confirmation carries `accept_full_mode: true`; the pass shows 「這個員工可以動
  你電腦上的任何檔案」 and 確認啟動 stays off until the box is ticked. New role cards start in safe mode when their tool has
  one (only Claude Code), otherwise in full mode with the reason; the catalog's default is `safe`. Cards that exist are not
  changed. Codex has a safe launch in the tool list but VBear refuses it for its interactive mode, so in practice Codex runs
  in full mode only.
- **試一下.** Each installed tool has a button that sends one fixed short sentence headless, in a new empty scratch folder
  and a new process group that is ended however the call ends, with a 60 second limit, and reads only whether it answered
  (the answer and anything about the account are dropped, never stored). The page says it costs about under US$0.01 and
  needs a second press to confirm. The result is success, not logged in, timeout, not found or an answer VBear cannot read.
  The cost is kept in `setup-try.json` (tool, times, cap, cost) and counts in the same day as the meetings, staffing meetings
  and chats: what Claude Code reports, else US$0.01 (a try that started a program is booked even when it fails); when the
  day cannot take another US$0.01 nothing starts. The ledger's `includes` list gains `setup_try`.
  Codex's try puts `--ask-for-approval never` before `exec`, because it is a top-level option of `codex` and
  `codex exec --help` does not list it; the other flags were checked against each tool's own `--help`. None of these calls
  was run against a real tool for this change.
- **Choose a daily limit (每天上限) on the start-up page.** US$1, US$3 (the default) or US$10, each with a sentence on what
  it roughly covers, written for the default per-call limits. It sets `meeting_limits.daily_usd`, shared by chats, meetings,
  staffing meetings and tries, and only ever lowers the other limits that would otherwise be above it (the meeting, per
  call, staffing total and chat turn limits); choosing US$10 raises none. The same rule now applies when
  `meeting_limits` is written through `/api/config`.
- **A note where a page needs Claude Code.** The meetings, staffing meetings, chat and skill-translation pages show
  「這個功能目前需要 Claude Code」, how to get it and a button to the start-up page when Claude Code is not ready; when the state
  cannot be read nothing is shown and the page works as before.
- **The tool list is in one place (`vbear/ai_tools.py`).** The Python tables that used to repeat the tools (profiles,
  position guide, flows, launch, runtime, the catalog's `tool_list`) are built from it, and a test keeps the page's own copy
  equal to it.
- **Sentences that said VBear cannot start AGY are corrected.** They now say safe mode does not start AGY and full mode does,
  for example 「安全模式不會啟動 AGY，要出發請選完整模式」.
- **Documents.** Both READMEs describe the start-up page, Grok and hidden MCODE, Codex as full mode only, the daily limit,
  the 我了解 tick, safe mode for new cards, what a try costs and the first-time page. `SECURITY.md` and
  `docs/SECURITY-MODEL.md` say that the start-up page's commands come only from the server's list, how a try is isolated
  and booked, and that status commands are read by exit code only.
- **Going back to v0.11.0.** v0.11.0 reads the new config keys (`setup_done`, `setup_notice`, `welcome_seen`, `show_mcode`)
  as extra keys and leaves them in `config.json`; it leaves `setup_marks.json`, `setup-try.json` and `setup-try.blocked` as
  they are, and it has no start-up page. **v0.11.0 does not count tries in the day's ledger**, so on a day that tries spent
  money here it lets meetings spend the whole of `meeting_limits.daily_usd` again. Daily limits lowered by the start-up page
  stay lowered. **Role cards that use Grok or MCODE are the one thing to fix first:** v0.11.0 does not know those tools and
  treats `agent_profiles.json` with such a card as damaged. It moves the file aside, marks it, and stops reading and writing
  role cards until you recover it by hand. Before going back, change those cards to another tool or delete them (switching
  `show_mcode` off is not enough). This was read from the v0.11.0 code and was not run; flows and task cards that name a
  Grok or MCODE card were not checked.

## v0.11.0 — chatting with role cards

You can now talk with a role card. Pick an enabled card whose tool is Claude Code, say something, and the card answers
through your own Claude Code in its own work folder. When it wants to run a command, change a file or write one, a card
asks you and nothing happens until you allow it. A chat uses your Claude usage, and no Claude Code version is allowed to
chat until it has passed a real check on your Mac.

- **A chat page (`#/chat`, `#/chat/<id>`) and a chat button on a role card.** The list shows the chats, the day's
  lamp and spend, and the cards you may open a chat with. A card that is off or whose tool is not Claude Code is listed
  with the reason and cannot be picked; the card's own 聊天 button is shut for it the same way. A chat is opened only
  by 開始聊天 and costs nothing until you send a message. One chat shows the record in order (what you said, the reply,
  each tool the card used and its result, each card and how it ended, what each turn cost), the reply while it is being
  written, a stop button, and a delete button. The first visit opens a short explainer: what it is, what it costs, that
  nothing runs without your yes, and which instructions go in.
- **Permission cards.** Bash, Edit and Write always ask. Each card says what is asked and has 允許這一次, 拒絕 and
  改內容再允許 (the command, the content or the new text is yours to change; a card with nothing to change has the other
  two). There is no 「以後都允許」. A card can be answered once, within 5 minutes; after that it is refused for you, and the
  record says so. When you press allow, VBear judges the call again as it will be sent: an Edit or Write that is now
  outside the work folder is refused with the reason (`refused`). Reading inside the work folder is allowed without a
  card.
- **Whose instructions go in.** Only the instructions you wrote on the card, as one `--append-system-prompt` argument
  (the flag is in Claude Code 2.1.318's `--help`). The default text of the card's position is never sent, and a card
  with no instructions of its own sends none; each chat says in its record whether instructions went in. Claude Code
  keeps the system prompt of a session when it is resumed (`--system-prompt-snapshot` is on by default), so editing the
  card does not change a conversation that has begun. **This was not checked on a real machine**: neither that Claude
  Code applies the appended text nor how it treats an edited one on resume. The chat check records whether the first
  reply followed a made-up instruction, as an observation and not as a pass condition.
- **Money.** A turn costs at most `chat_limits.per_turn_usd` (new top-level key of `config.json`, US$0.50 by default,
  US$0.01 to US$5, never more than the daily limit) or what is left of the day, whichever is smaller. The chats count
  in the same day as the meetings and the staffing meetings: `meeting_limits.daily_usd` covers all three, and the
  lamp says so. Amounts are Claude Code's estimates, shown as such; a turn whose cost Claude Code did not report is
  counted at its cap. On a red lamp, or with less than a cent left, no message is sent.
- **Which Claude Code may chat.** No version is chat-verified out of the box. The page shows the detected version and
  whether it passed; for one that did not, 驗證聊天 runs `python3 -m vbear.boundary_check --mode chat` after telling you
  it makes about six small Haiku calls on your own login. It opens a chat with a made-up card in a temporary state
  folder and sends six messages: a streamed text turn, a Bash card allowed with a changed command (which also tries a
  write inside and outside the work folder), a Bash card denied, a Bash card answered with the error VBear gives a
  request it does not know, a resumed process that must remember a code word, and a resume under the smallest budget.
  It judges from the events VBear recorded and the files left behind: the initialize answer was accepted, every Bash
  asked, the chosen command ran, a denied one did not, the sandbox stopped the write outside, no shared-tmp error, the
  total is cumulative across a resume, `system/init` named no extra folder and no MCP server, nothing from the
  initialize answer was kept, the check cleaned up. Only a pass writes `<state>/claude-chat-verified.json`; the version
  counts only while the report it names (mode `chat`, passed, the same version, owned by you) reads back, so a record
  without a passing report counts for nothing. It also records what a resumed session's `--max-budget-usd` counts (it
  can tell only when the session already spent more than the smallest budget). The check's few cents go on your
  Claude account and not into the day's ledger.
- **Administrator policy for 2.1.318.** The version has its own list of the places Claude Code reads policy from: the
  directory `/Library/Application Support/ClaudeCode`, the managed preferences for `com.anthropic.claudecode`,
  `~/.claude/remote-settings.json`, and, new in this version, `~/.claude/policy-limits.json`. If any exists, or its
  existence cannot be established, no chat starts and the page says which. The last one is stricter than the older
  versions on purpose: nothing says what it can change. The evidence is in
  `docs/evidence/claude-code-2.1.318-chat.md`. **If your Mac already has `~/.claude/policy-limits.json`, chats stay
  shut.**
- **No settings of yours are read by a chat (`--setting-sources ""`).** Found by running the check on the real 2.1.318:
  `system/init` still named the extra folders of your own Claude user settings, which `--settings` cannot remove, so the
  chat was stopped and the check failed. The chat's argv now loads no user, project or local settings, so VBear's own
  settings are the only ones; your login still works. A chat therefore does not see your own permission rules, extra
  folders or hooks. `additionalDirectories: []` and the check of `system/init` stay as a second layer.
- **A Python without `os.waitid` starts no chat.** macOS's own `/usr/bin/python3` (3.9) has none, and VBear needs Python
  3.13 or newer. The check and a chat now say so (`unsupported_python`) before starting anything; before, the first turn
  ended in an `AttributeError` and left a process for a person to look at. An unexpected error while a chat process is
  managed now ends the process (after the identity check) and cleans up its launch instead of leaving it.
- **Every refusal is said in words.** The console answers a refusal with a sentence, not a code: 這張卡片過期（5 分鐘）,
  VBear 又檢查了一次所以拒絕 (`refused`), 員工的程序正在換新的所以你的訊息還沒送出 (`restarting`, tried again by itself
  a few times first), 今天已經花了多少讀不出來 (`spend_unknown`), and 這個聊天的紀錄有問題 (`damaged`: it is not written
  to, not sent to and not deleted, because deleting it would drop what it spent from the day). A test reads every code
  the runtime can give and fails until it has a sentence.
- **A meeting turn skipped because the day's spend is unknown** now reads 無法確認花費, with the reason underneath,
  on a meeting and on a staffing meeting, instead of 沒有發言.
- **Under the chats.** The console talks to the runtime daemon, which owns the chat processes and is the only writer
  of a chat's record. `GET /api/chats/<id>/stream` is a live view as server-sent events and needs the same `X-VBear`
  header as every write (the page reads it with `fetch`, and polls when the stream cannot be had); at most four
  streams are open at once. Nothing of what a chat's initialize answer carries (the account, the commands, the models,
  the extra folders) is kept or sent to the page.
- **Going back to v0.10.0.** v0.10.0 does not know chats: it leaves `chats/`, `chat-work/`, `chat-spend/` and
  `claude-chat-verified.json` as they are, and `chat_limits` stays in `config.json`. **v0.10.0's daily ledger does not
  count what the chats spent**, so on a day a chat spent money here, v0.10.0 lets meetings spend the whole of
  `meeting_limits.daily_usd` again. A meeting turn this version skipped for an unknown spend shows there as 沒有發言 with
  代碼：spend_unknown. The explainer's "seen" mark is kept in this browser only.

## v0.10.0 — staffing meetings, shorter meetings, and adopting a team step by step

The CEO card can now staff a task card: the positions say who and which skills the task needs, the CEO writes a staffing
proposal, and you change it as a draft and adopt it one step at a time, each step a button you press. Meetings got
shorter: Claude Code thinks at low or medium effort and a meeting runs on a clock. This section is everything since
v0.9.0; going back to v0.9.0 is described once, at the end.

- **A staffing meeting (組隊會議) asks the CEO card to staff one task card.** 請 CEO 組隊 on a task card (in the lobby,
  the workbench and its team board) opens a form (`#/staffing?task=`) with the speakers VBear ticked from a fixed table,
  one enabled card per position, each with its reason (固定規則，不是 AI 判斷); you change any of it. A disabled card
  cannot speak, but the CEO may propose it. The preview shows every text each call sends, the models and the effort, the
  money it reserves (each speaker's call and the CEO's), the day's lamp and how many cards and skills the list left out;
  only 開始組隊會議 starts it. Each speaker says once, alone, then the CEO writes the proposal: who goes in the four places of
  the task card, which staff to bring to a meeting, which new cards to make, the skills for each card, the skill gaps,
  the risks, the questions for you, and which opinions it adopted and which not, with why. Cards and skills are sent
  under aliases (`C1`, `S1`, ...), never their ids; the page shows each alias as the card's or the skill's name today,
  or 「找不到」. A skill gap comes with a search of this console's skill library, never a link out. Each record is a
  file of its own in `staffing/`.
- **What a staffing meeting costs, and when it can run.** A speaker's call costs at most `meeting_limits.per_call_usd`,
  the CEO's at most `staffing_limits.proposal_call_usd` (US$0.50 by default) and a whole staffing record at most
  `staffing_limits.total_usd` (US$2.00 by default); `staffing_limits` is a new top-level key of `config.json`. It counts
  in the same day as the meetings: `meeting_limits.daily_usd` covers both, and the ledger says so. It uses the meetings'
  one worker, so a meeting and a staffing meeting never run at the same time; the one started second is refused. A failed
  turn is retried only by you, through its own preview (twice at most), and retrying a speaker asks the CEO again; a
  restart interrupts what was running and resumes nothing. VBear runs no rule of the meetings (R1–R8) on it.
- **Your draft of the proposal.** On a staffing record (`#/staffing/<id>`), 改成你要的樣子（草稿） lets you put
  someone else in a place, empty a place or take a staff row out, add a staff position, and add or untick skills; only
  the skills that card can read are offered. VBear checks each row again by the page's own rules (the card as it is now,
  the place it fits, a review's camp against the executor's, as on a task card) and does not tick a row it flags; a row
  you tick yourself stays ticked. The draft is kept in this browser only, and a draft of an earlier proposal is not used.
- **Adopting the draft, one step at a time.** Under the draft, 照草稿採用 lists six steps in a fixed order: 啟用 (switch
  a disabled card on), 建新卡 (the card wizard opens filled from the CEO's new card: name, position, camp, model and the
  skills it can read; nothing is saved until 建立), 插技能 (a dialog shows the card's skills before and after;
  插上技能只是紀錄，不會安裝或下載), 帶到隊伍 (the task card opens with the team placed on its board but not saved: `flows.json` is
  written only when you press 建立隊伍 or 儲存隊伍 there; a place the proposal does not name stays as it is, and leaving
  the page drops what was placed), 帶去開會 (optional: the meeting form with the staff ticked as speakers; nothing is
  sent until 預覽) and 記下. Each step is a button you press and goes through an endpoint VBear already had; a step waits
  for the ones before it, and 記下：採用 is offered only once the first four are done. The adoption keeps the rows as
  they are on the cards (each place, the card in it, the CEO's new card it was made from and its skills); like 記下：不採用
  it is a record of the console (主控台記錄（未驗證身分）) and does nothing by itself. A record whose proposal the CEO did
  not finish can only be dismissed. The cards made in the wizard are remembered in this browser.
- **Meetings are shorter, and say why they cost money.** A speaker thinks at low effort and the CEO at medium
  (`meeting_speed`, a new top-level key of `config.json`; high is not offered), and a meeting runs at most 15 minutes (5
  to 30) with the last three kept for the CEO; a speaker with less than a minute left is skipped, 時間到沒發言. The
  meeting pages and their previews say the speed and the clock, and why a meeting costs money: each speaker (and the
  CEO) is one call of a model through your own Claude Code; the dollars are Claude Code's estimate, and a subscription
  uses your usage instead of being charged apart. The same holds for a staffing meeting.
- **The office and the board show the staffing meetings.** The office's 會議室 also seats a staffing meeting that runs
  or waits, marked 組隊會議, its seats leading to its record, and the 董事長桌 counts 組隊提案待你看, with 去看提案. The home
  page's 「輪到你」 lists a proposal waiting for you. A staffing list that cannot be read is said (讀不到組隊會議), not
  taken as none.
- **Under the meetings.** The meetings' engine is split out of the meeting runner (`board_engine.py`), with no change in
  how a meeting behaves, and a turn whose text cannot be made now ends as failed instead of staying queued.
  `skill_fit.py` is a Python copy of the page's rules for which skill a card can take, so the server checks a proposal
  as the page checks a card.
- **Going back to v0.9.0.** v0.9.0 reads what this version wrote, except the staffing meetings: it does not know the
  `staffing/` folder and leaves it as it is, so coming back finds the records again. `staffing_limits` and
  `meeting_speed` stay in `config.json` (v0.9.0 keeps a top-level key it does not know when it saves) and are not used
  there; its meetings run without `--effort` and without the clock, and a turn this version skipped for time shows there
  as 沒有發言 with 代碼：time_up. **v0.9.0's daily ledger does not count what the staffing meetings spent**: on a day a
  staffing meeting spent money here, v0.9.0 lets meetings spend the whole of `meeting_limits.daily_usd` again, so that
  day can go over it. `meeting-worker.lock` and `meeting-worker.blocked` are the meetings' own files both ways. The
  drafts and the cards made in the wizard (kept in this browser) and a team placed on a board but not saved are not used
  there; a role card, a skill, a task card or a flow changed by an adoption is an ordinary one there, because each step
  went through an endpoint v0.9.0 has too.

## v0.9.0 — seven positions, role instructions, full-mode launches and office meetings

Role cards now follow the seven positions of a one-person company, carry instructions and a launch mode, and can hold
a meeting: the positions talk a question over in writing, the CEO decides, and what is major waits for you, the
chairman. A card in the new full mode starts its tool the way you would in your own terminal, with nothing limited by
VBear; the safe mode is the sandboxed launch VBear had before, unchanged, and every card saved before this version
stays in it. This version was never published on its own, so this section is everything since v0.8.9, the profession
picker and the hover box for skill descriptions included; going back to v0.8.9 is described once, at the end.

- **A role card's suggested position now follows the seven positions of a one-person company.** Step 2 of the card
  wizard offers CEO, 全端工程師, 社群媒體經理 and 藝術總監 as the positions done on a task card, PM, 法務經理 and 會計師
  as staff, and 先不指定 beside the staff row. The independent review is not one of the seven: it is VBear's own review
  gate, offered apart as 「VBear 內建：審查關卡（給任務卡的審查位）」. A position you pick shows what it does, where on a
  task card it is suggested to go, the camp and model it is suggested for (the art director's is AGY, which VBear does not
  start, and the box says so), and a one-line reminder of the division of work, which is also added to the note about
  permissions. Positions are labels only: every one still suggests the same permission intents (the one combination a
  launch honours), and the reminder is words for you to write into the task card's goal, because VBear cannot enforce
  it. The ids planner, executor and reviewer keep their meaning and only change their words (CEO, 全端工程師, 獨立審查;
  the badges are 長, 工, 審), so a card saved in v0.8.9 reads as before. The starter deck's second card is now named
  全端工程師. The ids that only a local build of this version wrote are read as the position they became (qa as 獨立審查,
  product and records as PM, design as 藝術總監) and marked 舊位置; research and business have no successor, so those cards
  show 先不指定 with 請重選. Nothing is rewritten by looking: a card is rewritten when you save it in the wizard, and a
  stored value the page cannot show stays until you press a position button. A save accepts only the eight listed ids.
  On a task card each place says what suits it (適合：…), and 放上任務卡 on a card made for a place of the task card has
  that place chosen for you (a review card gets the empty review place; a PM or other staff card gets none); nothing is
  written until you press 放上去. The profession picker guesses among the same eight positions (a security, test or review
  role fits the review gate, a legal or compliance role 法務經理, a finance role 會計師). The task card's places and its
  saved flow are unchanged.
- **A role card's position is now kept on the card, not only in the browser.** The card has an optional `position`
  field, so the position is still there in another browser or on another port (the app picks 7789 and up when 7788 is
  busy, and each port was its own browser store). The wizard and the starter deck send the position with the card, a
  copy carries it, and switching a card off or on leaves it alone. A card whose position was only remembered in the
  browser looks as before, and the position is written onto the card when you save it in the wizard; the browser's
  note is still written too. A card with no position stores nothing new, so its revision does not change, while a
  position counts in the revision like any other field. A position this version does not list (written by a newer
  one) shows as 先不指定, is kept when you save without touching it, and does not make the card file unreadable. The
  save refuses a position outside the eight listed ones.
- **A role card can carry its own instructions, a launch mode and the boundaries that go with them.** The card
  wizard's step 2 has a box for the position's instructions (starting from the position's default, up to 2000
  characters, with 回復預設), a choice of how the card departs (完整模式 for a new card, 安全模式 for the sandboxed
  launch; a card saved before this stays safe) and, below, what each position's boundaries are for the tool and mode you
  chose, each marked as enforced when launched, only a reminder, not possible or not applicable. In the safe mode the
  instructions are not sent into the tool when it starts. After you take over a terminal,
  貼上職位指示 pastes them into the input box without pressing Enter; you read them and press Enter yourself. The back of
  a card and the pass say where the instructions go, the pass suggests a folder name for the position (a suggestion, not
  a check), and step 3 marks the skills that fit the position as 推薦 with a 只看推薦 toggle. Two skill categories are new,
  法規與合規 and 財務與帳務, so the skill index version is now 3 and the index is rebuilt once. Cards without the new
  fields store nothing new.
- **A card in full mode now departs, with nothing limited.** 完整模式 starts Claude Code, Codex or AGY the way you would
  start it in your own terminal: your own settings, skills, `CLAUDE.md`, MCP servers and plugins, and the network. VBear
  adds no sandbox, no `--safe-mode`, no settings file, no tool list and no scratch folder, so the pass for such a card
  starts with 「VBear 沒有限制這張卡」 and shows no shield; only the tool's own permission prompts are left, and a
  permission intent written as "deny" is listed as not kept. The command is built on the server and shown on the pass
  (`claude [--model X] [--append-system-prompt …]`, `codex [-m X]`, `agy [--model X]`); you confirm it as before, and the
  preview is voided if the card or the program file changes. Claude Code is started with the card's instructions as one
  `--append-system-prompt` argument, shown in full on the pass (VBear did not verify that Claude Code receives them);
  Codex and AGY have no such option, so their instructions stay the 貼上職位指示 button's. AGY can now be started this
  way (not in the safe mode). The terminal appears in the office and the workbench as an agent whose state reads 狀態未知,
  because no signal was checked for it. A card without `launch_mode` is still the safe one, started exactly as before.
- **The executor's role card can open the plan of automatic mode with its instructions.** When the card placed on a flow's
  executor place has instructions, the plan the approval shows, hashes and saves starts with them (naming the card),
  followed by the task; with no card or no instructions the plan is the same text as before, and an already approved
  flow keeps its own plan. The approval dialog says which card, and the dispatch box has 加上職位指示, which puts the same
  text first in the box without sending anything.
- **Meetings: the positions talk a question over in writing, the CEO decides, and what is major waits for you.** The new
  會議 page (`#/meetings`, also 開會討論 on a task card of the home page and of the workbench) takes a topic, an optional
  supplement and task card, a chair (an enabled card whose saved position is CEO), up to six speakers with one card per
  position (PM, 全端工程師, 社群媒體經理, 藝術總監, 法務經理, 會計師) and six 涉及 boxes (對外發布, 花錢, 刪除資料, 法律或合約,
  上線部署, 個資). 預覽（還不會開始） shows, before anything is sent, every card's instructions and the whole text each call
  will send, the model, the number of calls and the money reserved, the day's spending and whether this Claude Code
  version has passed the tool-less check; only 開始開會 starts the meeting, and the preview is used once and lapses after
  five minutes. Each speaker answers once without seeing the others (with a task card, the PM also gets a progress
  summary VBear writes from its records, and the accountant what the meeting has cost so far); then the CEO reads every
  answer and writes a decision with its reasons and actions. Every call is Claude Code with no tools at all, the kind of
  call a skill translation makes: each call's own start is checked for only StructuredOutput and no MCP server, and
  anything else stops it at once, throws its answer away and voids that version's check until it is checked again. A
  Codex or AGY card does not speak itself: Claude speaks for it with that position's instructions, marked 代發言. The
  texts go through your own Claude Code to Anthropic under your account, with secret-shaped text masked; a task card's
  fields are sent, never its folder. A fixed table, R1–R8, decides whether the decision goes to you: a box you ticked;
  an action that publishes, deploys, pays, deletes, signs or changes a price; a keyword or any amount of money in the
  topic, the supplement or the decision; a high risk, or a legal risk with no source (查無出處); the legal manager
  opposing; a speaker that failed; or anyone asking for you. A model's fields are read only to raise that verdict, never
  to lower it, and the keyword list can miss a paraphrase, which is what the 涉及 boxes are for. You approve or veto at
  the 董事長桌 with a note, a record in the console (主控台記錄（未驗證身分）): anyone who can use the console can press it.
  A decision that does not need you reads CEO 已決定, and you can still veto it. A decision is only a record: VBear
  carries out nothing, and 寫進任務卡 opens the task card's editor with the decision added to its goal, for you to save.
  Spending has three limits, kept in `config.json` as `meeting_limits` (US$0.20 per call, 1.50 per meeting and 3.00 per
  day by default): a call counts what Claude Code reported, or the per-call limit when it reported nothing; the figures
  are Claude Code's estimates, not a bill; the page turns yellow at 80% of the day's limit and starts no meeting and no
  retry at 100%. A failed speaker is never retried by itself: you can retry it twice through its own small preview, and
  a third failure blocks it. When the console restarts, the call that was running is interrupted and nothing resumes.
  When this Claude Code version has not passed the check, the preview offers 先做無工具安全檢查, asked in the page first:
  it is the translations' check and is kept in the same record, but always of Claude Code, whichever engine the
  translations use. Each meeting is one file in `meetings/` in VBear's state folder; a meeting writes no task card, no
  flow and nothing in a project folder.
- **The office has a meeting room and a chairman's desk, and the home page lists the meetings that wait for you.** The
  office's 會議室 shows the newest meeting that is running or waiting for you (the others as 還有 N 場): each participant
  at the table, drawn by its card's tool, with the words over it taken only from the meeting's record through a closed
  list (等發言, 發言中, 支持, 反對, 有條件支持, 要更多資訊, 失敗, …; for the CEO 整理意見中, 已決定, 交董事長), and a
  spoken-for card marked 代發言. The 董事長桌 under it counts the meetings waiting for your approval and has 去核准. The home
  page's 輪到你 lists those meetings (輪到你：董事長核准), and a task card in the workbench lists its own meetings. A meeting
  record that cannot be read is said so, never taken for no meeting.
- **The card wizard's profession is now a picker you can read and use.** It moved out of 進階 to step 2, under the
  suggested position, as one line (目前：…) that opens into a search, buttons for the position each role probably fits,
  and a list. It lists only your card's own tool (a Claude Code card no longer lists Codex roles) and no longer lists the
  two "main agent" entries, which were the tools themselves, not professions. Every name shows in Chinese beside the
  English once translated, with 待翻 on the ones that are not, and each row has one line of what the role does: the
  translated sentence (marked 機器翻譯), or the author's first 60 characters (marked 原文), plus a position guess made
  from the name or the first sentence of the description (marked as a guess; the roles it cannot place sit in 其他).
  Choosing a role shows what it brings and each item is one click: its guessed position (put on the card only when the
  card has none, otherwise offered as a button), the skills the template names that your card's tool can read (一起插上,
  seen in step 3), and the model it names (套用模型). Choosing only labels the card: launching still does not load the
  role's instructions. When names are still English, the open picker says so and offers 把職業名稱翻成中文; it asks
  before anything is sent, and when the first translation needs the one-time safety check it offers 先檢查 there (also
  asking first). 先不翻 folds the prompt into one small button. A label the card already holds from another tool, from
  the tool itself, or from a role the index no longer finds stays, with the reason and a 解除 button; nothing is cleared
  for you. Roles of a plugin that is switched off are behind 也顯示用不到的. The back of a card calls the row 職業 and adds
  the one Chinese sentence. VBear's own two main-agent names are no longer sent for translation. The choice is still
  saved as the role id.
- **Switching a card off or on no longer clears its profession.** The 停用／啟用 button on the 角色 tab of the terminal
  workbench sends only the new on/off state, and the save treated the missing profession as "none", so the card lost
  its profession. A save that leaves out the profession now keeps the stored one; sending `null` or an empty value still
  clears it, and the card wizard and the starter deck send the same data as before.
- **Skill descriptions that are cut short on a card can now be read whole.** Rest the pointer on a skill card (in the
  skill library, the four-state overview and step 3 of the card wizard) or on the description in the skills table, or
  move to it with the Tab key, and a small box opens with the full text: the whole Chinese description, when to use it
  and what it needs if the author said so, a line that it is a machine translation, and the original underneath; a
  skill that has no translation shows its whole original. A long text scrolls inside the box, you can move the pointer
  into it, and it moves out of the way of the window edge. Esc, moving away, or leaving the card closes it, and it never
  takes the keyboard focus or covers the card. The cards keep their short line, and 看完整說明 in the wizard is still
  there for touch screens. To make this possible the card wizard is now sent up to 2000 characters of a skill's
  original description (it was 140); nothing is sent anywhere else.
- **Going back to v0.8.9.** v0.8.9 reads what this version wrote. It reads the role card file and leaves the new fields
  `position`, `instructions` and `launch_mode` on every card it does not touch, but saving or copying a card there
  writes that card without them. It has no full mode: a card made for it is started there with v0.8.9's sandboxed launch
  (which starts Claude Code cards only). The page there shows the position this browser remembers, and only the three
  positions it knows (CEO, 全端工程師 and 獨立審查, which it calls 規劃, 執行 and 審查); any other reads as not specified.
  The skill index is rebuilt once each way (its version is 3 here and 2 there), and the two new skill categories are not
  there. The `meetings/` folder and the `meeting_limits` in `config.json` are left as they are and not used, so coming
  back finds them again. A flow approved here keeps the plan it saved in `plan.txt`, instructions included, and
  `translation-boundaries.json` is the same file both ways, so a version checked for meetings counts for translations
  there too.

## v0.8.9 — skills by use, role names in Chinese, a model menu

- **The profession menu in the card wizard can show the role names in Chinese.** Under 進階 → 職業標籤, a new button,
  「把職業名稱翻成中文（N 個未翻）」, translates the role names (Brand Guardian, Trend Researcher, …) on your own
  Claude account, usually under 1 US cent each, after a confirmation that says what is sent: only each role's name and
  the description its author wrote. Translated entries read 中文名稱（English name）・Claude Code, untranslated ones
  stay as they were, and the same Chinese name (with the English in brackets) is used on the back of a role card, on the
  role cards in the card pool and on the role page. The Chinese names are a machine translation and the menu says so.
  Nothing is translated unless you press the button, and the skill translations are not changed.
- **The model box in the card wizard is now a drop-down.** For a Claude Code or Codex card, step 2 (進階) lets you pick
  the model instead of typing it: 工具預設 (leave it to the tool), then for Claude the aliases `fable`, `opus`,
  `sonnet` and `haiku` (an alias always means the newest version, so it needs no update), then the full names VBear
  has seen in your own Claude Code usage. For Codex it lists the models Codex itself lists, taken from the cache Codex
  keeps, so it is only as fresh as the last time you opened Codex. 其他（自己輸入）… still lets you type any name, and a
  card that already holds a name not in the list keeps it. Antigravity and shared cards keep the text box. What is
  saved is the same text as before. VBear reads only each model's name from Codex's cache (never its other fields),
  runs no program and uses no network for this.

- **Step 3 of the card wizard sorts the skills by use.** Above the skill cards there is now a row of categories with
  how many skills each has, such as 設計與介面, 寫作與內容, 測試與審查 and AI 與代理, plus 全部 and 其他 (skills in no
  category). Pick one to see only those skills; it works together with the search box. These are the categories VBear
  already gives skills from words in their text, the same as in the skill library, so a skill can be in more than one
  and the sorting can be rough. Only categories the list has are shown, and which skills a card can take is unchanged.

## v0.8.8 — skill cards you can read in Chinese

- **A translated skill card in the card wizard reads whole, in Chinese.** The card used to show the first sentence of
  the long Chinese text, cut off after two lines with "…", and the fold beside it, 看原文, only held the English. The
  card now shows the translation's short "what it does" in full (50 characters at most, never cut) and, when the
  author said it, a line 「什麼時候用：…」. The fold is now 看完整說明: the whole Chinese text first, then the original.
  The search box also looks at the Chinese, so typing Chinese finds a translated skill. Cards without a translation
  are as before.

## v0.8.7 — the app finds Claude Code; delete works

- **The VBear app now finds Claude Code and Codex installed in your home folder's `.local/bin`.** Claude Code's own
  installer puts `claude` there, but an app started from Finder does not see your terminal's search path, so VBear
  could not find it. The translation check then wrongly said the safety boundary was "not verified", and the version
  check before a Claude Code launch could miss it the same way. VBear now also looks in `.local/bin` (after Homebrew
  and the system folders, never ahead of them), and nowhere else. If `claude` still cannot be found, the translation check now says
  so plainly ("找不到 Claude Code …") instead of blaming the boundary. "Not verified" appears only when the check
  really did not pass. No safety check was relaxed: finding the file does not verify it.

- **The small skill cards in step 3 of the card wizard read in one glance.** Each card is now three parts: the
  name, one small row of tags, and the description (still two lines). Before, every tag sat on a line of its own and
  a card was a stack of five or six short lines. Tags that told nothing are gone: "AGY reads it" (every skill an AGY
  card lists is read by AGY), the camp tag on a skill of the card's own camp (a Claude Code skill on a Claude Code
  card), and the "machine translation" badge on every card. A shared skill says "shared" on the other camps' cards, a
  skill from another camp says which one (for example "Codex" on an AGY card), and the row also holds the plain
  reason a skill is greyed or marked, "N more with this name" and "out of date". When some listed description is a
  machine translation, one line above the list says so and points to "see the original"; the library and the skill
  page keep their own translation badge. Long names still wrap instead of being cut, and picking, taking off, the
  keyboard and the greyed cards work as before.

- **The delete buttons on role cards and task cards now work in the app window.** They used the browser's own yes/no
  box, which the app window never shows, so pressing 刪除 did nothing there. They now ask in the page, like the other
  confirmations: a box titled 刪除角色卡 or 刪除任務卡 that names the card and says it cannot be undone. 取消 or closing
  the box sends nothing; 刪除 deletes the card as before. No other place used the browser's own boxes, and a test now
  keeps it that way.

## v0.8.6 — skill cards you can read

- **Small tidy-ups from the last two reviews.** In the card wizard's second step the four camp buttons now line up
  by the room they have: four in a row if they all fit, two by two otherwise, one under another on a narrow screen,
  and never three and one (the other button rows are unchanged). The launch pass of an Antigravity (AGY) card says
  once that VBear does not start AGY; the line beside the off start button now only points up to it. In the settings
  list, the AGY config file's row no longer repeats its own name at the front of each problem; the overview's problem
  list keeps the name, since it has no row title above it. How the file is read, and what it refuses, is unchanged.

- **Step 3 of the card wizard, the skill cards, is now readable.** The step opens with a few plain sentences: a skill
  card is a work note written for an AI (how to make slides, how to handle a PDF); inserting one only records what the
  role is good at, so the team looks divided when you build it; VBear does not load these skills when a role departs
  yet; and the step can be skipped. The list now shows only what the card's camp really uses: a Claude Code or Codex
  card lists that tool's active skills plus the shared ones, an AGY card what AGY reads, a shared card the shared skills.
  Skills of other camps, old cached versions, copies in a plugin marketplace that is not installed, disabled ones and
  ones a plugin ships but the tool does not load are behind a switch, "also show the skills that cannot be used (N)";
  with it on they are greyed or marked in plain words. Copies of one skill with the same name are listed once, with
  "N more with this name" on it. A skill already inserted stays under "inserted" with its reason even if the list
  hides it. Search looks only at what is shown, and says how many matches wait behind the switch. Which skills a card
  can take is unchanged, and so are the skill overview, the skill card page and the launch pass.

## v0.8.5 — the skills AGY reads

- **An AGY card can now hold the skills AGY actually reads.** VBear used to say it did not know which skills
  Antigravity (AGY) reads and let an AGY card hold only shared skill cards. It now works it out from files on your
  Mac, without running AGY: a project's `.agents/skills`, `~/.gemini/antigravity-cli/skills`, and the folders listed in
  `~/.gemini/config/skills.json` (only the skills directly in a folder, or the ones its `include_only` names). Skills
  VBear already knew are marked as read by AGY instead of being copied; a folder it did not scan becomes an AGY source in
  the settings list. In the card wizard those skills can be inserted and the rest are greyed with
  「AGY 不會讀這張技能卡（依這台電腦的 AGY 設定）」. The shared store `~/.agents/skills` is not AGY's unless that file
  lists it. A card saved earlier with a shared skill keeps it and shows 「AGY 不會讀」 on it, for you to take off or
  keep. It stays a collection (VBear does not start AGY), AGY's built-in and plugin skills are not covered, and only
  that one config file under `~/.gemini` is opened; a missing or unusable file is skipped and shown in the settings
  list. Claude Code, Codex and shared cards are unchanged.
- **No false launch warning on AGY and shared cards.** In the card wizard's second step, an Antigravity (AGY) card or a
  共用 card set to something like 「編輯寫入・拒絕」 no longer shows 「這個組合目前不能出發」. VBear never starts those
  cards, so the warning was noise; their permission intents stay what they always were, a record for building teams.
  A shared card now says so beside the camp row (「共用卡不能出發，權限意圖只是分工記錄。」), and the AGY card keeps its
  existing sentence. Switching the camp updates the step at once: from AGY back to Claude Code the warning returns when
  the combination cannot be launched. Claude Code and Codex cards, the launch pass and the server's launch checks are
  unchanged.

## v0.8.4 — an Antigravity (AGY) camp

**Role cards can be Antigravity (AGY) cards.** The card wizard's 「陣營」 row, and the card editor, now offer
Antigravity（AGY） beside Claude Code, Codex CLI and 共用. VBear does not start Antigravity (and does not yet know how
to), so an AGY card is a record for building teams, and the app says so in plain words wherever it matters.

- **The card.** An AGY card is the fox in the Google colours. Its model family is always Google, in the page and on the
  server alike: put on a task card's review place beside a Claude Code or Codex executor it counts as an independent
  review, and beside an executor written by hand as Google (Gemini), or beside another AGY card, it turns red with
  the usual reason. A flow that holds an AGY card with any other family is refused.
- **No launch.** 出發 on an AGY card opens a pass that says 「VBear 還不會啟動 AGY，這張卡目前只用來排隊伍與記錄」, with no
  preview, no start button, no shield and no limits listed; the card's light says the same. The server refuses to
  prepare a launch for it, and a team place or the next-steps list offers no 出發 for an AGY card.
- **Skill cards and role labels.** VBear does not know which skills AGY reads, so no skill is shown as one it would
  load. An AGY card can hold shared skill cards, as a collection only; every other skill card is greyed with
  「VBear 還不知道 AGY 會讀哪些技能」. VBear scans no Agent role of Antigravity, so there is no role label to pick, and a
  Claude Code or Codex one does not stand in for it.
- **Automatic mode is unchanged.** The automatic review is still the Codex that VBear starts, and it is recorded as
  that. An AGY card on a review place is a record of who reviews by hand; it is never described as the automatic reviewer.
- **Nothing existing changed.** Role cards and flows already stored read back as before, and any other tool name
  (`gemini`, `antigravity`, `AGY`) is still refused.

## v0.8.3 — keyboard focus and plain-language terminal errors

Two small interface fixes.

- **The keyboard stays inside the skill card window.** The window put the focus on 返回, then drew its buttons again
  once the skill had loaded, and the focus fell to the page: Esc did not close it and Tab started from the top of the
  page. The focus now ends up on 返回 after the load (also when the load fails), unless you had already moved it
  somewhere else in the window. A window you closed while it was still loading is left alone: nothing is drawn into it
  and the focus does not move. Closing returns the focus to the button that opened the window; when that button is
  gone (taking a skill off a role card redraws the card) it goes to the main region of the page instead of the top.
  The same fault is fixed where it was found elsewhere: taking a skill off the card with its 移除 button in the card
  wizard, and choosing a task card or a place in the 放上任務卡 window, no longer drop the focus when the list is drawn again.
- **Terminal, takeover and handoff failures are said in plain words.** When a takeover, 改成只觀看, typing, closing a
  terminal, opening a terminal, the stream, a handoff, or recording a terminal on a task card fails, the page used to
  print what the server or the runtime had answered (`目前沒有這個 Terminal`, `內部錯誤：TypeError`, `HTTP 502`, the
  reason a closed terminal's scratch was kept). It now says what happened and what to do next in a sentence of its own
  (for example 這個終端已經不存在了（可能已關閉）。要繼續的話，請重新開啟一個終端。). An answer the page does not know gets
  only a general sentence such as 沒能接手這個終端。 and no guess at the cause. The original is always kept: behind 「技術細節」
  in a notice (the takeover reminder now shows its failure inside the dialog, where it stays), and in brackets after the
  sentence in a toast (`（原文：…）`). The words are one table, shared with the line under a closed terminal. What the server
  and the runtime send, and their codes, are unchanged. A terminal that could not be recorded on its task card now says so
  in a sentence and puts the original at the end of the message.

## v0.8.2 — hardening and a dark icon

Hardening that follows the first security review of v0.8.1. It found no confirmed vulnerability; these two changes make
the code do what the documents already say. The entries after them are small interface changes.

- **Skill secrets under a name with no value are masked.** A secret-looking name whose line ends at the colon
  (`tokens:`, `api_key:`, `credentials:`) now masks the more deeply indented lines below it: a list, a value on the next
  line, a nested mapping, as a `|` block already did. It stops at the next line that is as shallow as the name. The same holds when the name's line carries only a comment,
  an opening bracket, a block header such as `|2` or `>-`, or a tag or anchor (`!vault |`, `&k`). A name
  that only describes a secret (`max_tokens`, `api_key_env`) keeps its harmless values visible, as before. Text such as
  `Passwords:` followed by an indented explanation is masked as well; masking more was chosen over missing a value. This
  applies to the raw SKILL.md and the referenced files in the skill details.
- **A managed launch's work directory follows the folder chooser's list.** The home directory itself, `~/.ssh`,
  `~/.gnupg`, `~/.aws`, `~/.config`, `~/.vbear`, `~/.claude`, `~/.codex`, `~/.gemini`, `~/Library`, the state directory
  and anything below them are refused as a work directory when a launch is previewed, prepared and again just before it
  starts. Names are compared without regard to case and symlinks are resolved first, so `~/.SSH` and a link that points
  at `~/.ssh` are refused too; the earlier protected places (`/tmp`, the scratch parent, `~/.claude`, `~/.codex`) are
  compared the same way. The refusal comes before the check that the folder exists and reads the same either way
  (`invalid_workdir`; the preview shows it as a reason the launch cannot start).
  **Behaviour change:** a work directory under `~/Library` (for example iCloud Drive's `~/Library/Mobile Documents`) or
  `~/.config`, which the folder chooser has always refused, is now refused for managed launches as well.
- **A skill can be taken off a role card from its back again.** The back of a role card now lists the skill cards on it,
  each with a 技能卡特性 button. Opened from there, the skill card window offers 從這個角色移除 (with the usual
  confirmation) and the card redraws by itself afterwards. This works in the card pool, the workbench's role tab and the
  office roster; sample cards and the armory's view stay read-only. A skill the index can no longer find is listed
  without a button and points to editing the card.
- **The small bear's plate has a visible edge in the light theme.** Its cream plate was almost the colour of the light
  sidebar. In the light theme the mark now has a one-pixel edge in a muted tan that follows the plate's stepped corners;
  the dark theme looks exactly as before. It follows VBear's own light/dark setting, whether chosen or following the
  system. The edge is drawn on the page only: the favicon is unchanged.
- **On macOS 26 and later the app icon follows light and dark mode.** The Dock and Finder show a dark plate with the
  bear outlined in cream in dark mode and the cream plate in light mode. The icon is now an Icon Composer `.icon`
  (`macos/AppIcon.icon`, compiled by `actool` into `Assets.car`), so macOS draws the plate itself: its rounded shape,
  edge and finish differ a little from the old hand-drawn plate, and the small sizes are scaled down from the large
  bear rather than drawn on their own 16 x 16 grid. Older macOS versions keep `AppIcon.icns`, unchanged, byte for byte.
  The build skips `Assets.car` when Xcode is not installed (and says so); the release workflow fails if the app has no
  `Assets.car` with both appearances.

## v0.8.1 — pixel black bear

- **New logo: a pixel Formosan black bear with a white V on its chest.** The app icon, the browser tab icon, the mark at
  the top left of the page and the banner at the top of both READMEs (the bear wears a headset there, and a dark version
  is shown on GitHub's dark theme) are all new. The icons are drawn cell by cell, so they stay sharp: the page mark is
  `web/logo.svg`, the tab icon `web/favicon.svg`, and the app icon is drawn by `macos/make_icon.swift` from the pixels in
  `macos/AppIcon.pixels.json` (the 16 and 32 pixel sizes use a simpler 16 x 16 bear). No behaviour changes.

## v0.8.0 — launch and hand over

- The import-a-project window: the list of projects VBear has seen (and the recent folders) now fades at its bottom
  edge and says 「共 N 個，往下捲動看更多」 while rows are hidden below it, so a cut-off last row no longer looks like
  the end of the list. The note for a folder without git no longer ends a full-width bracket right before a full stop,
  which read like a stray space; the same was done to a few other sentences on the main paths.

**After a start, and picking a task up.** A start from a task card now stays in the workbench: the new terminal sits
beside the same task card, and the terminal is noted on the card (a tracking record, nothing is sent into it; if you
changed the folder, or the note could not be saved, the page says so). A terminal this tab has just started from a launch
pass can be typed into at once, with one line saying so and a 「改成只觀看」 button; the right to type is held only in memory,
is used once, and lapses after two minutes, so a reload or a link never gets it. Taking over a terminal that is already
running now opens a 「接手提醒」: the task card linked to it and its next step, the agent's state as VBear can read it, whether
the card's flow waits for you, and three fixed lines; the focus starts on 「取消」. A task card made by a handoff shows a
「接手提醒」 at its top with the earlier card, its written note and its last state, and nothing the page does not know.

- **Workbench.** With no terminal open the task card is the page and one line says so, instead of an empty black area. The
  four-column 「狀態依據」 block and the project and global rules sit behind a folded 「進階（工程資訊）」. The card's top shows the
  flow's current gate, and the old mark (「草稿」) becomes small text. The 「角色」 tab shows the same two-sided role card as
  the card pool, and the office's 「打開角色卡」 opens that card in the card pool. Skill words say one thing: 「收藏在角色卡上」
  and 「出發時不會載入」 (a recorded pick, not a broken skill).
- **The next step's own buttons.** When it is your turn, the 「下一步」 box holds the button: 「核准計畫」 (a manual record,
  behind a confirmation) and 「核准計畫並開啟自動執行…」 (the same approval window as before); when it is your turn to merge or
  upload there is a sentence, not a button. The launch pass fetches its preview when the commit sentence is ticked (and
  fetches it on opening when that was ticked already); it never ticks it for you and the focus never lands on 「確認啟動」.
- **Plain words.** The flow and terminal pages say 版本 (commit), 執行階段, 上傳到遠端 and 只能觀看／你正在操作 instead of session,
  HEAD, push, Observe and Control; the technical values stay in small brackets, and the plan hash is still in the approval
  window. Flow phase names follow (「等你上傳」). Two cards or flows with the same title also show their folder and day; the
  common English skill categories show in Chinese (the filter values do not change). A terminal page's back button says
  where it goes (「回角色卡池」, and 「回任務卡」 for a terminal linked to a card). The home page no longer puts the cursor in the
  skill search.
- **Card feel.** The shields have new art with the same three meanings (solid, dashed, empty with a slash; partly blocked,
  untested and unknown still get none). Team places that hold a role card take the card's camp colour and the place's badge
  (規／執／審); the pool below the places is a row of small cards. Skill cards are chips with a cut corner and a band in the
  tool's colour. The starter deck and task cards have card frames; a task card has a header and three lights (規→執→審)
  that come only from the flow's real phase and are empty when there is none. The office has a small prop beside each
  station's title and a wooden strip under each desk character. Putting a card on a task card keeps you in the card pool
  and asks whether to fill another place.
- **Dark theme and small fixes.** The office outline, the deep red rule, the warning text and the solid shield now pass the
  contrast bar in the dark theme; the robot's eyes follow the camp instead of one blue; 「執行觀察」 is no longer said twice;
  the draft card's long explanation is one line with 「這是什麼」 for the rest (the meaning is kept: a mark, not a count of
  work); a role card's back says 「往下捲動看更多」 when it scrolls.
- **Last small fixes.** The launch pass no longer says 「S0 驗收」 (it now says the mode was tested to be able to write to your
  home folder, which is the same fact); 「輪到你」 has no stray space; a task card's template badge says 「自訂」 and so on
  instead of the stored key; a terminal that is gone says so in plain words, with the runtime's own sentence kept under
  「技術細節」; and on a narrow screen a long skill name no longer pushes the ⓘ out of its card.
- **Docs.** The README screenshots (both languages) were retaken for this state, mostly in the light theme and two in the
  dark theme, with new ones for the workbench task card, a handoff, a terminal just opened, the takeover reminder and the
  skills library.
- **Card back pattern.** The pattern along the top of a role card's back is now a tidy row of small crosses on a clear
  ground (「角色卡背面花紋改成整齊的小十字」), where it used to look like noise; it is drawn a little stronger so it still shows on
  every camp's card in both themes.


## v0.7.0 — card play

A first-time user can now build a team in three card moves, with no form to fill in: **collect** role cards (or take
the starter deck), **equip** skill cards, and **play** a card onto a task card's team place, then set out. A task card
is one folder, and an existing project can be brought in and managed.

**Words.** 「Agent 團隊」 is now 「角色卡池」; a profile is a 「角色卡」, chosen skills are 「技能卡」 in slots
(dashed 「收藏中」, solid 「生效中」 only when the loadout says a skill really loads, which no launch does today),
the tool is the 「陣營」, permission intents have Chinese labels and say they are a record, not a grant.

- **Card pool and wizard.** A card-pool page with a starter deck of three (CEO, 工匠, 審查員; the reviewer is left
  unticked when Codex is not installed), a three-step wizard (name and look, tool and place, skill cards) whose
  bottom buttons stay in view on a phone, suggested permission intents marked 「建議，可改」, and a same-name hint that
  never blocks. `GET /api/agent-builder/catalog` carries the deck, positions, `verified_intents` and
  `codex_installed`. All three starter cards (and the wizard's suggestions, with or without a place) carry the one
  combination a managed launch honours, so none of them is stopped by its own intents; the wizard says why the
  suggestions are all alike and, for a combination you change to, asks `GET /api/agent-builder/intent-check` and shows
  the server's reasons on the spot.
- **Codex cards.** A Codex card whose only reasons are `codex_` ones (it cannot open a terminal, but the flow's
  automatic review can use it) shows a neutral light, 「不能直接開終端」, not the red 「目前不能出發」.
- **Card art v3.** Position badges are a hard square with one character (規／執／審／？), the shields are flat-topped
  and pointed (filled, dashed, slashed), the folder and import icons are redrawn and used on the import dialog.
- **Role card.** Two faces (front: avatar, place, slots, a light that says why a launch is or is not possible; back:
  tool and model, permission intents with 「只是記錄，不是授權」, evidence, advanced). Flip with the button or F; no
  animation under reduced motion; the hidden face is `aria-hidden`. The office panel uses the same card.
  `loadout` skill rows now carry `will_load` and the block carries `all_inactive`; the page decides dashed or solid
  from that field and never from text.
- **Task card = folder; bring in a project.** 「＋ 任務卡（導入專案）」 picks a folder from the projects VBear saw, the
  recent folders or a pasted path (the app window also has a native chooser, `vbearPickFolder`, restricted to the main
  frame of the console's own origin, one panel at a time). New: `GET /api/folders/inspect`, read-only (a few
  `stat`s and the repository's HEAD, no git process, no walk), refusing the home directory itself and sensitive
  places (`~/.ssh`, `~/.gnupg`, `~/.aws`, `~/.config`, `~/.vbear`, `~/.claude`, `~/.codex`, `~/.gemini`, `~/Library`,
  and symlinks into them) with the same answer whether or not they exist. A folder that is not a git repository is
  said so plainly: reviews tied to a commit will not count there. Config gets `recent_folders` (at most 10) and
  `onboarding_dismissed`. A card's front names the folder, branch and HEAD, and counts the terminals whose working
  directory is in it, without saying which role card opened them.
- **Teams on a task card.** Team places (規劃位, 執行位, 審查位, an optional second review) filled by clicking, dragging
  or 「放上任務卡」. A review place that would not count turns red at once with the reason (`slotProblem`); an empty
  second place is not sent; errors show on the place. Flow roles can carry `profile_id` and a strict
  `profile_snapshot` (`name`, `tool`, `model_id`, `revision`), and the page says when a card changed after it was
  placed. `profile_digest` moved to `agent_profiles.py` with an unchanged value. A 「下一步」 list says whose turn each
  step is.
- **Launch pass (出發通行證).** The pre-launch check is now a pass. Its front has three lines: where it can write,
  whether the network is blocked, and always 「擋不住版本紀錄（commit）」. Each line is worded by the level the preview
  gives it; a check mark is drawn only for an enforced level, and partly blocked, untested and unknown items say so
  in words. A shield legend (solid, dashed, empty; shape, not only colour) explains the shields. The seven labels sit
  behind 「看七項細節」, unchanged. The commit acknowledgement is written out in plain words. Each reason that stops a
  launch has a button next to it (decide the intents, change the folder, tick the box), and fixing it returns to the
  same pass with a new preview. Server wording that said Profile follows the new name.
- **The first game and the board.** The home page starts with 「新手第一局」 (get role cards, bring in a project, put the
  team on it), each step ticked from real data, folded to one line when done, dismissable and restorable in
  settings. Flow cards on the board show their team and whose turn the next step is.
- **Phone menu.** At 720px and narrower the navigation folds behind one button that names the current page.
- **Skill translation.** The confirmation is one sentence (your own account, usually under one US cent) with the
  whole budget and timeout text behind 「詳細」. The progress bar folds away: success after 5 seconds, failure after
  10 seconds into a dot at the lower right that reopens the reason, a close button on each. A failure is also shown
  on the skill card the job was started from, with 「重試」 and 「原因」.
- **Opening with a login code.** `#auth=` is now traded for the session before anything else asks the server: the
  translation poll, hash changes and tab focus wait, and a 401 met in that moment no longer puts up 「請從 VBear 開啟」.
  The router no longer keeps polling after the login page is shown.
- **Closing fixes (P7).** The import box says how to get a folder's path (Finder: right-click, hold Option, copy as
  pathname) when no project or recent folder is listed, 「檢查」 is the main button and Enter or a pasted absolute path
  checks once (read-only). The next step on a task card has a button, 「讓 X 出發」, that goes through the same launch
  pass as a place's own 出發 button; in manual mode a sentence says VBear will not move the flow on and where to record
  the step, and after a launch from a place the card says 「已開啟 N 個終端」 from VBear's own launch result only (never
  which terminal belongs to which card). A skill's page says 收藏中（這次出發不載入）, like the card, and keeps 啟用／已停用
  for the card itself; weapons explain 鎖住; the intents are 「權限意圖（分工記號）」. Without a terminal chosen, the
  tracking box no longer says it is linked. 「工作中」 is only used for the working status ("N open terminals" elsewhere);
  the English words Terminal, Session, Armory, Context and Status Provenance are gone from the screens. The phone
  workbench opens at the task card and its team when you come from a task card, and 「右欄」 is 「任務與隊伍」. The same
  card cannot review itself. The pass words its commit note by the folder (no `.git` in it: it says so; a `.git`: it
  says that one is writable; `derive_labels` does one `lstat` for this), and a card's back, which has no folder, says
  「工作目錄內若有 .git」 instead of claiming one, names the field 「在哪裡做（工作資料夾）」, and says 「出發後 VBear
  暫時看不出它在忙還是在等你」 for an unverified Claude Code. `GET /api/live` also carries `managed_root`, the folder
  a launch may work in, and the pass's range hint is made from it. A role card's front has one line from its armor
  data (「出發後可以改檔案；擋不住 commit；詳情看出發通行證」, never more hopeful than the pass). The skill picker shows the
  Chinese 「what it does」 (marked 機器翻譯 or 過期) with the original behind 「看原文」. On the home page, 「到終端工作台」
  is a plain button while the first game is on. `VBEAR_QA_FRESH=1` no longer carries the HTML probe skill.
- **QA and tests.** The QA console gained `VBEAR_QA_FRESH=1` and `VBEAR_QA_TRANSLATE=fail`; the fake translation CLI
  follows the structured-output change. New tests cover the folder API, the config keys, flow role cards, `will_load`,
  the starter deck, the pass table level by level, the team places and the first game.
- **Docs: README screenshots retaken.** Both READMEs now show v0.7.0 (demo data): the home page and the fresh-install home, the card pool (front and back, the starter deck, the light theme), task cards and the project import, a flow's team places, the launch pass (the three-line front and 「看七項細節」), a skill card, and the office with its stage panel. Four older pictures (`role-card*.png`, `preflight-check.png`) are gone; the captions say only what a picture shows, and the status line reads v0.7.
- Add an opt-in macOS browser startup mode, an open-in-browser menu command, and an Option-key escape to
  window mode. Failed or timed-out browser launches fall back to the window with an error message.
- Isolate macOS smoke tests by port and process ID, and add optional browser startup/reuse acceptance.

## v0.6.0 — Chinese skill summaries

Skill descriptions can show Chinese machine translations and summaries alongside the author's original text.
Source fingerprints identify changes to the original text, and stale translations are marked; automatic
retranslation is off by default. Translation runs only after the installed Claude Code version passes a check that its translation run
offers no tool but StructuredOutput and no MCP server; the Codex translation engine is disabled.

- Add a guarded skill-translation candidate: redacted author-field fingerprints, a bounded atomic cache,
  stale/orphan states, sequential cancellable jobs, and consent-bound automatic work after explicit rescans.
- Add Chinese summaries and author-original toggles to skill cards/details, translated library search,
  cost/quota disclosures, global progress, settings and two-step orphan cleanup.
- Add fake-only translation tests and `VBEAR_QA_TRANSLATE=1` to the isolated QA console. Production CLI
  providers remain blocked until the exact no-tools boundary has version-specific evidence. No real model
  was called; existing launch and dispatch behaviour is unchanged.

## v0.5.0 — quest board and pixel office

The home page is now the quest board, 冒險者大廳, with flows and agents that need your attention and other open
tasks. The pixel office, `#/office`, places teams by their task phase, live terminals at desks and saved profiles
in the lounge. Characters have persona lines with evidence labels and expandable reasons; a station describes
task location. Safe-mode launches were tested on Claude Code 2.1.299: VBear's flags left user and project skills
unlisted and offered only Bash, so a profile's skill list remains a record of your picks.

- **Embodied office characters.** New supplied pixel art and camp colors, two-frame typing only for working
  desk sessions, and reduced-motion support. Panels add fixed persona lines with evidence labels and expandable
  reasons, plus a responsive SVG character stage with a status monitor and a locally saved collapse preference.
  Team and roster characters remain static; their monitors describe task location and roster membership.
  Waiting lines distinguish terminal-title and background-stream evidence; review lines describe the recorded
  phase without claiming that a review process is running.

- **A pixel office, `#/office`.** A new page after 冒險者大廳 in the menu. Four workstations (計畫板, 實作區,
  審查室, 合併關卡) hold the flows' teams by their phase (at most 3 per station, then 「這站還有 N 隊」; a team that
  waits for you is taken first); each live terminal sits at a desk with its state in words over the character
  (an ended one has none); the saved profiles stay in the lounge (at most 24, then a link). A station says only
  where the task is, never what an agent is doing. The red (#DA251D) is used only for 「輪到你」, and always with
  words. Click a character for its panel: weapons (the tools a launch offers), armor with solid frames for
  enforced and dashed for the rest, and its skill cards (a skill the index cannot find says so with the index
  time). A flow's team has no gear panel (flow roles record only a name and a model family) and a session's gear is
  unknown. Species (bear, fox, robot, alien) follows the tool or the model family; you can change a profile's
  species (kept in the browser). On a phone it is a list, not a scene. It reads only what the flows, live and
  profile APIs already return. The one backend change: `GET /api/agent-profiles/<id>/loadout` has a read-only
  `tools` object, taken from the same two constants the Claude argv is built from (`Bash`; `Edit,Write`), so the
  argv text is unchanged and a test locks it. The characters are original pixel art, inspired by Pixel-Crew
  (MIT) but using none of its art or code. `tests/qa_game_ui.py` has `VBEAR_QA_OFFICE=1` and `=stress`.
- **The home page is the quest board, 冒險者大廳.** 「我的工作台」 (the home page and the first menu item) is now
  冒險者大廳. Its first block, 「需要你處理」, became two blocks: 「輪到你」 (the flows the server marks as needing
  you, a stale review of a manual or stopped flow, and the agents that wait for your reply) and
  「其他進行中的任務」 (the other open flows, at most 4, then 「還有 N 則」 to the flows page). A flow card is one
  card with one link: the title, stretched over the card; its type label is the phase's own words and its
  frame is drawn with words beside it, so colour is never the only sign. A finished flow is never on the board.
  Manual flows say that VBear will not move them for you. It reads only what the flows and live APIs already
  return: no new API, no change to launches, dispatch or the state files. A failed flows read says so in both
  blocks and is never drawn as 「沒有任務」; with nothing at all, the board becomes a first-run block that points to
  the terminal workbench. It repaints on the 5-second refresh only when a shown field changed, so the search box
  keeps its focus. The other pages' flow and agent cards are unchanged. `tests/qa_game_ui.py` has
  `VBEAR_QA_LOBBY=1` (more flows) and `VBEAR_QA_LOBBY=empty` for it.
- **Safe-mode launches tested on Claude Code 2.1.299.** In a throwaway project with a project-level skill, a launch
  with VBear's flags listed none of the user's or the project's skills (a plain launch did), and its only tool was
  Bash, so there is no Skill tool to call even a built-in skill. The READMEs say so; the skill list of a profile
  is still only a record of your picks.
- **README: a picture of the home page.** `docs/images/lobby.png` (demo data).

## v0.4.0 — game-style screens

The READMEs were rewritten for first-time readers around a game-style vocabulary (character, class, skill card,
armor, party, gates, stamina), with screenshots of demo data. The role card, the skill card, the pre-launch check
and a flow's 任務進度 / 隊伍 / 體力 follow that vocabulary, and a flow's phase now also reads automatic mode's own
events. The README says what to do after Claude Code updates itself (the new version shows *unknown* until you
verify it), and the Codex review token figures from v0.3.0 (see below) are unchanged. A role VBear launches runs in
Claude Code's safe mode, so a role's skill list is only a record of your picks, not something a launch loads.

- **Game-style role card, skill card and pre-launch check.** The workbench's right tab 「角色」 shows a profile as a
  card: its role (a label), its chosen skills (each marked as not loaded by a launch, with the author's text and
  where it came from) and its armor in five groups with the original level words; the same skill card opens from
  the Armory. 「預覽並啟動」 is now 「出發前檢查」: the same one-time preview and confirmation, with the seven labels in
  the same five groups, the list of chosen skills marked 「本次不會載入」, and a reason beside the button while it is
  off. New read-only answers: `GET /api/agent-profiles/<id>/loadout` and `GET /api/skills/<id>?view=card`
  (from what is already loaded; nothing is scanned or started). Names on the screens changed; see the README.
  A flow's page shows 任務進度 as a row of gates (by the phase VBear already derives), 隊伍 as cards (the planner
  marked as only a record; each reviewer says whether it counts as independent of the executor), and 體力 as
  bars with the words: the executor's cost is split into what the CLI recorded and what is counted for turns
  without a result, with 「實際費用尚未知」; a figure that cannot be counted is not drawn as zero.
- **A flow's phase now follows automatic mode's own events.** The phase (and so 任務進度) was read only from the
  events entered by hand, so a flow that only the runner moved stayed at 「計畫中」 even after it had been
  reviewed. It now also reads the runner's events: turning automatic mode on counts as the plan's approval, a
  sent dispatch as the start of work, a verified report as the executor's report, and a valid review result as
  a review. The same fact recorded by hand and by the runner is one round and one review, not two (a report of the
  same commit after a review of it is a new round, whoever made the first); the last event on the timeline
  wins. An automatic result counts once, only for the job and round the runner started,
  and a repeated dispatch or job is ignored with a warning on the page. This changes only what the page derives
  and shows: nothing is written, and the merge gate and the 「需要你處理」 list are read as before. A review made
  by the runner counts as independent only when the executor's model family is known and is not OpenAI, and not
  when the roles were changed after it was made. In automatic mode, when the executor role names no work
  directory, HEAD is compared in the task's directory (the one the automation uses) and the page says so; if
  it cannot be read the pass stays unverified. The flows notice now says what VBear does in each mode instead
  of 「VBear 不會為流程派工」.
- **Screenshots in the READMEs.** Six pictures of demo data (a synthetic Claude Code and Codex in a temporary
  folder; the pre-launch picture has the lines that print the work and temporary folders cut out) are in
  `docs/images/`. They come from `tests/qa_game_ui.py` with `VBEAR_QA_DEMO=1`, which also drops the HTML probe
  skill and any path of the machine from the screens.
- **The pre-launch check of a Codex role speaks for Codex.** The dialog no longer shows Claude Code's version
  notice, the 「驗證這個版本」 button, the terminal-title notice or the Haiku call for a Codex role; it names
  「Codex CLI <version>」, lists the reasons it cannot be launched or the evidence of each label, and its armor
  groups list only the levels a Codex label can have (the preview now carries `armor_groups`). A profile of
  another tool (shared) gets neither tool's words and no Claude-only level, only the reasons. The reason a role
  cannot be launched is shown right under the buttons of its profile page. The question that asks whether to
  remove a skill from a role names the skill (「未提供（ID：…）」 without a name) instead of 「[object Object]」.
- **Correction to the v0.3.0 summary: what a daemon restart needs.** After the background program restarts,
  every automatic flow is stopped and runs again only when you press 「繼續」. VBear first checks that your risk
  acceptance still counts and that HEAD, the reviews and the limits allow it. A turn that was cut off is charged at
  its worst case (often the whole budget), and then you raise the limit, accept again and approve automatic mode
  again. The v0.3.0 summary said acceptance and approval are always needed again; that was too strong. The
  security model's note on how the loop was verified now names the real-model runs.
- **README rewritten for first-time readers.** Both READMEs now open with what VBear is and a game-style
  reading of its screens (character, class, faction, skill cards, armor, party, gates, stamina), then feature
  cards, what to know before you start (the limitations, in plain words) ahead of the install steps, a 3-step
  first use with the real screen names, and the earlier details and technical notes below. The automatic mode's
  note now says it was verified with real models, and says what happens after the background program restarts
  (stopped; you press continue; the limit may need raising and a new acceptance).
  Skills and roles are described as labels and choices a profile records, not as things a launch loads. The
  Traditional Chinese README's long reference sections moved to `docs/REFERENCE.zh-TW.md`.
  The README also says that a launch starts Claude Code in its safe mode, which turns skills off, and describes the
  limits as a stop-loss that real usage can pass.

## v0.3.0 — multi-agent flows

Multi-agent flows: a look-only flows board; a coordinator that runs each step only when you press it; after a
plan is approved, the executor and its reviews run on their own and stop at the merge gate. Claude Code 2.1.296
is stream-verified. Evidence of real-model end-to-end runs: `docs/evidence/s3-real-e2e-2026-10-12.md`.
Merging, pushing and tagging are always done by you, never by VBear. After the daemon restarts, automatic
execution continues only once you accept the risk again and approve the plan again.

- **Codex review tokens.** A review's record now keeps the tokens the review used, taken from the rollout's
  cumulative usage chain (input, cached input, cache-write input, output, reasoning output, total), and the
  reviews panel shows them. A turn that did not finish (a stop, a failure) shows "at least" the recorded part;
  a number that cannot be had (no rollout, a chain that does not add up or disagrees with `turn.completed`, a
  record from before this field or one rebuilt after a crash) reads 「無法取得」 and is never shown as 0. Nothing is converted to money: VBear has no
  reliable price source. The S3 run summary's whitelist carries the same counts. Older records stay readable.
- **Test ports and shared directories.** No test names a port: every test listener binds port 0 and reads the real
  one back, and a test fails the suite if one is added that does not. The test that checks a failed launch leaves
  no scratch directory looks at what its own call made, not at a listing of the shared `/private/tmp`, so two
  copies of the suite can run at the same time. The test that a close does not stall another session no longer
  counts that session's output changes (a CI virtual machine stretched its timer to 48 in a 3 s close); it
  measures the longest time without output over the whole close, trailing stretch included.
- **Unverified Claude Code version, said before start.** When the installed Claude Code has no verified stream mode,
  the flow page says so in the executor panel before the executor is started, and the start button is off. The
  message (also the answer to a refused acceptance, preparation or open) names the version found, lists the versions
  VBear supports (generated from the stream-verified lists) and says what can be done: install one of them, or wait
  for a VBear update. A version that cannot be read is shown as unreadable, never as unverified. The panel reads
  the version from the same cached fact the acceptance uses (at most once per ten seconds).
- **Flows board (look-only).** A new 「流程」 page records multi-agent work on a task card: planner, executor and
  reviewers with their model families, and an append-only event log entered by hand (「手動記錄（未驗證）」). The
  phase, review rounds and commit binding are derived on every read; a review counts as a pass only for different,
  known families, and a pass goes out of date when the executor's directory moves off the reviewed commit. The
  home page's 「需要你處理」 lists flow gates (approval, merge, push, a pass whose HEAD cannot be checked). Stored
  in `flows.json` under the same fail-closed rules as `tasks.json`, now shared in `vbear/jsonstore.py`. VBear does
  not dispatch work, type into a terminal, run `git` or start an agent through the board's recording routes; those
  routes read live state only from the console's cache and never start anything (the managed executor and review
  below are separate, gated routes). Like the home page, the flows pages load the live view,
  which can start VBear's own runtime; they wait for it at most 10 s. A session state from that cache is shown as
  current only when the cache is at most 30 s old, its time is valid, the runtime answered, and this page's own
  load succeeded. Otherwise the executor reads 「即時狀態未載入」 (no cache yet, or this page's load failed or timed
  out), 「即時狀態時間不明」 (the cache's time is missing, invalid or in the future), 「即時狀態已過期」 (older than
  30 s), 「runtime 未連線」 (the runtime did not answer) or 「runtime 狀態不明」 (the cache does not say).
- **Managed Claude stream executor and Codex review (Phase 2).** A flow can now run a pipe-based Claude Code
  `claude-stream` executor and daemon-managed Codex review jobs, started and driven from the console (risk
    acceptance and every dispatch are previewed and approved).
  - *Risk acceptance.* A per-flow dialog shows the three residual risks in full (text version `2026-10-11.1`),
    the CLI versions, models and account fingerprints (first 16 hex digits) it binds to, and nine limits with
    defaults and caps. The preview is stored server-side (five minutes, one use) and confirming carries only its
    id; a change in account, version, key or text voids it. Editing any field voids the held preview.
  - *Executor and dispatch.* Start, stop and continue the executor; each dispatch is previewed as the exact
    sanitized text and approved separately. Strict event attribution, order and tool/result checks decide valid
    turns; failures hold the flow, and a turn with no result is charged at its worst case (an estimate, not a
    bill). Boundary evidence: [Claude Code 2.1.292](docs/evidence/claude-code-2.1.292-stream.md) and [2.1.296](docs/evidence/claude-code-2.1.296-stream.md).
  - *Reports.* The executor's own statement is shown apart from VBear's file checks (HEAD and commit object, read
    without running `git`); a check that fails or cannot be read is not shown as a pass.
  - *Codex review.* Runs in a separate sandboxed clone with a dedicated `CODEX_HOME` and temporary `HOME`; the
    daemon checks completion, report format, events, rollout, usage, model family and the reviewed commit before
    accepting a result. Reports are shown as plain text; `BASE_IS_ANCESTOR` is labelled self-reported. Codex
    0.160.0 cannot disable multi-agent: closed record kinds and an `exec`-only allow-list detect it and
    `SUBAGENT_ACTIVITY` invalidates the whole review without undoing anything. Evidence:
    [Codex 0.160.0](docs/evidence/codex-0.160.0-review.md).
  - *Merge gate.* Three conditions must hold before commands are shown; VBear never runs them, and local refs
    are labelled as local.
  - *Data.* Stream and review records are bounded by a 4 GiB reservation ledger and write-time caps; they are
    kept until you delete the flow, which is refused while anything runs or awaits manual review. When the room
    is used up the console lists the deletable flows with their sizes.
  - *Known limits.* See the residual-risk list in the [security model](docs/SECURITY-MODEL.md#phase-2-coordination).
- **Automatic mode (Phase 3).** After you approve a plan, VBear dispatches it, starts the reviews, forwards NEEDS
  WORK comments (in a block marked as data) and stops at the merge gate, with no per-item approval.
  - *Approval.* One preview shows the plan text in full, the automatic-mode text, the three residual risks, both
    account prefixes and the nine limits (4 h elapsed prefilled); confirming records one event that is both plan
    approval and risk acceptance, saves `plan.txt` and names its hash. The daemon re-verifies the event, the plan
    hash and "newest acceptance" on every automatic action; manual dispatches, reviews and acceptances are refused
    meanwhile (console and daemon).
  - *Runner.* A console thread (one per state directory) writes intent, daemon call, result for every action;
    stops on any invalid turn, failed tests, a report that does not match the files, a bad review, a limit or a
    changed account, an event it cannot write, or anything unexpected; never releases a stop, never starts a
    session, never runs git. A console restart resumes from the events; a daemon restart stops every automatic
    flow until you continue.
  - *Stopping.* Stop is yours, takes effect for new actions at once and lets the executor's turn in progress finish
    by itself. After a turn without a result, continuing needs a higher limit and a new approval (worst-case
    charge). A review ended by a stop is run again as the next round if HEAD is unchanged.
  - *Screens.* The flow page shows the mode, the current step, the approval it runs on and who wrote each event;
    the home list shows stopped flows and flows waiting at the merge gate.
  - Verified with synthetic CLIs; see the [security model](docs/SECURITY-MODEL.md#phase-3-automatic-mode).
- At phone width a long sidebar now scrolls inside the nav instead of widening every page.
- Terminal attachments under backpressure now drop only frames and keep the handshake and protocol notices in
  order; client commands pause at 256 queued notices.
- Four timing-sensitive tests no longer fail on a busy machine: the abandoned-launch expiry log and the open/close
  round trip's hang-up grace no longer race; the linear-parse test budgets CPU time instead of wall time; the
  streaming-during-close test allows half a grace period instead of 0.2 s.

- **Working/waiting follows version verification.** 「驗證這個版本」 now also checks Claude Code's terminal title
  in the same interactive run (no extra model call) and records it apart from the launch-boundary result; a
  version whose title passed shows working/waiting on this Mac. A title failure leaves the launch verified and the
  state unknown. Versions whose boundary is verified but title is not get a notice and the same button. Claude Code
  **2.1.291** is now built in for the title signal too ([evidence](docs/evidence/claude-code-2.1.291-activity.md));
  2.1.286 is not installed here and stays trial.
Ideas adopted from OpenRig, re-implemented ([notes](docs/evidence/openrig-learnings.md)):

- **Working or waiting.** Profile-launched Claude Code sessions now show 「工作中」 or 「等你回覆」 instead of
  always 「狀態未知」, read from the terminal title Claude sets (its idle mark, or its working spinner). Only the
  title's first character is kept, never its text. The signal is used only for Claude Code versions with recorded
  evidence (2.1.292, [evidence](docs/evidence/claude-code-2.1.292-activity.md)); on other versions it is recorded as
  a trial and the state stays unknown. Every status badge says what it is based on. The home page's 「需要你處理」
  lists the agents waiting for you.
- **Task cards bind results to commits.** With a work directory set, a passed test and an approval record the
  commit the directory was on. When it moves, the card reads 「結果對應的版本已變更」 and no longer counts as
  verification asserted. HEAD is read from the `.git` files; VBear never runs `git` there.
- **Closure reasons.** Marking a card 「已回報完成」 or 「阻塞」 asks what follows (no follow-on, handed off,
  superseded, canceled, denied; blocked on, escalated), with a target where one is needed. Enforced by the API.
- **Handoff.** 「交接給…」 closes the card and creates its successor in one write, carrying the chain of earlier
  cards.
- **Pickup state.** Each card shows whether its linked terminal is working, waiting, gone or unclaimed, derived
  when the card is read.
- Research note on giving Codex its own `CODEX_HOME` on 0.160.0
  ([docs/evidence/codex-0.160.0-isolated-codex-home.md](docs/evidence/codex-0.160.0-isolated-codex-home.md)). Codex
  launches stay off; the note also records that the interactive command rejects all four exec-only flags in
  `codex_argv()`.
- The runtime daemon reports itself as `native-r2-s3`. A daemon started by an older VBear keeps running and does
  not report activity evidence until it is restarted.

## v0.2.1

- **Unverified Claude Code versions can launch.** Claude Code updates itself almost daily; a release VBear has not
  verified no longer blocks profile launches. Its permission labels say 「未驗證」, and you tick that you know before
  it starts. A verified version, when installed, is still preferred.
- **「驗證這個版本」** in the launch dialog runs the boundary check on the current Claude Code (two small model calls
  with your own login). A pass is recorded in `~/.vbear/claude-verified.json` and the version counts as verified.
- **Claude Code 2.1.292 verified** (headless and interactive, 15/15 each), through the new button itself.
- The verification script moved into the package (`vbear/boundary_check.py`); `tools/verify_claude_boundary.py`
  still works.
- The CLI version probe waits up to 8 s (was 3 s), so a busy Mac no longer blocks launches.
- GitHub secret scanning and push protection are on for the repositories.

## v0.2.0 — installable macOS workbench

- **macOS app** (Apple Silicon): `VBear.app` with Python 3.13 included, in a `.dmg`. It starts VBear in the
  background (or reuses a running one), signs its window in, and opens external links in your browser. Quitting
  stops only the server it started; terminals keep running. Ad-hoc signed: allow it once in Privacy & Security.
- **Claude Code 2.1.291 verified**: the version gate now accepts a list of verified versions (2.1.286, 2.1.291) and
  launches the newest one installed. New `tools/verify_claude_boundary.py` re-runs the boundary check on any version
  (one model call per run); evidence in `docs/evidence/claude-code-2.1.291.md`.
- Faster live refresh: project lookups are resolved once per build (about 4x faster with many sessions).
- **Access token on the local API**: each start creates a random token; `/api/` needs it as an HttpOnly cookie
  or a Bearer header. Other user accounts on the Mac can no longer drive VBear. Open VBear with
  `python3 -m vbear launch`, which signs the browser in through a private local file.
- **Built-in terminal**: a 「終端機」 page opens your login shell in a folder under your home directory,
  with tabs and direct typing. Labelled as an ordinary, unsandboxed terminal.

## v0.1.0 — first public release

First open-source release under the MIT License.

- **Renamed from SID Console to VBear.** The package is now `vbear` and the state directory is
  `~/.vbear` (an existing `~/.sid-console` is moved on first start). Environment variables are now
  `VBEAR_HOME` and `VBEAR_RUNTIME_AUTOSTART`, and the CSRF header is now `X-VBear`.

- **VBear runtime.** A local daemon that owns agent terminals, so they survive console restarts. Terminals can
  be watched in the browser, typed into after an explicit takeover (one controller at a time),
  and closed from the UI.
- **Profile-managed Claude Code launches** with a preview of seven permission labels, followed by confirmation.
  Bash writes are limited to the work directory and a scratch directory for each session, the network is
  off, Edit and Write are disabled, and files are cleaned up only after every process is proven gone.
  Requires Claude Code 2.1.286 exactly.
- **Codex.** Its terminals can be watched and typed into; profile-managed launch is not available yet (fail closed).
- Skill and agent-role library for Claude Code, Codex and shared skills, with load status, sources,
  search and your own notes.
- Projects and team views, task cards that keep self-reported and verified status separate.
- The Herdr compatibility layer was removed. The last Herdr-based version is tagged `last-herdr`.
- Requires macOS and Python 3.13 or newer.
