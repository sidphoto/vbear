"""The chat protocol (P36-1): what VBear writes to Claude Code 2.1.318 in a chat, how it reads what comes back, and
which tool calls it answers itself. Pure: replayed from the recorded transcripts (tests/chat_fixtures.py); no process
is started."""

from __future__ import annotations

import dataclasses
import json
import os
import shutil
import tempfile
import unittest
from decimal import Decimal
from pathlib import Path

from tests import chat_fixtures as cf
from tests import leftover
from vbear.runtime import chat_protocol as cp

SID = "0f1e2d3c-4b5a-4968-8776-655443322110"


def bind(ev, work: str):
    """A recorded event as the fake CLI prints it: this test's session id and work folder."""
    return json.loads(json.dumps(ev).replace(cf.SESSION, SID).replace(cf.WORK, work))


def init_answer(**over) -> dict:
    """An initialize answer like 2.1.318's, with fictional values in the fields VBear must never keep."""
    body = {"claude_code_version": cf.VERSION, "current_permission_mode": "default",
            "account": {"email": "fictional-person@example.invalid", "organization": "Fictional Org"},
            "commands": [{"name": "fictional-command"}], "models": [{"value": "fictional-model"}], "pid": 4242}
    body.update(over)
    return {"type": "control_response", "response": {"subtype": "success", "request_id": "init-1", "response": body}}


class Replay:
    def __init__(self, work: str = cf.WORK):
        self.work = work
        self.t = cp.ChatTracker(cp.VERSIONS[cf.VERSION], session_id=SID, workdir=work, init_request_id="init-1")
        self.facts: list[tuple[str, dict]] = []

    def feed(self, ev):
        out = self.t.on_event(bind(ev, self.work))
        self.facts += out
        return out

    def kinds(self):
        return [k for k, _ in self.facts]

    def of(self, kind):
        return [d for k, d in self.facts if k == kind]


class ConstantsTests(unittest.TestCase):
    def test_2_1_318_is_the_recorded_version(self):
        c = cp.VERSIONS["2.1.318"]
        self.assertEqual(c.tools, frozenset({"Bash", "Read", "Edit", "Write", "Grep", "Glob"}))
        self.assertEqual(c.permission_mode, "default")
        self.assertTrue(c.cost_cumulative)
        self.assertIsNone(cp.constants_for("2.1.296"))
        self.assertIsNone(cp.constants_for(None))

    def test_2_1_319_has_the_same_constants_as_2_1_318(self):
        """P40-6: the --help of 2.1.319 is identical to 2.1.318's (docs/evidence/claude-code-2.1.318-chat.md), so the chat's
        constants are the same; only the version differs. Not yet in any verified list: that needs boundary_check --mode chat."""
        new, old = cp.VERSIONS["2.1.319"], cp.VERSIONS["2.1.318"]
        self.assertEqual(new.version, "2.1.319")
        self.assertEqual(dataclasses.replace(new, version="2.1.318"), old)
        self.assertIs(cp.constants_for("2.1.319"), new)
        self.assertEqual(sorted(cp.VERSIONS), ["2.1.318", "2.1.319"])

    def test_every_recorded_event_kind_is_known(self):
        for name in ("ask", "text"):
            for direction, line in cf.load(name):
                if direction == "out" and isinstance(line, dict):
                    self.assertIn(cp.kind_of(line), cp.VERSIONS["2.1.318"].known, line.get("type"))


class LineTests(unittest.TestCase):
    def test_initialize_and_user_lines(self):
        init = json.loads(cp.initialize_line("init-1"))
        self.assertEqual(init, {"type": "control_request", "request_id": "init-1",
                                "request": {"subtype": "initialize"}})
        line = cp.user_line("你好", SID)
        self.assertTrue(line.endswith(b"\n"))
        self.assertEqual(json.loads(line), {"type": "user", "message": {"role": "user", "content": [
            {"type": "text", "text": "你好"}]}, "session_id": SID, "parent_tool_use_id": None})

    def test_answers_have_the_recorded_shape(self):
        recorded = [x["line"] for t in cf.turns("ask") for x in t["out"] if x["dir"] == "in"]
        modify = next(r for r in recorded if r["response"]["response"]["updatedInput"].get("command")
                      == "echo changed-by-user")
        rid = modify["response"]["request_id"]
        self.assertEqual(json.loads(cp.allow_line(rid, {"command": "echo changed-by-user",
                                                        "description": "Print the word original"})), modify)
        deny = json.loads(cp.deny_line(rid, "使用者拒絕"))
        self.assertEqual(deny, {"type": "control_response", "response": {
            "subtype": "success", "request_id": rid, "response": {"behavior": "deny", "message": "使用者拒絕"}}})
        err = json.loads(cp.error_line("r-9", "VBear 不回答這種請求"))
        self.assertEqual(err, {"type": "control_response", "response": {
            "subtype": "error", "request_id": "r-9", "error": "VBear 不回答這種請求"}})

    def test_a_line_over_the_limit_is_refused_not_cut(self):
        with self.assertRaises(ValueError):
            cp.allow_line("r-1", {"content": "x" * (cp.MAX_STDIN_LINE + 1)})
        with self.assertRaises(ValueError):
            cp.user_line("\ud800", SID)


class TrackerTests(unittest.TestCase):
    def test_bash_turn_from_the_recording(self):
        r = Replay()
        r.feed(init_answer())
        steps = cf.script("ask", 0, init=cf.clean_init())
        for step in steps:
            for ev in step.get("emit", []):
                r.feed(ev)
            if "ask" in step:
                [(kind, req)] = r.feed(step["ask"])
                self.assertEqual(kind, "permission_request")
                self.assertEqual((req["tool"], req["input"]["command"]), ("Bash", "ls -a"))
                self.assertTrue(cp.UUID_RE.match(req["request_id"]))
                r.t.approve(req["tool_use_id"])
        self.assertEqual(r.of("initialized"), [{"claude_code_version": "2.1.318", "permission_mode": "default"}])
        ready = r.of("session_ready")
        self.assertEqual(ready, [{"claude_code_version": "2.1.318", "permission_mode": "default",
                                  "model": "claude-haiku-5-5"}])
        [call] = r.of("tool_call")
        self.assertEqual((call["tool"], call["input"]["command"]), ("Bash", "ls -a"))
        [res] = r.of("tool_result")
        self.assertEqual((res["is_error"], res["text"], res["source"]), (False, ".\n..\n.claude", "user_temporary"))
        reply = "".join(d["text"] for d in r.of("delta"))
        self.assertEqual([x["text"] for x in r.of("reply")], [reply])
        self.assertIn(".claude", reply)
        [result] = r.of("result")
        self.assertEqual(result["total_cost_usd"], 0.00100946)
        self.assertEqual((result["subtype"], result["is_error"], result["denials"]), ("success", False, 0))
        self.assertNotIn("violation", r.kinds())
        self.assertNotIn("anomaly", r.kinds())

    def test_nothing_of_the_account_or_the_extra_folders_is_kept(self):
        r = Replay()
        r.feed(init_answer())
        for step in cf.script("ask", 0):
            for ev in step.get("emit", []):
                r.feed(ev)
        dumped = json.dumps(r.facts, ensure_ascii=False)
        for secret in ("fictional-person", "Fictional Org", "fictional-command", "fictional-model", "USER-DIR",
                       "/SOCKET", "4242"):
            self.assertNotIn(secret, dumped)
        [v] = r.of("violation")
        self.assertIn("額外資料夾", v["message"])
        self.assertIn("2", v["message"])                          # how many, never which

    def test_the_initialize_answer_must_name_this_version_and_mode(self):
        for over in ({"claude_code_version": "2.1.319"}, {"current_permission_mode": "bypassPermissions"}):
            r = Replay()
            r.feed(init_answer(**over))
            self.assertEqual(r.kinds(), ["violation"], over)
        r = Replay()
        r.feed({"type": "control_response", "response": {"subtype": "error", "request_id": "init-1",
                                                          "error": "no"}})
        self.assertEqual(r.kinds(), ["violation"])

    def test_init_must_match_the_launch(self):
        base = cf.events("ask", 0)
        init = next(e for e in base if e.get("type") == "system" and e.get("subtype") == "init")
        cases = {"permissionMode": "acceptEdits", "claude_code_version": "2.1.317", "cwd": "/elsewhere",
                 "tools": ["Bash", "Edit", "Glob", "Grep", "Read", "Write", "WebFetch"], "mcp_servers": [{"name": "x"}]}
        for key, value in cases.items():
            r = Replay()
            ev = dict(init, additional_directories=[], **{key: value})
            r.feed(ev)
            self.assertEqual(r.kinds(), ["violation"], key)
        r = Replay()
        r.feed(dict(init, additional_directories=[], mcp_servers=[]))
        self.assertEqual(r.kinds(), ["session_ready"])
        r.feed(dict(init, additional_directories=[], uuid="11111111-2222-4333-8444-555555555555"))
        self.assertEqual(r.kinds(), ["session_ready"])           # every turn sends init again; checked, not repeated

    def test_a_tool_run_without_a_card_stops_the_chat(self):
        """The text transcript was recorded without --permission-prompt-tool stdio: Claude Code ran ``ls -a`` by
        itself. VBear never answered that call, so it is a broken promise ("ask every time")."""
        r = Replay()
        for ev in cf.events("text", 1):
            r.feed(dict(ev, additional_directories=[]) if ev.get("subtype") == "init" else ev)
        [v] = r.of("violation")
        self.assertIn("Bash", v["message"])

    def test_a_refusal_by_claude_code_itself_is_not_a_violation(self):
        r = Replay()
        for ev in cf.events("text", 2):
            r.feed(dict(ev, additional_directories=[]) if ev.get("subtype") == "init" else ev)
        self.assertNotIn("violation", r.kinds())
        self.assertEqual(r.of("denied"), [{"tool": "Write", "tool_use_id": "toolu_01WKctLnmPmYpDBe22VjetTA"}])
        [res] = r.of("tool_result")
        self.assertTrue(res["is_error"])

    def test_a_read_claude_code_allowed_in_the_work_folder_is_fine_outside_it_is_not(self):
        tmp = Path(os.path.realpath(tempfile.mkdtemp(prefix="vbc-")))
        self.addCleanup(shutil.rmtree, tmp, True)
        self.addCleanup(leftover.assert_clean, tmp)
        r = Replay(str(tmp))
        r.feed(init_answer())
        for step in cf.script("ask", 3, init=cf.clean_init()):
            for ev in step.get("emit", []):
                r.feed(ev)
            if "ask" in step:
                [(_, req)] = r.feed(step["ask"])
                r.t.approve(req["tool_use_id"])
        self.assertNotIn("violation", r.kinds())
        self.assertEqual([c["tool"] for c in r.of("tool_call")], ["Read", "Edit"])
        # the same read while the folder holds a link that leads out: VBear would have asked, so it ran without a yes
        (tmp / "away").symlink_to("/etc")
        r = Replay(str(tmp))
        for ev in cf.events("ask", 3):
            if ev.get("type") == "control_request":
                break
            r.feed(dict(ev, additional_directories=[]) if ev.get("subtype") == "init" else ev)
        [v] = r.of("violation")
        self.assertIn("Read", v["message"])
        r = Replay()
        for ev in cf.events("ask", 3):
            if ev.get("type") == "assistant":
                for item in ev["message"]["content"]:
                    if item.get("name") == "Read":
                        item["input"]["file_path"] = "/etc/hosts"
            if ev.get("type") == "control_request":
                break
            r.feed(dict(ev, additional_directories=[]) if ev.get("subtype") == "init" else ev)
        [v] = r.of("violation")
        self.assertIn("Read", v["message"])

    def test_unknown_events_are_named_never_shown(self):
        r = Replay()
        out = r.feed({"type": "telemetry_ping", "session_id": SID, "secret_value": "fictional-secret-1",
                      "bad field!": 1})
        self.assertEqual(out, [("anomaly", {"event_type": "telemetry_ping", "fields": ["?", "secret_value",
                                                                                          "session_id", "type"]})])
        self.assertNotIn("fictional-secret-1", json.dumps(out))
        out = r.feed({"type": "system", "subtype": "brand_new", "session_id": SID})
        self.assertEqual(out[0][1]["event_type"], "system/brand_new")
        self.assertEqual(r.feed("not an object")[0][0], "anomaly")

    def test_an_unknown_control_request_is_answered_with_a_refusal(self):
        r = Replay()
        out = r.feed({"type": "control_request", "request_id": "req-7", "request": {"subtype": "hook_callback",
                                                                                   "callback_id": "x"}})
        self.assertEqual(out, [("unknown_control", {"request_id": "req-7", "subtype": "hook_callback"})])
        out = r.feed({"type": "control_request", "request_id": "has spaces\n", "request": {"subtype": "x"}})
        self.assertEqual(out[0][0], "anomaly")                   # no id to answer: nothing can be written back

    def test_another_sessions_event_is_not_read(self):
        r = Replay()
        ev = cf.events("ask", 0)[-1]                              # the result
        self.assertEqual(ev["type"], "result")
        out = r.t.on_event(dict(bind(ev, cf.WORK), session_id="99999999-2222-4333-8444-555555555555"))
        self.assertEqual([k for k, _ in out], ["anomaly"])


class JudgeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(os.path.realpath(tempfile.mkdtemp(prefix="vbc-")))
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.addCleanup(leftover.assert_clean, self.tmp)
        self.work = self.tmp / "work"
        self.work.mkdir()
        (self.tmp / "outside").mkdir()
        (self.work / "out-link").symlink_to(self.tmp / "outside")
        self.w = str(self.work)

    def j(self, tool, **inp):
        return cp.judge(tool, inp, self.w)

    def test_bash_always_asks_and_its_command_may_be_changed(self):
        j = self.j("Bash", command="ls", description="list")
        self.assertEqual((j.action, j.editable), ("ask", "command"))

    def test_write_and_edit_inside_ask_outside_are_refused(self):
        (self.tmp / "outside" / "a").write_text("x")                     # links followed: also when the file exists
        self.assertEqual((self.j("Write", file_path=f"{self.w}/a.txt", content="x").action,
                          self.j("Write", file_path=f"{self.w}/a.txt", content="x").editable), ("ask", "content"))
        self.assertEqual(self.j("Edit", file_path=f"{self.w}/a.txt", old_string="a", new_string="b").editable,
                         "new_string")
        self.assertEqual(self.j("Write", file_path="a.txt", content="x").action, "ask")     # relative to the folder
        for path in ("/etc/x", f"{self.tmp}/outside/a", f"{self.w}/../a", f"{self.w}/out-link/a", f"{self.w}2/a",
                     f"{self.w}/.claude/settings.json", f"{self.w}/.claude", "../a"):
            for tool in ("Write", "Edit"):
                j = self.j(tool, file_path=path, content="x", old_string="a", new_string="b")
                self.assertEqual(j.action, "deny", (tool, path))
                self.assertTrue(j.reason)
        self.assertEqual(self.j("Write", content="x").action, "deny")                       # no path at all

    def test_reads_ask_while_the_folder_holds_a_link_that_leads_out(self):
        """Automated security review finding (P36-1): a link inside the work folder that points outside it makes
        every Read, Grep and Glob ask, whatever its own path says."""
        for tool, inp in (("Read", {"file_path": f"{self.w}/a.txt"}), ("Grep", {"pattern": "x"}),
                          ("Glob", {"pattern": "*.py"}), ("Glob", {"pattern": "*.py", "path": self.w})):
            self.assertEqual(cp.judge(tool, inp, self.w).action, "ask", (tool, inp))
        (self.work / "deep" / "er").mkdir(parents=True)
        (self.work / "out-link").unlink()
        (self.work / "deep" / "er" / "x").symlink_to("/etc")                  # nested, absolute
        self.assertEqual(self.j("Glob", pattern="*.py").action, "ask")
        (self.work / "deep" / "er" / "x").unlink()
        (self.work / "deep" / "er" / "y").symlink_to("../../..")                # relative, climbing out
        self.assertEqual(self.j("Read", file_path=f"{self.w}/a.txt").action, "ask")

    def test_reads_inside_the_folder_are_allowed_by_vbear_others_ask(self):
        (self.work / "out-link").unlink()
        (self.work / "sub").mkdir()
        (self.work / "in-link").symlink_to(self.work / "sub")                  # a link that stays inside is fine
        self.assertEqual(self.j("Read", file_path=f"{self.w}/a.txt").action, "allow")
        self.assertEqual(self.j("Read", file_path="sub/a.txt").action, "allow")
        self.assertEqual(self.j("Grep", pattern="x").action, "allow")                      # no path: the folder
        self.assertEqual(self.j("Grep", pattern="a/b", glob="*.md").action, "allow")       # a content regex is no path
        self.assertEqual(self.j("Glob", pattern="*.py").action, "allow")
        self.assertEqual(self.j("Glob", pattern="*.py", path=f"{self.w}/sub").action, "allow")
        (self.tmp / "outside" / "a").write_text("x")
        for tool, inp in (("Read", {"file_path": "/etc/hosts"}), ("Read", {"file_path": f"{self.w}/../outside/a"}),
                          ("Grep", {"pattern": "x", "path": "/"}), ("Glob", {"pattern": "*.py", "path": "/etc"}),
                          # automated security review finding (P36-1): a file pattern with a path in it asks
                          ("Glob", {"pattern": "../**/*.env"}), ("Glob", {"pattern": "../x/**"}),
                          ("Glob", {"pattern": "/etc/*"}), ("Glob", {"pattern": "**/*.py"}),
                          ("Glob", {"pattern": "sub/*.py"}), ("Glob", {"pattern": "~/x"}), ("Glob", {"pattern": ""}),
                          ("Glob", {}), ("Grep", {"pattern": "x", "glob": "../*"}),
                          ("Grep", {"pattern": "x", "glob": "/etc/*"}), ("Grep", {"pattern": "x", "glob": "a/*.py"}),
                          ("Grep", {"pattern": "x", "glob": "{..,x}*"})):
            j = cp.judge(tool, inp, self.w)
            self.assertEqual((j.action, j.editable), ("ask", None), (tool, inp))

    def test_a_read_through_a_link_that_leads_out_is_asked_by_its_own_path(self):
        j = self.j("Read", file_path=f"{self.w}/out-link/a")
        self.assertEqual(j.action, "ask")
        self.assertIn("以外", j.reason)

    def test_any_other_tool_is_refused(self):
        for tool in ("WebFetch", "WebSearch", "Task", "NotebookEdit", "mcp__x__y", ""):
            self.assertEqual(cp.judge(tool, {}, self.w).action, "deny", tool)
        self.assertEqual(cp.judge("Bash", "not a dict", self.w).action, "deny")


class CostTests(unittest.TestCase):
    def test_the_turns_cost_is_this_total_minus_the_last(self):
        """P36-0 fact 6/7: total_cost_usd counts the whole session, the resumed process included (ask: 0.00246117
        at the end of the first process, 0.00262565 after one more turn in the resumed one)."""
        cap = Decimal("0.50")
        self.assertEqual(cp.turn_cost(0.00262565, 0.00246117, cap), (Decimal("0.00016448"), True))
        self.assertEqual(cp.turn_cost(0.001, None, cap), (Decimal("0.001"), True))
        self.assertEqual(cp.turn_cost(None, 0.2, cap), (cap, False))             # nothing reported: the cap
        self.assertEqual(cp.turn_cost(0.1, 0.2, cap), (cap, False))              # went back: not a cost, the cap
        self.assertEqual(cp.turn_cost(0.9, 0.2, cap), (Decimal("0.7"), True))    # over the cap: what it says


if __name__ == "__main__":
    unittest.main()
