"""P44-6: one walk through skills, routines, waking up and the countdown over the real routes of a loopback server.

A skill is saved (a made-up key is refused, an order to act without asking needs the person's second word) and used (what goes to the
employee is the skill's words, as the person's own message); a routine is made and, with 「自己動手」 item 3 off, only reminds until the
person presses 「現在開始」; item 3 is ticked and a routine starts by itself, once; the console is closed and opened again later and a
missed time is caught up by itself (item 3 on) or listed and pressed by hand (item 3 off); a dispatch that stopped at the daily limit
counts down, and with item 5 off only offers 「繼續」 while with item 5 on VBear presses it as ``vbear``. At the end ``config.json`` has
only the ``autonomy`` block the settings page's route wrote, the role cards are as they were, and no record or log holds a name or a word.

Seams: the HTTP routes (``/api/my-skills``, ``/api/chats``, ``/api/routines``, ``/api/waiting``, ``/api/actions``, ``/api/dispatch``,
``/api/settings/autonomy``) and the files a person could look at in the state folder. The chat service is the real one over the
dispatch tests' fake daemon, the clock is a hand-moved one (a Monday in Taipei), nothing waits for real time, no CLI runs, nothing leaves
the machine, and no ``caffeinate`` is started (a console built this way has no command for it)."""
from __future__ import annotations

import hashlib
import json
import threading
import types
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer

from tests.test_auto_continue import AutoBase, HOUR, TAIPEI, at
from vbear import auto_continue, config as cfg, routine_rules as rr, routine_runner as rrun, server
from vbear.index import Store

TOKEN = "synthetic-test-token"
SKILL_NAME = "獨一無二的做法"
SKILL_TEXT = "第一步：先看昨天的銷售。\n第二步：整理成三句話。\n第三步：不要加價格以外的數字。"
ROUTINE_NAME = "獨一無二的例行工作"
ROUTINE_TEXT = "獨一無二的內容：請整理昨天的銷售。"
FOREVER = [0, 1, 2, 3, 4, 5, 6]


def fake_key() -> str:
    return "sk-" + "c3" * 12


class Walk(AutoBase):
    def setUp(self):
        super().setUp()
        self.profiles_before = self.profile_bytes()
        self.console = c = server.Console.__new__(server.Console)
        c.lock = threading.Lock()
        c.auth_token = TOKEN
        c.store = Store()
        c.store._static = {"skills": [], "roles": []}
        c.store.set_conf(cfg.load())
        c.chats = self.service
        c._dispatcher = self.dispatcher
        c._dispatch_runner = self.drunner
        c.meeting_runner = lambda: types.SimpleNamespace(ledger=lambda conf: self.ledger())
        self.auto = auto_continue.AutoContinue(conf=lambda: c.store.conf, ledger=self.ledger, resume=self.press, usage=lambda did: self.usage[0],
                                               clock=lambda: self.now[0], tz=TAIPEI)
        self.open_console()
        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), None)
        c.port = self.httpd.server_address[1]
        self.httpd.RequestHandlerClass = server.make_handler(c)
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()
        self.addCleanup(self.httpd.server_close)
        self.addCleanup(self.httpd.shutdown)

    # -- the world ------------------------------------------------------------------------------------------------------

    def open_console(self):
        """A console is opened: a new routine runner that remembers nothing, over the same records."""
        c = self.console
        self.rrunner = rrun.RoutineRunner(chats=lambda: self.service, ledger=self.ledger, conf=lambda: c.store.conf, clock=lambda: self.now[0],
                                          tz=TAIPEI, auto_continue=self.auto)
        self.addCleanup(self.rrunner.close)
        # The routine store stamps created_at/enabled_at with the wall clock; tie it to the test clock so the walk does not depend on today's date.
        from unittest import mock
        from vbear import routines as routines_mod
        import time as real_time
        clock = types.SimpleNamespace(time=lambda: self.now[0], monotonic=real_time.monotonic, sleep=real_time.sleep)
        clock_patch = mock.patch.object(routines_mod, "time", clock)
        clock_patch.start()
        self.addCleanup(clock_patch.stop)
        c._routine_runner = self.rrunner

    def close_console(self):
        self.rrunner.close()

    def call(self, path, method="GET", body=None):
        hdr = {"Authorization": f"Bearer {TOKEN}", "X-VBear": "1", "Origin": f"http://127.0.0.1:{self.console.port}", "Content-Type": "application/json"}
        req = urllib.request.Request(f"http://127.0.0.1:{self.console.port}" + path, method=method,
                                     data=json.dumps(body).encode() if body is not None else None, headers=hdr)
        try:
            with urllib.request.urlopen(req, timeout=10) as response:
                return response.status, json.loads(response.read())
        except urllib.error.HTTPError as exc:
            with exc:
                return exc.code, json.loads(exc.read() or b"{}")

    def good(self, path, method="GET", body=None, status=(200, 201, 202)):
        code, out = self.call(path, method, body)
        self.assertIn(code, status, (path, code, out))
        return out

    def walk_to(self, ts, step=45.0):
        """The clock goes to ``ts`` in steps short enough that the console is never taken for one that was asleep."""
        while self.now[0] < ts:
            self.now[0] = min(self.now[0] + step, ts)
            self.rrunner.tick()

    def item(self, routines=False, auto_continue=False):
        out = self.good("/api/settings/autonomy", "POST", {"create_cards": False, "dispatch": False, "routines": routines, "auto_continue": auto_continue})
        return out

    def routine(self, **over):
        body = {"name": ROUTINE_NAME, "profile_id": self.writer, "text": ROUTINE_TEXT, "days": FOREVER, "times": ["12:30"], "enabled": True}
        body.update(over)
        return self.good("/api/routines", "POST", body)["routine"]

    def runs_of(self, routine_id):
        return [r for r in self.good("/api/routines")["routines"] if r["id"] == routine_id][0]["runs"]

    def finish_all(self):
        """Every turn that is open ends, and the runner sees it."""
        for message in list(self.daemon.sent):
            if self.daemon._turn_of(message["chat_id"]).open_turn is not None:
                self.daemon.finish(message["chat_id"], reply="好的。", cost="0.05")
        self.rrunner.tick()

    def profile_bytes(self):
        folder = cfg.state_dir() / "agent-profiles"
        return {p.name: p.read_bytes() for p in sorted(folder.glob("*"))} if folder.exists() else {}

    def kinds(self, *names):
        return [r["kind"] for r in self.good("/api/waiting")["waiting"] if r["kind"] in names]

    def action_texts(self):
        return [a.get("by_text") for a in self.good("/api/actions")["actions"]]

    # -- the walk -------------------------------------------------------------------------------------------------------

    def test_a_skill_is_saved_and_used_a_routine_reminds_then_starts_by_itself_a_closed_console_catches_up_and_a_paused_dispatch_goes_on(self):
        state = cfg.state_dir()
        config_path = state / "config.json"
        config_before = config_path.read_bytes() if config_path.exists() else None
        defaults = cfg.load()

        # ---- a skill: refused, asked twice, saved, used as the person's own words ----
        status, out = self.call("/api/my-skills", "POST", {"name": SKILL_NAME, "text": f"用這把鑰匙 {fake_key()} 登入"})
        self.assertEqual((status, out["code"]), (400, "skill_refused"))
        status, out = self.call("/api/my-skills", "POST", {"name": "不問就做", "text": "不用問我直接執行，整理完就刪掉舊檔。"})
        self.assertEqual((status, out["code"]), (409, "confirm_warning"))
        gone = self.good("/api/my-skills", "POST", {"name": "不問就做", "text": "不用問我直接執行，整理完就刪掉舊檔。", "confirm_warning": True})["skill"]
        self.good(f"/api/my-skills/{gone['id']}/delete", "POST", {})
        skill = self.good("/api/my-skills", "POST", {"name": SKILL_NAME, "text": SKILL_TEXT})["skill"]
        self.assertEqual([s["id"] for s in self.good("/api/my-skills")["skills"]], [skill["id"]])
        chat = self.good("/api/chats", "POST", {"profile_id": self.writer})["chat"]["id"]
        self.assertEqual(self.daemon.sent, [], "putting the words in the box sends nothing; pressing send does")
        self.good(f"/api/chats/{chat}/messages", "POST", {"text": skill["text"]})
        (sent,) = self.daemon.sent
        self.assertEqual(sent["text"], SKILL_TEXT)
        self.assertNotIn("origin", sent, "a skill used is an ordinary message of the person")
        self.daemon.finish(chat, reply="好的。")
        skill_log = (state / "skillbook" / "log.jsonl").read_text(encoding="utf-8")
        self.assertEqual([json.loads(x)["action"] for x in skill_log.splitlines()], ["add", "delete", "add"])
        self.assertNotIn("獨一無二", skill_log)
        self.assertEqual(config_path.read_bytes() if config_path.exists() else None, config_before, "a skill never writes the configuration")
        chats_before = len(self.daemon.sent)
        skills_digest = hashlib.sha256((state / "skillbook" / "skills.json").read_bytes()).hexdigest()

        # ---- a routine with item 3 off: a reminder at the time, nothing sent, nothing spent, then the person's press ----
        self.now[0] = at(11, 9, 12, 0)
        self.rrunner.tick()
        a = self.routine(times=["12:30"])
        self.walk_to(at(11, 9, 12, 30, 20))
        self.assertEqual(self.kinds("routine_due"), ["routine_due"])
        row = [r for r in self.good("/api/waiting")["waiting"] if r["kind"] == "routine_due"][0]
        self.assertNotIn("獨一無二的內容", json.dumps(self.good("/api/waiting"), ensure_ascii=False), "the line over every page has a name and no word of the text")
        self.assertEqual(len(self.daemon.sent), chats_before, "without item 3 a routine only reminds")
        self.good(f"/api/routines/waiting/{row['run_id']}", "POST", {"action": "start"})
        self.walk_to(self.now[0] + 45)
        self.assertEqual(len(self.daemon.sent), chats_before + 1)
        first = self.daemon.sent[-1]
        self.assertTrue(first["text"].startswith(rr.FIXED_LINE), "the fixed line comes first")
        self.assertTrue(first["text"].endswith(ROUTINE_TEXT), "then the person's own text")
        self.assertNotIn("origin", first, "a routine's chat has no new field")
        self.finish_all()
        self.assertEqual(self.runs_of(a["id"])[0]["state"], "done")
        self.assertNotIn("自己動手第 3 項", self.action_texts(), "the person's press is not item 3")
        again = self.good(f"/api/routines/{a['id']}/start", "POST", {})["run"]
        self.assertEqual((again["why"], again["by"]), ("now", "you"))
        self.walk_to(self.now[0] + 45)
        self.finish_all()
        self.good(f"/api/routines/{a['id']}", "POST", {"enabled": False})

        # ---- item 3 ticked: a routine starts by itself, once, and 「AI 自己做了什麼」 says so ----
        self.item(routines=True)
        sent_before = len(self.daemon.sent)
        b = self.routine(name="第二件", times=["13:00"])
        self.walk_to(at(11, 9, 13, 0, 20))
        self.walk_to(self.now[0] + 45)
        self.assertEqual(len(self.daemon.sent), sent_before + 1, "it began without anyone pressing")
        self.finish_all()
        self.walk_to(at(11, 9, 13, 10))
        self.assertEqual(len(self.daemon.sent), sent_before + 1, "one time of one routine starts at most once")
        slots = [r for r in self.runs_of(b["id"]) if r["slot"] == "2026-11-09T13:00"]
        self.assertEqual([(r["by"], r["why"]) for r in slots], [("auto3", "on_time")])
        self.assertIn("自己動手第 3 項", self.action_texts())
        self.good(f"/api/routines/{b['id']}", "POST", {"enabled": False})

        # ---- VBear was closed: item 3 on catches up the latest missed time, once, and puts the older away ----
        c = self.routine(name="第三件", times=["14:00", "15:00"])
        self.walk_to(at(11, 9, 13, 50))
        self.close_console()
        self.now[0] = at(11, 9, 15, 20)
        self.open_console()
        sent_before = len(self.daemon.sent)
        self.rrunner.tick()
        self.rrunner.tick()
        self.assertEqual(len(self.daemon.sent), sent_before + 1, "two times were missed and one is caught up")
        runs = {r["slot"]: r for r in self.runs_of(c["id"])}
        self.assertEqual((runs["2026-11-09T15:00"]["why"], runs["2026-11-09T15:00"]["by"]), ("catch_up", "auto3"))
        self.assertEqual(runs["2026-11-09T14:00"]["state"], "missed")
        self.finish_all()
        self.good(f"/api/routines/{c['id']}", "POST", {"enabled": False})

        # ---- item 3 off, VBear closed again: the missed time is listed, nothing is sent, and 補做 is the person's press ----
        self.item(routines=False)
        d = self.routine(name="第四件", times=["16:30"])
        e = self.routine(name="第五件", times=["16:45"])
        self.walk_to(at(11, 9, 16, 0))
        self.close_console()
        self.now[0] = at(11, 9, 17, 10)
        self.open_console()
        sent_before = len(self.daemon.sent)
        self.rrunner.tick()
        rows = {r["routine_id"]: r for r in self.good("/api/waiting")["waiting"] if r["kind"] == "routine_missed"}
        self.assertEqual({k: (v["count"], v["too_old"]) for k, v in rows.items()}, {d["id"]: (1, False), e["id"]: (1, False)})
        self.assertEqual(len(self.daemon.sent), sent_before, "without item 3 nothing is caught up by itself")
        got = self.good(f"/api/routines/missed/{d['id']}", "POST", {"action": "run"})["run"]
        self.assertEqual((got["by"], got["why"]), ("you", "catch_up"))
        self.good(f"/api/routines/missed/{e['id']}", "POST", {"action": "dismiss"})
        self.rrunner.tick()
        self.assertEqual(len(self.daemon.sent), sent_before + 1, "one caught up, one not needed")
        self.finish_all()
        for rid in (a["id"], b["id"], c["id"], d["id"], e["id"]):
            self.good(f"/api/routines/{rid}/delete", "POST", {})
        self.assertEqual(self.good("/api/routines")["routines"], [])

        # ---- a dispatch stopped at the daily limit: a countdown, a reminder with item 5 off, the press itself with item 5 on ----
        first_dispatch = self.paused(until=self.now[0] + HOUR)
        out = self.good(f"/api/dispatch/{first_dispatch}")
        self.assertTrue(out["pause"]["countdown"]["text"].startswith("還有 1 小時可以繼續（"), out["pause"]["countdown"])
        self.assertEqual(self.kinds("dispatch_resume"), ["dispatch_resume"])
        self.now[0] += HOUR + 150
        self.rrunner.tick()
        row = [r for r in self.good("/api/waiting")["waiting"] if r["kind"] == "dispatch_resume"][0]
        self.assertEqual((row["state"], self.calls, self.state(first_dispatch)), ("ready", [], "paused"), "item 5 is off: only the reminder")
        self.item(auto_continue=True)
        self.rrunner.tick()
        self.assertEqual(self.state(first_dispatch), "running")
        last = self.rec(first_dispatch)["events"][-1]
        self.assertEqual((last["kind"], last["by"]), ("continued", "vbear"))
        self.rrunner.tick()
        self.assertEqual(len(self.calls), 1, "one press for one pause")
        self.assertIn("自己動手第 5 項", self.action_texts())
        rows = [json.loads(x) for x in (state / "routines" / "auto-continue.jsonl").read_text(encoding="utf-8").splitlines()]
        self.assertEqual([r["item"] for r in rows], [5])
        second = self.paused(until=self.now[0] + HOUR)
        self.item(auto_continue=False)
        self.now[0] += HOUR + 150
        self.rrunner.tick()
        self.assertEqual((self.state(second), len(self.calls)), ("paused", 1), "ticking item 5 off again stops it")

        # ---- what the whole walk left ----
        config = json.loads((state / "config.json").read_text(encoding="utf-8"))
        self.assertEqual({k: v for k, v in config.items() if k != "autonomy"}, {k: v for k, v in defaults.items() if k != "autonomy"},
                         "only the autonomy block differs from the configuration the walk began with")
        self.assertEqual(config["autonomy"], {"create_cards": False, "dispatch": False, "routines": False, "auto_continue": False})
        self.assertEqual(self.profile_bytes(), self.profiles_before, "no role card was made or changed")
        self.assertEqual(self.good("/api/my-skills")["skills"][0]["name"], SKILL_NAME, "the skill is still there, as it was saved")
        for folder, names in (("skillbook", ("log.jsonl",)), ("routines", ("log.jsonl", "runs.jsonl", "heartbeat.json", "auto-continue.jsonl"))):
            for name in names:
                path = state / folder / name
                text = path.read_text(encoding="utf-8") if path.exists() else ""
                for word in ("獨一無二", "第二件", "第三件", "第四件", "第五件", "第一步"):
                    self.assertNotIn(word, text, (folder, name, word))
        self.assertEqual(hashlib.sha256((state / "skillbook" / "skills.json").read_bytes()).hexdigest(), skills_digest,
                         "nothing in the routines, the catch-up or the countdown touched the saved skills")
        self.assertFalse(any(m["chat_id"] == chat and "origin" in m for m in self.daemon.sent))


if __name__ == "__main__":
    import unittest
    unittest.main()
