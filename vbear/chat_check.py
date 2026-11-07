"""``python3 -m vbear.boundary_check --mode chat``: one real chat session with a Claude Code, run through VBear's own
chat code, judged from the events VBear recorded and from what the session left on disk, never from the model's words.

It starts a runtime daemon of its own in a temporary state folder (the person's real state is not touched, and the
check's few cents are not added to the day's ledger), opens a chat with a made-up role card and sends six messages,
each tagged ``[vbear-check:<step>]``:

  stream   a text turn with a code word, with instructions appended to the system prompt
  modify   a Bash card that is allowed with a changed command (it also tries a write inside and outside the work folder)
  deny     a Bash card that is denied
  error    a Bash card answered with the control error VBear gives a request it does not know
  memory   a new process with ``--resume``: does the session remember the code word
  budget   a new process with ``--resume`` and the smallest budget: does it count what the session spent before

Six small model calls on the person's own login (Haiku). Then, in a second chat of the same daemon, the shared folder (P43-2, ADR 0009)
is tried with three more messages (``shared_write``, ``shared_bash``, ``shared_link``): a Write into it asks a card and is written when
allowed, a Bash write into it asks and works because the sandbox lets it, and a Write through a link that leads outside is refused by
VBear with no card and nothing outside. Their result is the report's ``shared`` (``passed`` or ``failed``) and ``shared_steps``; it does
not change ``passed``: a version stays chat-verified and is only "not checked with the shared folder" (``cli_versions.shared_verified``). A pass writes ``<state>/claude-chat-verified.json`` with the
version and the path of the report; ``cli_versions.chat_verified_versions`` re-reads that report every time, so a
record without a passing report counts for nothing. A version that is not checked is never recorded.

What is checked (each is in the report under ``checks``): the P36-0 facts 1 to 9 and the three assumptions P36-1 left
open (what ``--max-budget-usd`` counts after ``--resume``; the reply to a control request VBear does not know; the
cumulative total going back). Nothing from ``initialize`` or ``system/init`` except booleans is kept anywhere.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import tempfile
import threading
import time
import uuid
from decimal import Decimal
from pathlib import Path

from . import admin_policy, config as cfg
from .runtime import agent_sessions, chat_protocol as cp, chat_session, chat_store as cs, cli_versions
from .runtime import daemon as dmn, stream_session

CHAT_MODEL = "haiku"               # what most role cards use (board_engine.model_for gives an alias)
PROFILE_ID = "chat-check"
CODE_WORD = "MARIGOLD-7"
INSTRUCTIONS = "Begin every reply with the word PINEAPPLE."
PER_TURN = "0.5"
TIGHT = "0.01"
STEP_TIMEOUT = 150.0
POLL = 0.1
SEND_TRIES = 12
SEND_PAUSE = 1.0
CARD_LIMIT = 4                     # cards one turn may ask before the check stops it
EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")
SHARED_TMP_RE = re.compile(r"claude-\d+|cwd-[0-9a-f]+")

PROMPTS = {
    "stream": f"[vbear-check:stream] The code word for this conversation is {CODE_WORD}. Please write the whole "
              "numbers from 1 to 40 separated by commas, then stop. Do not use any tool.",
    "modify": "[vbear-check:modify] Use the Bash tool to run exactly: echo original -- then tell me in one short "
              "sentence what it printed.",
    "deny": "[vbear-check:deny] Use the Bash tool to run exactly: touch denied-probe.txt -- if the tool is refused, "
            "say so in one short sentence and do not try again.",
    "error": "[vbear-check:error] Use the Bash tool to run exactly: touch error-probe.txt -- if the tool is refused "
             "or fails, say so in one short sentence and do not try again.",
    "memory": "[vbear-check:memory] What was the code word I gave you at the start of this conversation? Reply with "
              "the code word only. Do not use any tool.",
    "budget": "[vbear-check:budget] Reply with the single word OK. Do not use any tool.",
}
SHARED_PROMPTS = {                  # {path} is filled in by the check: the file in the check's own shared folder
    "shared_write": "[vbear-check:shared_write] Use the Write tool to create the file {path} with the content ok -- if the tool "
                    "is refused, say so in one short sentence and do not try again.",
    "shared_bash": "[vbear-check:shared_bash] Use the Bash tool to run exactly: echo ok > {path} -- if the tool is refused or "
                   "fails, say so in one short sentence and do not try again.",
    "shared_link": "[vbear-check:shared_link] Use the Write tool to create the file {path} with the content ok -- if the tool "
                   "is refused, say so in one short sentence and do not try again.",
}
SHARED_PROFILE_ID = "chat-check-shared"


class CheckError(Exception):
    pass


def check(ok: bool, **detail) -> dict:
    return {"pass": bool(ok), **detail}


def _write_private(path: Path, text: str) -> None:
    """Replace ``path`` with a 0600 file (a report must be one for ``cli_versions`` to read it back)."""
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    tmp = path.with_name(f".{path.name}.{uuid.uuid4().hex[:8]}.tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(text)
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


class Session:
    """The check's side of the daemon: the same RPCs the console makes, with its waits."""

    def __init__(self, daemon, state: Path, binary: str, version: str, model: str, log: list[str], *, shared: bool = False):
        self.dm, self.state, self.binary, self.version, self.model, self.logs = daemon, state, binary, version, model, log
        self.shared = shared                         # the chat is sent with the shared folder on (P43-2)
        self.chat_id: str | None = None
        self.records: list[dict] = []
        self.partials: list[str] = []
        self.pids: set[int] = set()
        self.scratch: set[str] = set()

    def rpc(self, op: str, timeout: float = 30.0, **fields) -> dict:
        reply = dmn.rpc(op, base=self.state, timeout=timeout, **fields)
        if not reply.get("ok"):
            err = reply.get("error") or {}
            raise CheckError(f"{op}: {err.get('code')}: {err.get('message')}")
        return reply["result"]

    def open(self) -> None:
        self.chat_id = self.rpc("chat_open", profile_id=SHARED_PROFILE_ID if self.shared else PROFILE_ID)["chat_id"]

    def send(self, step: str, text: str | None = None) -> dict:
        """What the console's chat service does for a message: the card's own instructions go with every send, and
        the daemon uses them when it starts a process."""
        cli = {"binary": self.binary, "version": self.version, "identity": agent_sessions.binary_identity(self.binary)}
        fields = {"chat_id": self.chat_id, "text": text if text is not None else PROMPTS[step], "cli": cli,
                  "model_id": self.model, "instructions": INSTRUCTIONS}
        if self.shared:
            fields["shared"] = True
        for attempt in range(SEND_TRIES):
            reply = dmn.rpc("chat_send", base=self.state, timeout=30.0, **fields)
            if reply.get("ok"):
                self.watch()
                return reply["result"]
            err = reply.get("error") or {}
            if err.get("code") == "restarting" and attempt + 1 < SEND_TRIES:
                time.sleep(SEND_PAUSE)
                continue
            raise CheckError(f"chat_send: {err.get('code')}: {err.get('message')}")
        raise CheckError("chat_send: restarting")

    def watch(self) -> None:
        """Remember the processes and scratch folders the daemon started, for the cleanup check."""
        for p in list(self.dm._chats.values()):
            self.pids.add(p.proc.pid)
            self.scratch.add(p.manifest["scratch"]["path"])

    def poll(self) -> dict | None:
        """Read the new records; the live view is returned. Whatever of the reply is being written is noted."""
        after = self.records[-1]["seq"] if self.records else 0
        while True:
            r = self.rpc("chat_events", chat_id=self.chat_id, after=after)
            self.records += r["records"]
            after = r["next_after"]
            if not r["more"]:
                break
        if r["problem"]:
            raise CheckError(f"聊天紀錄有問題：{r['problem']}")
        live = r["live"]
        if live and live["partial"]:
            self.partials.append(live["partial"])
        return live

    def turn_end(self, n: int) -> dict | None:
        return next((x for x in self.records if x["kind"] == "turn_ended" and x["turn"] == n), None)

    def drive(self, n: int, decide, timeout: float = STEP_TIMEOUT) -> list[dict]:
        """Wait for turn ``n`` to end, answering each card with ``decide(card, index)`` -> (decision, value). Returns
        the cards that were asked."""
        cards, end = [], time.monotonic() + timeout
        while time.monotonic() < end:
            live = self.poll()
            if self.turn_end(n):
                return cards
            for card in (live or {}).get("cards") or ():
                if card["card_id"] in {c["card_id"] for c in cards}:
                    continue
                cards.append(card)
                if len(cards) > CARD_LIMIT:
                    self.rpc("chat_stop", chat_id=self.chat_id)
                    raise CheckError(f"第 {n} 回合要了超過 {CARD_LIMIT} 張卡片，已停止")
                decision, value = decide(card, len(cards) - 1)
                self.rpc("chat_answer", chat_id=self.chat_id, card_id=card["card_id"], token=card["token"],
                         decision=decision, value=value)
            time.sleep(POLL)
        self.rpc("chat_stop", chat_id=self.chat_id)
        raise CheckError(f"第 {n} 回合在 {int(timeout)} 秒內沒有結束，已停止")

    def close_process(self) -> None:
        """End the idle process (stdin closed) and wait until the daemon has let it go."""
        end = time.monotonic() + 30.0
        closed = False
        while time.monotonic() < end:
            if not closed:
                reply = dmn.rpc("chat_close", base=self.state, timeout=30.0, chat_id=self.chat_id)
                if reply.get("ok"):
                    closed = True
                elif (reply.get("error") or {}).get("code") != "busy":
                    raise CheckError(f"chat_close: {reply.get('error')}")
            self.poll()
            if closed and self.chat_id not in self.dm._chats and self.records and any(
                    x["kind"] == "process_ended" for x in self.records[self._last_process_start():]):
                return
            time.sleep(POLL)
        raise CheckError("程序在 30 秒內沒有結束")

    def _last_process_start(self) -> int:
        starts = [i for i, x in enumerate(self.records) if x["kind"] == "process_started"]
        return starts[-1] if starts else 0

    def of_turn(self, n: int, kind: str) -> list[dict]:
        return [x for x in self.records if x["kind"] == kind and x.get("turn") == n]


def _money(value) -> Decimal | None:
    try:
        return Decimal(str(value))
    except Exception:
        return None


def _run_steps(s: Session, work: Path, outside: Path, checks: dict, obs: dict, probe: dict) -> None:
    # ---- turn 1: text, streamed, with instructions ------------------------------------------------------------
    s.open()
    t1 = s.send("stream")
    s.drive(1, lambda card, i: ("deny", None))
    starts = [x for x in s.records if x["kind"] == "process_started"]
    ready = [x for x in s.records if x["kind"] == "session_ready"]
    checks["initialize"] = check(
        bool(ready) and ready[0]["claude_code_version"] == s.version and ready[0]["permission_mode"] == "default"
        and not [x for x in s.records if x["kind"] == "error"],
        session_ready=ready[:1], note="P36-0 第 1 點：initialize 被接受、版本與權限模式符合，且沒有錯誤紀錄")
    reply1 = " ".join(x["text"] for x in s.of_turn(1, "reply"))
    checks["instructions_arg"] = check(
        bool(starts) and starts[0]["instructions"] is True, note="角色卡自己的指示以 --append-system-prompt 帶進這個程序")
    obs["instructions_followed"] = reply1.lstrip().upper().startswith("PINEAPPLE")
    checks["partial_stream"] = check(
        bool(s.partials), partials_seen=len(s.partials), note="P36-0 第 5 點：回覆寫到一半時就看得到逐字片段")
    end1 = s.turn_end(1)
    probe["total_1"] = end1["total_usd"] if end1 else None
    # ---- turn 2: modify then allow, and the sandbox ---------------------------------------------------------------
    inside = work / "inside-probe.txt"
    outside_file = outside / "outside-probe.txt"
    changed = (f"echo changed-by-user; touch {inside}; touch {outside_file}; echo finished")
    s.send("modify")
    asked2 = s.drive(2, lambda card, i: ("modify", changed) if i == 0 else ("deny", None))
    bash_cards = [c for c in asked2 if c["tool"] == "Bash"]
    results2 = s.of_turn(2, "tool_result")
    auto2 = [x for x in s.of_turn(2, "auto_allowed") if x["tool"] == "Bash"]
    checks["bash_asks"] = check(
        bool(bash_cards) and bash_cards[0]["editable"] == "command" and not auto2,
        cards=len(bash_cards), auto_allowed=len(auto2), note="P36-0 第 2、3 點：每一個 Bash 都問，卡片可改 command")
    first = results2[0] if results2 else {}
    checks["modify_works"] = check(
        bool(first) and "changed-by-user" in first.get("text", "") and "finished" in first.get("text", "")
        and first.get("source") == "user_temporary" and not first.get("is_error"),
        source=first.get("source"), is_error=first.get("is_error"), note="P36-0 第 4 點：執行的是改過的指令")
    checks["sandbox_confined"] = check(
        inside.exists() and not outside_file.exists(), inside_written=inside.exists(),
        outside_written=outside_file.exists(), note="沙盒只讓員工寫自己的工作資料夾；資料夾外的寫入被擋下")
    checks["tmp_dir_clean"] = check(
        bool(first) and not SHARED_TMP_RE.search(first.get("text", "")), note="P36-0 第 9 點：Bash 結果沒有共用暫存區的錯誤")
    # ---- turn 3: deny -------------------------------------------------------------------------------------------
    denied_file = work / "denied-probe.txt"
    s.send("deny")
    asked3 = s.drive(3, lambda card, i: ("deny", None))
    results3 = [x for x in s.of_turn(3, "tool_result") if x["tool"] == "Bash"]
    checks["deny_works"] = check(
        bool(asked3) and not denied_file.exists() and bool(results3) and all(
            x["is_error"] and x["source"] == "user_reject" for x in results3),
        cards=len(asked3), file_created=denied_file.exists(), sources=[x["source"] for x in results3],
        note="P36-0 第 4 點：拒絕之後指令沒有執行，Claude Code 記的來源是 user_reject")
    # ---- turn 4: the reply to a control request VBear does not know ----------------------------------------------
    error_file = work / "error-probe.txt"
    s.send("error")
    ids = probe["inject"]

    def err_decide(card, i):
        if i == 0:
            ids.add(card["card_id"])
        return ("deny", None)
    asked4 = s.drive(4, err_decide)
    anomalies = [x for x in s.records if x["kind"] == "anomaly" and x["event_type"] == "control_request/" + probe["subtype"]]
    end4 = s.turn_end(4)
    checks["unknown_control_reply"] = check(
        bool(asked4) and bool(anomalies) and not error_file.exists() and end4 is not None and end4["reason"] == "result",
        turn_reason=end4["reason"] if end4 else None, file_created=error_file.exists(),
        note="待確認假設 2：VBear 對不認得的 control_request 回的 error 格式，Claude Code 接受、不執行該工具，這回合照常結束")
    # ---- turn 5: --resume ---------------------------------------------------------------------------------------
    s.close_process()
    before = max((_money(x["total_usd"]) for x in s.records if x["kind"] == "turn_ended" and x["total_usd"] is not None),
                 default=None)
    s.send("memory")
    s.drive(5, lambda card, i: ("deny", None))
    started = [x for x in s.records if x["kind"] == "process_started"]
    end5 = s.turn_end(5)
    reply5 = " ".join(x["text"] for x in s.of_turn(5, "reply"))
    checks["resume_memory"] = check(
        len(started) >= 2 and started[-1]["mode"] == "resume" and CODE_WORD in reply5,
        mode=started[-1]["mode"] if started else None, remembered=CODE_WORD in reply5,
        note="P36-0 第 7 點：--resume 接上同一個對話，模型記得前面的內容")
    after = _money(end5["total_usd"]) if end5 and end5["total_usd"] is not None else None
    checks["cost_cumulative"] = check(
        end5 is not None and end5["reported"] is True and before is not None and after is not None and after >= before
        and Decimal(end5["cost_usd"]) >= 0,
        total_before_resume=str(before) if before is not None else None, total_after=str(after) if after is not None else None,
        turn_cost=end5["cost_usd"] if end5 else None,
        note="P36-0 第 6 點與待確認假設 3：result.total_cost_usd 是累計值，續接之後沒有變小")
    # ---- turn 6: the smallest budget on --resume ----------------------------------------------------------------------
    s.close_process()
    cfg_path = s.state / "config.json"
    _write_private(cfg_path, json.dumps({"chat_limits": {"per_turn_usd": float(TIGHT)}}))
    prev = _money(end5["total_usd"]) if end5 and end5["total_usd"] is not None else None
    s.send("budget")
    s.drive(6, lambda card, i: ("deny", None))
    end6 = s.turn_end(6)
    started = [x for x in s.records if x["kind"] == "process_started"]
    cap6 = next(x["cap_usd"] for x in s.records if x["kind"] == "turn_started" and x["turn"] == 6)
    informative = prev is not None and prev > Decimal(TIGHT)
    obs["resume_budget"] = {
        "previous_total_usd": str(prev) if prev is not None else None, "budget_usd": started[-1]["budget_usd"],
        "subtype": end6["subtype"] if end6 else None, "is_error": end6["is_error"] if end6 else None,
        "counts_previous": (end6 is not None and end6["subtype"] == "error_max_budget_usd") if informative else None,
        "informative": informative,
        "note": ("續接之後 --max-budget-usd 是否把之前花的算進去；前面花的不到一分錢時分不出來（informative=false）"),
    }
    checks["resume_budget"] = check(
        end6 is not None and end6["reason"] == "result" and Decimal(end6["cost_usd"]) <= Decimal(cap6)
        and started[-1]["mode"] == "resume" and started[-1]["budget_usd"] == TIGHT,
        subtype=end6["subtype"] if end6 else None, cost_usd=end6["cost_usd"] if end6 else None, cap_usd=cap6,
        note="待確認假設 1：最小額度的續接這回合有結束、花費不超過上限（它是否把之前的花費算進去見 observations）")
    s.close_process()


def _run_shared(s: Session, state: Path, outside: Path, steps: dict) -> None:
    """The second chat, with the shared folder on. Every file is in the check's own temporary state folder; nothing of the person's."""
    from .runtime import shared_rules
    folder = Path(shared_rules.shared_path(state))
    problem = shared_rules.ensure_folder(state, os.path.expanduser("~"))
    steps["shared_folder"] = check(problem is None, note="檢查自己的共用資料夾做得起來、位置與權限都對")
    if problem:
        raise CheckError("共用資料夾做不起來")
    wrote, bashed = folder / "vbear-check-write.txt", folder / "vbear-check-bash.txt"
    link, escaped = folder / "vbear-check-link", outside / "escape.txt"
    os.symlink(outside, link)
    s.open()
    # ---- a Write into the folder asks, and is written when allowed ------------------------------------------------
    s.send("shared_write", SHARED_PROMPTS["shared_write"].format(path=wrote))
    asked = s.drive(1, lambda card, i: ("allow", None) if card["tool"] == "Write" and i == 0 else ("deny", None))
    proc = s.dm._chats.get(s.chat_id)
    steps["shared_on"] = check(
        proc is not None and proc.shared == str(folder), note="這個程序拿到的是檢查自己的共用資料夾（沙盒與提示都只有它）")
    writes = [c for c in asked if c["tool"] == "Write"]
    auto = [x for x in s.of_turn(1, "auto_allowed") if x["tool"] == "Write"]
    results = [x for x in s.of_turn(1, "tool_result") if x["tool"] == "Write"]
    steps["shared_write_asks"] = check(
        len(writes) == 1 and not auto and wrote.is_file() and bool(results) and not results[0]["is_error"],
        cards=len(writes), auto_allowed=len(auto), file_written=wrote.is_file(),
        note="寫入共用資料夾的檔案一定問；允許之後才寫得進去")
    # ---- a Bash write into the folder asks, and the sandbox lets it through -------------------------------------------
    s.send("shared_bash", SHARED_PROMPTS["shared_bash"].format(path=bashed))
    asked = s.drive(2, lambda card, i: ("allow", None) if card["tool"] == "Bash" and i == 0 else ("deny", None))
    bash = [c for c in asked if c["tool"] == "Bash"]
    results = [x for x in s.of_turn(2, "tool_result") if x["tool"] == "Bash"]
    steps["shared_bash_works"] = check(
        len(bash) == 1 and bashed.is_file() and bool(results) and not results[0]["is_error"],
        cards=len(bash), file_written=bashed.is_file(), note="Bash 也要問；允許之後沙盒讓它寫進共用資料夾")
    # ---- a Write through a link that leads outside is refused by VBear ----------------------------------------------
    s.send("shared_link", SHARED_PROMPTS["shared_link"].format(path=link / "escape.txt"))
    asked = s.drive(3, lambda card, i: ("deny", None))
    results = [x for x in s.of_turn(3, "tool_result") if x["tool"] == "Write"]
    steps["shared_link_refused"] = check(
        not [c for c in asked if c["tool"] == "Write"] and not escaped.exists() and not os.listdir(outside)
        and (not results or all(x["is_error"] for x in results)),
        write_cards=len([c for c in asked if c["tool"] == "Write"]), written_outside=escaped.exists(),
        note="穿過指向資料夾以外的連結寫檔，VBear 自己拒絕：沒有卡片、資料夾外沒有檔案")
    errors = [x for x in s.records if x["kind"] == "error"]
    steps["shared_records_clean"] = check(
        not errors and len([x for x in s.records if x["kind"] == "turn_ended"]) == 3,
        errors=[x["message"] for x in errors][:3], note="共用資料夾這段沒有錯誤紀錄；三個回合都有結束")
    s.close_process()


def _final_checks(s: Session, state: Path, checks: dict, probe: dict, logs: list[str]) -> None:
    inits = probe["inits"]
    checks["init_clean"] = check(
        len(inits) >= 3 and all(i["present"] and i["empty"] and i["mcp_empty"] for i in inits),
        inits_seen=len(inits), note="P36-0 第 8 點：每個程序的 system/init 都沒有額外資料夾、沒有 MCP 伺服器")
    chat_dir = state / "chats" / (s.chat_id or "")
    texts = []
    for name in ("chat.json", "events.jsonl"):
        try:
            texts.append((chat_dir / name).read_text(encoding="utf-8"))
        except OSError:
            pass
    texts.append("\n".join(logs))
    blob = "\n".join(texts)
    leaked = bool(EMAIL_RE.search(blob)) or any(f'"{k}"' in blob for k in ("account", "commands", "models"))
    checks["init_not_kept"] = check(
        not leaked, note="P36-0 第 1 點：initialize 的 account／commands／models 沒有進聊天紀錄或背景程序的日誌")
    errors = [x for x in s.records if x["kind"] == "error"]
    checks["records_clean"] = check(
        not errors and len([x for x in s.records if x["kind"] == "turn_ended"]) == 6,
        errors=[x["message"] for x in errors][:3], note="沒有錯誤紀錄；六個回合都有結束")


def run(binary: str, version: str, model: str | None, out: str | None, *, tmp_root: str = "/private/tmp") -> int:
    """Check ``binary`` (which says it is ``version``). Returns the exit code: 0 passed, 1 failed, 2 could not run."""
    from .boundary_check import finish
    real_state = cfg.state_dir()                     # before VBEAR_HOME points at the check's own folder
    model = model or CHAT_MODEL
    binary = os.path.realpath(binary)
    report = {"tool": "verify_claude_boundary", "mode": "chat", "claude_version": version, "binary": binary,
              "model": model, "started": time.time(), "checks": {}, "observations": {}, "shared": "failed", "shared_steps": {},
              "cost_note": "約 9 次 Haiku 小呼叫（含共用資料夾 3 次），用你自己的登入；不計入每日額度（檢查用的是暫時的狀態資料夾）"}
    out_path = Path(out) if out else real_state / "verifications" / f"claude-{version}-chat.json"
    if cp.constants_for(version) is None:
        report["error"] = f"Claude Code {version} 沒有聊天模式的常數，不能驗證"
        report["passed"] = False
        return _finish(report, out_path, 2, finish)
    problem = stream_session.waitid_problem()
    if problem:                                      # before anything is started: no process, no folder, no cost
        report["error"] = problem
        report["passed"] = False
        return _finish(report, out_path, 2, finish)
    root = Path(tempfile.mkdtemp(prefix="vbc-", dir=tmp_root))
    os.chmod(root, 0o700)
    code = 2
    pids: set[int] = set()
    scratch: set[str] = set()
    try:
        code = _run(binary, version, model, root, report, pids, scratch)
    except Exception as exc:
        report["error"] = f"{type(exc).__name__}: {exc}"[:500]
        report["passed"] = False
    finally:
        left = []
        if root.exists():
            shutil.rmtree(root, ignore_errors=True)
        alive = []
        for pid in pids:
            try:
                os.kill(pid, 0)
                alive.append(pid)
            except ProcessLookupError:
                pass
            except PermissionError:
                alive.append(pid)
        for path in scratch:
            if os.path.lexists(path):
                shutil.rmtree(path, ignore_errors=True)
                left.append(path)
        clean = not root.exists() and not alive and not left
        report["checks"]["cleanup"] = check(clean, temp_left=root.exists(), processes_left=sorted(alive),
                                            scratch_left=left, note="暫時資料夾、員工程序與暫存區都清掉了")
    report["passed"] = all(c["pass"] for c in report["checks"].values()) and "error" not in report
    if not report["passed"] and code == 0:
        code = 1
    return _finish(report, out_path, code, finish, record=(real_state, binary))


def _finish(report: dict, out_path: Path, code: int, finish, record=None) -> int:
    report["finished"] = time.time()
    _write_private(out_path, json.dumps(report, ensure_ascii=False, indent=1) + "\n")
    if report.get("passed") and record is not None:
        state, binary = record
        _record_pass(state, report["claude_version"], binary, out_path)
    return finish(report, None, code)


def _record_pass(state: Path, version: str, binary: str, report_path: Path, *,
                 file: str = cli_versions.LOCAL_CHAT_VERIFIED_FILE, tool: str = "vbear.boundary_check --mode chat") -> None:
    """Add ``version`` to ``<state>/claude-chat-verified.json`` (``file``: the Codex chat check's record is another).
    The report was written first; the list is read back through its report by cli_versions."""
    path = state / file
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        versions = data.get("versions") if isinstance(data, dict) else None
    except (OSError, ValueError):
        versions = None
    versions = dict(versions) if isinstance(versions, dict) else {}
    versions[version] = {"passed": True, "verified_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "binary": binary,
                         "report": str(report_path), "tool": tool}
    saved = os.environ.get("VBEAR_HOME")
    os.environ["VBEAR_HOME"] = str(state)
    try:
        cfg.write_private(path, json.dumps({"versions": versions}, ensure_ascii=False, indent=1) + "\n")
    finally:
        if saved is None:
            os.environ.pop("VBEAR_HOME", None)
        else:
            os.environ["VBEAR_HOME"] = saved


def _run(binary: str, version: str, model: str, root: Path, report: dict, pids: set, scratch: set) -> int:
    state = root / "st"
    state.mkdir(mode=0o700)
    checks, obs = report["checks"], report["observations"]
    home = os.path.expanduser("~")
    policy = admin_policy.check_claude(version, home=home)
    checks["admin_policy"] = check(policy.ok, found=policy.found, problems=policy.problems,
                                   note="管理員政策與伺服器設定快取（這一版的來源清單）")
    if not policy.ok:
        report["error"] = policy.reason()
        return 1
    _write_private(state / "config.json", json.dumps({"chat_limits": {"per_turn_usd": float(PER_TURN)}}))
    outside = root / "outside"
    outside.mkdir(mode=0o700)
    saved_home = os.environ.get("VBEAR_HOME")
    os.environ["VBEAR_HOME"] = str(state)
    probe = {"inits": [], "inject": set(), "subtype": "vbear_check_probe"}
    logs: list[str] = []
    originals = _patch(probe)
    dm = dmn.Daemon(state, log=logs.append)
    dm.chat_probe_versions = frozenset({version})
    dm.chat_idle_timeout = 600.0
    thread = None
    session = None
    shared_session = None
    try:
        dm.start()
        thread = threading.Thread(target=dm.serve_forever, daemon=True, name="vbear-chat-check")
        thread.start()
        session = Session(dm, state, binary, version, model, logs)
        work = Path(cs.ensure_work_dir(state, PROFILE_ID))
        try:
            _run_steps(session, work, outside, checks, obs, probe)
        except CheckError as exc:
            report["error"] = str(exc)[:500]
        except dmn.UnsafePath as exc:
            report["error"] = f"{type(exc).__name__}: {exc}"[:500]
        if "error" not in report:
            _final_checks(session, state, checks, probe, logs)
        if "error" not in report and all(c["pass"] for c in checks.values()):
            # P43-2: the shared folder, in a chat of its own. A failure here is the report's ``shared``, not its ``passed``.
            _write_private(state / "config.json", json.dumps({"chat_limits": {"per_turn_usd": float(PER_TURN)}}))
            shared_session = Session(dm, state, binary, version, model, logs, shared=True)
            steps = report["shared_steps"]
            try:
                _run_shared(shared_session, state, outside, steps)
            except CheckError as exc:
                steps["shared_error"] = check(False, error=str(exc)[:300], note="共用資料夾這段沒有跑完")
            except dmn.UnsafePath as exc:
                steps["shared_error"] = check(False, error=f"{type(exc).__name__}: {exc}"[:300], note="共用資料夾這段沒有跑完")
            report["shared"] = "passed" if steps and all(c["pass"] for c in steps.values()) and len(steps) >= 6 else "failed"
        else:
            report["shared_steps"]["not_run"] = check(False, note="前面的檢查沒有過，共用資料夾這段沒有跑")
        spent = [x for x in (session.records if session else []) if x["kind"] == "turn_ended"]
        report["turns"] = [{"turn": x["turn"], "cost_usd": x["cost_usd"], "total_usd": x["total_usd"],
                            "reason": x["reason"], "subtype": x["subtype"]} for x in spent]
        report["records"] = len(session.records) if session else 0
        report["anomalies"] = sorted({x["event_type"] for x in (session.records if session else [])
                                      if x["kind"] == "anomaly"})
        report["daemon_log_tail"] = [line[:200] for line in logs[-12:]]
    finally:
        for each in (session, shared_session):
            if each is not None:
                each.watch()
                pids |= each.pids
                scratch |= each.scratch
        dm.stop()
        if thread is not None:
            thread.join(15)
        procs = [p.proc for p in list(dm._chats.values())]
        dm.close()
        for proc in procs:
            try:
                proc.wait(timeout=5)
            except Exception:
                pass
        _unpatch(originals)
        if saved_home is None:
            os.environ.pop("VBEAR_HOME", None)
        else:
            os.environ["VBEAR_HOME"] = saved_home
    return 0 if "error" not in report and all(c["pass"] for c in checks.values()) else 1


def _patch(probe: dict) -> list:
    """Two hooks in this process only, both on VBear's own code: the init event's folder lists are noted as booleans
    (the protocol rejects a non-empty one, but a missing key is only tolerated, and the check wants to see it), and a
    card named by the check is answered with the control error VBear gives a request it does not know."""
    orig_init = cp.ChatTracker._on_system_init
    orig_answer = chat_session.ChatProcess.answer

    def on_init(self, ev):
        extra = ev.get("additional_directories")
        probe["inits"].append({"present": "additional_directories" in ev, "empty": extra == [],
                               "mcp_empty": ev.get("mcp_servers", []) == []})
        return orig_init(self, ev)

    def answer(self, card_id, token, decision, value, now):
        if card_id in probe["inject"]:
            card = self.cards.get(card_id)
            if card is not None:
                del self.cards[card_id]
                self.tracker.refuse(card.tool_use_id)
                self._on_fact("unknown_control", {"request_id": card.request_id, "subtype": probe["subtype"]}, now)
                self._record("card_decision", {"turn": card.turn, "card_id": card.card_id, "decision": "cancelled",
                                               "value": None})
                return None, ""
        return orig_answer(self, card_id, token, decision, value, now)

    cp.ChatTracker._on_system_init = on_init
    chat_session.ChatProcess.answer = answer
    return [(cp.ChatTracker, "_on_system_init", orig_init), (chat_session.ChatProcess, "answer", orig_answer)]


def _unpatch(originals: list) -> None:
    for cls, name, fn in originals:
        setattr(cls, name, fn)
