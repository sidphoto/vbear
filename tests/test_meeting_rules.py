"""The fixed table that decides whether a meeting is major (P34-4). Every rule is tested, and the AI's fields can only raise it."""
import copy
import unittest
from decimal import Decimal

from vbear import meeting_rules as mr


def opinion(position="pm", state="done", **out):
    output = {"stance": "支持", "summary": "可以", "points": [], "risks": [], "needs_chairman": False}
    output.update(out)
    return {"seq": 1, "profile_id": f"p-{position}", "kind": "opinion", "state": state, "output": output if state == "done" else None}


def decision(state="done", **out):
    output = {"decision": "照計畫做", "rationale": "沒有問題", "dissent_addressed": [], "actions": [{"type": "撰寫程式", "text": "寫"}],
              "escalate": False, "escalate_reason": "", "follow_up_topics": []}
    output.update(out)
    return {"seq": 9, "profile_id": "p-ceo", "kind": "decision", "state": state, "output": output if state == "done" else None}


def meeting(*turns, topic="整理文件", context="", flags=(), **extra):
    base = {"topic": topic, "context": context, "flags_by_chairman": list(flags),
            "participants": [{"profile_id": "p-ceo", "position": "planner"}, {"profile_id": "p-pm", "position": "pm"},
                             {"profile_id": "p-legal", "position": "legal"}],
            "turns": list(turns) or [opinion(), decision()]}
    base.update(extra)
    return base


def ids(m, **kw):
    return [r["id"] for r in mr.evaluate(m, **kw)["rules"]]


class RuleTableTests(unittest.TestCase):
    def test_the_table_is_eight_visible_rules_in_order(self):
        self.assertEqual([r["id"] for r in mr.RULES], ["R1", "R2", "R3", "R4", "R5", "R6", "R7", "R8"])
        for rule in mr.RULES:
            self.assertTrue(rule["text"])

    def test_a_quiet_meeting_is_not_major(self):
        verdict = mr.evaluate(meeting())
        self.assertEqual((verdict["major"], verdict["rules"]), (False, []))

    def test_R1_any_flag_the_chairman_ticked(self):
        self.assertEqual(ids(meeting(flags=["spend"])), ["R1"])
        self.assertEqual(ids(meeting(flags=[])), [])

    def test_R2_an_action_of_a_major_type(self):
        for kind in ("對外發布", "部署上線", "花錢付款", "刪除資料", "簽約承諾", "調整價格"):
            with self.subTest(kind=kind):
                self.assertIn("R2", ids(meeting(opinion(), decision(actions=[{"type": kind, "text": "x"}]))))
        for kind in ("撰寫程式", "修改文件", "寫草稿", "其他"):
            with self.subTest(kind=kind):
                self.assertNotIn("R2", ids(meeting(opinion(), decision(actions=[{"type": kind, "text": "x"}]))))

    def test_R3_keywords_in_the_topic_context_decision_and_actions_in_both_languages(self):
        for text in ("要不要發布", "先上架再說", "部署到正式機", "訂閱服務", "匯款給廠商", "刪除舊資料", "合約內容", "個資盤點",
                     "Publish the post", "deploying tonight", "We will pay", "delete it", "the contract", "a refund", "new price",
                     "was released", "they paid", "subscribing", "published"):
            with self.subTest(text=text):
                self.assertIn("R3", ids(meeting(topic=text)))
                self.assertIn("R3", ids(meeting(context=text)))
                self.assertIn("R3", ids(meeting(opinion(), decision(decision=text))))
                self.assertIn("R3", ids(meeting(opinion(), decision(rationale=text))))
                self.assertIn("R3", ids(meeting(opinion(), decision(actions=[{"type": "其他", "text": text}]))))

    def test_R3_does_not_fire_on_words_that_only_contain_a_keyword(self):
        for text in ("postgres 資料庫", "payload 格式", "整理文件", "整理筆記", "priceless"):
            with self.subTest(text=text):
                self.assertNotIn("R3", ids(meeting(topic=text)))

    def test_R4_any_amount_with_the_default_threshold_of_zero(self):
        for text in ("NT$1,000", "NT$ 500", "花 300 元", "US$20", "USD 5", "$3", "VND 2,000,000", "100 美元", "50 越南盾", "5萬元", "１２０元"):
            with self.subTest(text=text):
                self.assertIn("R4", ids(meeting(topic=text)))
        self.assertNotIn("R4", ids(meeting(topic="第 3 項，共 10 個")))

    def test_R4_other_magnitudes_and_currencies_and_unreadable_sums_fail_closed(self):
        for text in ("EUR 5", "€5", "¥300", "5 million dollars", "NT$ 3k", "三萬元", "NT$三百"):
            with self.subTest(text=text):
                self.assertIn("R4", ids(meeting(topic=text)))
        self.assertIn("R4", ids(meeting(topic="NT$999k"), amount_threshold=Decimal(1000)))  # 999k is 999,000: above
        self.assertNotIn("R4", ids(meeting(topic="NT$0.5"), amount_threshold=Decimal(1)))
        self.assertIn("R4", ids(meeting(topic="三萬元"), amount_threshold=Decimal(10**12)))

    def test_R2_an_action_type_that_is_not_listed_counts_as_major(self):
        for kind in ("轉帳", " 對外發布 ", 5, None):
            with self.subTest(kind=kind):
                self.assertIn("R2", ids(meeting(opinion(), decision(actions=[{"type": kind, "text": "x"}]))))

    def test_R4_the_threshold_decides_when_it_is_raised(self):
        self.assertNotIn("R4", ids(meeting(topic="NT$999"), amount_threshold=Decimal(1000)))
        self.assertIn("R4", ids(meeting(topic="NT$1,000"), amount_threshold=Decimal(1000)))
        self.assertIn("R4", ids(meeting(topic="5萬元"), amount_threshold=Decimal(1000)))

    def test_R5_a_high_risk_or_a_legal_opinion_without_a_source(self):
        high = opinion(risks=[{"level": "高", "text": "x", "source": "y"}])
        self.assertIn("R5", ids(meeting(high, decision())))
        self.assertNotIn("R5", ids(meeting(opinion(risks=[{"level": "中", "text": "x", "source": "y"}]), decision())))
        legal = opinion("legal", risks=[{"level": "低", "text": "x", "source": "查無出處，需人工複核"}])
        self.assertIn("R5", ids(meeting(legal, decision())))
        # the sentence from a speaker that is not the legal manager is only text
        self.assertNotIn("R5", ids(meeting(opinion("pm", risks=[{"level": "低", "text": "x", "source": "查無出處，需人工複核"}]), decision())))

    def test_R6_the_legal_manager_opposes(self):
        self.assertIn("R6", ids(meeting(opinion("legal", stance="反對"), decision())))
        self.assertNotIn("R6", ids(meeting(opinion("pm", stance="反對"), decision())))
        self.assertNotIn("R6", ids(meeting(opinion("legal", stance="有條件支持"), decision())))

    def test_R7_a_failed_blocked_skipped_or_interrupted_turn(self):
        for state in ("failed", "blocked", "skipped", "interrupted"):
            with self.subTest(state=state):
                self.assertIn("R7", ids(meeting(opinion("pm", state=state), decision())))
                self.assertIn("R7", ids(meeting(opinion(), decision(state=state))))
        for state in ("queued", "running", "done"):
            self.assertNotIn("R7", ids(meeting(opinion("pm", state=state), decision(state=state))))

    def test_R8_the_ceo_or_a_speaker_hands_it_up(self):
        self.assertIn("R8", ids(meeting(opinion(), decision(escalate=True, escalate_reason="x"))))
        self.assertIn("R8", ids(meeting(opinion(needs_chairman=True), decision())))
        self.assertNotIn("R8", ids(meeting()))

    def test_no_field_of_the_output_can_lower_the_verdict(self):
        for claim in ({"escalate": False, "escalate_reason": ""}, {"decision": "不重大，不需要董事長"}):
            self.assertTrue(mr.evaluate(meeting(opinion(), decision(**claim), flags=["publish"]))["major"])
        # a risk the model rates low, a stance it calls support, and a "no need" cannot cancel a high risk elsewhere
        self.assertTrue(mr.evaluate(meeting(opinion(risks=[{"level": "高", "text": "x", "source": "y"}]),
                                            opinion("legal", stance="支持", needs_chairman=False), decision(escalate=False)))["major"])
        # a record that says it was major when decided stays major even if today's table would not say so
        m = meeting(major_at_decision=True)
        self.assertEqual(mr.evaluate(m)["rules"], [])
        self.assertTrue(mr.is_major(m))
        self.assertFalse(mr.is_major(meeting(major_at_decision=False)))

    def test_it_never_changes_what_it_is_given(self):
        m = meeting(opinion("legal", stance="反對"), decision(), flags=["spend"], topic="NT$5")
        before = copy.deepcopy(m)
        mr.evaluate(m)
        self.assertEqual(m, before)

    def test_text_that_is_not_text_is_skipped_not_a_crash(self):
        m = meeting(opinion(), decision(), topic="x")
        m["turns"][1]["output"]["actions"] = [{"type": 5, "text": None}, "nope"]
        m["turns"][1]["output"]["decision"] = 3
        self.assertIsInstance(mr.evaluate(m)["major"], bool)


if __name__ == "__main__":
    unittest.main()
