"""P40-5: tools/qa_p40.py, the coordinator's real-machine check, must refuse to run without a state folder of its own, never aim at
the person's VBear (its folder, ports 7788 and 7789), and build the bodies the plan says. Nothing here starts a console or a model.

Seams: ``qa_p40.main`` (the command line), ``refusal``, ``plan_body``, ``config_problems``, ``card_problems`` and a ``Run`` over a
fake console that answers the preview only."""
import contextlib
import importlib.util
import io
import json
import tempfile
import unittest
from pathlib import Path

SPEC = importlib.util.spec_from_file_location("qa_p40", Path(__file__).resolve().parent.parent / "tools" / "qa_p40.py")
qa = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(qa)


class CommandLineTests(unittest.TestCase):
    def test_it_does_not_run_without_a_state_folder(self):
        err = io.StringIO()
        with contextlib.redirect_stderr(err), self.assertRaises(SystemExit) as stop:
            qa.main([], out=lambda *_: None)
        self.assertEqual(stop.exception.code, 2)
        self.assertIn("--state", err.getvalue())

    def test_it_refuses_the_ports_of_the_persons_own_vbear(self):
        with tempfile.TemporaryDirectory(prefix="qa40-") as tmp:
            for port in (7788, 7789):
                lines = []
                self.assertEqual(qa.main(["--state", tmp, "--port", str(port)], out=lines.append), 2)
                self.assertTrue(lines[0].startswith("refused"), lines)

    def test_it_refuses_the_persons_own_state_folder_and_a_missing_one(self):
        with tempfile.TemporaryDirectory(prefix="qa40-") as tmp:
            home = Path(tmp)
            (home / ".vbear").mkdir()
            self.assertIn("own VBear", qa.refusal(str(home / ".vbear"), 50001, home=home))
            self.assertIn("does not exist", qa.refusal(str(home / "nope"), 50001, home=home))
            self.assertIsNone(qa.refusal(str(home), 50001, home=home))

    def test_the_default_port_is_not_the_persons(self):
        import re
        source = (Path(qa.__file__)).read_text(encoding="utf-8")
        default = int(re.search(r'"--port", type=int, default=(\d+)', source).group(1))
        self.assertNotIn(default, (7788, 7789))

    def test_a_state_folder_without_a_matching_token_stops_with_a_line_not_a_trace(self):
        with tempfile.TemporaryDirectory(prefix="qa40-") as tmp:
            lines = []
            self.assertEqual(qa.main(["--state", tmp, "--port", str(qa.FORBIDDEN_PORTS[0] + 7)], out=lines.append), 1)
            self.assertTrue(any(l.startswith("FAIL stopped") for l in lines), lines)
            (Path(tmp) / "server.token").write_text(json.dumps({"port": 1, "token": "x"}))
            with self.assertRaises(qa.Stop):
                qa.read_token(Path(tmp), 50001)
            (Path(tmp) / "server.token").write_text(json.dumps({"port": 50001, "token": "synthetic"}))
            self.assertEqual(qa.read_token(Path(tmp), 50001), "synthetic")


class BodyTests(unittest.TestCase):
    VIEW = {"proposal_sha": "a" * 64, "plan": {
        "title": "標題", "goal": "目標",
        "new_cards": [{"ref": "N1", "name": "會計師", "position": "accountant", "tool": "claude", "model_alias": "sonnet", "why": "算價"},
                      {"ref": "N2", "name": "沒用到", "position": "social", "tool": "claude", "model_alias": "sonnet", "why": "x"}],
        "steps": [{"who": "C1", "text": "寫介紹"}, {"who": "N1", "text": "算價"}, {"who": "C1", "text": "第三步"}]}}

    def test_the_body_has_two_steps_the_chosen_model_and_only_the_cards_a_step_uses(self):
        body = qa.plan_body(self.VIEW)
        self.assertEqual(set(body), {"proposal_sha", "title", "goal", "new_cards", "steps"})
        self.assertEqual([s["who"] for s in body["steps"]], ["C1", "N1"])
        self.assertTrue(all(s["text"].startswith("用三行回答：") for s in body["steps"]))
        self.assertEqual([(c["ref"], c["model_alias"]) for c in body["new_cards"]], [("N1", "haiku")])
        self.assertEqual(set(body["new_cards"][0]), {"ref", "name", "position", "tool", "model_alias"})

    def test_the_config_check_ignores_only_the_keys_the_script_wrote(self):
        before = {"a": 1, "meeting_limits": {"daily_usd": 0.45}, "autonomy": {}}
        after = {"a": 1, "meeting_limits": {"daily_usd": 0.01}, "autonomy": {"dispatch": True}}
        self.assertEqual(qa.config_problems(before, after), [])
        self.assertEqual(qa.config_problems(before, {**after, "language": "x"}), ["language"])
        self.assertEqual(qa.config_problems(before, {"meeting_limits": {}}), ["a"])

    def test_a_card_a_dispatch_made_must_be_safe_with_no_skill(self):
        self.assertEqual(qa.card_problems({"launch_mode": "safe", "equipped_skill_ids": []}), [])
        self.assertEqual(qa.card_problems({"launch_mode": "full", "equipped_skill_ids": ["s"]}), ["launch_mode", "equipped_skill_ids"])


class FakeConsole:
    def __init__(self, preview):
        self.preview, self.calls = preview, []

    def ok(self, path, method="GET", body=None, status=(200, 202)):
        self.calls.append((method, path.split("?")[0]))
        if path.startswith("/api/chief/preview"):
            return self.preview
        raise qa.Stop("unexpected " + path)


class PreviewStageTests(unittest.TestCase):
    def run_preview(self, preview, until="preview"):
        with tempfile.TemporaryDirectory(prefix="qa40-") as tmp:
            (Path(tmp) / "config.json").write_text("{}")
            lines = []
            check = qa.Check(lines.append)
            console = FakeConsole(preview)
            run = qa.Run(console, Path(tmp), "c-1", until, check)
            try:
                run.preview("c-1")
            except qa.Stop:
                pass
            return check, console, lines

    def test_a_good_preview_passes_and_asks_nothing_else(self):
        check, console, _ = self.run_preview({"ok": True, "preview_id": "p", "sends_to": "Claude Code", "cap_usd": "0.3", "day_left_usd": "2.5",
                                              "messages": 2, "cards": 1})
        self.assertEqual((check.failed, console.calls), (0, [("GET", "/api/chief/preview")]))

    def test_a_blocked_preview_fails_and_stops(self):
        check, _, lines = self.run_preview({"ok": False, "blockers": [{"code": "boundary_unverified"}]})
        self.assertGreater(check.failed, 0)
        self.assertTrue(any("boundary_unverified" in l for l in lines))

    def test_the_stages_run_in_order(self):
        with tempfile.TemporaryDirectory(prefix="qa40-") as tmp:
            run = qa.Run(None, Path(tmp), None, "propose", qa.Check(lambda *_: None))
            self.assertEqual([run.reached(s) for s in qa.STAGES], [True, True, False, False])


if __name__ == "__main__":
    unittest.main()
