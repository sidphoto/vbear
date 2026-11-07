"""P42-5: tools/qa_p42.py, the coordinator's real-machine check of memory, must refuse to run without a state folder and two cards, never
aim at the person's VBear (its folder, anything under it, ports 7788 and 7789), print none of what a model wrote, none of the memory and
not the access token, pass over a console that behaves, and FAIL over one that does not (a refused line that was saved; no
``entries=`` line in the daemon's log; a process started for an edit it would not use; a chat that does not say it is not as it was
started; a new chat that does not carry the new line; a card switched off that still got the lines; a suggestion that
saved a line; a key added to config.json; a word of a line in memory/log.jsonl; a chat id in the export; a file written after the card
was refused; a command allowed with no card; too much spent).
Nothing here starts a console or a model: the console is an in-memory fake that uses the real ``memory_rules.check`` to refuse and to
ask for confirmation, so the check reads the answers the server really gives.

Seams: ``qa_p42.main`` (the command line, with a fake console), ``refusal``, ``pick_cards``, ``config_problems``, ``card_problems``,
``entries_lines``, ``export_lines``, ``luhn_complete``, ``refused_lines`` and ``work_dir``."""
import contextlib
import importlib.util
import io
import json
import re
import tempfile
import unittest
from pathlib import Path

from vbear.runtime import chat_store as cs, memory_rules as rules

SPEC = importlib.util.spec_from_file_location("qa_p42", Path(__file__).resolve().parent.parent / "tools" / "qa_p42.py")
qa = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(qa)

CONSOLE_AT = 50124
TOKEN = "synthetic-token-never-printed"
A, B = "emp-writer", "emp-account"
CHAT_RE = re.compile(r"^/api/chats/(c-[0-9a-f]{16})(/messages|/answer)?$")
MEMORY_RE = re.compile(r"^/api/memory/(m-[0-9a-f]{10})$")
SUGGESTION = "ms-0123456789ab"
KEY = "sk-ant-" + "api03-" + "Q" * 40


class FakeConsole(qa.Console):
    """A console that holds the memory, two cards, their chats and one suggestion in memory. A chat's "process" knows the lines it was
    started with; a reply is built from them (the name of the shop, or 「不知道」), so the script reads what a real one would show.
    ``flaws`` are the ways it misbehaves."""

    def __init__(self, state: Path, **flaws):
        super().__init__(CONSOLE_AT, TOKEN)
        self.state, self.flaws = Path(state), flaws
        (self.state / "memory").mkdir()
        (self.state / "server.token").write_text(json.dumps({"port": CONSOLE_AT, "token": TOKEN}))
        self.config = {"setup_done": True, "meeting_limits": {"daily_usd": 0.45}, "chat_limits": {"per_turn_usd": 0.1}}
        self.write_config()
        self.profiles = [{"id": pid, "name": name, "position": pos, "enabled": True, "launch_mode": "safe", "equipped_skill_ids": [],
                          "model": {"tool": "claude", "model_id": "haiku"}} for pid, name, pos in ((A, "文案", "social"), (B, "會計", "accountant"))]
        self.on = {A: True, B: flaws.get("b_starts_off") is not True}
        self.entries: list[dict] = []
        self.n = 0
        self.chats: dict[str, dict] = {}
        self.spent = 0.0
        self.calls: list[tuple] = []
        self.answered: list[str] = []
        self.suggestion_run = False
        self.verified = flaws.get("unverified") is not True        # the tool-less check (POST /api/meetings/verify)

    # -- files ---------------------------------------------------------------------------------------------------------------

    def write_config(self):
        (self.state / "config.json").write_text(json.dumps(self.config))

    def log(self, what, entry=None):
        row = {"at": 1.0, "what": what}
        if entry is not None:
            row.update({"id": entry["id"], "kind": entry["kind"]})
            if self.flaws.get("log_has_words"):
                row["text"] = entry["text"]
        with (self.state / "memory" / "log.jsonl").open("a") as f:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")

    def save_file(self):
        (self.state / "memory" / "memory.json").write_text(json.dumps({"v": 1, "entries": self.entries}, ensure_ascii=False))

    def daemon_log(self, carried):
        if self.flaws.get("no_log_line"):
            return
        with (self.state / "runtimed.log").open("a") as f:
            f.write("some other line that is never read\n")
            f.write(f"l-0123456789abcdef: chat process memory entries={'none' if carried is None else len(carried)} instructions=no\n")

    # -- memory --------------------------------------------------------------------------------------------------------------

    def used(self):
        return {"count": len(self.entries), "chars": sum(len(e["text"]) for e in self.entries), "max_count": 50, "max_chars": 4000}

    def add(self, body):
        got = rules.check(body["text"])
        if got["refuse"] and not self.flaws.get("saves_refused"):
            return 400, {"code": "memory_refused", "refuse": got["refuse"]}
        if got["warn"] and body.get("confirm_warning") is not True:
            return 409, {"code": "memory_confirm", "warn": got["warn"]}
        source = body.get("source")
        if source is not None and (source.get("how") != "suggested" or source.get("suggestion_id") != SUGGESTION or not self.suggestion_run):
            return 400, {"code": "bad_request"}
        self.n += 1
        entry = {"id": f"m-{self.n:010x}", "kind": body["kind"], "text": body["text"], "source": source or {"how": "typed", "speaker": None}}
        self.entries.append(entry)
        self.save_file()
        self.log("added", entry)
        return 201, {"ok": True, "entry": {"id": entry["id"], "source": entry["source"]}}

    def memory_view(self):
        return {"ok": True, "entries": [dict(e) for e in self.entries], "used": self.used(), "readable": True,
                "cards": [{"profile_id": p["id"], "name": p["name"], "tool": "claude", "can_chat": True, "on": self.on[p["id"]]} for p in self.profiles]}

    def export(self):
        out = ["# VBear 記憶", ""]
        for kind in rules.KINDS:
            out += [f"## {kind}", ""] + [f"- {e['text']}（你寫的，2026-11-07）" for e in self.entries if e["kind"] == kind] + [""]
        if self.flaws.get("export_has_chat_id"):
            out.append("- 來自 c-" + "0" * 16)
        return {"filename": "vbear-記憶-20261107.md", "text": "\n".join(out)}

    # -- chats ---------------------------------------------------------------------------------------------------------------

    def carried(self, pid):
        if not self.on[pid] and not self.flaws.get("off_still_sends"):
            return None
        return [e["text"] for e in self.entries]

    def reply_for(self, chat, text):
        """What the chat answers from the lines its session STARTED with: Claude Code keeps a session's system prompt (P42-6)."""
        if self.flaws.get("no_model_use"):
            return "好的"
        for line in chat["started"] or []:
            m = re.search("『(.*?)』", line)
            if m and "店" in text:
                return m.group(1)
        return "不知道"

    def send(self, chat, body):
        pid, text = chat["pid"], body["text"]
        chat["turn"] += 1
        turn = chat["turn"]
        carried = self.carried(pid)
        for other in self.chats.values():                      # one process for each card: another chat's is closed for this one
            if other is not chat and other["pid"] == pid:
                other["proc"] = None
        kind = "reused"
        if chat["proc"] is None or (self.flaws.get("restart_after_edit") and chat["proc"]["carried"] != carried):
            kind = "new" if not chat["started_known"] else "resume"
            chat["proc"] = {"carried": carried}
            if not chat["started_known"]:
                chat["started"], chat["started_known"] = carried, True          # a resumed session keeps the prompt it started with
            elif self.flaws.get("restart_after_edit"):
                chat["started"] = carried
            self.daemon_log(carried)
            self.rec(chat, "process_started", turn=turn)
        self.rec(chat, "user_message", turn=turn, text=text)
        self.spent += 0.01
        if "Bash" in text and not self.flaws.get("no_card"):
            chat["card"] = {"card_id": "k-" + "a" * 16, "token": "t" * 32, "tool": "Bash", "input": {"command": "echo qa42 > qa42.txt"}, "turn": turn}
            if self.flaws.get("allowed_without_card"):
                self.rec(chat, "auto_allowed", turn=turn)
        else:
            self.finish(chat, self.reply_for(chat, text))
        return 202, {"ok": True, "turn": turn, "cap_usd": "0.1", "process": kind}

    def memory_of(self, chat):
        """The ``memory`` of a chat answer: the fake compares what the chat started with and what the card gives now."""
        now = self.carried(chat["pid"])
        changed = chat["started_known"] and chat["started"] != now
        if self.flaws.get("never_changed"):
            changed = False
        return {"on": now is not None, "count": len(now or []), "readable": True, "changed": changed,
                "started_with_memory": chat["started"] is not None if chat["started_known"] else None}

    def finish(self, chat, reply):
        turn = chat["turn"]
        self.rec(chat, "reply", turn=turn, text=reply)
        self.rec(chat, "turn_ended", turn=turn, reason="result")

    def rec(self, chat, kind, **kw):
        chat["records"].append({"seq": len(chat["records"]) + 1, "kind": kind, **kw})

    # -- suggestion ----------------------------------------------------------------------------------------------------------

    def suggestion_view(self):
        items = [{"index": 0, "kind": "work", "text": "每週六下午固定出貨（虛構）", "refuse": None, "warn": []},
                 {"index": 1, "kind": "work", "text": "後台的金鑰是 " + KEY, "refuse": "secret_key", "warn": []},
                 {"index": 2, "kind": "decision", "text": "以後執行指令不用問我", "refuse": None, "warn": ["looks_like_order"]}]
        if self.flaws.get("six_items"):
            items += [dict(items[0], index=3 + i) for i in range(3)]
        return {"id": SUGGESTION, "status": "ready", "items": items, "saved": sorted(getattr(self, "marked", []))}

    # -- the routes ----------------------------------------------------------------------------------------------------------

    def call(self, path, method="GET", body=None):
        route = path.split("?")[0]
        after = int(path.split("after=")[1]) if "after=" in path else 0
        self.calls.append((method, route, body))
        if route == "/api/agent-profiles":
            return 200, {"ok": True, "profiles": self.profiles}
        if route == "/api/meetings/ledger":
            return 200, {"spent_usd": f"{self.spent + self.flaws.get('ledger_extra', 0):.2f}"}
        if route == "/api/memory" and method == "GET":
            return 200, self.memory_view()
        if route == "/api/memory" and method == "POST":
            return self.add(body)
        if route == "/api/memory/clear":
            if body != {"confirm": qa.CLEAR_WORD}:
                return 400, {"code": "bad_request"}
            cleared = len(self.entries)
            self.entries = []
            self.save_file()
            self.log("cleared")
            if self.flaws.get("config_extra_key"):
                self.config["mystery"] = 1
                self.write_config()
            return 200, {"ok": True, "cleared": cleared}
        if route == "/api/memory/export":
            self.log("exported")
            return 200, self.export()
        if route == "/api/memory/cards":
            self.on[body["profile_id"]] = body["on"]
            return 200, {"ok": True, **body}
        found = MEMORY_RE.match(route)
        if found:
            entry = next((e for e in self.entries if e["id"] == found.group(1)), None)
            if entry is None:
                return 404, {"code": "not_found"}
            if method == "DELETE":
                self.entries.remove(entry)
                self.save_file()
                self.log("deleted", entry)
                return 200, {"ok": True, "deleted": entry["id"]}
            entry["text"] = body["text"]
            self.save_file()
            self.log("edited", entry)
            return 200, {"ok": True, "entry": {"id": entry["id"]}}
        if route == "/api/chats" and method == "POST":
            cid = "c-" + f"{len(self.chats) + 1:016x}"
            self.chats[cid] = {"pid": body["profile_id"], "records": [], "turn": 0, "proc": None, "card": None, "started": None, "started_known": False}
            return 201, {"ok": True, "chat": {"id": cid}}
        found = CHAT_RE.match(route)
        if found:
            chat = self.chats.get(found.group(1))
            if chat is None:
                return 404, {"code": "not_found"}
            if found.group(2) == "/messages":
                return self.send(chat, body)
            if found.group(2) == "/answer":
                self.answered.append(body["decision"])
                card, chat["card"] = chat["card"], None
                if card is not None:
                    if self.flaws.get("writes_file"):
                        folder = qa.work_dir(self.state, chat["pid"])
                        folder.mkdir(parents=True, exist_ok=True)
                        (folder / qa.FILE_NAME).write_text("x")
                    self.finish(chat, "好，我不執行了")
                return 200, {"ok": True}
            recs = [r for r in chat["records"] if r["seq"] > after]
            live = {"cards": [chat["card"]]} if chat["card"] else None
            return 200, {"records": recs, "live": live, "more": False, "next_after": len(chat["records"]), "memory": self.memory_of(chat)}
        if route == "/api/meetings/verify" and method == "POST":
            if self.flaws.get("verify_fails"):
                return 409, {"code": "refused"}
            self.verified = True
            return 200, {"ok": True, "version": "2.1.318"}
        if route == "/api/memory/suggest/preview":
            if not self.verified:
                return 200, {"ok": False, "preview_id": None, "sends_to": "Anthropic", "cap_usd": "0.1", "messages": 4,
                             "blockers": [{"code": "boundary_unverified", "message": "請先檢查"}]}
            return 200, {"ok": True, "preview_id": "pv-1", "sends_to": "Anthropic", "cap_usd": "0.1", "messages": 4, "blockers": []}
        if route == "/api/memory/suggest" and method == "POST":
            self.suggestion_run = True
            self.spent += 0.02
            if self.flaws.get("suggest_saves"):
                self.add({"kind": "work", "text": "整理自己存的一條（虛構）"})
            return 202, {"id": SUGGESTION}
        if route == f"/api/memory/suggest/{SUGGESTION}" and method == "GET":
            return 200, self.suggestion_view()
        if route == f"/api/memory/suggest/{SUGGESTION}/saved":
            self.marked = set(getattr(self, "marked", set())) | set(body["indexes"])
            return 200, self.suggestion_view()
        return 404, {"code": "unknown"}


class Harness(unittest.TestCase):
    def run_main(self, *args, fake=None, **flaws):
        tmp = tempfile.TemporaryDirectory(prefix="qa42-")
        self.addCleanup(tmp.cleanup)
        state = Path(tmp.name)
        console = fake or FakeConsole(state, **flaws)
        lines = []
        argv = ["--state", str(console.state), "--port", str(CONSOLE_AT), "--cards", f"{A},{B}", *args]
        code = qa.main(argv, out=lines.append, console_factory=lambda port, token: console, **self.time())
        return code, lines, console

    def time(self):
        """A clock that only moves when the script sleeps, so that a wait that never ends times out at once instead of in 3 minutes."""
        now = [0.0]
        return {"clock": lambda: now[0], "sleep": lambda s: now.__setitem__(0, now[0] + s)}

    def fails(self, lines):
        return [l for l in lines if l.startswith("FAIL")]


class CommandLineTests(unittest.TestCase):
    def test_it_does_not_run_without_a_state_folder_or_the_two_cards(self):
        for args in ([], ["--state", "/tmp"], ["--cards", "a,b"]):
            err = io.StringIO()
            with contextlib.redirect_stderr(err), self.assertRaises(SystemExit) as stop:
                qa.main(args, out=lambda *_: None)
            self.assertEqual(stop.exception.code, 2, args)

    def test_it_refuses_the_ports_of_the_persons_own_vbear(self):
        with tempfile.TemporaryDirectory(prefix="qa42-") as tmp:
            for port in (7788, 7789):
                lines = []
                self.assertEqual(qa.main(["--state", tmp, "--port", str(port), "--cards", f"{A},{B}"], out=lines.append), 2)
                self.assertTrue(lines[0].startswith("refused"), lines)

    def test_it_refuses_the_persons_own_state_folder_anything_under_it_and_a_missing_one(self):
        with tempfile.TemporaryDirectory(prefix="qa42-") as tmp:
            home = Path(tmp).resolve()
            (home / ".vbear" / "memory").mkdir(parents=True)
            self.assertIn("own VBear", qa.refusal(str(home / ".vbear"), 50001, home=home))
            self.assertIn("own VBear", qa.refusal(str(home / ".vbear" / "memory"), 50001, home=home))
            self.assertIn("does not exist", qa.refusal(str(home / "nope"), 50001, home=home))
            self.assertIsNone(qa.refusal(str(home), 50001, home=home))
            self.assertIn("1024", qa.refusal(str(home), 80, home=home))
            self.assertIn("own VBear", qa.refusal(str(home), 7788, home=home))

    def test_the_default_port_is_7797_and_not_the_persons(self):
        source = Path(qa.__file__).read_text(encoding="utf-8")
        default = int(re.search(r'"--port", type=int, default=(\d+)', source).group(1))
        self.assertEqual(default, 7797)
        self.assertNotIn(default, qa.FORBIDDEN_PORTS)

    def test_two_cards_that_are_one_or_three_are_refused_before_any_call(self):
        with tempfile.TemporaryDirectory(prefix="qa42-") as tmp:
            for cards in ("emp-a", "a,a", "a,b,c", ""):
                lines = []
                code = qa.main(["--state", tmp, "--port", str(CONSOLE_AT), "--cards", cards], out=lines.append,
                               console_factory=lambda *_: self.fail("called"))
                self.assertEqual(code, 2, cards)

    def test_a_state_folder_without_a_matching_token_stops_with_a_line_not_a_trace(self):
        with tempfile.TemporaryDirectory(prefix="qa42-") as tmp:
            lines = []
            self.assertEqual(qa.main(["--state", tmp, "--port", str(CONSOLE_AT), "--cards", f"{A},{B}"], out=lines.append), 1)
            self.assertTrue(any(l.startswith("FAIL stopped") for l in lines), lines)
            (Path(tmp) / "server.token").write_text(json.dumps({"port": 1, "token": "x"}))
            with self.assertRaises(qa.Stop):
                qa.read_token(Path(tmp), CONSOLE_AT)
            (Path(tmp) / "server.token").write_text(json.dumps({"port": CONSOLE_AT, "token": "synthetic"}))
            self.assertEqual(qa.read_token(Path(tmp), CONSOLE_AT), "synthetic")


class PureTests(unittest.TestCase):
    def test_the_work_folder_is_the_one_the_chat_store_names(self):
        self.assertEqual(qa.work_dir(Path("/s"), "emp-aaaa"), Path("/s/chat-work") / cs.work_dir_name("emp-aaaa"))

    def test_the_two_cards_are_the_ones_given_in_the_order_given_and_must_be_claude_code_and_on(self):
        def card(pid, **over):
            return {"id": pid, "enabled": True, "model": {"tool": "claude", "model_id": "haiku"}, **over}
        rows = [card("a"), card("b"), card("off", enabled=False), card("codex", model={"tool": "codex", "model_id": ""})]
        self.assertEqual(qa.pick_cards(rows, ["b", "a"]), ["b", "a"], "the order is the caller's: the previous version swapped the roles")
        for given in (["a", "ghost"], ["a", "off"], ["a", "codex"], ["a", "a"], ["a"]):
            with self.assertRaises(qa.Stop):
                qa.pick_cards(rows, given)

    def test_the_four_lines_that_must_be_refused_are_refused_by_the_real_rules_and_none_is_written_out_whole(self):
        lines = qa.refused_lines()
        self.assertEqual([rules.check(text)["refuse"] for _, text in lines], ["secret_password", "secret_key", "secret_account", "secret_payment"])
        source = Path(qa.__file__).read_text(encoding="utf-8")
        for _, text in lines:
            for piece in re.findall(r"[A-Za-z0-9\-]{16,}", text):
                self.assertNotIn(piece, source, "built at run time, not written out")
        self.assertEqual(rules.check(qa.ORDER_LINE), {"refuse": None, "warn": ["looks_like_order"]})
        for _kind, text in qa.LINES:
            self.assertEqual(rules.check(text), {"refuse": None, "warn": []}, text)
        self.assertEqual(rules.check(qa.NEW_SHOP_LINE), {"refuse": None, "warn": []})

    def test_the_card_number_passes_the_luhn_check_and_the_helper_is_right_on_a_known_number(self):
        self.assertEqual(qa.luhn_complete("411111111111111"), "4111111111111111")
        self.assertEqual(qa.luhn_complete("7992739871"), "79927398713")

    def test_the_log_lines_and_the_export_are_read_narrowly(self):
        text = ("noise entries=9\n"
                "l-1: chat process memory entries=3 instructions=no\n"
                "l-2: chat process memory entries=none instructions=yes\n"
                "l-3: chat process memory entries=x instructions=no\n")
        self.assertEqual(qa.entries_lines(text), ["3", "none"])
        self.assertEqual(qa.export_lines("# t\n## a\n\n- one\n- two（你寫的）\n（目前沒有）\n"), 2)
        self.assertTrue(qa.holds_any("abc def", ["zzz", "def"]))
        self.assertFalse(qa.holds_any("abc", ["", "zz"]))

    def test_the_config_and_the_card_checks(self):
        self.assertEqual(qa.config_problems({"a": 1, "m": {"d": 1}}, {"a": 1, "m": {"d": 1}}), [])
        self.assertEqual(qa.config_problems({"a": 1}, {"a": 1, "b": 2}), ["b"])
        self.assertEqual(qa.card_problems({"launch_mode": "safe", "equipped_skill_ids": []}), [])
        self.assertEqual(qa.card_problems({"launch_mode": "full", "equipped_skill_ids": ["s"]}), ["launch_mode", "equipped_skill_ids"])


class WholeRunTests(Harness):
    def test_a_console_that_behaves_passes_every_stage_and_leaves_the_memory_empty(self):
        code, lines, fake = self.run_main()
        self.assertEqual(self.fails(lines), [])
        self.assertEqual(code, 0, lines)
        self.assertTrue(lines[-1].startswith("qa_p42: PASS"), lines[-1])
        for phrase in ("three lines were saved", "a password is refused", "a key is refused", "an account is refused", "a card number is refused",
                       "needs 「我確定」", "the daemon's log has a new process with 3 lines", "the old chat says it is not as it was started",
                       "went on without a new process", "a new chat is as the memory is now", "the new chat's reply holds the new name",
                       "the daemon's log says the new process was given no memory", "a permission card appeared",
                       "nothing was allowed without a card", "the preview names Anthropic", "the run saved nothing", "saved as a suggested one",
                       "config.json is as it was before", "the export has as many lines as the memory", "memory/log.jsonl holds no word of any line",
                       "turns by stage"):
            self.assertTrue(any(phrase in l for l in lines), phrase)
        self.assertEqual(fake.entries, [], "cleared at the end")
        self.assertEqual(fake.answered, ["deny"], "the only card it answered, it refused")
        self.assertEqual(fake.on, {A: True, B: True})
        self.assertTrue(lines[[i for i, l in enumerate(lines) if "turns by stage" in l][0]].endswith("add 0, chat 1, edit 2, off 2, inject 1, suggest 0)"), lines[-3])

    def test_it_prints_none_of_the_memory_nothing_a_model_wrote_and_not_the_token(self):
        code, lines, fake = self.run_main()
        text = "\n".join(lines)
        self.assertEqual(code, 0, lines)
        for secret in [t for _, t in qa.LINES] + [qa.NEW_SHOP_LINE, qa.ORDER_LINE, qa.SHOP, qa.SHOP_NEW, TOKEN, "qa-Pass", "qa-user", KEY, "好，我不執行了",
                                                   "echo qa42", "每週六"] + [t for _, t in qa.refused_lines()]:
            self.assertNotIn(secret, text, secret)
        self.assertNotIn("4111", text)

    def test_the_cards_switches_are_put_back_as_they_were(self):
        code, lines, fake = self.run_main(b_starts_off=True)
        self.assertEqual((code, self.fails(lines)), (0, []), lines)
        self.assertEqual(fake.on, {A: True, B: False})

    def test_until_add_saves_asks_nothing_and_spends_nothing(self):
        code, lines, fake = self.run_main("--until", "add")
        self.assertEqual((code, self.fails(lines)), (0, []), lines)
        self.assertEqual(fake.chats, {})
        self.assertEqual(fake.spent, 0.0)

    def test_it_never_calls_a_route_that_starts_a_tool_or_changes_a_limit(self):
        code, lines, fake = self.run_main()
        self.assertEqual(code, 0, lines)
        routes = {r for _, r, _ in fake.calls}
        for route in routes:
            self.assertTrue(route.startswith(("/api/memory", "/api/chats", "/api/agent-profiles", "/api/meetings/ledger")), route)
        self.assertNotIn("/api/config", routes)
        self.assertNotIn("/api/meetings/verify", routes, "the tool-less check is asked for only when the preview says it was not done")

    def test_a_claude_code_that_has_not_passed_the_tool_less_check_gets_it_once_before_the_suggestion(self):
        """P42-6 (the real run found the preview blocked by ``boundary_unverified`` with only the words 「請先檢查」): the script does the
        check the dialog's button does (POST /api/meetings/verify, the chief of staff's and the meetings'), then asks for the preview again."""
        code, lines, fake = self.run_main(unverified=True)
        self.assertEqual((code, self.fails(lines)), (0, []), lines)
        checks = [(m, r, b) for m, r, b in fake.calls if r == "/api/meetings/verify"]
        self.assertEqual(checks, [("POST", "/api/meetings/verify", {})])
        self.assertTrue(any("the tool-less check was not done" in l for l in lines), lines)
        order = [r for _, r, _ in fake.calls if r in ("/api/memory/suggest/preview", "/api/meetings/verify", "/api/memory/suggest")]
        self.assertEqual(order, ["/api/memory/suggest/preview", "/api/meetings/verify", "/api/memory/suggest/preview", "/api/memory/suggest"])
        self.assertTrue(fake.verified)

    def test_a_check_that_fails_stops_the_run_with_a_line_and_asks_for_no_suggestion(self):
        code, lines, fake = self.run_main(unverified=True, verify_fails=True)
        self.assertEqual(code, 1, lines)
        self.assertTrue(any(l.startswith("FAIL") and "tool-less check" in l for l in lines), lines)
        self.assertNotIn("/api/memory/suggest", [r for _, r, _ in fake.calls])

    def test_a_model_that_did_not_ask_for_the_command_is_a_warning_not_a_failure(self):
        code, lines, fake = self.run_main(no_card=True)
        self.assertEqual((code, self.fails(lines)), (0, []), lines)
        self.assertTrue(any(l.startswith("warn the model did not ask for the command") for l in lines), lines)
        self.assertEqual(fake.answered, [])


class FailureTests(Harness):
    def assertFailsWith(self, phrase, **flaws):
        code, lines, _ = self.run_main(**flaws)
        self.assertEqual(code, 1, lines)
        self.assertTrue(any(l.startswith("FAIL") and phrase in l for l in lines), (phrase, lines))
        self.assertTrue(lines[-1].startswith("qa_p42: FAIL"), lines[-1])

    def test_a_refused_line_that_was_saved(self):
        self.assertFailsWith("is refused and not saved", saves_refused=True)

    def test_no_entries_line_in_the_daemons_log(self):
        self.assertFailsWith("the daemon's log has a new process with 3 lines", no_log_line=True)

    def test_a_process_started_for_an_edit_it_would_not_use(self):
        self.assertFailsWith("went on without a new process", restart_after_edit=True)

    def test_a_chat_that_does_not_say_it_is_not_as_it_was_started(self):
        self.assertFailsWith("the old chat says it is not as it was started", never_changed=True)

    def test_a_card_switched_off_that_still_got_the_lines(self):
        self.assertFailsWith("the daemon's log says the new process was given no memory", off_still_sends=True)

    def test_a_suggestion_that_saved_a_line(self):
        self.assertFailsWith("the run saved nothing", suggest_saves=True)

    def test_a_key_added_to_config_json(self):
        self.assertFailsWith("config.json is as it was before", config_extra_key=True)

    def test_a_word_of_a_line_in_the_memory_log(self):
        self.assertFailsWith("memory/log.jsonl holds no word of any line", log_has_words=True)

    def test_a_chat_id_in_the_export(self):
        self.assertFailsWith("and no chat id", export_has_chat_id=True)

    def test_a_file_written_although_the_card_was_refused(self):
        self.assertFailsWith("the work folder has no such file", writes_file=True)

    def test_a_command_allowed_with_no_card(self):
        self.assertFailsWith("nothing was allowed without a card", allowed_without_card=True)

    def test_too_much_spent(self):
        self.assertFailsWith("within the allowance", ledger_extra=0.5)

    def test_a_model_that_never_uses_the_line_is_said_to_be_the_models_to_explain(self):
        code, lines, _ = self.run_main(no_model_use=True)
        self.assertEqual(code, 1, lines)
        self.assertTrue(any(l.startswith("FAIL the reply holds the shop's name") and "the model did not use the line" in l for l in lines), lines)

    def test_a_card_switched_off_whose_reply_still_holds_the_name(self):
        code, lines, _ = self.run_main(off_still_sends=True)
        self.assertEqual(code, 1, lines)
        self.assertTrue(any(l.startswith("FAIL the reply does not hold the name") for l in lines), lines)


if __name__ == "__main__":
    unittest.main()
