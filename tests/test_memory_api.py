"""P42-1: the memory routes (/api/memory) over a real loopback console, and the way a saved line reaches a new chat: through
the chat service, a real runtime daemon (in this process, in a temporary folder) and the fake Claude Code
(tests/fake_chat_cli.py). Nothing here starts a real AI tool; the lines of memory, the cards and the replies are made up."""

from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from tests import test_chat_api as tca
from tests.test_chat_daemon import clean
from vbear import agent_profiles as ap, chat_service, config as cfg, memory
from vbear.runtime import chat_store as cs, memory_rules as mr

LINES = [("about_you", "回答一律用繁體中文，三句話以內"), ("work", "我的店叫「QA熊皂坊」，在週末市集擺攤（虛構）"),
         ("decision", "價格一律用新台幣標示")]


class RoutesCase(tca.ApiCase):
    def add(self, kind, text, **extra):
        return self.call("/api/memory", "POST", {"kind": kind, "text": text, **extra})

    def add_all(self):
        for kind, text in LINES:
            status, out = self.add(kind, text)
            self.assertEqual(status, 201, out)

    def appended(self, index=0):
        starts = [x for x in self.fake_log() if x["event"] == "start"]
        argv = starts[index]["argv"]
        return argv[argv.index("--append-system-prompt") + 1] if "--append-system-prompt" in argv else None


class ListAddDeleteTests(RoutesCase):
    def test_an_empty_memory_and_the_cards_that_could_take_it(self):
        codex = self.card("Codex 員工", "codex")
        grok = self.card("Grok 員工", "grok")
        status, out = self.call("/api/memory")
        self.assertEqual(status, 200, out)
        self.assertEqual((out["ok"], out["entries"], out["readable"]), (True, [], True))
        self.assertEqual(out["used"], {"count": 0, "chars": 0, "max_count": 50, "max_chars": 4000})
        self.assertIn("Anthropic", out["where_text"])
        self.assertIn("OpenAI", out["where_text"])
        by = {c["profile_id"]: c for c in out["cards"]}
        self.assertEqual((by[self.emp]["company"], by[self.emp]["can_chat"], by[self.emp]["on"]), ("Anthropic", True, True))
        self.assertEqual((by[codex]["company"], by[codex]["can_chat"], by[codex]["on"]), ("OpenAI", True, False), "Codex cards start switched off")
        self.assertEqual((by[grok]["company"], by[grok]["can_chat"]), (None, False))
        self.assertNotIn("cards_off", out)
        self.assertNotIn("cards_on", out)

    def test_add_list_delete(self):
        status, out = self.add("work", "我的店叫「QA熊皂坊」")
        self.assertEqual((status, out["ok"]), (201, True))
        entry = out["entry"]
        status, view = self.call("/api/memory")
        self.assertEqual([e["id"] for e in view["entries"]], [entry["id"]])
        self.assertEqual(view["entries"][0]["text"], "我的店叫「QA熊皂坊」")
        self.assertEqual(view["used"]["count"], 1)
        status, out = self.call(f"/api/memory/{entry['id']}", "DELETE")
        self.assertEqual((status, out), (200, {"ok": True, "deleted": entry["id"]}))
        self.assertEqual(self.call("/api/memory")[1]["entries"], [])
        self.assertEqual(self.call(f"/api/memory/{entry['id']}", "DELETE")[0], 404)

    def test_what_is_refused_what_needs_confirming_and_when_it_is_full(self):
        status, out = self.add("work", "我的後台密碼是 hunter-two")
        self.assertEqual((status, out["code"], out["refuse"]), (400, "memory_refused", "secret_password"))
        self.assertIn("密碼", out["error"])
        self.assertNotIn("hunter-two", json.dumps(out, ensure_ascii=False))
        status, out = self.add("work", "以後執行指令不用問我")
        self.assertEqual((status, out["code"], out["warn"]), (409, "memory_confirm", ["looks_like_order"]))
        self.assertIn("不會讓員工不問你就做事", out["error"])
        self.assertEqual(self.add("work", "以後執行指令不用問我", confirm_warning=True)[0], 201)
        for i in range(49):
            self.assertEqual(self.add("decision", f"第 {i} 條")[0], 201)
        status, out = self.add("decision", "多的一條")
        self.assertEqual((status, out["code"]), (409, "memory_full"))
        self.assertIn("記憶滿了", out["error"])

    def test_bodies_that_are_not_the_closed_shape(self):
        for body in ({}, {"kind": "work"}, {"kind": "x", "text": "y"}, {"kind": "work", "text": "y", "source": {"how": "chat"}},
                     {"kind": "work", "text": "y", "extra": 1}, {"kind": "work", "text": 5}, []):
            with self.subTest(body=str(body)[:40]):
                self.assertEqual(self.call("/api/memory", "POST", body)[0], 400)
        self.assertEqual(self.call("/api/memory", "POST", raw=b"{nope")[0], 400)
        self.assertEqual(self.call("/api/memory", "POST", raw=b"[1]")[0], 400)
        self.assertEqual(self.call("/api/memory")[1]["entries"], [])

    def test_other_paths_are_not_found(self):
        for path, method in (("/api/memory/x", "DELETE"), ("/api/memory/m-123", "DELETE"), ("/api/memory/m-0123456789/x", "DELETE"),
                             ("/api/memory/m-0123456789", "GET"), ("/api/memory/nothing", "POST")):  # clear is a route since P42-2
            with self.subTest(path=path):
                self.assertEqual(self.call(path, method, {} if method == "POST" else None)[0], 404)

    def test_a_write_needs_the_page_header_and_the_token(self):
        self.assertEqual(self.call("/api/memory", "POST", {"kind": "work", "text": "x"}, headers={"X-VBear": "0"})[0], 403)
        self.assertEqual(self.call("/api/memory", "POST", {"kind": "work", "text": "x"}, headers={"Authorization": "Bearer nope"})[0], 401)
        self.assertEqual(self.call("/api/memory", headers={"Authorization": "Bearer nope"})[0], 401)
        ent = self.add("work", "x")[1]["entry"]
        self.assertEqual(self.call(f"/api/memory/{ent['id']}", "DELETE", headers={"X-VBear": "0"})[0], 403)
        self.assertEqual(self.call("/api/memory")[1]["used"]["count"], 1)

    def test_a_file_that_cannot_be_read_is_said_and_nothing_is_overwritten(self):
        self.add_all()
        path = cfg.state_dir() / "memory" / "memory.json"
        path.write_text("{broken")
        status, out = self.call("/api/memory")
        self.assertEqual((status, out["readable"], out["entries"]), (200, False, []))
        self.assertIn("記憶的檔案有問題", out["problem"])
        status, out = self.add("work", "x")
        self.assertEqual((status, out["code"]), (503, "memory_unreadable"))
        self.assertIn("記憶的檔案有問題", out["error"])
        self.assertFalse(path.exists(), "the damaged file was moved aside by the store, not overwritten with a new one")


class NewChatTests(RoutesCase):
    def test_a_saved_line_is_in_the_next_new_chat_of_every_employee(self):
        self.add_all()
        second = self.card("第二位員工")
        self.dm.chat_idle_timeout = 0.5
        self.configure([clean("text", 0), clean("text", 0)])
        first_chat = self.open_http()
        self.assertEqual(self.say(first_chat)[0], 202)
        self.wait_http_turn(first_chat, 1)
        got = self.appended(0)
        self.assertEqual(got, mr.block([{"kind": k, "text": t} for k, t in LINES]))
        self.assertTrue(got.startswith("[VBear 記憶]"))
        self.assertEqual(json.loads(json.loads(got.split("\n")[-2])), [[k, t] for k, t in LINES])
        self.wait_gone(first_chat)
        self.assertEqual(self.say(self.open_http(second))[0], 202)
        self.wait(lambda: len([x for x in self.fake_log() if x["event"] == "start"]) >= 2, "the second employee's process")
        self.assertEqual(self.appended(1), got)

    def test_the_cards_instructions_come_first_and_memory_follows(self):
        self.add_all()
        mine = self.card("有指示的員工", instructions="先說結論，再說理由。")
        self.configure([clean("text", 0)])
        chat_id = self.open_http(mine)
        self.assertEqual(self.say(chat_id)[0], 202)
        self.wait_http_turn(chat_id, 1)
        self.assertEqual(self.appended(), "先說結論，再說理由。\n\n" + mr.block([{"kind": k, "text": t} for k, t in LINES]))

    def test_no_lines_yet_still_carries_the_explanation(self):
        self.configure([clean("text", 0)])
        chat_id = self.open_http()
        self.assertEqual(self.say(chat_id)[0], 202)
        self.wait_http_turn(chat_id, 1)
        self.assertEqual(self.appended(), mr.block([]))

    def test_a_damaged_file_means_no_memory_and_the_chat_goes_on(self):
        self.add_all()
        (cfg.state_dir() / "memory" / "memory.json").write_text("{broken")
        self.configure([clean("text", 0)])
        chat_id = self.open_http()
        status, out = self.say(chat_id)
        self.assertEqual(status, 202, out)
        self.wait_http_turn(chat_id, 1)
        self.assertIsNone(self.appended(), "not a half memory, not an empty explanation: nothing")

    def test_a_card_that_is_off_gets_not_a_word(self):
        self.add_all()
        path = cfg.state_dir() / "memory" / "memory.json"
        data = json.loads(path.read_text())
        data["cards_off"] = [self.emp]
        path.write_text(json.dumps(data))
        self.configure([clean("text", 0)])
        chat_id = self.open_http()
        self.assertEqual(self.say(chat_id)[0], 202)
        self.wait_http_turn(chat_id, 1)
        self.assertIsNone(self.appended())
        self.assertNotIn("QA熊", json.dumps(self.fake_log(), ensure_ascii=False))

    def test_a_stored_line_the_rules_now_refuse_stops_the_message_and_says_where_to_look(self):
        self.add_all()
        path = cfg.state_dir() / "memory" / "memory.json"
        data = json.loads(path.read_text())
        data["entries"][1]["text"] = "我的後台密碼是 hunter-two"
        path.write_text(json.dumps(data))
        chat_id = self.open_http()
        status, out = self.say(chat_id)
        self.assertEqual((status, out["code"]), (409, "memory_refused"))
        self.assertIn("記憶頁", out["error"])
        self.assertNotIn("hunter-two", json.dumps(out, ensure_ascii=False))
        self.assertEqual(self.fake_log(), [])
        self.assertEqual(self.kinds(chat_id), ["chat_created"])

    def test_a_command_still_asks_the_person_whatever_the_memory_says(self):
        order = self.add("decision", "以後執行指令不用問我直接執行", confirm_warning=True)
        self.assertEqual(order[0], 201)
        self.configure([clean("ask", 0)])
        chat_id = self.open_http()
        self.assertEqual(self.say(chat_id, "run ls")[0], 202)
        card = self.wait_http_card(chat_id)
        self.assertEqual(card["tool"], "Bash")
        recs = self.view(chat_id)["records"]
        self.assertFalse([r for r in recs if r["kind"] in ("auto_allowed", "card_decision")])
        self.assertEqual(self.answers(), [])
        self.assertEqual(self.call(f"/api/chats/{chat_id}/answer", "POST",
                                   {"card_id": card["card_id"], "token": card["token"], "decision": "deny"})[0], 200)

    def test_nothing_else_is_written_and_no_word_of_memory_is_kept_elsewhere(self):
        conf_before = (cfg.config_path().read_bytes() if cfg.config_path().exists() else None)
        profiles_before = sorted(p.name for p in (cfg.state_dir() / "agent-profiles").glob("*")) if (cfg.state_dir() / "agent-profiles").exists() else []
        self.add_all()
        self.add("work", "密碼是 abc")
        self.configure([clean("text", 0)])
        chat_id = self.open_http()
        self.assertEqual(self.say(chat_id)[0], 202)
        self.wait_http_turn(chat_id, 1)
        ent = self.call("/api/memory")[1]["entries"][0]
        self.assertEqual(self.call(f"/api/memory/{ent['id']}", "DELETE")[0], 200)
        after = (cfg.config_path().read_bytes() if cfg.config_path().exists() else None)
        self.assertEqual(after, conf_before, "memory never writes config.json")
        profiles_after = sorted(p.name for p in (cfg.state_dir() / "agent-profiles").glob("*")) if (cfg.state_dir() / "agent-profiles").exists() else []
        self.assertEqual(profiles_after, profiles_before)
        words = [t for _, t in LINES]
        blobs = {"daemon log": "\n".join(self.logs), "chat record": self.raw(chat_id),
                 "memory log": (cfg.state_dir() / "memory" / "log.jsonl").read_text()}
        for name, blob in blobs.items():
            for word in words:
                self.assertNotIn(word, blob, name)
        self.assertNotIn("hunter", json.dumps(blobs))
        # the lines are in memory.json and nowhere else under the state folder except the launch records of a live process
        for root, _dirs, files in os.walk(cfg.state_dir()):
            for name in files:
                path = Path(root) / name
                if name in ("memory.json",) or "sessions" in path.parts or path.suffix in (".sock", ".lock"):
                    continue
                try:
                    text = path.read_text(errors="ignore")
                except OSError:
                    continue
                for word in words:
                    self.assertNotIn(word, text, str(path.relative_to(cfg.state_dir())))


class FieldsOfTheServiceTests(unittest.TestCase):
    """What ChatService asks the daemon, with a runtime that only writes the request down."""

    class Runtime:
        def __init__(self):
            self.sent = []

        def _rpc(self, op, timeout=2.0, **fields):
            self.sent.append((op, fields))
            return {"ok": True, "result": {"turn": 1, "cap_usd": "0.5", "process": "new"}}

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="vbs-")
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name)
        self.chat = cs.create(self.base, "emp-1", now=1.0)["id"]
        self.runtime = self.Runtime()
        self.given = memory.ChatMemory(True, True, [{"kind": "work", "text": "一"}])
        self.svc = chat_service.ChatService(
            self.runtime, claude=lambda: ("/bin/echo", "2.1.318", ""), base=self.base,
            profile=lambda pid: {"id": pid, "name": "x", "enabled": True, "model": {"tool": "claude"}, "position": "pm"},
            memory=lambda pid, engine: self.given)
        patch = mock.patch.object(chat_service.agent_sessions, "binary_identity", lambda b: [1, 2, 3])
        patch.start()
        self.addCleanup(patch.stop)

    def fields(self):
        return self.runtime.sent[-1][1]

    def test_the_lines_go_when_the_card_takes_memory(self):
        self.svc.send(self.chat, {"text": "hi"})
        self.assertEqual(self.fields()["memory"], [{"kind": "work", "text": "一"}])

    def test_an_empty_memory_is_an_empty_list_not_a_missing_field(self):
        self.given = memory.ChatMemory(True, True, [])
        self.svc.send(self.chat, {"text": "hi"})
        self.assertEqual(self.fields()["memory"], [])

    def test_a_card_that_is_off_or_a_file_that_cannot_be_read_sends_no_field(self):
        for given in (memory.ChatMemory(True, False, []), memory.ChatMemory(False, False, [])):
            self.given = given
            self.svc.send(self.chat, {"text": "hi"})
            self.assertNotIn("memory", self.fields())

    def test_a_message_vbear_sends_for_a_dispatch_carries_it_too(self):
        self.svc.send_for_dispatch(self.chat, "step", {"dispatch": "d-" + "a" * 12, "step": 1})
        self.assertEqual(self.fields()["memory"], [{"kind": "work", "text": "一"}])

    def test_the_service_never_calls_what_writes(self):
        src = (Path(chat_service.__file__)).read_text()
        for name in ("memory_store.add", "memory_store.delete", "memory.add", "memory.delete"):
            self.assertNotIn(name, src)


class DefaultByToolTests(unittest.TestCase):
    """The person's choice for v0.17: a Claude Code card takes memory along from the start, a Codex card only after the person
    switches it on (memory goes to OpenAI there). The real reader of the memory file, a service per tool, a runtime that
    only writes the request down."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="vbd-")
        self.addCleanup(self.tmp.cleanup)
        home = Path(self.tmp.name) / "h"
        home.mkdir()
        patch = mock.patch.dict(os.environ, {"HOME": str(home), "VBEAR_HOME": str(home / ".vbear"), "VBEAR_RUNTIME_AUTOSTART": "0"})
        patch.start()
        self.addCleanup(patch.stop)
        ident = mock.patch.object(chat_service.agent_sessions, "binary_identity", lambda b: [1, 2, 3])
        ident.start()
        self.addCleanup(ident.stop)
        self.base = cfg.state_dir()
        self.runtime = FieldsOfTheServiceTests.Runtime()
        self.cards = {"claude-1": "claude", "codex-1": "codex"}
        self.svc = chat_service.ChatService(
            self.runtime, claude=lambda: ("/bin/echo", "2.1.318", ""), codex=lambda: {"state": "ready"},
            codex_binary=lambda: ("/bin/echo", "0.163.0"), base=self.base,
            profile=lambda pid: {"id": pid, "name": "x", "enabled": True, "model": {"tool": self.cards[pid]}, "position": "pm"})
        memory.add({"kind": "work", "text": "我的店叫「QA熊皂坊」（虛構）"})

    def say(self, pid):
        engine = "codex-chat" if self.cards[pid] == "codex" else "claude-chat"
        chat = cs.create(self.base, pid, now=1.0, engine=engine)["id"]
        self.svc.send(chat, {"text": "hi"})
        return self.runtime.sent[-1][1]

    def test_a_claude_code_card_takes_it_and_a_codex_card_does_not(self):
        self.assertEqual(self.say("claude-1")["memory"], [{"kind": "work", "text": "我的店叫「QA熊皂坊」（虛構）"}])
        codex = self.say("codex-1")
        self.assertNotIn("memory", codex, "not a word goes to OpenAI until the person switches the card on")
        self.assertNotIn("QA熊", json.dumps(codex, ensure_ascii=False))
        self.assertEqual(codex["engine"], "codex-chat")

    def test_switched_on_the_codex_card_takes_it_and_switched_off_the_claude_card_does_not(self):
        path = self.base / "memory" / "memory.json"
        data = json.loads(path.read_text())
        path.write_text(json.dumps(dict(data, cards_on=["codex-1"], cards_off=["claude-1"])))
        self.assertEqual(self.say("codex-1")["memory"], [{"kind": "work", "text": "我的店叫「QA熊皂坊」（虛構）"}])
        self.assertNotIn("memory", self.say("claude-1"))

    def test_the_memory_page_lists_each_card_with_its_start_value(self):
        cards = [{"id": "claude-1", "name": "a", "tool": "claude", "engine": "claude-chat", "can_chat": True},
                 {"id": "codex-1", "name": "b", "tool": "codex", "engine": "codex-chat", "can_chat": True},
                 {"id": "grok-1", "name": "c", "tool": "grok", "engine": None, "can_chat": False}]
        view = memory.view()
        got = {c["profile_id"]: c for c in memory.cards_view(cards, view["cards_off"], view["cards_on"])}
        self.assertEqual([got[k]["on"] for k in ("claude-1", "codex-1", "grok-1")], [True, False, False])
        self.assertEqual([got[k]["company"] for k in ("claude-1", "codex-1", "grok-1")], ["Anthropic", "OpenAI", None])
        view2 = dict(view, cards_on=["codex-1"], cards_off=["claude-1"])
        got = {c["profile_id"]: c for c in memory.cards_view(cards, view2["cards_off"], view2["cards_on"])}
        self.assertEqual([got[k]["on"] for k in ("claude-1", "codex-1")], [False, True])


if __name__ == "__main__":
    unittest.main()
