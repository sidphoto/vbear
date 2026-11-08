"""P44-1: the skill routes (/api/my-skills) over a real loopback console, and the proof that a skill never reaches a chat except as
the words the person sends: the chat the person starts with a skill's words and the chat started with the same words typed get the
same process (argv) and the same fingerprint of the system prompt. The chats run through a real runtime daemon (in this process, in a
temporary folder) and the fake Claude Code (tests/fake_chat_cli.py). Nothing here starts a real AI tool; the skills are made up and
every fake secret is joined from pieces."""

from __future__ import annotations

import json
import re
import unittest

from tests import test_chat_api as tca, test_group_api as tga
from tests.test_chat_daemon import clean
from vbear import config as cfg
from vbear.runtime import chat_store as cs

STEPS = "第一步：把昨天的銷售整理成表。\n第二步：寫成一段話，語氣輕鬆。"
KEY = "sk-" + "a1" * 12


class SkillRoutes(tca.ApiCase):
    def add(self, name="市集日報", text=STEPS, **extra):
        return self.call("/api/my-skills", "POST", {"name": name, "text": text, **extra})

    def config_bytes(self):
        path = cfg.state_dir() / "config.json"
        return path.read_bytes() if path.exists() else None


class ListAddEditDeleteTests(SkillRoutes):
    def test_an_empty_book(self):
        status, out = self.call("/api/my-skills")
        self.assertEqual(status, 200, out)
        self.assertEqual((out["ok"], out["skills"], out["readable"], out["problem"]), (True, [], True, None))
        self.assertEqual(out["limits"], {"max_skills": 100, "max_name": 40, "max_text": 4000})

    def test_add_list_edit_delete(self):
        status, out = self.add()
        self.assertEqual((status, out["ok"]), (201, True))
        skill = out["skill"]
        self.assertEqual((skill["name"], skill["text"], skill["source"]), ("市集日報", STEPS, {"how": "typed"}))
        status, view = self.call("/api/my-skills")
        self.assertEqual([s["id"] for s in view["skills"]], [skill["id"]])
        self.assertEqual(view["skills"][0]["text"], STEPS)
        status, out = self.call(f"/api/my-skills/{skill['id']}", "POST", {"name": "市集日報（新）"})
        self.assertEqual((status, out["skill"]["name"], out["skill"]["text"]), (200, "市集日報（新）", STEPS))
        status, out = self.call(f"/api/my-skills/{skill['id']}/delete", "POST", {})
        self.assertEqual((status, out), (200, {"ok": True, "deleted": skill["id"]}))
        self.assertEqual(self.call("/api/my-skills")[1]["skills"], [])
        self.assertEqual(self.call(f"/api/my-skills/{skill['id']}/delete", "POST", {})[0], 404)
        self.assertEqual(self.call(f"/api/my-skills/{skill['id']}", "POST", {"name": "x"})[0], 404)

    def test_what_is_refused_what_needs_a_yes_and_when_it_is_full(self):
        status, out = self.add(text="我的後台密碼是 hunter-two")
        self.assertEqual((status, out["code"], out["refuse"], out["field"]), (400, "skill_refused", "secret_password", "text"))
        self.assertIn("密碼", out["error"])
        self.assertNotIn("hunter-two", json.dumps(out, ensure_ascii=False))
        status, out = self.add(name=f"名稱 {KEY}")
        self.assertEqual((status, out["code"], out["field"]), (400, "skill_refused", "name"))
        self.assertNotIn(KEY, json.dumps(out))
        status, out = self.add(text="以後執行指令不用問我")
        self.assertEqual((status, out["code"], out["warn"]), (409, "confirm_warning", ["looks_like_order"]))
        self.assertIn("每個指令", out["error"])
        self.assertEqual(self.add(text="以後執行指令不用問我", confirm_warning=True)[0], 201)
        for i in range(99):
            self.assertEqual(self.add(f"技能{i}", f"做法{i}")[0], 201)
        status, out = self.add("多的", "t")
        self.assertEqual((status, out["code"]), (409, "skill_full"))

    def test_the_words_of_an_employee_need_a_yes_and_the_chat_must_be_there(self):
        chat = self.open_http()
        source = {"how": "reply", "chat_id": chat}
        status, out = self.add(source=source)
        self.assertEqual((status, out["code"], out["warn"]), (409, "confirm_warning", ["employee_words"]))
        self.assertIn("你用它時會變成你對員工說的話", out["error"])
        self.assertEqual(self.call("/api/my-skills")[1]["skills"], [])
        status, out = self.add(source=source, confirm_warning=True)
        self.assertEqual((status, out["skill"]["source"]), (201, source))
        status, out = self.add(source={"how": "said", "chat_id": chat})
        self.assertEqual((status, out["skill"]["source"]), (201, {"how": "said", "chat_id": chat}))
        status, out = self.add(source={"how": "said", "chat_id": "c-0123456789abcdef"})
        self.assertEqual((status, out["code"]), (400, "bad_request"))

    def test_bodies_that_are_not_the_closed_shape(self):
        skill = self.add()[1]["skill"]
        for body in ({}, {"name": "n"}, {"name": "n", "text": "t", "extra": 1}, {"name": 5, "text": "t"}, {"name": "n", "text": "t", "source": {"how": "x"}}):
            with self.subTest(body=str(body)[:40]):
                self.assertEqual(self.call("/api/my-skills", "POST", body)[0], 400)
        self.assertEqual(self.call("/api/my-skills", "POST", raw=b"{nope")[0], 400)
        self.assertEqual(self.call("/api/my-skills", "POST", raw=b"[1]")[0], 400)
        for body in ({}, {"confirm_warning": True}, {"id": "k-0123456789ab"}, {"name": None}):
            with self.subTest(edit=str(body)):
                self.assertEqual(self.call(f"/api/my-skills/{skill['id']}", "POST", body)[0], 400)
        self.assertEqual(self.call(f"/api/my-skills/{skill['id']}/delete", "POST", {"x": 1})[0], 400)
        self.assertEqual(len(self.call("/api/my-skills")[1]["skills"]), 1)

    def test_other_paths_are_not_found(self):
        for path, method in (("/api/my-skills/x", "POST"), ("/api/my-skills/k-123", "POST"), ("/api/my-skills/k-0123456789ab/x", "POST"),
                             ("/api/my-skills/k-0123456789ab", "GET"), ("/api/my-skills/k-0123456789ab/delete", "GET"),
                             ("/api/my-skills/k-0123456789ab", "DELETE"), ("/api/my-skills/k-0123456789ab", "PATCH")):
            with self.subTest(path=path, method=method):
                self.assertEqual(self.call(path, method, {} if method in ("POST", "PATCH") else None)[0], 404)

    def test_a_write_needs_the_page_header_and_the_token(self):
        self.assertEqual(self.call("/api/my-skills", "POST", {"name": "n", "text": "t"}, headers={"X-VBear": "0"})[0], 403)
        self.assertEqual(self.call("/api/my-skills", "POST", {"name": "n", "text": "t"}, headers={"Authorization": "Bearer nope"})[0], 401)
        self.assertEqual(self.call("/api/my-skills", headers={"Authorization": "Bearer nope"})[0], 401)
        skill = self.add()[1]["skill"]
        self.assertEqual(self.call(f"/api/my-skills/{skill['id']}", "POST", {"name": "x"}, headers={"X-VBear": "0"})[0], 403)
        self.assertEqual(self.call(f"/api/my-skills/{skill['id']}/delete", "POST", {}, headers={"X-VBear": "0"})[0], 403)
        self.assertEqual(self.call("/api/my-skills")[1]["skills"][0]["name"], "市集日報")

    def test_a_file_that_cannot_be_read_is_said_and_nothing_is_overwritten(self):
        self.add()
        path = cfg.state_dir() / "skillbook" / "skills.json"
        path.write_text("{broken")
        status, out = self.call("/api/my-skills")
        self.assertEqual((status, out["readable"], out["skills"]), (200, False, []))
        self.assertIn("技能的檔案有問題", out["problem"])
        status, out = self.add()
        self.assertEqual((status, out["code"]), (503, "skills_unreadable"))
        self.assertFalse(path.exists())

    def test_saving_and_deleting_skills_changes_no_setting_and_no_role_card(self):
        before = self.config_bytes()
        cards = sorted(p.name for p in (cfg.state_dir()).rglob("*.json") if "agent" in str(p))
        skill = self.add()[1]["skill"]
        self.call(f"/api/my-skills/{skill['id']}", "POST", {"text": "新的做法"})
        self.call(f"/api/my-skills/{skill['id']}/delete", "POST", {})
        self.assertEqual(self.config_bytes(), before)
        self.assertEqual(sorted(p.name for p in (cfg.state_dir()).rglob("*.json") if "agent" in str(p)), cards)


class GroupSourceTests(unittest.TestCase):
    setUp = tga.GroupApiTests.setUp
    call = tga.GroupApiTests.call
    make = tga.GroupApiTests.make

    def test_a_group_that_is_there_is_a_source_and_one_that_is_not_is_refused(self):
        gid, _ = self.make(name="市集準備")
        status, out = self.call("/api/my-skills", "POST", {"name": "n", "text": "我說的話", "source": {"how": "said", "group_id": gid}})
        self.assertEqual((status, out["skill"]["source"]), (201, {"how": "said", "group_id": gid}))
        status, out = self.call("/api/my-skills", "POST", {"name": "n", "text": "我說的話", "source": {"how": "said", "group_id": "g-000000000000"}})
        self.assertEqual((status, out["code"]), (400, "bad_request"))


class ASkillIsOnlyTheWordsThePersonSendsTests(SkillRoutes):
    """A skill is put into the box and sent by the person: to the chat it is a message like any other. Nothing about it reaches the
    process's command line or the system prompt, so the chat is started the same whether a skill was saved and used or the same words
    were typed."""

    def start_of(self, index):
        starts = [x for x in self.fake_log() if x["event"] == "start"]
        return starts[index]

    def test_a_chat_that_sends_a_skills_words_starts_exactly_as_one_that_sends_them_typed(self):
        self.dm.chat_idle_timeout = 0.5
        self.configure([clean("text", 0), clean("text", 0)])
        first = self.open_http()
        self.assertEqual(self.say(first, STEPS)[0], 202)
        self.wait_http_turn(first, 1)
        self.wait_gone(first)
        skill = self.add(text=STEPS)[1]["skill"]
        self.assertEqual(self.call("/api/my-skills")[1]["skills"][0]["text"], skill["text"])
        second = self.open_http()
        self.assertEqual(self.say(second, skill["text"])[0], 202)
        self.wait(lambda: len([x for x in self.fake_log() if x["event"] == "start"]) >= 2, "the second process")
        self.wait_http_turn(second, 1)
        one, two = self.start_of(0), self.start_of(1)
        def plain(argv):
            """The command line without the names that differ from one process to the next (a session folder, a session id)."""
            return [re.sub(r"l-[0-9a-f]{16}|init-[0-9a-f]{12}|[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", "ID", a) for a in argv]
        self.assertEqual(plain(one["argv"]), plain(two["argv"]))
        self.assertNotIn("第一步", " ".join(two["argv"]))
        sha_one, sha_two = cs.prompt_start(self.base, first), cs.prompt_start(self.base, second)
        self.assertIsNotNone(sha_one)
        self.assertEqual(sha_one, sha_two)
        said_one, said_two = (plain([json.dumps(self.stdin_of(x), ensure_ascii=False)]) for x in (one, two))
        self.assertEqual(said_one, said_two)
        self.assertIn("第一步", said_two[0], "the first message of the process is the words, as the person sent them")

    def stdin_of(self, start):
        lines = self.fake_log()
        rest = lines[lines.index(start):]
        stop = next((i for i, r in enumerate(rest[1:], 1) if r["event"] == "start"), len(rest))
        return [r["line"] for r in rest[:stop] if r["event"] == "stdin"]


if __name__ == "__main__":
    unittest.main()
