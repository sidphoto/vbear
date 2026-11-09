"""P46-6: one walk over HTTP through the AGY chat, from a role card to the last delete (ADR 0012), with the stand-in AGY of tests/fake_agy_acp.py behind the
runtime daemon. A card is made, the page's support block says what the person must do, the check is started (a stand-in verifier), the card chats, a
command is allowed, another is refused, a changed command is asked again, the memory opens only with the yes to Google, the shared folder does NOT open to an
AGY employee (this release), a group of AGY employees is made, a routine is given to one, a team template is applied with AGY and undone, and the chats are
deleted. And what going back to v0.19.0 reads of what this release wrote (the day's spending, the engine table, the kinds of record).
Everything here is made up: a synthetic HOME and VBEAR_HOME under /tmp; the real agy is never run and nothing reaches a network."""

from __future__ import annotations

import json
import re
import subprocess
import sys
import time
import unittest
from decimal import Decimal
from pathlib import Path
from unittest import mock

from tests.test_p46_agy_chat_api import ApiCase, FakeVerifier, READY, status as agy_status
from tests.test_p46_agy_chat_daemon import USAGE_COST, VERSION
from vbear import shared_folder
from vbear.runtime import chat_store as cs

REPO = Path(__file__).resolve().parent.parent
V019 = "v0.19.0"


def v019_kinds():
    """The kinds of record a chat had in v0.19.0, read from the tag when git can show it, else from the check script's own list."""
    try:
        old = subprocess.run(["git", "-C", str(REPO), "show", f"{V019}:vbear/runtime/chat_store.py"], capture_output=True, timeout=30)
    except (OSError, subprocess.SubprocessError):
        old = None
    if old is not None and old.returncode == 0:
        block = old.stdout.decode().split("\nKINDS = {", 1)[1].split("\n}\n", 1)[0]
        found = set(re.findall(r'^    "([a-z_]+)": ', block, re.M))
        if found:
            return found
    return set(qa_kinds())


def qa_kinds():
    import importlib.util
    spec = importlib.util.spec_from_file_location("qa_p46_kinds", REPO / "tools" / "qa_p46.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.V019_KINDS


class OneWalk(ApiCase):
    def watched(self):
        return {name: (self.base / name).read_bytes() if (self.base / name).is_file() else None for name in ("config.json", "memory/memory.json")}

    def test_from_a_role_card_to_the_last_delete(self):
        # 1. the page: the card chats, the support block says what is left to do
        self.svc.agy = lambda: agy_status("unverified", version=VERSION)
        self.svc.agy_verifier = FakeVerifier()
        status_, out = self.call("/api/chat-support")
        self.assertEqual((status_, out["support"]["agy"]["state"], out["support"]["agy"]["engine"]), (200, "unverified", "agy-chat"))
        status_, lst = self.call("/api/chats")
        by = {c["id"]: c for c in lst["cards"]}
        self.assertEqual((by[self.emp]["can_chat"], by[self.emp]["engine"]), (True, "agy-chat"))
        # 2. the check is started (a stand-in; the real check is `--mode agy-chat`), and then the version is verified
        with mock.patch.object(sys.modules["vbear.chat_service"].admin_policy, "check_agy", return_value=mock.Mock(ok=True)):
            status_, out = self.call("/api/chat-support/verify", "POST", {"engine": "agy"})
        self.assertEqual((status_, out["ok"]), (202, True), out)
        self.assertEqual(self.svc.agy_verifier.started, [("", VERSION)])
        self.svc.agy = lambda: dict(READY)
        self.assertEqual(self.call("/api/chat-support")[1]["support"]["agy"]["state"], "ready")

        # 3. a command is allowed (the card says what it is), the turn is counted as an estimate
        self.configure("permission")
        first = self.open_http()
        self.assertEqual(cs.load(self.base, first)["engine"], "agy-chat")
        self.assertEqual(self.say(first, "run ls")[0], 202)
        card = self.wait_http_card(first)
        self.assertEqual((card["tool"], card["input"]["command"]), ("command", "ls -a"))
        self.assertEqual(self.answer_http(first, card, "allow")[0], 200)
        end = self.wait_http_turn(first, 1)
        self.assertEqual((end["reason"], end["estimate"], end["tokens"], end["cost_usd"]), ("result", True, 86000, USAGE_COST))

        # 4. a command that is refused does not run
        self.configure("permission")
        other = self.open_http(self.card("虛構的第二位 AGY 員工"))
        self.say(other, "run ls")
        card = self.wait_http_card(other)
        self.assertEqual(self.answer_http(other, card, "deny")[0], 200)
        self.assertEqual(self.wait_http_turn(other, 1)["reason"], "result")
        self.assertEqual([x["decision"] for x in self.view(other)["records"] if x["kind"] == "card_decision"], ["deny"])

        # 5. a changed command: the original is refused, the changed one is asked again in a card of its own
        self.configure("edit-input")
        third = self.open_http(self.card("虛構的第三位 AGY 員工"))
        self.say(third, "run one")
        card = self.wait_http_card(third)
        self.assertEqual(self.answer_http(third, card, "modify", "echo two")[0], 200)
        self.assertEqual(self.wait_http_turn(third, 1)["reason"], "result")
        again = self.wait(lambda: next((c for c in (self.view(third)["live"] or {}).get("cards", []) if c["card_id"] != card["card_id"]), None), "the second card")
        self.assertEqual(again["input"]["command"], "echo two")
        self.assertEqual(self.answer_http(third, again, "allow")[0], 200)
        self.wait_http_turn(third, 2)

        # 6. the money: the day's spending counts the three chats' estimates (and a stand-in cannot make it unknown)
        spent = cs.day_spent(self.base, time.time())
        self.assertGreaterEqual(spent, Decimal(USAGE_COST) * 3)

        # 7. memory: off for AGY, 409 with the word for Google, 200 with the yes, off again
        before = self.watched()
        memory_card = next(c for c in self.call("/api/memory")[1]["cards"] if c["profile_id"] == self.emp)
        self.assertEqual((memory_card["company"], memory_card["on"]), ("Google", False))
        status_, out = self.call("/api/memory/cards", "POST", {"profile_id": self.emp, "on": True})
        self.assertEqual((status_, out["code"], out["warn"]), (409, "memory_confirm", ["send_to_google"]))
        self.assertEqual(self.call("/api/memory/cards", "POST", {"profile_id": self.emp, "on": True, "confirm_company": True})[0], 200)
        self.assertEqual(self.call("/api/memory/cards", "POST", {"profile_id": self.emp, "on": False})[0], 200)

        # 8. the shared folder does not open to an AGY employee in this release, with or without the yes
        for body in ({"profile_id": self.emp, "on": True}, {"profile_id": self.emp, "on": True, "confirm_company": True}):
            status_, out = self.call("/api/shared/cards", "POST", body)
            self.assertEqual((status_, out["code"]), (400, "card_tool_unsupported"), out)
            self.assertEqual(out["error"], "AGY 員工這版不能用共用資料夾，之後 AGY 新版再檢查。")
        shared = next(c for c in self.call("/api/shared")[1]["cards"] if c["profile_id"] == self.emp)
        self.assertEqual((shared["on"], shared["company"], shared["can_chat"]), (False, None, True))
        self.assertFalse(shared_folder.for_card(self.emp, "agy-chat"))

        # 9. a group of two AGY employees, and a routine for one
        status_, made = self.call("/api/groups", "POST", {"profile_ids": [self.emp, self.card("虛構的第四位 AGY 員工")], "name": "QA 群組"})
        self.assertEqual(status_, 200, made)
        self.assertEqual(made["notes"], [], "one company says nothing")
        status_, grp = self.call("/api/groups")
        self.assertEqual(len(grp["groups"]), 1)
        status_, routine = self.call("/api/routines", "POST", {"name": "每天早上的整理", "profile_id": self.emp, "text": "請整理三行待辦。",
                                                              "days": [1], "times": ["09:00"], "enabled": False})
        self.assertEqual((status_, routine["routine"]["enabled"]), (201, False), routine)
        self.assertEqual(self.call(f"/api/routines/{routine['routine']['id']}/delete", "POST", {})[0], 200)
        self.assertEqual(self.call(f"/api/groups/{made['group']['id']}", "DELETE")[0], 200)

        # 10. a team template with AGY: safe, tool agy, no model, memory and shared files unchanged; the undo takes it away
        body = {"tool": "agy", "cards": [{"from": {"template": "life", "key": "coach"}}], "skills": [], "routines": []}
        status_, preview = self.call("/api/templates/preview", "POST", body)
        self.assertEqual((status_, len(preview["preview"]["cards"])), (200, 1), preview)
        status_, applied = self.call("/api/templates/apply", "POST", body)
        self.assertEqual(status_, 201, applied)
        made_card = next(i["id"] for i in applied["apply"]["items"] if i["kind"] == "card")
        stored = next(p for p in self.call("/api/agent-profiles")[1]["profiles"] if p["id"] == made_card)
        self.assertEqual((stored["launch_mode"], stored["model"]["tool"], stored["model"].get("model_id") or ""), ("safe", "agy", ""))
        after = self.watched()
        self.assertEqual(after["config.json"], before["config.json"], "an apply does not touch config.json")
        status_, plan = self.call(f"/api/templates/applies/{applied['apply']['id']}/undo-preview", "POST", {})
        status_, done = self.call(f"/api/templates/applies/{applied['apply']['id']}/undo", "POST", {"delete": [d["id"] for d in plan["delete"]]})
        self.assertEqual((status_, len(done["deleted"])), (200, 1), done)

        # 11. the kinds of record the chats wrote are the ones v0.19.0 had
        kinds = set()
        for chat_id in (first, other, third):
            kinds |= {r["kind"] for r in self.view(chat_id)["records"]}
        self.assertLessEqual(kinds, v019_kinds())
        # 12. the chats are deleted; AGY's own copies are not VBear's to delete
        for chat_id in (first, other, third):
            self.assertEqual(self.call(f"/api/chats/{chat_id}", "DELETE")[0], 200)
            self.assertFalse((self.base / "chats" / chat_id).exists())


class GoingBackToV019(ApiCase):
    """Read from the code and a test: what v0.19.0 does with what this release wrote. (The text of what happens is in the CHANGELOG and in the security model.)"""

    def chat_with_cost(self):
        self.configure("text")
        chat_id = self.open_http()
        self.say(chat_id)
        self.wait_http_turn(chat_id, 1)
        return chat_id

    def test_the_days_spending_does_not_read_chat_json(self):
        """The engine is in chat.json; the spending is in the events. A chat.json that v0.19.0 does not understand cannot make the day unknown."""
        chat_id = self.chat_with_cost()
        now = time.time()
        known = cs.day_spent(self.base, now)
        self.assertEqual(known, Decimal(USAGE_COST))
        path = self.base / "chats" / chat_id / "chat.json"
        data = json.loads(path.read_text())
        self.assertEqual(data["engine"], "agy-chat")
        path.write_text(json.dumps(dict(data, engine="a-future-engine")))
        self.assertEqual(cs.day_spent(self.base, now), known)
        path.unlink()
        self.assertEqual(cs.day_spent(self.base, now), known, "not even a chat.json that is gone")

    def test_an_agy_chat_writes_only_the_kinds_v019_had_and_chat_json_only_gets_one_new_engine_word(self):
        chat_id = self.chat_with_cost()
        records = self.view(chat_id)["records"]
        self.assertLessEqual({r["kind"] for r in records}, v019_kinds())
        data = json.loads((self.base / "chats" / chat_id / "chat.json").read_text())
        self.assertEqual(set(data), {"v", "id", "profile_id", "created_at", "engine"}, "no new field in chat.json")
        self.assertEqual(data["v"], 2)

    OLD_READS = """
import json, sys, time
sys.path.insert(0, sys.argv[1])
from pathlib import Path
from vbear.runtime import chat_store as cs
from vbear import chat_service, templates_apply
base, chat_id = Path(sys.argv[2]), sys.argv[3]
out = {}
try:
    cs.load(base, chat_id)
    out["load"] = "read"
except cs.ChatStoreError as exc:
    out["load"] = [exc.code, str(exc)]
out["spent"] = str(cs.day_spent(base, time.time()))
out["gate"] = list(chat_service.card_gate({"enabled": True, "model": {"tool": "agy"}})[:2])
out["gate_claude"] = list(chat_service.card_gate({"enabled": True, "model": {"tool": "claude"}})[:2])
apply = {"id": "ta-0123456789ab", "at": 1.0, "tool": "agy", "state": "done", "undone_at": None, "items": []}
out["apply_problem"] = templates_apply.problem_of_apply(apply)
try:
    templates_apply.begin_apply("agy")
    out["begin_apply"] = "made"
except Exception as exc:
    out["begin_apply"] = type(exc).__name__
print(json.dumps(out))
"""

    def test_v0190_itself_reads_what_this_release_wrote_the_way_the_changelog_says(self):
        """Run the code of the v0.19.0 tag (git archive, a temporary folder) over an AGY chat this release wrote."""
        import os
        import shutil
        import tempfile
        try:
            tmp = Path(tempfile.mkdtemp(prefix="vb19-"))
        except OSError:
            self.skipTest("no temporary folder")
        self.addCleanup(shutil.rmtree, tmp, True)
        try:
            tar = subprocess.run(["git", "-C", str(REPO), "archive", V019, "vbear"], capture_output=True, timeout=60)
        except (OSError, subprocess.SubprocessError):
            self.skipTest("git cannot show v0.19.0 here")
        if tar.returncode != 0:
            self.skipTest("v0.19.0 is not in this checkout")
        subprocess.run(["tar", "-x", "-C", str(tmp)], input=tar.stdout, check=True, timeout=60)
        chat_id = self.chat_with_cost()
        env = {"PATH": os.environ.get("PATH", ""), "HOME": str(tmp), "VBEAR_HOME": str(self.base)}
        done = subprocess.run([sys.executable, "-c", self.OLD_READS, str(tmp), str(self.base), chat_id], capture_output=True, text=True,
                              timeout=60, env=env, cwd=str(tmp))
        self.assertEqual(done.returncode, 0, done.stderr[-800:])
        got = json.loads(done.stdout.strip().splitlines()[-1])
        self.assertEqual(got["load"][0], "damaged", "v0.19.0 reads the AGY chat.json as one whose fields do not match")
        self.assertIn("欄位不符", got["load"][1])
        self.assertEqual(Decimal(got["spent"]), Decimal(USAGE_COST), "the day's spending still counts the AGY turn (no new kind of record)")
        self.assertEqual(got["gate"][0], False)
        self.assertEqual(got["gate"][1], "card_tool_unsupported", "an AGY card cannot chat in v0.19.0")
        self.assertEqual(got["gate_claude"], [True, ""])
        self.assertEqual(got["apply_problem"], "tool", "an apply record made with AGY is a record v0.19.0 cannot read")
        self.assertEqual(got["begin_apply"], "StoreError", "and v0.19.0 itself cannot make an apply with AGY")


if __name__ == "__main__":
    unittest.main()
