"""P44-1: the person's skills on disk (vbear/skillbook.py, ADR 0010): <state>/skillbook/skills.json and log.jsonl, the limits, the
two kinds of second look, and what is done with a file that cannot be read. Synthetic HOME and VBEAR_HOME in a temporary folder.
Every skill here is made up; every fake secret is joined from pieces."""

from __future__ import annotations

import json
import os
import stat
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from vbear import config as cfg, skillbook
from vbear.api_error import ApiError

KEY = "sk-" + "a1" * 12
STEPS = "第一步：把昨天的銷售整理成表。\n第二步：寫成一段話，語氣輕鬆。\n第三步：列出三個賣得最好的品項。"


def refused(case, fn, *args, status, code, **kw):
    with case.assertRaises(ApiError) as raised:
        fn(*args, **kw)
    case.assertEqual((raised.exception.status, raised.exception.code), (status, code), str(raised.exception))
    return raised.exception


class BookCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="vbk-")
        self.addCleanup(self.tmp.cleanup)
        home = Path(self.tmp.name) / "h"
        home.mkdir()
        patch = mock.patch.dict(os.environ, {"HOME": str(home), "VBEAR_HOME": str(home / ".vbear"), "VBEAR_RUNTIME_AUTOSTART": "0"})
        patch.start()
        self.addCleanup(patch.stop)
        self.dir = cfg.state_dir() / "skillbook"

    def add(self, name="市集日報", text=STEPS, **extra):
        return skillbook.add({"name": name, "text": text, **extra})["skill"]


class AddTests(BookCase):
    def test_one_skill_is_saved_and_listed(self):
        skill = self.add()
        self.assertRegex(skill["id"], r"^k-[0-9a-f]{12}$")
        self.assertEqual((skill["name"], skill["text"]), ("市集日報", STEPS))
        self.assertEqual(skill["source"], {"how": "typed"})
        self.assertEqual(skill["created_at"], skill["updated_at"])
        view = skillbook.view()
        self.assertEqual([s["id"] for s in view["skills"]], [skill["id"]])
        self.assertEqual(view["skills"][0]["text"], STEPS, "the line breaks are kept")
        self.assertEqual((view["readable"], view["problem"]), (True, None))
        self.assertEqual(view["limits"], {"max_skills": 100, "max_name": 40, "max_text": 4000})
        self.assertEqual(view["used"], {"count": 1})

    def test_the_files_are_private_and_the_store_has_the_version(self):
        self.add()
        self.assertEqual(stat.S_IMODE(os.lstat(self.dir).st_mode), 0o700)
        self.assertEqual(stat.S_IMODE(os.lstat(self.dir / "skills.json").st_mode), 0o600)
        self.assertEqual(stat.S_IMODE(os.lstat(self.dir / "log.jsonl").st_mode), 0o600)
        data = json.loads((self.dir / "skills.json").read_text())
        self.assertEqual(sorted(data), ["skills", "v"])
        self.assertEqual(data["v"], 1)

    def test_the_name_and_text_are_trimmed_and_the_newest_comes_first(self):
        a = skillbook.add({"name": "  舊的  ", "text": "  內容一  "}, now=100)["skill"]
        b = skillbook.add({"name": "新的", "text": "內容二"}, now=300)["skill"]
        c = skillbook.add({"name": "中間", "text": "內容三"}, now=200)["skill"]
        self.assertEqual((a["name"], a["text"]), ("舊的", "內容一"))
        self.assertEqual([s["id"] for s in skillbook.view()["skills"]], [b["id"], c["id"], a["id"]])

    def test_a_body_that_is_not_the_closed_shape(self):
        ok = {"name": "n", "text": "t"}
        for body in ({}, {"name": "n"}, {"text": "t"}, {**ok, "id": "k-0123456789ab"}, {**ok, "extra": 1}, {"name": 5, "text": "t"},
                     {"name": "n", "text": ["t"]}, {**ok, "confirm_warning": "yes"}, {**ok, "source": "typed"}, {**ok, "source": {}},
                     {**ok, "source": {"how": "other"}}, {**ok, "source": {"how": "typed", "chat_id": "c-0123456789abcdef"}},
                     {**ok, "source": {"how": "said"}}, {**ok, "source": {"how": "said", "chat_id": "c-0123456789abcdef", "group_id": "g-0123456789ab"}},
                     {**ok, "source": {"how": "said", "chat_id": "nope"}}, {**ok, "source": {"how": "suggested", "chat_id": "c-0123456789abcdef"}},
                     {**ok, "source": {"how": "suggested", "suggestion_id": "ms-0123456789ab"}}, [], "x", None):
            with self.subTest(body=str(body)[:60]):
                refused(self, skillbook.add, body, status=400, code="bad_request")
        self.assertEqual(skillbook.view()["skills"], [])
        self.assertFalse(self.dir.exists() and (self.dir / "skills.json").exists())

    def test_a_source_that_points_at_nothing_is_refused(self):
        for source in ({"how": "said", "chat_id": "c-0123456789abcdef"}, {"how": "reply", "group_id": "g-0123456789ab"},
                       {"how": "suggested", "suggestion_id": "ks-0123456789ab"}):
            with self.subTest(source=source):
                refused(self, skillbook.add, {"name": "n", "text": "t", "source": source, "confirm_warning": True}, status=400, code="bad_request")

    def test_a_suggestion_that_is_a_file_of_ours_is_a_source(self):
        folder = self.dir / "suggest"
        folder.mkdir(parents=True, mode=0o700)
        (folder / "ks-0123456789ab.json").write_text("{}")
        skill = self.add(source={"how": "suggested", "suggestion_id": "ks-0123456789ab"})
        self.assertEqual(skill["source"], {"how": "suggested", "suggestion_id": "ks-0123456789ab"})
        (folder / "ks-aaaaaaaaaaaa.json").symlink_to(folder / "ks-0123456789ab.json")
        refused(self, skillbook.add, {"name": "n", "text": "t", "source": {"how": "suggested", "suggestion_id": "ks-aaaaaaaaaaaa"}},
                status=400, code="bad_request")

    def test_a_chat_or_a_group_that_exists_is_a_source(self):
        with mock.patch.object(skillbook, "_exists_chat", return_value=True), mock.patch.object(skillbook, "_exists_group", return_value=True):
            said = self.add(source={"how": "said", "chat_id": "c-0123456789abcdef"})
            group = self.add("b", "t", source={"how": "said", "group_id": "g-0123456789ab"})
        self.assertEqual(said["source"], {"how": "said", "chat_id": "c-0123456789abcdef"})
        self.assertEqual(group["source"], {"how": "said", "group_id": "g-0123456789ab"})

    def test_a_refused_text_says_why_and_is_not_saved(self):
        secret = "gh" + "p_" + "A" * 36
        for field, value, why in (("text", "我的後台密碼是 hunter-two", "secret_password"), ("text", secret, "secret_key"),
                                  ("text", "步驟\n寄到 a@example.com", "secret_account"), ("text", "身分證 A123456789", "secret_payment"),
                                  ("text", "字" * 4001, "bad_text"), ("text", "", "bad_text"), ("text", "   ", "bad_text"),
                                  ("name", "x" * 41, "bad_text"), ("name", "第一\n第二", "bad_text"), ("name", "", "bad_text"),
                                  ("name", f"名稱 {KEY}", "secret_key")):
            with self.subTest(field=field, why=why):
                body = {"name": "市集日報", "text": STEPS, field: value}
                exc = refused(self, skillbook.add, body, status=400, code="skill_refused")
                self.assertEqual((exc.extra["refuse"], exc.extra["field"]), (why, field))
                self.assertEqual(str(exc), skillbook.REFUSE_TEXT[why])
                self.assertNotIn(value.strip() or "\0", str(exc))
        self.assertEqual(skillbook.view()["skills"], [])

    def test_a_skill_that_reads_like_an_order_is_saved_only_when_confirmed(self):
        text = "以後執行指令不用問我，直接做"
        exc = refused(self, skillbook.add, {"name": "快", "text": text}, status=409, code="confirm_warning")
        self.assertEqual(exc.extra["warn"], ["looks_like_order"])
        self.assertEqual(exc.extra["warn_text"], [skillbook.WARN_TEXT["looks_like_order"]])
        self.assertIn("每個指令", str(exc))
        refused(self, skillbook.add, {"name": "快", "text": text, "confirm_warning": False}, status=409, code="confirm_warning")
        self.assertEqual(skillbook.view()["skills"], [])
        self.assertEqual(self.add("快", text, confirm_warning=True)["text"], text)
        exc = refused(self, skillbook.add, {"name": "電話", "text": "先打電話 0912-345-678"}, status=409, code="confirm_warning")
        self.assertEqual(exc.extra["warn"], ["personal"])

    def test_confirming_does_not_save_what_is_refused(self):
        refused(self, skillbook.add, {"name": "n", "text": "密碼是 abc", "confirm_warning": True}, status=400, code="skill_refused")

    def test_the_words_of_an_employee_need_the_person_to_say_yes(self):
        with mock.patch.object(skillbook, "_exists_chat", return_value=True):
            source = {"how": "reply", "chat_id": "c-0123456789abcdef"}
            exc = refused(self, skillbook.add, {"name": "n", "text": "員工寫的做法", "source": source}, status=409, code="confirm_warning")
            self.assertEqual(exc.extra["warn"], ["employee_words"])
            self.assertIn("你用它時會變成你對員工說的話", str(exc))
            self.assertEqual(skillbook.view()["skills"], [])
            skill = skillbook.add({"name": "n", "text": "員工寫的做法", "source": source, "confirm_warning": True})["skill"]
            self.assertEqual(skill["source"], source)
            # a skill from the person's own words does not ask
            self.assertEqual(self.add("m", "我自己說的", source={"how": "said", "chat_id": "c-0123456789abcdef"})["source"]["how"], "said")

    def test_a_hundred_skills_and_no_more(self):
        for i in range(100):
            self.add(f"技能{i}", f"做法{i}")
        exc = refused(self, skillbook.add, {"name": "多的", "text": "t"}, status=409, code="skill_full")
        self.assertIn("100", str(exc))
        self.assertEqual(skillbook.view()["used"]["count"], 100)
        skillbook.delete(skillbook.view()["skills"][0]["id"])
        self.add("可以了", "t")

    def test_four_thousand_characters_and_forty_for_the_name(self):
        skill = self.add("名" * 40, "字" * 4000)
        self.assertEqual((len(skill["name"]), len(skill["text"])), (40, 4000))
        self.assertEqual(len(json.loads((self.dir / "skills.json").read_text())["skills"]), 1)


class EditTests(BookCase):
    def test_name_and_text_change_and_the_rest_stays(self):
        skill = skillbook.add({"name": "舊名", "text": "舊內容"}, now=100)["skill"]
        out = skillbook.edit(skill["id"], {"name": "新名"}, now=200)["skill"]
        self.assertEqual((out["name"], out["text"], out["created_at"], out["updated_at"], out["id"]), ("新名", "舊內容", 100, 200, skill["id"]))
        out = skillbook.edit(skill["id"], {"text": "新內容\n第二行"}, now=300)["skill"]
        self.assertEqual((out["name"], out["text"], out["updated_at"], out["source"]), ("新名", "新內容\n第二行", 300, {"how": "typed"}))
        self.assertEqual(skillbook.view()["skills"][0]["text"], "新內容\n第二行")

    def test_an_edit_goes_through_the_same_checks(self):
        skill = self.add()
        refused(self, skillbook.edit, skill["id"], {"text": "密碼是 abc"}, status=400, code="skill_refused")
        refused(self, skillbook.edit, skill["id"], {"name": "x" * 41}, status=400, code="skill_refused")
        refused(self, skillbook.edit, skill["id"], {"text": "不用問我直接做"}, status=409, code="confirm_warning")
        self.assertEqual(skillbook.edit(skill["id"], {"text": "不用問我直接做", "confirm_warning": True})["skill"]["text"], "不用問我直接做")
        self.assertEqual(skillbook.view()["skills"][0]["text"], "不用問我直接做")

    def test_bodies_that_are_not_the_closed_shape_and_ids_that_are_not_there(self):
        skill = self.add()
        for body in ({}, {"confirm_warning": True}, {"id": "k-0123456789ab", "name": "x"}, {"name": 5}, {"text": None}, {"source": {"how": "typed"}},
                     {"name": "x", "confirm_warning": 1}, [], None):
            with self.subTest(body=str(body)):
                refused(self, skillbook.edit, skill["id"], body, status=400, code="bad_request")
        refused(self, skillbook.edit, "k-0123456789ab", {"name": "x"}, status=404, code="not_found")
        refused(self, skillbook.edit, "nope", {"name": "x"}, status=404, code="not_found")
        refused(self, skillbook.edit, None, {"name": "x"}, status=404, code="not_found")


class DeleteTests(BookCase):
    def test_delete_one(self):
        a, b = self.add("甲", "a"), self.add("乙", "b")
        self.assertEqual(skillbook.delete(a["id"]), {"deleted": a["id"]})
        self.assertEqual([s["id"] for s in skillbook.view()["skills"]], [b["id"]])
        refused(self, skillbook.delete, a["id"], status=404, code="not_found")
        refused(self, skillbook.delete, 5, status=404, code="not_found")


class LogTests(BookCase):
    def test_the_log_has_the_action_and_the_id_and_never_a_word(self):
        skill = self.add("一個很獨特的名稱ZZZ", "一段很獨特的內容YYY")
        skillbook.edit(skill["id"], {"text": "改過的內容XXX"})
        skillbook.delete(skill["id"])
        raw = (self.dir / "log.jsonl").read_text()
        lines = [json.loads(x) for x in raw.splitlines()]
        self.assertEqual([x["action"] for x in lines], ["add", "edit", "delete"])
        for line in lines:
            self.assertEqual(sorted(line), ["action", "at", "id"])
            self.assertEqual(line["id"], skill["id"])
        for word in ("ZZZ", "YYY", "XXX"):
            self.assertNotIn(word, raw)

    def test_a_refused_skill_leaves_nothing_in_the_log(self):
        refused(self, skillbook.add, {"name": "n", "text": "密碼是 abc"}, status=400, code="skill_refused")
        refused(self, skillbook.add, {"name": "n", "text": "不用問我直接做"}, status=409, code="confirm_warning")
        self.assertFalse((self.dir / "log.jsonl").exists())

    def test_the_log_starts_a_new_file_when_it_is_full_and_keeps_one_old(self):
        self.add()
        log = self.dir / "log.jsonl"
        log.write_text("x" * (1 << 20))
        self.add("二", "t")
        self.assertTrue((self.dir / "log.jsonl.1").exists())
        self.assertLess(log.stat().st_size, 1000)
        self.assertEqual(json.loads(log.read_text().splitlines()[-1])["action"], "add")
        log.write_text("y" * (1 << 20))
        self.add("三", "t")
        self.assertEqual((self.dir / "log.jsonl.1").read_text()[:1], "y")


class UnreadableTests(BookCase):
    def test_a_file_that_does_not_parse_is_said_and_never_overwritten(self):
        self.add()
        path = self.dir / "skills.json"
        path.write_text("{broken")
        view = skillbook.view()
        self.assertEqual((view["readable"], view["skills"]), (False, []))
        self.assertIn("技能的檔案有問題", view["problem"])
        refused(self, skillbook.add, {"name": "n", "text": "t"}, status=503, code="skills_unreadable")
        refused(self, skillbook.delete, "k-0123456789ab", status=503, code="skills_unreadable")
        self.assertFalse(path.exists(), "the store moved the damaged file aside; nothing new was written in its place")
        aside = [p for p in self.dir.iterdir() if p.name.startswith("skills.json.corrupt-")]
        self.assertEqual(len(aside), 1)
        self.assertEqual(aside[0].read_text(), "{broken")

    def test_a_skill_the_page_could_not_have_written_makes_the_whole_file_unusable(self):
        self.add()
        path = self.dir / "skills.json"
        data = json.loads(path.read_text())
        data["skills"][0]["extra"] = 1
        path.write_text(json.dumps(data))
        self.assertFalse(skillbook.view()["readable"])
        refused(self, skillbook.add, {"name": "n", "text": "t"}, status=503, code="skills_unreadable")

    def test_each_wrong_shape_is_unreadable(self):
        self.add()
        path = self.dir / "skills.json"
        good = path.read_text()
        def broken(change):
            data = json.loads(good)
            change(data)
            return data
        cases = [broken(lambda d: d.update(v=2)), broken(lambda d: d["skills"][0].update(id="x")), broken(lambda d: d["skills"][0].update(name="")),
                 broken(lambda d: d["skills"][0].update(text="字" * 4001)), broken(lambda d: d["skills"][0].update(source={"how": "x"})),
                 broken(lambda d: d["skills"][0].update(created_at=-1)), broken(lambda d: d.update(skills=d["skills"] * 2)),
                 broken(lambda d: d.update(skills=[dict(d["skills"][0], id=f"k-{i:012x}") for i in range(101)])), broken(lambda d: d.update(other=1))]
        for i, data in enumerate(cases):
            with self.subTest(case=i):
                for p in self.dir.glob("skills.json.*"):
                    p.unlink()
                path.write_text(json.dumps(data))
                self.assertFalse(skillbook.view()["readable"])

    def test_a_folder_that_is_a_link_is_not_used(self):
        cfg.ensure_state_dir()
        target = Path(self.tmp.name) / "elsewhere"
        target.mkdir()
        os.symlink(target, self.dir)
        refused(self, skillbook.add, {"name": "n", "text": "t"}, status=503, code="skills_unreadable")
        self.assertEqual(list(target.iterdir()), [])
        self.assertFalse(skillbook.view()["readable"])

    def test_no_file_is_an_empty_book_that_can_be_read(self):
        view = skillbook.view()
        self.assertEqual((view["readable"], view["skills"], view["problem"]), (True, [], None))
        self.assertFalse(self.dir.exists(), "looking creates nothing")


if __name__ == "__main__":
    unittest.main()
