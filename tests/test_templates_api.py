"""P45-1: GET /api/templates and POST /api/templates/preview over a real loopback console. The chat service is a fake that only knows the
role cards (any other call is recorded and fails the test), the AI tools' status is a fake (nothing runs), the state is a temporary home.
The preview and the list write nothing: the whole home is compared (name, size, time) before and after."""

from __future__ import annotations

import json
import os
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest import mock

from vbear import agent_profiles as ap, config as cfg, routines, server, skillbook, templates as tp, templates_builtin as tb
from vbear.index import Store

TOKEN = "synthetic-test-token"
SHOP = tb.builtin()[0]


def ref(template, key):
    return {"template": template, "key": key}


def pick(template, key, **extra):
    return {"from": ref(template, key), **extra}


def row(tid, ready, state="ready", chat=None):
    out = {"id": tid, "ready": ready, "state": state, "installed": state != "not_installed"}
    if chat is not None:
        out["chat_login"] = {"state": chat, "problem": ""}
    return out


READY = [row("claude", True), row("codex", True, chat="logged_in")]


class FakeChats:
    """Knows the role cards and nothing else: whatever else a route asks of the chat service is written down and fails the test."""

    def __init__(self, cards=()):
        self.rows = [dict(c) for c in cards]
        self.calls = []

    def cards(self):
        self.calls.append("cards")
        return [dict(c) for c in self.rows]

    def __getattr__(self, name):
        if name.startswith("__"):
            raise AttributeError(name)
        self.calls.append(name)
        raise AssertionError(f"the chat service was asked for {name}")


def tree(root: Path) -> dict:
    out = {}
    for path in sorted(root.rglob("*")):
        st = path.lstat()
        out[str(path.relative_to(root))] = (st.st_size, st.st_mtime_ns, path.is_dir())
    return out


class ApiBase(unittest.TestCase):
    rows = READY

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="vbtq-")
        self.addCleanup(self.tmp.cleanup)
        self.home = Path(os.path.realpath(self.tmp.name)) / "h"
        (self.home / ".vbear").mkdir(parents=True, mode=0o700)
        patch = mock.patch.dict(os.environ, {"HOME": str(self.home), "VBEAR_HOME": str(self.home / ".vbear"), "VBEAR_RUNTIME_AUTOSTART": "0"})
        patch.start()
        self.addCleanup(patch.stop)
        self.status_calls = []

        def fake_report(conf, marks=None, *, force=False):
            self.status_calls.append(force)
            return [dict(r) for r in self.rows]
        for target in (mock.patch.object(server.ai_tool_status, "report", fake_report),
                       mock.patch("subprocess.run", side_effect=AssertionError("a program was started")),
                       mock.patch("subprocess.Popen", side_effect=AssertionError("a program was started"))):
            target.start()
            self.addCleanup(target.stop)
        self.chats = FakeChats([{"id": "p-old", "name": "老員工", "position": "pm", "tool": "claude", "engine": "claude", "enabled": True, "can_chat": True},
                                {"id": "p-off", "name": "停用員工", "position": None, "tool": "claude", "engine": "claude", "enabled": False, "can_chat": False}])
        self.console = c = server.Console.__new__(server.Console)
        c.lock = threading.Lock()
        c.auth_token = TOKEN
        c.store = Store()
        c.store._static = {"skills": [], "roles": []}
        c.store.set_conf(cfg.load())
        c.chats = self.chats
        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), None)
        c.port = self.httpd.server_address[1]
        self.httpd.RequestHandlerClass = server.make_handler(c)
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()
        self.addCleanup(self.httpd.server_close)
        self.addCleanup(self.httpd.shutdown)

    def call(self, path, method="GET", body=None, headers=None, raw=None):
        hdr = {"Authorization": f"Bearer {TOKEN}", "X-VBear": "1", "Origin": f"http://127.0.0.1:{self.console.port}", "Content-Type": "application/json"}
        hdr.update(headers or {})
        hdr = {k: v for k, v in hdr.items() if v is not None}
        data = raw if raw is not None else (json.dumps(body).encode() if body is not None else None)
        req = urllib.request.Request(f"http://127.0.0.1:{self.console.port}" + path, data=data, method=method, headers=hdr)
        try:
            with urllib.request.urlopen(req, timeout=10) as response:
                return response.status, json.loads(response.read())
        except urllib.error.HTTPError as exc:
            with exc:
                return exc.code, json.loads(exc.read() or b"{}")

    def preview(self, body):
        return self.call("/api/templates/preview", "POST", body)


class TheList(ApiBase):
    def test_the_four_built_in_templates_and_nothing_of_the_persons_yet(self):
        status, out = self.call("/api/templates")
        self.assertEqual(status, 200, out)
        self.assertTrue(out["ok"])
        self.assertEqual(out["builtin"], tb.builtin())
        self.assertEqual((out["mine"], out["mine_readable"], out["problem"], out["applies"]), ([], True, None, []))
        self.assertEqual(out["problems"], [])

    def test_what_the_person_has_now_and_the_limits(self):
        skillbook.add({"name": "舊技能", "text": "舊做法"})
        status, out = self.call("/api/templates")
        self.assertEqual(out["counts"], {"cards": 2, "skills": 1, "routines": 0})
        self.assertEqual([c["id"] for c in out["current"]["cards"]], ["p-old", "p-off"])
        self.assertEqual([(s["name"]) for s in out["current"]["skills"]], ["舊技能"])
        self.assertEqual(out["current"]["routines"], [])
        self.assertEqual(out["limits"], {"max_cards": 500, "max_skills": 100, "max_routines": 20, "per_apply": {"cards": 12, "skills": 24, "routines": 12},
                                         "per_template": {"cards": 12, "skills": 24, "routines": 12}, "max_mine": 20, "max_name": 40})
        for card in out["current"]["cards"]:
            self.assertEqual(set(card), {"id", "name", "position", "tool", "can_chat"})

    def test_the_tools_default_in_the_four_cases(self):
        cases = (
            ([row("claude", True), row("codex", True, chat="logged_in")], "claude", True, True),
            ([row("claude", True), row("codex", False, "not_logged_in", chat="not_logged_in")], "claude", True, False),
            ([row("claude", False, "not_logged_in"), row("codex", True, chat="logged_in")], "codex", False, True),
            ([row("claude", False, "not_installed"), row("codex", False, "not_installed")], "claude", False, False),
        )
        for rows, default, claude_ready, codex_ready in cases:
            type(self).rows = rows
            self.addCleanup(setattr, type(self), "rows", READY)
            tools = self.call("/api/templates")[1]["tools"]
            self.assertEqual((tools["default"], tools["claude"]["ready"], tools["codex"]["ready"]), (default, claude_ready, codex_ready), rows)
            self.assertEqual(set(tools), {"claude", "codex", "default"})

    def test_the_status_is_read_from_the_start_up_pages_source_and_never_forced(self):
        self.call("/api/templates")
        self.assertEqual(self.status_calls, [False])

    def test_a_status_that_cannot_be_read_does_not_hide_the_templates(self):
        def broken(conf, marks=None, *, force=False):
            raise server.ai_tool_status.StoreError("壞了")
        with mock.patch.object(server.ai_tool_status, "report", broken):
            status, out = self.call("/api/templates")
        self.assertEqual(status, 200)
        self.assertEqual(len(out["builtin"]), 4)
        self.assertEqual((out["tools"]["claude"]["ready"], out["tools"]["codex"]["ready"], out["tools"]["default"]), (False, False, "claude"))

    def test_a_skills_file_that_cannot_be_read_is_said_and_the_templates_still_show(self):
        folder = self.home / ".vbear" / "skillbook"
        folder.mkdir(mode=0o700)
        (folder / "skills.json").write_text("{not json", encoding="utf-8")
        status, out = self.call("/api/templates")
        self.assertEqual(status, 200, out)
        self.assertEqual(len(out["builtin"]), 4)
        self.assertEqual(len(out["problems"]), 1)
        self.assertIn("技能", out["problems"][0])

    def test_the_list_needs_the_token_and_writes_nothing_and_asks_no_chat(self):
        before = tree(self.home)
        self.assertEqual(self.call("/api/templates", headers={"Authorization": None})[0], 401)
        self.assertEqual(self.call("/api/templates")[0], 200)
        self.assertEqual(tree(self.home), before)
        self.assertEqual(set(self.chats.calls), {"cards"})


class ThePreview(ApiBase):
    def test_a_selection_comes_back_as_a_preview_with_no_body_in_it(self):
        status, out = self.preview({"tool": "claude", "cards": [pick("shop", "copy"), pick("shop", "accounting")],
                                    "skills": [pick("shop", "product")], "routines": [pick("shop", "promo"), pick("shop", "spend")]})
        self.assertEqual(status, 200, out)
        shown = out["preview"]
        self.assertTrue(shown["ok"])
        self.assertEqual(shown["problems"], [])
        self.assertEqual([c["name"] for c in shown["cards"]], ["商品文案", "會計"])
        self.assertEqual([c["model_id"] for c in shown["cards"]], ["sonnet", "haiku"])
        self.assertEqual([r["assignee"]["name"] for r in shown["routines"]], ["商品文案", "會計"])
        self.assertEqual(shown["after"]["cards"], {"now": 2, "add": 2, "after": 4, "max": 500})
        self.assertTrue(all("body" not in c for c in shown["cards"]))
        self.assertTrue(all("routine" not in r for r in shown["routines"]))
        self.assertEqual(shown["choices"]["existing"], [{"profile_id": "p-old", "name": "老員工"}], "the one who cannot chat is not offered")
        expected = tp.public(tp.plan({"tool": "claude", "cards": [pick("shop", "copy"), pick("shop", "accounting")], "skills": [pick("shop", "product")],
                                      "routines": [pick("shop", "promo"), pick("shop", "spend")]}, templates=tp.index(),
                                     current={"cards": self.chats.rows, "skills": 0, "routines": 0}))
        self.assertEqual(shown, expected)

    def test_it_writes_nothing_asks_no_chat_runs_no_program_and_asks_the_status_once_for_nothing(self):
        before = tree(self.home)
        for tool in ("claude", "codex"):
            status, out = self.preview({"tool": tool, "cards": [pick(t, c["key"]) for t, c in (("shop", c) for c in SHOP["cards"])],
                                        "skills": [pick("shop", "reply")], "routines": [pick("shop", "spend")]})
            self.assertEqual(status, 200, out)
        self.assertEqual(tree(self.home), before, "not one new file, not one file touched")
        self.assertEqual(set(self.chats.calls), {"cards"})
        self.assertEqual(self.status_calls, [], "the preview does not even look at the AI tools")

    def test_a_routine_for_an_employee_the_person_already_has(self):
        status, out = self.preview({"tool": "codex", "routines": [pick("shop", "spend", to={"profile_id": "p-old"})]})
        self.assertEqual(status, 200)
        self.assertEqual(out["preview"]["routines"][0]["assignee"], {"kind": "existing", "card": None, "profile_id": "p-old", "name": "老員工"})
        status, out = self.preview({"tool": "codex", "routines": [pick("shop", "spend", to={"profile_id": "p-off"})]})
        self.assertEqual([p["code"] for p in out["preview"]["problems"]], ["assignee_cannot_chat"])

    def test_over_the_limits_is_a_problem_with_the_numbers_of_the_files(self):
        for i in range(97):
            skillbook.add({"name": f"技能{i}", "text": f"做法{i}"})
        status, out = self.preview({"tool": "claude", "skills": [pick("shop", "reply"), pick("shop", "product"), pick("shop", "daybook"),
                                                                  pick("creator", "ideas"), pick("creator", "post")]})
        self.assertEqual(status, 200, out)
        problem = out["preview"]["problems"][0]
        self.assertEqual((problem["code"], problem["kind"], problem["over"]), ("template_full", "skills", 2))
        self.assertIn("技能會超過 100 個：你現在有 97 個，這次要加 5 個，請少勾 2 個", problem["text"])

    def test_a_bad_request_is_a_400_with_a_code(self):
        for body in ({}, {"tool": "agy", "cards": [pick("shop", "service")]}, {"tool": "claude", "cards": [pick("nope", "service")]},
                     {"tool": "claude", "cards": [pick("shop", "service"), pick("shop", "service")]}, {"tool": "claude", "extra": 1},
                     {"tool": "claude", "cards": [pick("shop", "service")], "launch_mode": "full"}):
            status, out = self.preview(body)
            self.assertEqual((status, out["code"]), (400, "bad_request"), body)
            self.assertTrue(out["error"])
        self.assertEqual(self.call("/api/templates/preview", "POST", raw=b"[1, 2]")[0], 400)
        self.assertEqual(self.call("/api/templates/preview", "POST", raw=b"not json")[0], 400)

    def test_no_token_or_no_marker_is_refused(self):
        body = {"tool": "claude", "cards": [pick("shop", "service")]}
        self.assertEqual(self.call("/api/templates/preview", "POST", body, headers={"X-VBear": None})[0], 403)
        self.assertEqual(self.call("/api/templates/preview", "POST", body, headers={"Authorization": None})[0], 401)
        self.assertEqual(self.call("/api/templates/preview", "POST", body, headers={"Origin": "http://evil.example.com"})[0], 403)

    def test_a_file_that_cannot_be_read_is_a_503_and_nothing_is_planned(self):
        folder = self.home / ".vbear" / "routines"
        folder.mkdir(mode=0o700)
        (folder / "routines.json").write_text("{not json", encoding="utf-8")
        status, out = self.preview({"tool": "claude", "cards": [pick("shop", "service")]})
        self.assertEqual(status, 503, out)
        self.assertTrue(out["error"])

    def test_a_card_file_that_cannot_be_read_is_a_503(self):
        def broken():
            raise ap.AgentProfileStorageError("x")
        self.chats.cards = broken
        status, out = self.preview({"tool": "claude", "cards": [pick("shop", "service")]})
        self.assertEqual(status, 503, out)

    def test_there_is_no_way_to_take_a_team_template_out_or_bring_one_in(self):
        for path in ("/api/templates/export", "/api/templates/import", "/api/templates/upload", "/api/templates/download",
                     "/api/templates/mine/tm-0123456789ab/export", "/api/templates/shop/export"):
            self.assertEqual(self.call(path, "POST", {})[0], 404, path)
            self.assertEqual(self.call(path)[0], 404, path)
        self.assertEqual(self.call("/api/templates/preview")[0], 404, "preview is a POST")


class ASavedTemplateIsPlannedLikeABuiltInOne(ApiBase):
    def setUp(self):
        super().setUp()
        self.saved = {"id": "tm-0123456789ab", "name": "我的店", "builtin": False,
                      "cards": [{"key": "boss", "name": "店長", "position": None, "instructions": "你是店長的小幫手。", "claude_model": None}],
                      "skills": [{"key": "daily", "name": "每日小結", "text": "請幫我寫今天的小結。"}], "routines": []}

    def test_it_is_listed_and_can_be_picked(self):
        self.console.template_mine = lambda: ([self.saved], True, None)
        out = self.call("/api/templates")[1]
        self.assertEqual([t["id"] for t in out["mine"]], ["tm-0123456789ab"])
        self.assertTrue(out["mine_readable"])
        status, out = self.preview({"tool": "claude", "cards": [pick("tm-0123456789ab", "boss")], "skills": [pick("tm-0123456789ab", "daily")]})
        self.assertEqual((status, out["preview"]["problems"]), (200, []))

    def test_when_the_persons_file_cannot_be_read_the_built_in_ones_still_work(self):
        self.console.template_mine = lambda: ([], False, "你存的團隊範本的檔案有問題")
        out = self.call("/api/templates")[1]
        self.assertEqual((out["mine"], out["mine_readable"], out["problem"]), ([], False, "你存的團隊範本的檔案有問題"))
        self.assertEqual(len(out["builtin"]), 4)
        self.assertEqual(self.preview({"tool": "claude", "cards": [pick("shop", "service")]})[0], 200)
        self.assertEqual(self.preview({"tool": "claude", "cards": [pick("tm-0123456789ab", "boss")]})[0], 400)


if __name__ == "__main__":
    unittest.main()
