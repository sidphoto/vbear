"""The runtime daemon's chats with role cards (P36-1): the RPC ops and the loop hooks. A mixin of Daemon, as
StreamOps is.

  chat_open    {profile_id, engine?}                        a new chat (engine claude-chat, or codex-chat for a role
                                                            card whose AI tool is Codex); no process
  chat_send    {chat_id, text, cli: {binary, version, identity}, model_id, instructions?, memory?, engine?, origin?}
                                                            a person's message: a turn, in the chat's live process
                                                            or a new one (``--resume`` once the session exists, a
                                                            Codex chat's ``thread/resume``); ``instructions`` is the
                                                            role card's own text, appended to the system prompt of a
                                                            new Claude process (a Codex chat's developer
                                                            instructions); ``engine``, when given, must be the
                                                            chat's; a Codex chat's ``model_id`` may be None (Codex's
                                                            own default); ``origin`` ({dispatch, step}) is only
                                                            written into the record: a message VBear sent for a dispatch;
                                                            ``memory`` (P42-1) is the person's memory as a list of
                                                            {kind, text}: checked again here (memory_rules.prepare), built
                                                            into one fixed paragraph and added after the instructions,
                                                            so that the chat record has no field for it
  chat_answer  {chat_id, card_id, token, decision, value}   a permission card, once, with its one-use token
  chat_stop    {chat_id}                                    ends the turn (at its cap) and the process
  chat_close   {chat_id}                                    ends an idle process (stdin closed); refused while busy
  chat_events  {chat_id, after}                             the events after a sequence number, and the live state
  chat_delete  {chat_id}                                    removes a chat without a process; its cost stays counted

Limits: one process per role card, CHAT_MAX in all (and every chat counts toward the daemon's session room); a
process ends after its idle time; a turn after its time limit. Money: a turn may cost at most the per-turn limit and
what is left of the day (the chats, the meetings and the staffing meetings together); on a red lamp, or with less
than a cent left, no message is sent.
"""

from __future__ import annotations

import json
import os
import secrets
import selectors
import subprocess
import time
from decimal import ROUND_DOWN, Decimal
from pathlib import Path

from .. import admin_policy, config as cfg, meetings as mt
from . import agent_sessions, chat_engines, chat_protocol as cp, chat_session, chat_store as cs, cli_versions, memory_rules, proctrack
from . import codex_chat_env, codex_chat_protocol as ccp, codex_chat_session
from . import stream_session

CHAT_MAX = 3
IDLE_TIMEOUT = 10 * 60.0
TURN_TIMEOUT = 10 * 60.0
CARD_TTL = 300.0
INIT_DEADLINE = 30.0
CLOSE_GRACE = 5.0
REPLY_BUDGET = 56 << 10        # bytes of records in one chat_events answer (the RPC reply limit is 64 KiB)
EVENTS_PAGE = 500
CENT = Decimal("0.01")


def _ok(rid, result) -> dict:
    return {"v": 1, "id": rid, "ok": True, "result": result}


def _err(rid, code: str, message: str) -> dict:
    return {"v": 1, "id": rid, "ok": False, "error": {"code": code, "message": message}}


def _said(turn: int, text: str, origin: dict | None) -> dict:
    """The data of a ``user_message``: the turn and the words, and the origin when VBear sent them for a dispatch."""
    return {"turn": turn, "text": text, **({"origin": origin} if origin is not None else {})}


def _store_err(rid, exc: cs.ChatStoreError) -> dict:
    return _err(rid, exc.code, exc.message)


class ChatOps:
    # set up by Daemon.__init__: base, _sel, _chats, chat_* timeouts, _log, max_sessions

    # ---- money ------------------------------------------------------------------------------------------------

    def _chat_config(self) -> dict:
        """config.json of this state folder, read only (never written here): {} when there is none."""
        path = Path(self.base) / "config.json"
        try:
            raw = path.read_bytes()
        except FileNotFoundError:
            return {}
        if len(raw) > 4 << 20:
            raise ValueError("設定檔太大")
        data = json.loads(raw.decode("utf-8"))
        if not isinstance(data, dict):
            raise ValueError("設定檔內容不是物件")
        return data

    def _chat_day_spent(self, now: float) -> Decimal:
        """What today cost: the chats (deleted ones included), the meetings, the staffing meetings, the tries, the chief of
        staff's proposals and the memory suggestions. Raises when it cannot be established; a damaged record of a meeting adds nothing (as for the
        meetings themselves), but a proposal that cannot be read makes the day unknown."""
        if os.path.realpath(cfg.state_dir()) != os.path.realpath(self.base):
            raise ValueError("背景程序的資料夾與設定的資料夾不同，無法確認今天的花費")
        from .. import chief, memory_suggest, staffing as st, try_spend    # here: they import the board engine, the daemon need not
        from ..jsonstore import StoreError
        total = cs.day_spent(self.base, now)
        records = []
        for ids, load, per_call in ((mt.meeting_ids, mt.load, mt.per_call_limit),
                                    (st.record_ids, st.load, st.per_call_of)):
            for rid in ids():
                try:
                    records.append((per_call, load(rid)))
                except mt.MeetingError:
                    continue
        for per_call, rec in records:
            total += mt.daily_spent([rec], now, per_call)
        try:
            total += mt.daily_spent([try_spend.record()], now, try_spend.turn_cap)      # 「試一下」 of the start-up page
        except StoreError as exc:
            raise ValueError(f"試一下的花費讀不出來（{exc}）") from None
        try:
            for kind in (chief.spend_kind(), memory_suggest.spend_kind()):            # the chief of staff's and the memory suggestions': unreadable is unknown
                ids, load, per_call = kind
                for rid in ids():
                    total += mt.daily_spent([load(rid)], now, per_call)
        except mt.MeetingError as exc:
            raise ValueError(str(exc)) from None
        return total

    def _chat_allowance(self, rid: str, now: float):
        """(the most this turn may cost, the per-turn limit, None) or (None, None, an error answer)."""
        try:
            conf = self._chat_config()
            spent = self._chat_day_spent(now)
        except (OSError, ValueError, UnicodeDecodeError, cs.ChatStoreError, mt.MeetingError) as exc:
            return None, None, _err(rid, "spend_unknown", f"無法確認今天已經花了多少（{exc}），不送出")
        daily = mt.limits_from(conf)["daily_usd"]
        per_turn = cs.limits_from(conf)["per_turn_usd"]
        if mt.lamp(spent, {"daily_usd": daily}) == "red":
            return None, None, _err(rid, "red", f"今天的花費 US${cs.usd(spent)} 已達每日上限 US${cs.usd(daily)}，"
                                          "今天不能再送訊息")
        allowance = min(per_turn, daily - spent).quantize(CENT, rounding=ROUND_DOWN)
        if allowance < CENT:
            return None, None, _err(rid, "budget", "今天剩下的額度不到 US$0.01，不送出")
        return allowance, per_turn, None

    # ---- the ops ----------------------------------------------------------------------------------------------

    def _op_chat_open(self, rid: str, req: dict) -> dict:
        try:
            chat = cs.create(self.base, req.get("profile_id"), now=time.time(),
                             engine=req.get("engine", "claude-chat"))
            cs.ensure_work_dir(self.base, chat["profile_id"])
        except cs.ChatStoreError as exc:
            return _store_err(rid, exc)
        return _ok(rid, {"chat_id": chat["id"], "profile_id": chat["profile_id"], "created_at": chat["created_at"],
                         "engine": chat["engine"]})

    def _op_chat_send(self, rid: str, req: dict) -> dict:
        if self._shutdown_requested:
            return _err(rid, "limit", "背景程序正在關閉，不接受新的訊息")
        python_problem = stream_session.waitid_problem()
        if python_problem:                  # nothing has been started: a process that cannot be watched is never begun
            return _err(rid, "unsupported_python", python_problem)
        chat_id, text, cli, model_id = req.get("chat_id"), req.get("text"), req.get("cli"), req.get("model_id")
        instructions = req.get("instructions")
        origin = req.get("origin")
        if origin is not None and not cs.origin_ok(origin):
            return _err(rid, "bad_request", "origin 格式不符")
        if instructions is not None and agent_sessions.append_prompt_problem(instructions):
            return _err(rid, "bad_request", agent_sessions.append_prompt_problem(instructions))
        memory = None                       # the paragraph for the system prompt, and how many lines are in it
        if req.get("memory") is not None:
            try:
                memory = memory_rules.prepare(req["memory"])
            except memory_rules.MemoryProblem as exc:       # one refused line refuses the message; none is left out quietly
                return _err(rid, "memory_refused" if exc.code == "memory_refused" else "bad_request", str(exc))
        if not isinstance(text, str) or not text.strip():
            return _err(rid, "bad_request", "訊息不能是空的")
        try:
            size = len(text.encode("utf-8"))
        except UnicodeEncodeError:
            return _err(rid, "bad_request", "訊息含有無法編碼的字元")
        if size > cp.MAX_TEXT_BYTES:
            return _err(rid, "bad_request", f"訊息超過 {cp.MAX_TEXT_BYTES // 1024} KiB")
        if model_id is not None and not (isinstance(model_id, str) and agent_sessions.MODEL_ID_RE.match(model_id)):
            return _err(rid, "bad_request", "model_id 格式不符")
        if not (isinstance(cli, dict) and set(cli) == {"binary", "version", "identity"}):
            return _err(rid, "bad_request", "cli 必須是 {binary, version, identity}")
        try:
            chat = cs.load(self.base, chat_id)
        except cs.ChatStoreError as exc:
            return _store_err(rid, exc)
        if req.get("engine") not in (None, chat["engine"]):
            return _err(rid, "bad_request", "這個聊天的引擎和送來的不同")
        send = getattr(self, chat_engines.by_engine(chat["engine"]).daemon_send)
        # only a message sent for a dispatch has an origin; an engine's method that does not know one is called as it was
        extra = {**({"origin": origin} if origin is not None else {}), **({"memory": memory} if memory is not None else {})}
        return send(rid, chat, text, cli, model_id, instructions, **extra)

    # ---- a Claude Code chat -------------------------------------------------------------------------------------

    def _claude_send(self, rid: str, chat: dict, text: str, cli: dict, model_id: str | None,
                     instructions: str | None, origin: dict | None = None, memory=None) -> dict:
        """A person's message in a Claude Code chat: a turn in the chat's live process (its limits as ``headroom``), or in
        a new one (``--resume`` once the session exists)."""
        chat_id = chat["id"]
        if model_id is None:
            return _err(rid, "bad_request", "model_id 格式不符")
        now = time.monotonic()
        p = self._chats.get(chat_id)
        if p is not None:
            if p.state == "closing" or p.phase is not None or p.exit_info is not None or p.finished:
                return _err(rid, "restarting", "這個聊天的程序正在結束，請稍後再送一次")
            if p.turn is not None or p.state == "starting":
                return _err(rid, "busy", "員工還在回覆上一則訊息")
        allowance, per_turn, refused = self._chat_allowance(rid, time.time())
        if refused:
            return refused
        if p is not None:
            # A live process may still spend what its --max-budget-usd leaves. Reused only when that is no more
            # than this turn may cost (else the CLI could spend past it), and at least a cent; the turn's cap is
            # then that headroom.
            headroom = p.headroom()
            if (p.model_id != model_id or p.cli_version != cli.get("version") or headroom > allowance
                    or headroom < CENT):
                p.close_gracefully("模型、版本或額度不同，要換新的程序", now)
                return _err(rid, "restarting", "員工要換新的程序（模型、版本或額度不同），請稍後再送一次")
            allowance = headroom
            try:
                line = cp.user_line(text, p.session_id)
                n = p.next_turn
                p.log.append("user_message", _said(n, text, origin), now=time.time())
                p.log.append("turn_started", {"turn": n, "cap_usd": cs.usd(allowance)}, now=time.time())
            except ValueError as exc:
                return _err(rid, "bad_request", f"訊息無法送出（{exc}）")
            except cs.ChatStoreError as exc:
                p.stop("聊天紀錄無法寫入", now)
                return _store_err(rid, exc)
            p.start_turn(n, allowance, line, now)
            return _ok(rid, {"turn": n, "cap_usd": cs.usd(allowance), "process": "reused"})
        return self._chat_spawn(rid, chat, text, cli, model_id, allowance, per_turn, instructions, origin, memory)

    def _chat_spawn(self, rid: str, chat: dict, text: str, cli: dict, model_id: str, allowance: Decimal,
                    per_turn: Decimal, instructions: str | None = None, origin: dict | None = None, memory=None) -> dict:
        from .daemon import build_env              # here: daemon imports this module
        chat_id, profile_id = chat["id"], chat["profile_id"]
        state, binary, version, identity, refused = self._chat_precheck(rid, chat, cli)
        if refused:
            return refused
        if cp.constants_for(version) is None:
            return _err(rid, "unsupported_version", f"Claude Code {str(version)[:32]} 沒有聊天模式的常數")
        if version not in cli_versions.chat_verified_versions() and version not in self.chat_probe_versions:
            return _err(rid, "unverified", cli_versions.chat_unverified_text(version))
        env = build_env()
        policy = admin_policy.check_claude(version, home=env.get("HOME", ""))
        if not policy.ok:
            return _err(rid, "admin_policy", policy.reason())
        try:
            workdir = cs.ensure_work_dir(self.base, profile_id)
            log = cs.ChatLog(self.base, chat_id)
        except cs.ChatStoreError as exc:
            return _store_err(rid, exc)
        resume = state.session_ready
        n = state.next_turn
        m = None
        try:
            m = agent_sessions.prepare_chat_launch(
                self.base, workdir=workdir, cli_binary=binary, cli_version=version, cli_identity=identity,
                model_id=model_id, chat_id=chat_id, profile_id=profile_id,
                claude_session_id=chat["claude_session_id"], budget_usd=float(allowance), resume=resume,
                append_prompt=memory_rules.combine(instructions, memory.block if memory else None))
            line = cp.user_line(text, chat["claude_session_id"])
            agent_sessions.update_manifest(self.base, m["launch_id"], state="launching")
            m = agent_sessions.load_validated(self.base, m["launch_id"])
            argv = agent_sessions.chat_argv(m)
        except (agent_sessions.LaunchRefused, OSError, ValueError) as exc:
            log.close()
            if m is not None:
                agent_sessions.cleanup_launch(self.base, m["launch_id"], proven_dead=True)
            return _err(rid, getattr(exc, "code", "refused"), str(exc))
        env["CLAUDE_CODE_TMPDIR"] = m["scratch"]["path"]
        env["DISABLE_AUTOUPDATER"] = "1"
        launch_id = m["launch_id"]
        self._log_memory(launch_id, memory, instructions)
        try:
            log.append("user_message", _said(n, text, origin), now=time.time())
            log.append("turn_started", {"turn": n, "cap_usd": cs.usd(allowance)}, now=time.time())
            log.append("process_started", {"mode": "resume" if resume else "new",
                                           "budget_usd": cs.usd(allowance), "instructions": instructions is not None},
                       now=time.time())
        except cs.ChatStoreError as exc:
            self._chat_not_started(log, n, launch_id, "聊天紀錄無法寫入")
            return _store_err(rid, exc)
        try:
            proc = subprocess.Popen(argv, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                    cwd=workdir, env=env, start_new_session=True, close_fds=True)
        except OSError as exc:
            self._chat_not_started(log, n, launch_id, f"無法啟動：{exc}"[:200])
            return _err(rid, "internal", f"無法啟動 Claude Code：{exc}")
        p = leader_start = None
        try:
            leader_start = stream_session.capture_leader(proc.pid)
            if leader_start is None:
                raise RuntimeError("無法取得 leader 的開始時間，這個程序無法安全地管理")
            sid = "n-" + secrets.token_hex(6)
            while sid in self._sessions or any(x.sid == sid for x in list(self._streams.values())
                                               + list(self._chats.values())):
                sid = "n-" + secrets.token_hex(6)
            p = chat_session.ChatProcess(
                sid=sid, chat_id=chat_id, profile_id=profile_id, manifest=m, proc=proc, log=log,
                last_total=state.last_total, next_turn=n, now=time.monotonic(), leader_start=leader_start,
                logger=self._log, watch=self._watch_chat, unwatch=self._unwatch_chat,
                card_ttl=self.chat_card_ttl, init_deadline=self.chat_init_deadline,
                turn_timeout=self.chat_turn_timeout, idle_timeout=self.chat_idle_timeout,
                close_grace=self.chat_close_grace,
                close_below=(per_turn / 2).quantize(CENT))
            self._chats[chat_id] = p
            self._watch_chat(p, "stdout")
            self._watch_chat(p, "stderr")
            try:
                p.descendants.observe(proctrack.process_table())
            except proctrack.ProcessTableUnavailable as exc:
                self._log(f"{sid}: process table unavailable at launch: {exc}")
            agent_sessions.update_manifest(self.base, launch_id, state="running", leader={
                "pid": proc.pid, "start": leader_start, "source": proctrack.SOURCE}, observed=p.descendants.export())
            p.send_initialize()
            p.start_turn(n, allowance, line, time.monotonic())
        except Exception as exc:
            return self._chat_abort_spawned(rid, log, n, m, proc, p, leader_start, f"{type(exc).__name__}: {exc}")
        return _ok(rid, {"turn": n, "cap_usd": cs.usd(allowance), "process": "resume" if resume else "new"})

    # ---- a Codex chat -------------------------------------------------------------------------------------------

    def _codex_send(self, rid: str, chat: dict, text: str, cli: dict, model_id: str | None,
                    instructions: str | None, origin: dict | None = None, memory=None) -> dict:
        """A person's message in a Codex chat (P38-3): a turn in the chat's live ``codex app-server`` (its thread goes
        on), or in a new one (``thread/start`` the first time, ``thread/resume`` after). Money is as for a Claude chat: the
        turn's cap is the per-turn limit or what is left of the day, whichever is less."""
        chat_id = chat["id"]
        now = time.monotonic()
        p = self._chats.get(chat_id)
        if p is not None:
            if p.state == "closing" or p.phase is not None or p.exit_info is not None or p.finished:
                return _err(rid, "restarting", "這個聊天的程序正在結束，請稍後再送一次")
            if p.turn is not None or p.state == "starting":
                return _err(rid, "busy", "員工還在回覆上一則訊息")
        allowance, per_turn, refused = self._chat_allowance(rid, time.time())
        if refused:
            return refused
        if p is None:
            return self._codex_spawn(rid, chat, text, cli, model_id, allowance, instructions, origin, memory)
        if p.model_id != model_id or p.cli_version != cli.get("version"):
            p.close_gracefully("模型或版本不同，要換新的程序", now)
            return _err(rid, "restarting", "員工要換新的程序（模型或版本不同），請稍後再送一次")
        try:
            n = p.next_turn
            p.log.append("user_message", _said(n, text, origin), now=time.time())
            p.log.append("turn_started", {"turn": n, "cap_usd": cs.usd(allowance)}, now=time.time())
        except cs.ChatStoreError as exc:
            p.stop("聊天紀錄無法寫入", now)
            return _store_err(rid, exc)
        p.start_turn(n, allowance, text, now)
        return _ok(rid, {"turn": n, "cap_usd": cs.usd(allowance), "process": "reused"})

    def _codex_followup(self, p, text: str) -> str | None:
        """A card the person changed whose steer Codex refused (its turn was over): the changed text is the next message,
        a new turn of the live process. None when it was sent, else why it was not (said in the chat's record)."""
        if self._chats.get(p.chat_id) is not p or p.state != "idle" or p.turn is not None:
            return "員工的程序已經不能收新的訊息"
        allowance, _per_turn, refused = self._chat_allowance("followup", time.time())
        if refused:
            return refused["error"]["message"]
        now = time.monotonic()
        try:
            n = p.next_turn
            p.log.append("user_message", {"turn": n, "text": text}, now=time.time())
            p.log.append("turn_started", {"turn": n, "cap_usd": cs.usd(allowance)}, now=time.time())
        except cs.ChatStoreError as exc:
            return exc.message
        p.start_turn(n, allowance, text, now)
        return None

    def _codex_spawn(self, rid: str, chat: dict, text: str, cli: dict, model_id: str | None, allowance: Decimal,
                     instructions: str | None, origin: dict | None = None, memory=None) -> dict:
        from .daemon import DAEMON_VERSION, build_env      # here: daemon imports this module
        chat_id, profile_id = chat["id"], chat["profile_id"]
        state, binary, version, identity, refused = self._chat_precheck(rid, chat, cli)
        if refused:
            return refused
        if ccp.constants_for(version) is None:
            return _err(rid, "unsupported_version", f"Codex {str(version)[:32]} 沒有聊天模式的常數")
        if version not in cli_versions.codex_chat_verified_versions() and version not in self.codex_chat_probe_versions:
            return _err(rid, "unverified", cli_versions.codex_chat_unverified_text(version))
        policy = admin_policy.check_codex(version)
        if not policy.ok:
            return _err(rid, "admin_policy", policy.reason())
        # The folder is <state>/codex-chat-home. Only the version check's own daemon (a temporary state folder) names the
        # person's real one in ``codex_chat_home``: Codex gets that login, the launch record still names the nominal folder.
        nominal = str(codex_chat_env.chat_home_path(self.base))
        folder, why = codex_chat_env.home_state(self.base, home=self.codex_chat_home)
        if folder == "missing":
            return _err(rid, "not_logged_in", "聊天用的 Codex 還沒有登入")
        if folder != "ok":
            return _err(rid, "codex_home", why)
        chat_home = self.codex_chat_home or nominal
        if codex_chat_env.login_state(binary, chat_home) != "logged_in":
            return _err(rid, "not_logged_in", "聊天用的 Codex 沒有登入，或查不出有沒有登入")
        try:
            workdir = cs.ensure_work_dir(self.base, profile_id)
            log = cs.ChatLog(self.base, chat_id)
        except cs.ChatStoreError as exc:
            return _store_err(rid, exc)
        if os.path.lexists(os.path.join(workdir, ".codex")):
            log.close()
            return _err(rid, "invalid_workdir", "員工的工作資料夾裡有 .codex，VBear 不讓 Codex 在那裡聊天")
        thread_id = state.thread_id
        resume = thread_id is not None
        n = state.next_turn
        m = None
        try:
            m = agent_sessions.prepare_codex_chat_launch(
                self.base, workdir=workdir, cli_binary=binary, cli_version=version, cli_identity=identity,
                model_id=model_id, chat_id=chat_id, profile_id=profile_id, resume=resume, thread_id=thread_id,
                codex_home=nominal)
            agent_sessions.update_manifest(self.base, m["launch_id"], state="launching")
            m = agent_sessions.load_validated(self.base, m["launch_id"])
            argv = agent_sessions.codex_chat_argv(m)
            env = agent_sessions.codex_chat_env(m, build_env(user_bin=False))
            env["CODEX_HOME"] = chat_home
        except (agent_sessions.LaunchRefused, OSError, ValueError) as exc:
            log.close()
            if m is not None:
                agent_sessions.cleanup_launch(self.base, m["launch_id"], proven_dead=True)
            return _err(rid, getattr(exc, "code", "refused"), str(exc))
        launch_id = m["launch_id"]
        self._log_memory(launch_id, memory, instructions)
        try:
            log.append("user_message", _said(n, text, origin), now=time.time())
            log.append("turn_started", {"turn": n, "cap_usd": cs.usd(allowance)}, now=time.time())
            log.append("process_started", {"mode": "resume" if resume else "new", "budget_usd": cs.usd(allowance),
                                           "instructions": instructions is not None}, now=time.time())
        except cs.ChatStoreError as exc:
            self._chat_not_started(log, n, launch_id, "聊天紀錄無法寫入")
            return _store_err(rid, exc)
        try:
            proc = subprocess.Popen(argv, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                    cwd=workdir, env=env, start_new_session=True, close_fds=True)
        except OSError as exc:
            self._chat_not_started(log, n, launch_id, f"無法啟動：{exc}"[:200])
            return _err(rid, "internal", f"無法啟動 Codex：{exc}")
        p = leader_start = None
        try:
            leader_start = stream_session.capture_leader(proc.pid)
            if leader_start is None:
                raise RuntimeError("無法取得 leader 的開始時間，這個程序無法安全地管理")
            sid = "n-" + secrets.token_hex(6)
            while sid in self._sessions or any(x.sid == sid for x in list(self._streams.values())
                                               + list(self._chats.values())):
                sid = "n-" + secrets.token_hex(6)
            p = codex_chat_session.CodexChatProcess(
                sid=sid, chat_id=chat_id, profile_id=profile_id, manifest=dict(m, codex_home=chat_home), proc=proc, log=log,
                next_turn=n,
                now=time.monotonic(), leader_start=leader_start, logger=self._log, watch=self._watch_chat,
                unwatch=self._unwatch_chat, card_ttl=self.chat_card_ttl, init_deadline=self.chat_init_deadline,
                turn_timeout=self.chat_turn_timeout, idle_timeout=self.chat_idle_timeout,
                close_grace=self.chat_close_grace, close_below=Decimal(0),
                instructions=memory_rules.combine(instructions, memory.block if memory else None),
                thread_id=thread_id, last_tokens=state.last_tokens, followup=self._codex_followup,
                client_version=DAEMON_VERSION)
            self._chats[chat_id] = p
            self._watch_chat(p, "stdout")
            self._watch_chat(p, "stderr")
            try:
                p.descendants.observe(proctrack.process_table())
            except proctrack.ProcessTableUnavailable as exc:
                self._log(f"{sid}: process table unavailable at launch: {exc}")
            agent_sessions.update_manifest(self.base, launch_id, state="running", leader={
                "pid": proc.pid, "start": leader_start, "source": proctrack.SOURCE}, observed=p.descendants.export())
            p.send_initialize()
            p.start_turn(n, allowance, text, time.monotonic())
        except Exception as exc:
            return self._chat_abort_spawned(rid, log, n, m, proc, p, leader_start, f"{type(exc).__name__}: {exc}")
        return _ok(rid, {"turn": n, "cap_usd": cs.usd(allowance), "process": "resume" if resume else "new"})

    def _log_memory(self, launch_id: str, memory, instructions) -> None:
        """One line a real-machine check can read: how many lines of memory the new process was given (none: the field was
        not sent) and whether the card has instructions of its own. Never a word of either."""
        count = "none" if memory is None else str(memory.count)
        self._log(f"{launch_id}: chat process memory entries={count} instructions={'yes' if instructions is not None else 'no'}")

    def _chat_precheck(self, rid: str, chat: dict, cli: dict):
        """What a new process of either engine needs first: (the chat's state, binary, version, identity, None), or
        (.., an error answer). The record reads whole and has no open turn or process, the role card has no other chat
        running, there is room for another process, no earlier launch of the chat waits for a person, and the CLI is
        the file that was checked."""
        chat_id, profile_id = chat["id"], chat["profile_id"]
        try:
            events = cs.read_events(self.base, chat_id)
        except cs.ChatStoreError as exc:
            return None, None, None, None, _store_err(rid, exc)
        if events.problem:
            return None, None, None, None, _err(rid, "damaged", f"聊天紀錄有問題，不能再送訊息（{events.problem}）")
        state = cs.derive(events.records)
        if state.open_turn is not None or state.process_open:
            return None, None, None, None, _err(rid, "busy", "這個聊天還有沒結束的回合或程序")
        same = [x for x in self._chats.values() if x.profile_id == profile_id]
        if same:
            if same[0].idle:
                same[0].close_gracefully("同一位員工要開另一個聊天", time.monotonic())
                return None, None, None, None, _err(rid, "restarting", "這位員工在另一個聊天裡的程序正在關閉，請稍後再送一次")
            return None, None, None, None, _err(rid, "busy", "這位員工正在另一個聊天裡工作，一次只能一個")
        if len(self._chats) >= self.chat_max:
            idle = sorted((x for x in self._chats.values() if x.idle), key=lambda x: x.last_activity)
            if idle:
                idle[0].close_gracefully("同時聊天的員工太多，關閉最久沒用的", time.monotonic())
                return None, None, None, None, _err(rid, "restarting", "同時聊天的員工已達上限，正在關閉最久沒用的，請稍後再送一次")
            return None, None, None, None, _err(rid, "limit", f"同時最多 {self.chat_max} 位員工在聊天")
        room = self._session_room(rid)
        if room:
            return None, None, None, None, room
        pending = self._chat_launches_left(chat_id)
        if pending:
            return None, None, None, None, _err(rid, "manual_review", f"這個聊天之前的程序還沒確認結束（{pending}），需要人工處理")
        binary, version, identity = cli["binary"], cli["version"], cli["identity"]
        try:
            if not (isinstance(binary, str) and os.path.isabs(binary) and os.path.realpath(binary) == binary):
                raise agent_sessions.LaunchRefused("invalid_binary", "CLI 必須是已解析的絕對路徑")
            if not (isinstance(identity, list) and identity == agent_sessions.binary_identity(binary)):
                raise agent_sessions.LaunchRefused("drift", "CLI 檔案在版本檢查後已改變")
        except OSError:
            return None, None, None, None, _err(rid, "drift", "CLI 檔案已消失或不可執行")
        except agent_sessions.LaunchRefused as exc:
            return None, None, None, None, _err(rid, exc.code, str(exc))
        return state, binary, version, identity, None

    def _chat_not_started(self, log: cs.ChatLog, n: int, launch_id: str, why: str) -> None:
        """No process was started for this turn: it costs nothing, and the launch goes."""
        for kind, data in (("turn_ended", {"turn": n, "cost_usd": "0", "reported": False, "total_usd": None,
                                           "reason": "not_sent", "subtype": None, "is_error": True}),
                           ("process_ended", {"reason": why[:cs.MAX_SHORT], "returncode": None})):
            try:
                log.append(kind, data, now=time.time())
            except cs.ChatStoreError:
                pass
        log.close()
        agent_sessions.cleanup_launch(self.base, launch_id, proven_dead=True)

    def _chat_abort_spawned(self, rid, log, n, m, proc, p, leader_start, why) -> dict:
        """The process started but could not be set up (as for a stream, review B2): ended after the identity check
        and proven gone, or kept for a person. Its message was never written, so the turn costs nothing."""
        launch_id = m["launch_id"]
        self._log(f"{launch_id}: chat set-up after spawn failed ({why}); ending the process")
        if p is not None:
            for which in list(p.registered):
                self._unwatch_chat(p, which)
        self._chats.pop(m["chat_id"], None)
        problem = stream_session.end_spawned(proc, leader_start, p.descendants if p is not None else None)
        for f in (proc.stdin, proc.stdout, proc.stderr):
            try:
                f.close()
            except OSError:
                pass
        for kind, data in (("turn_ended", {"turn": n, "cost_usd": "0", "reported": False, "total_usd": None,
                                           "reason": "not_sent", "subtype": None, "is_error": True}),
                           ("process_ended", {"reason": f"啟動後初始化失敗：{why}"[:cs.MAX_SHORT],
                                              "returncode": None})):
            try:
                log.append(kind, data, now=time.time())
            except cs.ChatStoreError:
                pass
        log.close()
        if problem is None:
            agent_sessions.cleanup_launch(self.base, launch_id, proven_dead=True)
        else:
            agent_sessions._retain(self.base, launch_id, f"啟動後初始化失敗（{why}）；{problem}")
            self._hold_leader(proc, launch_id)
        return _err(rid, "internal", f"啟動後初始化失敗：{why}")

    def _chat_launches_left(self, chat_id: str) -> str:
        """The chat's launches still in sessions/ that are not merely prepared (manual review, or left by a previous
        daemon): a new process waits until a person has looked. "" when there are none."""
        root = agent_sessions.sessions_root(self.base)
        try:
            names = sorted(os.listdir(root))
        except FileNotFoundError:
            return ""
        except OSError as exc:
            return f"sessions/ 無法列出（{exc.strerror}）"
        left = []
        for name in names:
            if not agent_sessions.LAUNCH_RE.match(name):
                continue
            try:
                m = agent_sessions._read_manifest(agent_sessions.launch_dir(self.base, name), os.getuid())
            except (OSError, agent_sessions.LaunchRefused):
                continue                          # another launch's problem; recovery reports it
            if chat_engines.is_chat_engine(m.get("engine")) and m.get("chat_id") == chat_id \
                    and m.get("state") != "prepared":
                left.append(name)
        return ", ".join(left[:4])

    def _op_chat_answer(self, rid: str, req: dict) -> dict:
        p = self._chats.get(req.get("chat_id")) if isinstance(req.get("chat_id"), str) else None
        if p is None or p.finished:
            return _err(rid, "gone", "這個聊天沒有在等回覆的卡片")
        code, message = p.answer(req.get("card_id"), req.get("token"), req.get("decision"), req.get("value"),
                                 time.monotonic())
        if code:
            return _err(rid, code, message)
        return _ok(rid, {"answered": req.get("card_id")})

    def _op_chat_stop(self, rid: str, req: dict) -> dict:
        p = self._chats.get(req.get("chat_id")) if isinstance(req.get("chat_id"), str) else None
        if p is None or p.finished:
            return _ok(rid, {"stopped": False})
        p.stop("你按了停止", time.monotonic())
        return _ok(rid, {"stopped": True})

    def _op_chat_close(self, rid: str, req: dict) -> dict:
        p = self._chats.get(req.get("chat_id")) if isinstance(req.get("chat_id"), str) else None
        if p is None or p.finished:
            return _ok(rid, {"closed": False})
        if not p.idle and p.state != "closing":
            return _err(rid, "busy", "員工還在回覆，請先停止這回合")
        p.close_gracefully("你關閉了這個聊天", time.monotonic())
        return _ok(rid, {"closed": True})

    def _op_chat_delete(self, rid: str, req: dict) -> dict:
        chat_id = req.get("chat_id")
        if isinstance(chat_id, str) and chat_id in self._chats:
            return _err(rid, "busy", "這個聊天的程序還在，請先關閉")
        if isinstance(chat_id, str) and cs.CHAT_RE.match(chat_id):
            pending = self._chat_launches_left(chat_id)
            if pending:
                return _err(rid, "manual_review", f"這個聊天之前的程序還沒確認結束（{pending}），需要人工處理")
        try:
            cs.delete(self.base, chat_id, now=time.time())
        except cs.ChatStoreError as exc:
            return _store_err(rid, exc)
        return _ok(rid, {"deleted": chat_id})

    def _op_chat_events(self, rid: str, req: dict) -> dict:
        after = req.get("after", 0)
        if not (isinstance(after, int) and not isinstance(after, bool) and 0 <= after <= 10 ** 9):
            return _err(rid, "bad_request", "after 必須是非負整數")
        chat_id = req.get("chat_id")
        try:
            ev = cs.read_events(self.base, chat_id, after=after, limit=EVENTS_PAGE)
        except cs.ChatStoreError as exc:
            return _store_err(rid, exc)
        p = self._chats.get(chat_id)
        live = p.live_view(time.monotonic()) if p is not None and not p.finished else None
        records, used = [], len(json.dumps(live, ensure_ascii=False).encode("utf-8"))
        for rec in ev.records:
            size = len(json.dumps(rec, ensure_ascii=False).encode("utf-8"))
            if records and used + size > REPLY_BUDGET:
                break
            if not records and used + size > REPLY_BUDGET:
                rec, size = _shortened(rec, REPLY_BUDGET - used)
            records.append(rec)
            used += size
        next_after = records[-1]["seq"] if records else after
        return _ok(rid, {"records": records, "next_after": next_after, "last_seq": ev.last_seq,
                         "more": next_after < ev.last_seq, "problem": ev.problem, "live": live})

    # ---- the loop -----------------------------------------------------------------------------------------------

    def _watch_chat(self, p, which: str) -> None:
        if which in p.registered or p.finished or (which == "stdin" and not p.stdin_open):
            return
        fd = {"stdin": p.stdin, "stdout": p.stdout, "stderr": p.stderr}[which]
        events = selectors.EVENT_WRITE if which == "stdin" else selectors.EVENT_READ
        self._sel.register(fd, events, ("chat", p, which))
        p.registered.add(which)

    def _unwatch_chat(self, p, which: str) -> None:
        if which not in p.registered:
            return
        fd = {"stdin": p.stdin, "stdout": p.stdout, "stderr": p.stderr}[which]
        try:
            self._sel.unregister(fd)
        except (KeyError, ValueError, OSError):
            pass
        p.registered.discard(which)

    def _chat_ready(self, p, which: str, now: float) -> None:
        try:
            if which == "stdout":
                p.on_stdout(now)
            elif which == "stderr":
                p.on_stderr(now)
            elif p.on_writable(now):
                self._unwatch_chat(p, "stdin")
        except Exception as exc:
            self._chat_crashed(p, exc)

    def _chat_tick(self, now: float) -> None:
        for p in list(self._chats.values()):
            if self._chats.get(p.chat_id) is not p:
                continue
            try:
                p.tick(now)
                if p.wants_write:
                    self._watch_chat(p, "stdin")
                else:
                    self._unwatch_chat(p, "stdin")
                if p.stdout_eof:
                    self._unwatch_chat(p, "stdout")
                if p.stderr_eof:
                    self._unwatch_chat(p, "stderr")
                if p.finished:
                    self._finish_chat(p)
            except Exception as exc:
                self._chat_crashed(p, exc)

    def _finish_chat(self, p) -> None:
        for which in list(p.registered):
            self._unwatch_chat(p, which)
        outcome = p.outcome if isinstance(p.outcome, dict) else {"manual_review": "聊天程序結束時沒有留下結果",
                                                                  "leader_held": not p.reaped}
        if outcome.get("manual_review"):
            agent_sessions._retain(self.base, p.launch_id, outcome["manual_review"])
            self._log(f"{p.sid}: chat process retained for manual review: {outcome['manual_review']}")
        else:
            result = agent_sessions.cleanup_launch(self.base, p.launch_id, proven_dead=True)
            self._log(f"{p.sid}: chat process ended ({'cleaned' if result.get('cleaned') else result})")
        if outcome.get("leader_held"):
            self._hold_leader(p.proc, p.launch_id)
        self._chats.pop(p.chat_id, None)

    def _chat_crashed(self, p, exc: Exception) -> None:
        """Never out of the loop: the chat process is given up to a person without a signal, as a stream is."""
        why = f"管理聊天程序時發生未預期的錯誤（{type(exc).__name__}）"
        for step in (lambda: self._log(f"{p.launch_id}: {why}"),
                     lambda: p._abandon(f"{why}，交人工處理") if not p.finished else None,
                     lambda: self._end_after_crash(p, why)):
            try:
                step()
            except Exception:
                pass
        try:
            self._finish_chat(p)
        except Exception:
            for step in (lambda: [self._unwatch_chat(p, w) for w in list(p.registered)],
                         lambda: agent_sessions._retain(self.base, p.launch_id, why),
                         lambda: self._hold_leader(p.proc, p.launch_id) if not p.reaped else None):
                try:
                    step()
                except Exception:
                    pass
            self._chats.pop(p.chat_id, None)

    def _end_after_crash(self, p, why: str) -> None:
        """An unexpected error must not leave a process behind. After the identity check (the same one a launch that
        could not be set up goes through) its group is killed, the leader seen to exit, the group proven empty and the
        leader reaped; the launch is then cleaned up as an ended one, not kept. When any of that cannot be shown (the
        check fails, the table cannot be read, a descendant left the group, or the check itself fails) nothing more is
        signalled and the process stays with a person, as before."""
        outcome = p.outcome
        if p.reaped or not isinstance(outcome, dict) or not outcome.get("leader_held"):
            return
        try:
            problem = stream_session.end_spawned(p.proc, p.leader_start, p.descendants)
        except Exception as exc:
            self._log(f"{p.launch_id}: 無法在錯誤之後結束程序（{type(exc).__name__}），交人工處理")
            return
        if problem:
            self._log(f"{p.launch_id}: 錯誤之後沒有結束程序：{problem}")
            return
        p.reaped = True
        p.outcome = dict(outcome, manual_review=None, leader_held=False,
                         close_reason=outcome.get("close_reason") or why)
        self._log(f"{p.launch_id}: 程序已在錯誤之後結束並回收（{why}）")

    def _kill_all_chats(self) -> None:
        """Daemon shutdown: every open turn costs its cap; nobody could manage the processes afterwards."""
        chats = list(self._chats.values())
        for p in chats:
            try:
                p.stop("背景程序關閉", time.monotonic())
            except Exception as exc:
                self._chat_crashed(p, exc)
        chats = [p for p in chats if self._chats.get(p.chat_id) is p]
        deadline = time.monotonic() + stream_session.TERM_GRACE + stream_session.KILL_GRACE + 2.0
        while chats and time.monotonic() < deadline:
            for p in chats:
                try:
                    for which in ("stdout", "stderr"):
                        if which in p.registered:
                            getattr(p, "on_" + which)(time.monotonic())
                    p.tick(time.monotonic())
                    if p.finished:
                        self._finish_chat(p)
                except Exception as exc:
                    self._chat_crashed(p, exc)
            chats = [p for p in chats if not p.finished and self._chats.get(p.chat_id) is p]
            time.sleep(0.05)
        for p in chats:
            self._chat_crashed(p, RuntimeError("關閉時程序沒有結束"))

    def _recover_chats(self) -> None:
        """Daemon start: a turn or process a previous daemon left open is closed, each turn at its cap."""
        try:
            for chat_id in cs.recover(self.base, now=time.time()):
                self._log(f"chat {chat_id}: an unfinished turn or process of a previous daemon closed at its cap")
        except Exception as exc:
            self._log(f"chat recovery failed: {type(exc).__name__}: {exc}")


def _shortened(rec: dict, room: int) -> tuple[dict, int]:
    """A copy of one record whose text fields are cut so that it fits ``room`` bytes, marked view_truncated (the
    record itself is unchanged)."""
    out = dict(rec, view_truncated=True)
    for name in ("text", "summary", "message", "value"):
        if isinstance(out.get(name), str):
            out[name] = ""
    if isinstance(out.get("input"), dict):
        out["input"] = {}
    base = len(json.dumps(out, ensure_ascii=False).encode("utf-8"))
    for name in ("text", "summary", "message", "value"):
        if isinstance(rec.get(name), str):
            keep = rec[name]
            while keep and base + len(json.dumps(keep, ensure_ascii=False).encode("utf-8")) > room:
                keep = keep[: len(keep) // 2]
            out[name] = keep
            base = len(json.dumps(out, ensure_ascii=False).encode("utf-8"))
    return out, base
