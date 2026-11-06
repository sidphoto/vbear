"""P40-3: the dispatch record, the confirmation of a proposal card, 「自己動手」 and 「AI 自己做了什麼」.

Seams: the proposal the chief of staff keeps (a real ChiefRunner with a fake call, hooked to ``Dispatcher.from_proposal``), the
Dispatcher's operations (confirm, dismiss, withdraw_card, delete, recover_all, actions) and what they leave in the person's
cards, task cards and chats. No CLI runs; nothing leaves the machine; HOME and VBEAR_HOME are synthetic and short."""
from __future__ import annotations

import copy
import hashlib
import json
import os
import tempfile
import time
import unittest
from decimal import Decimal
from pathlib import Path
from unittest import mock

from vbear import agent_profiles as ap, autonomy, chief, chief_runner as cr, config as cfg, dispatch, meeting_runner as mr
from vbear import position_guide, tasks
from vbear.runtime import chat_store as cs

VERSION = "2.1.296"
EVIDENCE = {"cli_version": VERSION, "model_reported": "m", "tools_reported": ["StructuredOutput"], "mcp_servers_reported": [],
            "exit_code": 0, "duration_ms": 1}


def plan(**changes):
    out = {"summary": "先寫介紹，再算價", "task": {"title": "週末市集攤位", "goal": "準備賣手工皂的攤位", "deliverables": ["攤位介紹", "價目表"]},
           "team": [{"who": "C1", "why": "會寫文案"}, {"who": "N1", "why": "要算成本"}],
           "new_cards": [{"ref": "N1", "name": "會計師", "position": "accountant", "tool": "claude", "model_alias": "haiku", "why": "算價"}],
           "steps": [{"who": "C1", "text": "請寫一份攤位介紹。"}, {"who": "N1", "text": "請算成本與定價。"}], "questions": []}
    out.update(changes)
    return out


def old_hands_plan(**changes):
    """A plan that needs nobody new: two steps for the one employee on the list."""
    return plan(team=[{"who": "C1", "why": "會寫文案"}], new_cards=[],
                steps=[{"who": "C1", "text": "請寫一份攤位介紹。"}, {"who": "C1", "text": "請依回饋改好。"}], **changes)


class Base(unittest.TestCase):
    TOOLS = ("claude",)

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="vbd-")
        self.addCleanup(self.tmp.cleanup)
        home = Path(os.path.realpath(self.tmp.name)) / "h"
        home.mkdir()
        (home / ".vbear").mkdir(mode=0o700)
        patch = mock.patch.dict(os.environ, {"HOME": str(home), "VBEAR_HOME": str(home / ".vbear"), "VBEAR_RUNTIME_AUTOSTART": "0"})
        patch.start()
        self.addCleanup(patch.stop)
        self.answer = plan()
        self.busy_chats: set = set()
        self.links: list = []
        self.dispatcher = dispatch.Dispatcher(conf=cfg.load, tools=lambda: self.TOOLS, link=self.link,
                                              busy=lambda chat_id: chat_id in self.busy_chats)
        self.runner = cr.ChiefRunner(provider=lambda e: ("unused", VERSION), call=self.fake_call,
                                     on_proposal=self.dispatcher.from_proposal)
        self.addCleanup(self.runner.wait, 5)
        card = lambda name, position, tool="claude": ap.save_profile(None, {"name": name, "position": position, "model": {"tool": tool}})["id"]
        self.ceo, self.writer = card("虛構CEO", "planner"), card("文案小編", "social")
        self.chat_id = self.make_chat(self.ceo)

    # -- the chief of staff, with a fake call -------------------------------------------------------------------

    def fake_call(self, spec, cancel):
        return mr.CallResult(copy.deepcopy(self.answer), dict(EVIDENCE), Decimal("0.02"))

    def link(self, chief_id, dispatch_id):
        self.links.append((chief_id, dispatch_id))
        self.runner.link_dispatch(chief_id, dispatch_id)

    def make_chat(self, profile_id, said=(("user_message", "我想在週末市集擺攤賣手工皂"), ("reply", "好，先問你預算"))):
        base = cfg.state_dir()
        chat = cs.create(base, profile_id, now=time.time())
        log = cs.ChatLog(base, chat["id"])
        for kind, text in said:
            log.append(kind, {"turn": 1, "text": text, **({"truncated": False} if kind == "reply" else {})}, now=time.time())
        log.close()
        return chat["id"]

    def sources(self):
        return cr.ChiefSources(chat=cr.chat_reader(), profile=ap.get_profile_readonly,
                               profiles=lambda: list(ap.load_all(None, None, mark_corrupt=False).values()),
                               tools=lambda: self.TOOLS, conf=cfg.load())

    def propose(self, answer=None):
        """Ask the chief of staff once; the dispatch made from its proposal (its id)."""
        if answer is not None:
            self.answer = answer
        preview = self.runner.preview(self.chat_id, self.sources())
        self.assertTrue(preview["ok"], preview)
        rec = self.runner.start(preview["preview_id"], {}, self.sources())
        self.runner.wait(10)
        did = chief.load(rec["id"])["outcome"]["dispatch_id"]
        self.assertIsNotNone(did)
        return did

    def autonomy_on(self, create_cards=False, dispatch_=False):
        conf = cfg.load()
        conf["autonomy"] = {"create_cards": create_cards, "dispatch": dispatch_}
        cfg.save(conf)

    # -- what a confirmation says --------------------------------------------------------------------------------

    def body_of(self, did, **changes):
        """What the person's page sends for the proposal as it stands, changed as asked."""
        rec = dispatch.load(did)
        proposal = rec["proposal_plan"]
        body = {"proposal_sha": rec["proposal_sha"], "title": proposal["title"], "goal": proposal["goal"],
                "new_cards": copy.deepcopy(proposal["new_cards"]), "steps": copy.deepcopy(proposal["steps"])}
        body.update(changes)
        return body

    def profile_ids(self):
        return set(ap.load_all(None, None, mark_corrupt=False))

    def config_bytes(self):
        path = cfg.state_dir() / "config.json"
        return path.read_bytes() if path.exists() else None

    def events(self, did):
        return [(e["kind"], e["by"]) for e in dispatch.load(did)["events"]]


class FromProposalTests(Base):
    def test_a_proposal_becomes_a_proposed_dispatch_and_makes_nothing(self):
        before = self.profile_ids()
        did = self.propose()
        rec = dispatch.load(did)
        self.assertRegex(did, r"^d-[0-9a-f]{12}$")
        self.assertEqual((rec["state"], rec["chief_id"], rec["chat_id"], rec["started_by"]),
                         ("proposed", chief.record_ids()[0], self.chat_id, None))
        self.assertEqual(self.events(did), [("proposed", "vbear")])
        self.assertEqual(self.links, [(rec["chief_id"], did)])
        self.assertEqual(chief.load(rec["chief_id"])["outcome"]["dispatch_id"], did)
        self.assertEqual(rec["proposal_sha"], hashlib.sha256(json.dumps(
            chief.load(rec["chief_id"])["turns"][0]["output"]["kept"], ensure_ascii=False, sort_keys=True,
            separators=(",", ":")).encode()).hexdigest())
        self.assertEqual(rec["plan"], rec["proposal_plan"])
        self.assertEqual([s["who"] for s in rec["plan"]["steps"]], ["C1", "N1"])
        self.assertEqual((rec["steps"], rec["task_id"], rec["made"], rec["pause"]), ([], None, {}, None))
        self.assertEqual(self.profile_ids(), before, "no employee was made")
        self.assertEqual(tasks.list_tasks(), [], "no task card was made")

    def test_the_view_has_names_and_no_conversation(self):
        did = self.propose()
        view = self.dispatcher.get(did)
        text = json.dumps(view, ensure_ascii=False)
        for word in ("預算", "先問你", self.ceo):
            self.assertNotIn(word, text)
        self.assertEqual(view["state"], "proposed")
        self.assertEqual([(s["who"], s["name"]) for s in view["plan"]["steps"]], [("C1", "文案小編"), ("N1", "會計師")])
        self.assertEqual(view["summary"], "先寫介紹，再算價")
        self.assertTrue(view["can"]["confirm"] and view["can"]["dismiss"])
        self.assertEqual((view["can"]["delete"], view["can"]["stop"], view["can"]["continue"]), (True, False, False))

    def test_asking_again_for_the_same_proposal_does_not_make_a_second_dispatch(self):
        did = self.propose()
        chief_id = dispatch.load(did)["chief_id"]
        self.assertEqual(self.dispatcher.from_proposal(chief_id), did)
        self.assertEqual(dispatch.record_ids(), [did])

    def test_a_proposal_with_only_questions_is_a_dispatch_that_cannot_be_confirmed(self):
        did = self.propose(plan(steps=[], team=[], new_cards=[], questions=["預算多少？"]))
        view = self.dispatcher.get(did)
        self.assertEqual((view["state"], view["questions"]), ("proposed", ["預算多少？"]))
        with self.assertRaises(dispatch.DispatchError) as cm:
            self.dispatcher.confirm(did, self.body_of(did))
        self.assertEqual((cm.exception.code, cm.exception.status), ("bad_request", 400))

    def test_the_chief_of_staffs_record_can_be_linked_once(self):
        did = self.propose()
        chief_id = dispatch.load(did)["chief_id"]
        self.runner.link_dispatch(chief_id, did)                       # the same one again is the same
        with self.assertRaises(chief.ChiefError) as cm:
            self.runner.link_dispatch(chief_id, "d-ffffffffffff")
        self.assertEqual(cm.exception.code, "already_decided")
        self.assertEqual(self.runner.get(chief_id)["dispatch_id"], did)


class ConfirmTests(Base):
    def test_confirming_makes_the_new_employee_the_task_card_and_starts_running(self):
        did = self.propose()
        config_before = self.config_bytes()
        before = self.profile_ids()
        view = self.dispatcher.confirm(did, self.body_of(did))
        rec = dispatch.load(did)
        self.assertEqual((rec["state"], rec["started_by"]), ("running", "you"))
        self.assertEqual(view["state"], "running")
        self.assertEqual(self.events(did), [("proposed", "vbear"), ("confirmed", "you"), ("card_intent", "you"),
                                             ("card_created", "you"), ("task_intent", "you"), ("task_created", "you")])
        self.assertEqual(rec["events"][1]["edited"], False)
        (new_id,) = self.profile_ids() - before
        self.assertEqual(rec["made"], {"N1": new_id})
        card = ap.get_profile_readonly(new_id)
        self.assertEqual((card["name"], card["position"], card["launch_mode"], card["equipped_skill_ids"], card["enabled"]),
                         ("會計師", "accountant", "safe", [], True))
        self.assertEqual(card["model"], {"tool": "claude", "model_id": "haiku"})
        self.assertEqual(card["instructions"], position_guide.GUIDE["accountant"]["prompt"],
                         "the position's own fixed words, none of the chief of staff's")
        task = tasks.get_task(rec["task_id"])
        self.assertEqual((task["title"], task["goal"], task["deliverables"], task["status"]),
                         ("週末市集攤位", "準備賣手工皂的攤位", ["攤位介紹", "價目表"], "draft"))
        self.assertEqual([(s["seq"], s["who"], s["name"], s["profile_id"], s["state"], s["chat_id"], s["turn"])
                          for s in rec["steps"]],
                         [(1, "C1", "文案小編", self.writer, "pending", None, None), (2, "N1", "會計師", new_id, "pending", None, None)])
        self.assertEqual([s["text"] for s in rec["steps"]], ["請寫一份攤位介紹。", "請算成本與定價。"])
        self.assertEqual(self.config_bytes(), config_before, "config.json is not touched")

    def test_an_employee_made_for_a_claude_card_without_an_alias_takes_the_positions_alias(self):
        cards = [{"ref": "N1", "name": "法務", "position": "legal", "tool": "claude", "model_alias": "", "why": "看合約"}]
        did = self.propose(plan(new_cards=cards))
        self.dispatcher.confirm(did, self.body_of(did))
        (new_id,) = dispatch.load(did)["made"].values()
        self.assertEqual(ap.get_profile_readonly(new_id)["model"]["model_id"], "sonnet")

    def test_what_the_person_changed_is_what_is_made_and_said_to_be_edited(self):
        did = self.propose()
        body = self.body_of(did)
        body["title"] = "市集攤位（改過）"
        body["new_cards"][0].update(name="小帳", model_alias="sonnet")
        body["steps"] = [{"who": "N1", "text": "請先算成本。"}]             # the first step is gone, the second is reworded
        self.dispatcher.confirm(did, body)
        rec = dispatch.load(did)
        self.assertEqual(rec["events"][1]["edited"], True)
        self.assertEqual([(s["name"], s["text"]) for s in rec["steps"]], [("小帳", "請先算成本。")])
        (new_id,) = rec["made"].values()
        self.assertEqual((ap.get_profile_readonly(new_id)["name"], ap.get_profile_readonly(new_id)["model"]["model_id"]), ("小帳", "sonnet"))
        self.assertEqual(tasks.get_task(rec["task_id"])["title"], "市集攤位（改過）")
        self.assertEqual(rec["proposal_plan"]["title"], "週末市集攤位", "what the chief of staff proposed is kept as it was")

    def test_the_person_may_remove_a_new_employee_when_no_step_needs_them(self):
        did = self.propose()
        body = self.body_of(did, new_cards=[], steps=[{"who": "C1", "text": "請寫一份攤位介紹。"}])
        before = self.profile_ids()
        self.dispatcher.confirm(did, body)
        self.assertEqual(self.profile_ids(), before)
        self.assertEqual(dispatch.load(did)["state"], "running")

    def bad(self, did, body, status, code=None):
        before = (self.profile_ids(), tasks.list_tasks(), dispatch.load(did))
        with self.assertRaises(dispatch.DispatchError) as cm:
            self.dispatcher.confirm(did, body)
        self.assertEqual(cm.exception.status, status, str(cm.exception))
        if code:
            self.assertEqual(cm.exception.code, code)
        after = (self.profile_ids(), tasks.list_tasks(), dispatch.load(did))
        self.assertEqual(after, before, "a refused confirmation changes nothing")

    def test_a_card_that_is_not_on_the_chief_of_staffs_list_is_refused(self):
        did = self.propose()
        other = ap.save_profile(None, {"name": "外人", "position": "pm", "model": {"tool": "claude"}})["id"]
        for who in ("C9", "C2", other, "", "N2"):
            body = self.body_of(did)
            body["steps"][0]["who"] = who
            self.bad(did, body, 400)

    def test_what_is_looser_than_the_proposals_rules_is_refused(self):
        did = self.propose()
        cases = {
            "the CEO position": lambda b: b["new_cards"][0].update(position="planner"),
            "a position that is not one": lambda b: b["new_cards"][0].update(position="boss"),
            "a tool that cannot chat": lambda b: b["new_cards"][0].update(tool="codex"),
            "a tool that is not one": lambda b: b["new_cards"][0].update(tool="grok-9"),
            "an alias that is not one": lambda b: b["new_cards"][0].update(model_alias="gpt-9"),
            "a name that is too long": lambda b: b["new_cards"][0].update(name="名" * 41),
            "a name that is blank": lambda b: b["new_cards"][0].update(name="  "),
            "a ref that was not proposed": lambda b: b["new_cards"][0].update(ref="N2"),
            "a title that is too long": lambda b: b.update(title="題" * 81),
            "a blank title": lambda b: b.update(title=" "),
            "a goal that is too long": lambda b: b.update(goal="目" * 501),
            "a text that is too long": lambda b: b["steps"][0].update(text="字" * 1501),
            "a blank text": lambda b: b["steps"][0].update(text=" \n"),
            "a text with a control character": lambda b: b["steps"][0].update(text="a\x00b"),
            "five steps": lambda b: b.update(steps=[{"who": "C1", "text": f"第{i}步"} for i in range(5)]),
            "no steps": lambda b: b.update(steps=[]),
            "a step that is not an object": lambda b: b.update(steps=["做事"]),
            "a step with another field": lambda b: b["steps"][0].update(launch_mode="full"),
            "a card with another field": lambda b: b["new_cards"][0].update(equipped_skill_ids=["s-1"]),
            "a limit": lambda b: b.update(daily_usd=99),
            "a mode": lambda b: b.update(launch_mode="full"),
            "a skill": lambda b: b.update(skills=["x"]),
            "no title": lambda b: b.pop("title"),
            "more than two new employees": lambda b: b.update(new_cards=b["new_cards"] * 3),
        }
        for name, change in cases.items():
            body = self.body_of(did)
            change(body)
            with self.subTest(name):
                self.bad(did, body, 400)
        for not_an_object in (None, [], "x", 3):
            self.bad(did, not_an_object, 400)

    def test_a_step_that_points_at_a_new_employee_who_was_taken_out_is_refused(self):
        did = self.propose()
        self.bad(did, self.body_of(did, new_cards=[]), 400)        # the second step is still for N1

    def test_more_than_three_people_is_refused(self):
        for n in "甲乙":
            ap.save_profile(None, {"name": n, "position": "pm", "model": {"tool": "claude"}})
        did = self.propose(plan(team=[{"who": "C1", "why": "a"}, {"who": "C2", "why": "b"}, {"who": "C3", "why": "c"}],
                                new_cards=[], steps=[{"who": "C1", "text": "一"}, {"who": "C2", "text": "二"}, {"who": "C3", "text": "三"}]))
        body = self.body_of(did, new_cards=[{"ref": "N1", "name": "第四位", "position": "pm", "tool": "claude", "model_alias": ""}])
        body["steps"].append({"who": "N1", "text": "四"})
        self.bad(did, body, 400)

    def test_another_proposal_than_the_one_shown_is_a_conflict(self):
        did = self.propose()
        for sha in ("0" * 64, "", None, 5):
            self.bad(did, self.body_of(did, proposal_sha=sha), 409 if isinstance(sha, str) and sha else 400)

    def test_a_dispatch_is_confirmed_once(self):
        did = self.propose()
        self.dispatcher.confirm(did, self.body_of(did))
        before = self.profile_ids()
        with self.assertRaises(dispatch.DispatchError) as cm:
            self.dispatcher.confirm(did, self.body_of(did))
        self.assertEqual((cm.exception.status, cm.exception.code), (409, "not_proposed"))
        self.assertEqual(self.profile_ids(), before)

    def test_an_employee_who_is_gone_or_switched_off_or_changed_since_is_a_conflict(self):
        did = self.propose()
        body = self.body_of(did)
        ap.save_profile(self.writer, {"enabled": False})
        self.bad(did, body, 409, "card_unavailable")
        ap.save_profile(self.writer, {"enabled": True, "name": "文案小編改名"})
        self.bad(did, body, 409, "card_changed")
        ap.delete_profile(self.writer)
        self.bad(did, body, 409, "card_unavailable")

    def test_a_tool_that_cannot_chat_any_more_is_a_conflict(self):
        did = self.propose()
        self.TOOLS = ()
        self.bad(did, self.body_of(did), 409, "tool_unavailable")

    def test_the_task_card_is_made_even_when_there_is_no_new_employee(self):
        did = self.propose(old_hands_plan())
        self.dispatcher.confirm(did, self.body_of(did))
        rec = dispatch.load(did)
        self.assertEqual((self.events(did)[1:]), [("confirmed", "you"), ("task_intent", "you"), ("task_created", "you")])
        self.assertEqual([s["profile_id"] for s in rec["steps"]], [self.writer, self.writer])

    def test_a_refusal_to_make_a_card_pauses_the_dispatch_and_says_so(self):
        did = self.propose()
        with mock.patch.object(ap, "save_profile", side_effect=ValueError("角色卡已達上限 500 筆")):
            with self.assertRaises(dispatch.DispatchError) as cm:
                self.dispatcher.confirm(did, self.body_of(did))
        self.assertEqual((cm.exception.status, cm.exception.code), (409, "create_failed"))
        rec = dispatch.load(did)
        self.assertEqual((rec["state"], rec["pause"]["reason"]), ("paused", "create_failed"))
        self.assertEqual(tasks.list_tasks(), [])

    def test_a_crash_between_the_intent_and_the_result_is_uncertain_after_a_restart(self):
        did = self.propose()

        class Killed(BaseException):
            pass
        with mock.patch.object(ap, "save_profile", side_effect=Killed()):
            with self.assertRaises(Killed):
                self.dispatcher.confirm(did, self.body_of(did))
        self.assertEqual(dispatch.load(did)["state"], "confirming")
        self.assertEqual(self.events(did)[-1], ("card_intent", "you"))
        self.assertEqual(self.dispatcher.recover_all(), [did])
        rec = dispatch.load(did)
        self.assertEqual((rec["state"], rec["pause"]["reason"]), ("paused", "uncertain"))
        self.assertEqual(self.dispatcher.recover_all(), [], "once is enough")
        self.assertIn("員工頁", dispatch.pause_text("uncertain"))

    def test_a_crash_with_no_intent_open_is_said_to_be_an_interruption(self):
        did = self.propose(old_hands_plan())

        class Killed(BaseException):
            pass
        with mock.patch.object(tasks, "save_task", side_effect=Killed()):
            with self.assertRaises(Killed):
                self.dispatcher.confirm(did, self.body_of(did))
        self.dispatcher.recover_all()
        self.assertEqual(dispatch.load(did)["pause"]["reason"], "uncertain", "a task card may have been written")

        did2 = self.propose(plan())

        def die(self_, *a, **k):
            raise Killed()
        with mock.patch.object(dispatch.Dispatcher, "_finish", die):
            with self.assertRaises(Killed):
                self.dispatcher.confirm(did2, self.body_of(did2))
        self.dispatcher.recover_all()
        self.assertEqual(dispatch.load(did2)["pause"]["reason"], "interrupted")


if __name__ == "__main__":
    unittest.main()
