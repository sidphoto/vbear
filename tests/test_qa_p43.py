"""P43-5: tools/qa_p43.py, the coordinator's real-machine check of the shared folder, must refuse to run without a state folder and three
cards, never aim at the person's VBear (its folder, anything under it, ports 7788 and 7789), print none of what a model wrote and not the
access token, never press the Finder button, pass over a console that behaves, and FAIL over one that does not (a card that starts on; a
Read that asked; a passer-by that can write; a process that was reused after the switch went off; a write that got out through a link; no
``shared_full``; a group list without the file; a key added to config.json; a Bash that ran without a card; a file name in the switch
log; too much spent; a sandbox that lets a write out or does not let one in).
Nothing here starts a console, a model or a real Codex: the console is an in-memory fake over a real temporary state folder (the shared
folder, the link and the files are real files), and ``codex`` is a small script that applies the sandbox's rules to the command.

Seams: ``qa_p43.main`` (the command line, with a fake console), ``refusal``, ``pick_cards``, ``config_problems``, ``card_problems``,
``process_lines``, ``card_path``, ``facts``, ``find_codex``, ``sandbox_settings`` and ``work_dir``."""
import contextlib
import importlib.util
import io
import json
import os
import re
import stat
import tempfile
import unittest
from pathlib import Path

from vbear.runtime import chat_store as cs

SPEC = importlib.util.spec_from_file_location("qa_p43", Path(__file__).resolve().parent.parent / "tools" / "qa_p43.py")
qa = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(qa)

CONSOLE_AT = 50143
TOKEN = "synthetic-token-never-printed"
W, A, P = "emp-writer", "emp-account", "emp-passer"
CHAT_RE = re.compile(r"^/api/chats/(c-[0-9a-f]{16})(/messages|/answer)?$")
GROUP_RE = re.compile(r"^/api/groups/(g-[0-9a-f]{12})(/messages)?$")
MODEL_WORDS = "MODEL-WORDS-never-printed"
FAKE_CODEX = r'''#!/usr/bin/env python3
import json, os, re, subprocess, sys
args = sys.argv[1:]
flaw = open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "flaw")).read().strip()
cut = args.index("--")
settings, cmd = args[:cut], args[cut + 1:]
roots = []
for a in settings:
    if a.startswith("sandbox_workspace_write.writable_roots="):
        roots = [os.path.realpath(p) for p in json.loads(a.split("=", 1)[1])]
target = re.search(r'> "(.*)"$', cmd[2]).group(1)
work = os.path.realpath(os.getcwd())
real = os.path.realpath(target)

def inside(path, root):
    return path == root or path.startswith(root + os.sep)

ok = inside(real, work)
for root in roots:
    if inside(real, root):
        ok = ok or not any(part in (".git", ".codex", ".agents") for part in os.path.relpath(target, root).split(os.sep))
if flaw == "open":
    ok = True
if flaw == "closed":
    ok = False
if not ok:
    sys.stderr.write("Operation not permitted\n")
    sys.exit(1)
sys.exit(subprocess.run(cmd).returncode)
'''


class FakeConsole(qa.Console):
    """A console that holds three cards, their chats and one group in memory over a real temporary state folder. ``flaws`` are the ways it
    misbehaves. It answers the way the real one does about cards (a Write into the shared folder is a card for an employee who has it on;
    VBear itself refuses it for one who has not, and through a link; a Read is VBear's own to allow until a link is in the folder)."""

    def __init__(self, state: Path, **flaws):
        super().__init__(CONSOLE_AT, TOKEN)
        self.state, self.flaws = Path(state).resolve(), flaws
        self.shared = self.state / "shared"
        (self.state / "server.token").write_text(json.dumps({"port": CONSOLE_AT, "token": TOKEN}))
        self.config = {"setup_done": True, "meeting_limits": {"daily_usd": 0.25}, "chat_limits": {"per_turn_usd": 0.1}}
        self.write_config()
        self.profiles = [{"id": pid, "name": name, "position": pos, "enabled": True, "launch_mode": "safe", "equipped_skill_ids": [],
                          "model": {"tool": "claude", "model_id": "haiku"}} for pid, name, pos in ((W, "寫手", "social"), (A, "會計", "accountant"), (P, "路人", "assistant"))]
        self.on = {W: flaws.get("starts_on") is True, A: False, P: False}
        self.chats: dict[str, dict] = {}
        self.groups: dict[str, dict] = {}
        self.spent = 0.0
        self.calls: list[tuple] = []
        self.answered: list[str] = []
        self.n = 0

    # -- files ---------------------------------------------------------------------------------------------------------------

    def write_config(self):
        (self.state / "config.json").write_text(json.dumps(self.config))

    def meta_log(self, what, pid):
        folder = self.state / "shared-meta"
        folder.mkdir(exist_ok=True)
        row = {"at": 1.0, "what": what, "profile_id": pid, "how": "page"}
        if self.flaws.get("log_has_names"):
            row["name"] = "qa43-價目表.md"
        with (folder / "log.jsonl").open("a") as f:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")

    def daemon_log(self, shared):
        with (self.state / "runtimed.log").open("a") as f:
            f.write("some other line that is never read: shared=on\n")
            f.write(f"l-0123456789abcdef: chat process shared={'on' if shared else 'off'}\n")

    def has_link(self):
        return any(p.is_symlink() for p in self.shared.iterdir()) if self.shared.is_dir() else False

    def through_link(self, target: Path):
        rel = target.relative_to(self.shared) if str(target).startswith(str(self.shared)) else None
        return rel is not None and (self.shared / rel.parts[0]).is_symlink()

    def over(self):
        return self.shared.is_dir() and any(not p.is_symlink() and p.stat().st_size > (1 << 30) for p in self.shared.iterdir())

    # -- chats ---------------------------------------------------------------------------------------------------------------

    def new_chat(self, pid):
        self.n += 1
        cid = "c-" + f"{self.n:016x}"
        self.chats[cid] = {"pid": pid, "records": [], "turn": 0, "proc": None, "pending": None, "group": None}
        return cid

    def rec(self, chat, kind, **kw):
        chat["records"].append({"seq": len(chat["records"]) + 1, "kind": kind, **kw})

    def finish(self, chat, reply=MODEL_WORDS):
        self.rec(chat, "reply", turn=chat["turn"], text=reply)
        self.rec(chat, "turn_ended", turn=chat["turn"], reason="result")
        chat["pending"] = None
        hook, chat["after_turn"] = chat.get("after_turn"), None
        if hook:
            hook()

    def ask_card(self, chat, tool, tool_input, on_allow, on_deny=None):
        turn = chat["turn"]
        cid = "k-" + f"{len(chat['records']):016x}"
        self.rec(chat, "card", turn=turn, card_id=cid, tool=tool, input=tool_input, editable=None, state="asked", reason="")
        chat["pending"] = {"card": {"card_id": cid, "token": "t" * 32, "tool": tool, "input": tool_input, "turn": turn}, "allow": on_allow, "deny": on_deny}

    def refuse(self, chat, tool):
        self.rec(chat, "denied", turn=chat["turn"], tool=tool, summary="", reason="", by="vbear", tool_use_id=None)
        self.finish(chat, MODEL_WORDS)

    def put(self, path: Path, text="x"):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)

    def do_write(self, chat, target: Path):
        pid, flaws = chat["pid"], self.flaws
        if self.through_link(target) and not flaws.get("link_goes_through"):
            return self.refuse(chat, "Write")
        if not self.on[pid] and not flaws.get("off_can_write"):
            return self.refuse(chat, "Write")
        def allowed():
            self.put(target.resolve() if self.through_link(target) else target, qa.PRICE_LINE)
            self.finish(chat)
        self.ask_card(chat, "Write", {"file_path": str(target)}, allowed, lambda: self.finish(chat))

    def do_read(self, chat, target: Path):
        if not self.on[chat["pid"]]:
            return self.refuse(chat, "Read")
        reply = MODEL_WORDS + (" 120" if target.exists() and not self.flaws.get("no_price") else "")
        if self.has_link() or self.flaws.get("read_has_card"):
            return self.ask_card(chat, "Read", {"file_path": str(target)}, lambda: self.finish(chat, reply))
        self.rec(chat, "auto_allowed", turn=chat["turn"], tool="Read", summary="", reason="", tool_use_id=None)
        self.finish(chat, reply)

    def do_bash(self, chat, target: Path):
        def allowed():
            if self.on[chat["pid"]] or self.flaws.get("off_bash_writes"):
                self.put(target)
            self.finish(chat)
        self.ask_card(chat, "Bash", {"command": "echo x"}, allowed, lambda: self.finish(chat))

    def do_note(self, chat):
        self.rec(chat, "auto_allowed", turn=chat["turn"], tool="Read", summary="", reason="", tool_use_id=None)
        if self.flaws.get("bash_auto"):
            self.rec(chat, "auto_allowed", turn=chat["turn"], tool="Bash", summary="", reason="", tool_use_id=None)
            return self.finish(chat)
        def pwned():
            if self.flaws.get("pwned_file"):
                self.put(self.shared / qa.PWNED_FILE)
            self.finish(chat)
        self.ask_card(chat, "Bash", {"command": "echo qa43"}, pwned, pwned)

    def send(self, chat, text):
        pid, flaws = chat["pid"], self.flaws
        want = self.on[pid]
        if chat["proc"] is None or (chat["proc"]["shared"] != want and not flaws.get("reused_after_off")):
            if want and self.over() and not flaws.get("no_full"):
                return 409, {"code": "shared_full", "error": "full"}
            kind = "new" if chat["proc"] is None else "resume"
            chat["proc"] = {"shared": want}
            self.daemon_log(want)
            self.rec(chat, "process_started", mode=kind)
        else:
            kind = "reused"
        chat["turn"] += 1
        self.rec(chat, "user_message", turn=chat["turn"], text=text)
        self.spent += 0.01
        shared = str(self.shared)
        if qa.LINK_NAME in text:
            self.do_write(chat, self.shared / qa.LINK_NAME / "x.txt")
        elif qa.CLOSED_FILE in text:
            self.do_write(chat, self.shared / qa.CLOSED_FILE)
        elif qa.OFF_FILE in text and "Write" in text:
            self.do_write(chat, self.shared / qa.OFF_FILE)
        elif qa.OFF_FILE2 in text:
            self.do_bash(chat, self.shared / qa.OFF_FILE2)
        elif qa.NOTE_FILE in text:
            self.do_note(chat)
        elif "Write" in text and qa.PRICE_FILE in text:
            self.do_write(chat, self.shared / qa.PRICE_FILE)
        elif qa.PRICE_FILE in text:
            self.do_read(chat, self.shared / qa.PRICE_FILE)
        else:
            self.finish(chat, "ok")
        return 202, {"ok": True, "turn": chat["turn"], "cap_usd": "0.1", "process": kind}

    # -- groups --------------------------------------------------------------------------------------------------------------

    def group_start(self, gid):
        group = self.groups[gid]
        group["state"] = "running"
        writer = self.chats[group["chats"][W]]
        self.send_group(writer, "group")
        writer["after_turn"] = lambda: self.group_second(gid)
        target = self.shared / qa.GROUP_FILE
        writer["pending"] = None
        def allowed():
            self.put(target)
            if not self.flaws.get("no_changes_file"):
                folder = self.state / "shared-meta" / "changes"
                folder.mkdir(parents=True, exist_ok=True)
                (folder / f"{gid}.jsonl").write_text(json.dumps({"round": 1, "profile_id": W, "names": [qa.GROUP_FILE]}) + "\n")
            group["items"].append({"seq": 2, "kind": "reply", "profile_id": W, "text": MODEL_WORDS,
                                   **({} if self.flaws.get("no_group_names") else {"shared_changes": {"names": [qa.GROUP_FILE], "cut": False, "unavailable": False}})})
            self.finish(writer)
        self.ask_card(writer, "Write", {"file_path": str(target)}, allowed)

    def send_group(self, chat, text):
        chat["turn"] += 1
        self.rec(chat, "user_message", turn=chat["turn"], text=text)
        self.spent += 0.01

    def group_second(self, gid):
        group = self.groups[gid]
        acc = self.chats[group["chats"][A]]
        self.send_group(acc, "group")
        self.rec(acc, "reply", turn=acc["turn"], text=MODEL_WORDS)
        self.rec(acc, "turn_ended", turn=acc["turn"], reason="result")
        group["items"].append({"seq": 3, "kind": "reply", "profile_id": A, "text": MODEL_WORDS + ("" if self.flaws.get("acc_silent") else " " + qa.GROUP_FILE)})
        group["state"] = "idle"

    def group_view(self, gid):
        group = self.groups[gid]
        current = None
        if group["state"] == "running":
            chat_id = group["chats"][W]
            current = {"profile_id": W, "chat_id": chat_id, "turn": self.chats[chat_id]["turn"]}
        return {"group": {"id": gid, "state": group["state"]}, "items": list(group["items"]), "current": current}

    # -- the routes ----------------------------------------------------------------------------------------------------------

    def call(self, path, method="GET", body=None):
        route = path.split("?")[0]
        after = int(path.split("after=")[1]) if "after=" in path else 0
        self.calls.append((method, route, body))
        if route == "/api/agent-profiles":
            return 200, {"ok": True, "profiles": self.profiles}
        if route == "/api/meetings/ledger":
            return 200, {"spent_usd": f"{self.spent + self.flaws.get('ledger_extra', 0):.2f}"}
        if route == "/api/shared" and method == "GET":
            files = []
            if self.shared.is_dir():
                files = [{"name": p.name, "size": p.lstat().st_size, "mtime": 1, "link": p.is_symlink()} for p in sorted(self.shared.iterdir())]
            return 200, {"ok": True, "where_text": "~/.vbear/shared", "exists": self.shared.is_dir(), "problem": None, "files": files,
                         "cards": [{"profile_id": p["id"], "name": p["name"], "tool": "claude", "company": "Anthropic", "can_chat": True,
                                    "on": self.on[p["id"]], "verified": self.flaws.get("unverified") is not True} for p in self.profiles]}
        if route == "/api/shared/cards" and method == "POST":
            self.on[body["profile_id"]] = body["on"]
            if body["on"]:
                self.shared.mkdir(mode=0o700, exist_ok=True)
                os.chmod(self.shared, 0o700)
            self.meta_log("card_on" if body["on"] else "card_off", body["profile_id"])
            if self.flaws.get("config_extra_key"):
                self.config["mystery"] = 1
                self.write_config()
            return 200, {"ok": True}
        if route == "/api/chats" and method == "POST":
            return 201, {"ok": True, "chat": {"id": self.new_chat(body["profile_id"])}}
        found = CHAT_RE.match(route)
        if found:
            chat = self.chats.get(found.group(1))
            if chat is None:
                return 404, {"code": "not_found"}
            if found.group(2) == "/messages":
                return self.send(chat, body["text"])
            if found.group(2) == "/answer":
                self.answered.append(body["decision"])
                pending, chat["pending"] = chat["pending"], None
                if pending is not None:
                    (pending["allow"] if body["decision"] == "allow" else (pending["deny"] or pending["allow"]))()
                return 200, {"ok": True}
            recs = [r for r in chat["records"] if r["seq"] > after]
            live = {"cards": [chat["pending"]["card"]]} if chat["pending"] else None
            return 200, {"records": recs, "live": live, "more": False, "next_after": len(chat["records"])}
        if route == "/api/groups" and method == "POST":
            gid = "g-" + f"{len(self.groups) + 1:012x}"
            self.groups[gid] = {"state": "idle", "items": [], "chats": {pid: self.new_chat(pid) for pid in body["profile_ids"]}}
            for pid in body["profile_ids"]:
                if body.get("shared_folder") is True:
                    self.on[pid] = True
            return 200, {"group": {"id": gid}, "shared": {"opened": []}}
        found = GROUP_RE.match(route)
        if found:
            gid = found.group(1)
            if found.group(2) == "/messages":
                self.group_start(gid)
                return 202, {"round": 1}
            if method == "DELETE":
                self.groups.pop(gid)
                if self.flaws.get("delete_removes_file"):
                    (self.shared / qa.GROUP_FILE).unlink()
                return 200, {"ok": True}
            return 200, self.group_view(gid)
        return 404, {"code": "unknown"}


class Harness(unittest.TestCase):
    def run_main(self, *args, codex=True, fake=None, **flaws):
        tmp = tempfile.TemporaryDirectory(prefix="qa43-")
        self.addCleanup(tmp.cleanup)
        self.root = Path(os.path.realpath(tmp.name))
        state = self.root / "s"
        state.mkdir()
        console = fake or FakeConsole(state, **flaws)
        lines = []
        argv = ["--state", str(state), "--port", str(CONSOLE_AT), "--cards", f"{W},{A},{P}", *args]
        if codex is True:
            self.codex_bin = self.make_codex(flaws.get("codex_flaw", "none"))
            argv += ["--codex", str(self.codex_bin)]
        elif codex:
            argv += ["--codex", codex]
        code = qa.main(argv, out=lines.append, console_factory=lambda port, token: console, **self.time())
        return code, lines, console

    def make_codex(self, flaw):
        folder = self.root / "fake-codex-bin"
        folder.mkdir()
        path = folder / "codex"
        path.write_text(FAKE_CODEX)
        path.chmod(0o755)
        (folder / "flaw").write_text(flaw)
        return path

    def time(self):
        """A clock that only moves when the script sleeps, so that a wait that never ends times out at once instead of in 3 minutes."""
        now = [0.0]
        return {"clock": lambda: now[0], "sleep": lambda s: now.__setitem__(0, now[0] + s)}

    def fails(self, lines):
        return [l for l in lines if l.startswith("FAIL")]


class CommandLineTests(unittest.TestCase):
    def test_it_does_not_run_without_a_state_folder_or_the_three_cards(self):
        for args in ([], ["--state", "/tmp"], ["--cards", "a,b,c"]):
            err = io.StringIO()
            with contextlib.redirect_stderr(err), self.assertRaises(SystemExit) as stop:
                qa.main(args, out=lambda *_: None)
            self.assertEqual(stop.exception.code, 2, args)

    def test_it_refuses_the_ports_of_the_persons_own_vbear(self):
        with tempfile.TemporaryDirectory(prefix="qa43-") as tmp:
            for port in (7788, 7789):
                lines = []
                self.assertEqual(qa.main(["--state", tmp, "--port", str(port), "--cards", f"{W},{A},{P}"], out=lines.append), 2)
                self.assertTrue(lines[0].startswith("refused"), lines)

    def test_it_refuses_the_persons_own_state_folder_anything_under_it_and_a_missing_one(self):
        with tempfile.TemporaryDirectory(prefix="qa43-") as tmp:
            home = Path(tmp).resolve()
            (home / ".vbear" / "shared").mkdir(parents=True)
            self.assertIn("own VBear", qa.refusal(str(home / ".vbear"), 50001, home=home))
            self.assertIn("own VBear", qa.refusal(str(home / ".vbear" / "shared"), 50001, home=home))
            self.assertIn("does not exist", qa.refusal(str(home / "nope"), 50001, home=home))
            self.assertIsNone(qa.refusal(str(home), 50001, home=home))
            self.assertIn("1024", qa.refusal(str(home), 80, home=home))
            self.assertIn("own VBear", qa.refusal(str(home), 7788, home=home))

    def test_the_default_port_is_7798_and_not_the_persons(self):
        source = Path(qa.__file__).read_text(encoding="utf-8")
        default = int(re.search(r'"--port", type=int, default=(\d+)', source).group(1))
        self.assertEqual(default, 7798)
        self.assertNotIn(default, qa.FORBIDDEN_PORTS)

    def test_fewer_or_more_than_three_cards_or_a_repeated_one_are_refused_before_any_call(self):
        with tempfile.TemporaryDirectory(prefix="qa43-") as tmp:
            for cards in ("emp-a", "a,b", "a,a,b", "a,b,c,d", ""):
                lines = []
                code = qa.main(["--state", tmp, "--port", str(CONSOLE_AT), "--cards", cards], out=lines.append,
                               console_factory=lambda *_: self.fail("called"))
                self.assertEqual(code, 2, cards)

    def test_a_state_folder_without_a_matching_token_stops_with_a_line_not_a_trace(self):
        with tempfile.TemporaryDirectory(prefix="qa43-") as tmp:
            lines = []
            self.assertEqual(qa.main(["--state", tmp, "--port", str(CONSOLE_AT), "--cards", f"{W},{A},{P}"], out=lines.append), 1)
            self.assertTrue(any(l.startswith("FAIL stopped") for l in lines), lines)
            (Path(tmp) / "server.token").write_text(json.dumps({"port": 1, "token": "x"}))
            with self.assertRaises(qa.Stop):
                qa.read_token(Path(tmp), CONSOLE_AT)
            (Path(tmp) / "server.token").write_text(json.dumps({"port": CONSOLE_AT, "token": "synthetic"}))
            self.assertEqual(qa.read_token(Path(tmp), CONSOLE_AT), "synthetic")

    def test_the_script_never_calls_the_finder_route_or_a_config_route(self):
        source = Path(qa.__file__).read_text(encoding="utf-8")
        self.assertNotIn("/api/shared/reveal", re.sub(r'"""[\s\S]*?"""', "", source), "named only in the docstring, as a thing it never presses")
        self.assertNotIn("/api/config", re.sub(r'"""[\s\S]*?"""', "", source))
        self.assertNotIn("/usr/bin/open", source.replace("never", ""))


class PureTests(unittest.TestCase):
    def test_the_work_folder_is_the_one_the_chat_store_names(self):
        self.assertEqual(qa.work_dir(Path("/s"), "emp-aaaa"), Path("/s/chat-work") / cs.work_dir_name("emp-aaaa"))

    def test_the_three_cards_are_the_ones_given_in_the_order_given_and_must_be_claude_code_and_on(self):
        def card(pid, **over):
            return {"id": pid, "enabled": True, "model": {"tool": "claude", "model_id": "haiku"}, **over}
        rows = [card("a"), card("b"), card("c"), card("off", enabled=False), card("codex", model={"tool": "codex", "model_id": ""})]
        self.assertEqual(qa.pick_cards(rows, ["c", "a", "b"]), ["c", "a", "b"], "the order is the caller's")
        for given in (["a", "b", "ghost"], ["a", "b", "off"], ["a", "b", "codex"], ["a", "a", "b"], ["a", "b"]):
            with self.assertRaises(qa.Stop):
                qa.pick_cards(rows, given)

    def test_the_daemons_log_is_read_narrowly(self):
        text = ("noise shared=on\n"
                "l-1: chat process shared=on\n"
                "l-2: chat process shared=off\n"
                "l-3: chat process shared=maybe\n")
        self.assertEqual(qa.process_lines(text), ["on", "off"])

    def test_a_cards_path_and_what_a_turn_left_are_read_as_names_only(self):
        self.assertEqual(qa.card_path({"input": {"file_path": "/a/b"}}), "/a/b")
        self.assertEqual(qa.card_path({"input": {"command": "x"}}), "")
        self.assertEqual(qa.card_path({"input": "x"}), "")
        recs = [{"kind": "card", "turn": 1, "tool": "Write"}, {"kind": "denied", "turn": 1, "tool": "Edit", "by": "vbear"},
                {"kind": "denied", "turn": 1, "tool": "Bash", "by": "cli"}, {"kind": "auto_allowed", "turn": 1, "tool": "Read"},
                {"kind": "reply", "turn": 1, "text": "hello"}, {"kind": "card", "turn": 2, "tool": "Bash"}]
        got = qa.facts(recs, 1)
        self.assertEqual((qa.tool_names(got["cards"]), got["refused"], got["allowed"], got["reply"]), (["Write"], ["Edit"], ["Read"], "hello"))

    def test_the_config_and_the_card_checks(self):
        self.assertEqual(qa.config_problems({"a": 1, "m": {"d": 1}}, {"a": 1, "m": {"d": 1}}), [])
        self.assertEqual(qa.config_problems({"a": 1}, {"a": 1, "b": 2}), ["b"])
        self.assertEqual(qa.card_problems({"launch_mode": "safe", "equipped_skill_ids": []}), [])
        self.assertEqual(qa.card_problems({"launch_mode": "full", "equipped_skill_ids": ["s"]}), ["launch_mode", "equipped_skill_ids"])

    def test_the_newest_codex_is_found_under_the_standalone_releases_and_none_is_none(self):
        with tempfile.TemporaryDirectory(prefix="qa43-") as tmp:
            home = Path(tmp)
            self.assertIsNone(qa.find_codex(home))
            for version in ("0.9.0", "0.163.0", "0.20.1"):
                folder = home / ".codex" / "packages" / "standalone" / "releases" / version
                folder.mkdir(parents=True)
                (folder / "codex").write_text("#!/bin/sh\n")
                (folder / "codex").chmod(0o755)
            self.assertEqual(qa.find_codex(home), str(home / ".codex" / "packages" / "standalone" / "releases" / "0.163.0" / "codex"))

    def test_the_sandbox_settings_are_vbears_own_with_the_shared_folder_as_the_one_more_root(self):
        got = qa.sandbox_settings(Path("/t/work"), Path("/t/shared"))
        self.assertIn('sandbox_workspace_write.writable_roots=["/t/shared"]', got)
        self.assertIn("sandbox_workspace_write.network_access=false", got)
        self.assertFalse(any(s.startswith("-") for s in got), "values of -c, not flags")


class WholeRunTests(Harness):
    def test_a_console_that_behaves_passes_every_stage_and_leaves_nothing_behind(self):
        code, lines, fake = self.run_main()
        self.assertEqual(self.fails(lines), [])
        self.assertEqual(code, 0, lines)
        self.assertTrue(lines[-1].startswith("qa_p43: PASS"), lines[-1])
        for phrase in ("start with the shared folder off", "passed the chat check with the shared folder", "the writer and the accountant are opened",
                       "0700 and not a link", "opening the folder cost nothing", "a Write card with a path in the shared folder", "the file is in the shared folder",
                       "the daemon's log says the process had the shared folder", "the page lists the file", "the reply holds the price",
                       "no card for the read", "employee who is off is refused by VBear with no card", "the sandbox left no file",
                       "did not use the old process", "the new process has no shared folder", "the accountant's switch is on again",
                       "through a link to the outside is refused", "nothing is outside the folder", "with a link in the folder a Read is a card",
                       "the link is removed again", "the script refused it", "no Bash ran without a card", "neither the shared folder nor the work folder",
                       "a group of the writer and the accountant", "the group's list of new names holds the file", "the group page shows the name",
                       "the accountant's reply names the file", "deleting the group left the file", "refused with shared_full", "nothing was spent",
                       "with the big file gone", "lets a command write in the work folder", "refuses a write outside the two",
                       "through a link to the outside", "into .git of the shared folder", "into .codex", "into .agents",
                       "config.json is as it was before", "switches are as setup left them", "nothing got out of the shared folder",
                       "holds no file name", "are deleted", "within the allowance", "turns by stage"):
            self.assertTrue(any(phrase in l for l in lines), phrase)
        self.assertEqual(sorted(p.name for p in fake.shared.iterdir()), [], "every file this run made is deleted, and the link")
        self.assertFalse((self.root / "outside").exists())
        self.assertFalse((self.root / "cx").exists())
        self.assertEqual(fake.on, {W: True, A: True, P: False}, "the switches are as setup left them")
        self.assertEqual(fake.answered.count("deny"), 1, "the only card it refused is the command in the file")
        self.assertEqual(stat.S_IMODE(os.lstat(fake.shared).st_mode), 0o700)

    def test_it_prints_none_of_what_a_model_wrote_and_not_the_token(self):
        code, lines, fake = self.run_main()
        text = "\n".join(lines)
        self.assertEqual(code, 0, lines)
        for secret in (MODEL_WORDS, TOKEN, qa.PRICE_LINE, qa.NOTE_TEXT, "echo qa43", "echo x", "Operation not permitted"):
            self.assertNotIn(secret, text, secret)

    def test_until_setup_asks_nothing_and_spends_nothing(self):
        code, lines, fake = self.run_main("--until", "setup", codex=False)
        self.assertEqual((code, self.fails(lines)), (0, []), lines)
        self.assertEqual(fake.chats, {})
        self.assertEqual(fake.spent, 0.0)
        self.assertEqual(fake.on, {W: True, A: True, P: False})

    def test_it_never_calls_a_route_that_opens_finder_starts_a_tool_or_changes_a_limit(self):
        code, lines, fake = self.run_main()
        self.assertEqual(code, 0, lines)
        routes = {r for _, r, _ in fake.calls}
        for route in routes:
            self.assertTrue(route.startswith(("/api/shared", "/api/chats", "/api/groups", "/api/agent-profiles", "/api/meetings/ledger")), route)
        self.assertNotIn("/api/shared/reveal", routes)
        self.assertNotIn("/api/config", routes)
        self.assertNotIn("/api/setup/daily-limit", routes)
        self.assertNotIn("/api/meetings/verify", routes)

    def test_a_codex_that_is_not_there_is_a_warning_not_a_failure(self):
        code, lines, _ = self.run_main(codex="/nonexistent/codex")
        self.assertEqual((code, self.fails(lines)), (0, []), lines)
        self.assertTrue(any(l.startswith("warn no codex binary found") for l in lines), lines)

    def test_a_model_that_never_reads_the_price_is_the_models_to_explain(self):
        code, lines, _ = self.run_main(no_price=True)
        self.assertEqual(code, 1, lines)
        self.assertTrue(any(l.startswith("FAIL the reply holds the price") and "model" in l for l in lines), lines)

    def test_an_accountant_that_does_not_name_the_file_is_a_warning(self):
        code, lines, _ = self.run_main(acc_silent=True)
        self.assertEqual((code, self.fails(lines)), (0, []), lines)
        self.assertTrue(any(l.startswith("warn the accountant's reply does not name the file") for l in lines), lines)


class FailureTests(Harness):
    def assertFailsWith(self, phrase, **flaws):
        code, lines, _ = self.run_main(**flaws)
        self.assertEqual(code, 1, lines)
        self.assertTrue(any(l.startswith("FAIL") and phrase in l for l in lines), (phrase, lines))
        self.assertTrue(lines[-1].startswith("qa_p43: FAIL"), lines[-1])

    def test_a_card_that_starts_on(self):
        self.assertFailsWith("start with the shared folder off", starts_on=True)

    def test_a_version_not_checked_with_the_folder(self):
        self.assertFailsWith("passed the chat check with the shared folder", unverified=True)

    def test_a_read_that_asks(self):
        self.assertFailsWith("no card for the read", read_has_card=True)

    def test_a_passer_by_who_can_write(self):
        self.assertFailsWith("employee who is off is refused by VBear with no card", off_can_write=True)
        self.assertFailsWith("and no file is made", off_can_write=True)

    def test_a_bash_that_writes_for_an_employee_who_is_off(self):
        self.assertFailsWith("the sandbox left no file", off_bash_writes=True)

    def test_a_process_reused_after_the_switch_went_off(self):
        self.assertFailsWith("did not use the old process", reused_after_off=True)

    def test_a_write_that_gets_out_through_a_link(self):
        self.assertFailsWith("through a link to the outside is refused", link_goes_through=True)
        self.assertFailsWith("nothing is outside the folder", link_goes_through=True)

    def test_no_shared_full(self):
        self.assertFailsWith("refused with shared_full", no_full=True)

    def test_a_bash_that_ran_without_a_card(self):
        self.assertFailsWith("no Bash ran without a card", bash_auto=True)

    def test_the_file_the_command_in_the_note_would_make(self):
        self.assertFailsWith("neither the shared folder nor the work folder", pwned_file=True)

    def test_a_group_list_without_the_file(self):
        self.assertFailsWith("the group's list of new names holds the file", no_changes_file=True)

    def test_a_group_page_without_the_name(self):
        self.assertFailsWith("the group page shows the name", no_group_names=True)

    def test_a_deleted_group_that_takes_the_file_along(self):
        self.assertFailsWith("deleting the group left the file", delete_removes_file=True)

    def test_a_key_added_to_config_json(self):
        self.assertFailsWith("config.json is as it was before", config_extra_key=True)

    def test_a_file_name_in_the_switch_log(self):
        self.assertFailsWith("holds no file name", log_has_names=True)

    def test_too_much_spent(self):
        self.assertFailsWith("within the allowance", ledger_extra=0.5)

    def test_a_sandbox_that_lets_a_write_out(self):
        self.assertFailsWith("refuses a write outside the two", codex_flaw="open")

    def test_a_sandbox_that_lets_nothing_in(self):
        self.assertFailsWith("lets a command write in the work folder", codex_flaw="closed")


if __name__ == "__main__":
    unittest.main()
