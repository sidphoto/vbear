"""P54: tools/shots_stub.py, the screenshots of VBear's pages from made-up data. These tests start no browser and no server: they test the pure parts (the ports it
refuses, the 409 for every write, that the invented data holds nothing real, the scenes, the files it may serve) and that the file keeps the rules of a developer tool
(standard library only, nothing of the product's server imported, no outside program run)."""
from __future__ import annotations

import ast
import importlib.util
import json
import re
import sys
import tempfile
import unittest
from pathlib import Path

SOURCE = Path(__file__).resolve().parent.parent / "tools" / "shots_stub.py"
SPEC = importlib.util.spec_from_file_location("shots_stub", SOURCE)
shots = importlib.util.module_from_spec(SPEC)
sys.modules["shots_stub"] = shots
SPEC.loader.exec_module(shots)

NOW = 1_790_000_000.0


def every_answer(world_name: str) -> list:
    fake = shots.Fake(shots.build_world(world_name, NOW), NOW)
    paths = ["/api/config", "/api/agent-profiles", "/api/agent-builder/catalog", "/api/chats", "/api/meetings/ledger", "/api/routines", "/api/waiting", "/api/flows", "/api/meetings",
             "/api/staffing", "/api/dispatch", "/api/groups", "/api/live", "/api/tasks", "/api/setup/tools", "/api/first-ceo?tool=claude", "/api/setup/daily-limit", "/api/overview",
             "/api/skills", "/api/roles", "/api/translations", "/api/settings/autonomy", "/api/templates", "/api/memory", "/api/not-a-route"]
    out = [fake.answer("GET", p) for p in paths]
    for cid in (c["id"] for c in fake.w.chats):
        out.append(fake.answer("GET", f"/api/chats/{cid}?after=0"))
    return out


class PortTests(unittest.TestCase):
    def test_the_reserved_ports_are_refused(self):
        for port in (7788, 7789, 7795, 7796, 7799, 7800, 7801, 7802, 7803):
            self.assertIsNotNone(shots.port_refusal(port), port)
            with self.assertRaises(ValueError):
                shots.Stub(port)

    def test_other_ports_pass_and_the_default_is_not_reserved(self):
        self.assertEqual(shots.DEFAULT_PORT, 7811)
        for port in (7811, 7812, 8123, 54321):
            self.assertIsNone(shots.port_refusal(port), port)

    def test_odd_ports_are_refused(self):
        for port in (0, 80, 1023, 65536, -1, "7811", None, True, 7811.0):
            self.assertIsNotNone(shots.port_refusal(port), repr(port))

    def test_main_refuses_a_reserved_port_before_it_starts_anything(self):
        lines = []
        for port in (7788, 7789, 7803):
            self.assertEqual(shots.main(["--port", str(port), "--tmp", tempfile.gettempdir(), "--out", tempfile.gettempdir()], out=lines.append), 2)
        self.assertTrue(all(line.startswith("refused:") for line in lines), lines)

    def test_the_server_is_bound_to_the_loopback_only(self):
        source = SOURCE.read_text(encoding="utf-8")
        self.assertIn('ThreadingHTTPServer(("127.0.0.1", port), Handler)', source)
        self.assertNotIn("0.0.0.0", source)


class FolderTests(unittest.TestCase):
    def test_nothing_under_a_dot_folder_of_the_home_is_used(self):
        home = Path(tempfile.mkdtemp(prefix="t54h"))
        try:
            for dot in (".vbear", ".claude", ".codex", ".gemini", ".ssh", ".config", ".agents"):
                self.assertIsNotNone(shots.path_refusal(home / dot / "x", home=home), dot)
                self.assertIsNotNone(shots.path_refusal(home / dot, home=home), dot)
            self.assertIsNone(shots.path_refusal(home / "Documents" / "x", home=home))
            self.assertIsNone(shots.path_refusal(Path("/tmp/v54.abcd"), home=home))
        finally:
            home.rmdir()

    def test_the_pictures_may_go_to_the_runs_folder_and_nowhere_else_in_a_dot_folder(self):
        home = Path(tempfile.mkdtemp(prefix="t54h"))
        try:
            ok = home / ".codex" / "projects" / "sid-console" / "runs" / "20261112-p50" / "shots-stub"
            self.assertIsNone(shots.path_refusal(ok, output=True, home=home))
            self.assertIsNotNone(shots.path_refusal(ok, output=False, home=home), "the browser's own folder may never be there")
            self.assertIsNotNone(shots.path_refusal(home / ".codex" / "sessions", output=True, home=home))
            self.assertIsNotNone(shots.path_refusal(home / ".vbear" / "runs" / "x", output=True, home=home))
        finally:
            pass


class WritesTests(unittest.TestCase):
    def test_every_write_is_409_and_recorded_and_changes_nothing(self):
        fake = shots.Fake(shots.build_world("home-busy", NOW), NOW)
        before = json.dumps(fake.chats(), sort_keys=True)
        for method in ("POST", "PUT", "PATCH", "DELETE", "post"):
            for path in ("/api/chats", "/api/config", "/api/setup/settle", "/api/chats/c-0123456789abcdef/messages", "/api/agent-profiles?x=1"):
                status, body = fake.answer(method, path)
                self.assertEqual(status, 409, (method, path))
                self.assertEqual(body["code"], "stub_read_only")
        self.assertEqual(len(fake.writes), 25)
        self.assertEqual(fake.writes[0], "POST /api/chats")
        self.assertTrue(all("?" not in w for w in fake.writes), "a recorded write is a method and a path only")
        self.assertEqual(json.dumps(fake.chats(), sort_keys=True), before)

    def test_a_read_is_not_a_write(self):
        fake = shots.Fake(shots.build_world("home-fresh", NOW), NOW)
        for method in ("GET",):
            status, _ = fake.answer(method, "/api/chats")
            self.assertEqual(status, 200)
        self.assertEqual(fake.writes, [])

    def test_the_server_class_answers_a_write_through_the_same_refusal(self):
        source = SOURCE.read_text(encoding="utf-8")
        self.assertIn("do_POST = do_PUT = do_PATCH = do_DELETE = _api", source)
        self.assertEqual(shots.WRITE_METHODS, ("POST", "PUT", "PATCH", "DELETE"))


class InventedDataTests(unittest.TestCase):
    def test_the_data_holds_nothing_real(self):
        for name in shots.WORLDS:
            text = json.dumps(every_answer(name), ensure_ascii=False)
            self.assertNotIn("/Users/", text, name)
            self.assertNotIn("/home/", text, name)
            self.assertNotIn("@", text, name)
            self.assertNotRegex(text, r"https?://", name)
            self.assertNotIn("~/", text, name)

    def test_the_source_has_no_path_in_a_home_folder_and_no_address(self):
        source = SOURCE.read_text(encoding="utf-8")
        data_part = source[source.index("# ---- the invented data"):source.index("# ---- the stub console (HTTP)")]
        self.assertNotIn("/Users/", data_part)
        self.assertNotRegex(data_part, r"\S@\S", "an address")          # (a decorator is ``@dataclass`` at the start of a word, not between two)
        self.assertNotRegex(data_part, r"https?://")

    def test_every_world_builds_and_every_answer_is_json(self):
        for name in shots.WORLDS:
            for status, body in every_answer(name):
                self.assertIn(status, (200, 404), name)
                json.dumps(body)

    def test_the_names_are_made_up(self):
        for name in shots.NAME.values():
            self.assertTrue(name.startswith("虛構"), name)

    def test_the_ids_have_the_shape_the_page_expects(self):
        self.assertRegex(shots.chat_id(1), r"^c-[0-9a-f]{16}$")
        self.assertRegex(shots.card_id(1), r"^k-[0-9a-f]{16}$")
        self.assertRegex(shots.CEO, r"^prof-[0-9a-f]{12}$")

    def test_the_rich_chat_has_what_the_scene_is_for(self):
        kinds = [r["kind"] for r in shots.rich_records(NOW)]
        for kind in ("user_message", "reply", "tool_call", "tool_result", "auto_allowed", "turn_ended", "process_started", "denied", "error", "card"):
            self.assertIn(kind, kinds, kind)
        seqs = [r["seq"] for r in shots.rich_records(NOW)]
        self.assertEqual(seqs, sorted(set(seqs)))
        world = shots.build_world("chat-rich", NOW)
        cid = shots.chat_id(1)
        self.assertEqual(world.details[cid]["live"]["cards"][0]["tool"], "Bash")
        status, detail = shots.Fake(world, NOW).answer("GET", f"/api/chats/{cid}?after=0")
        self.assertEqual(status, 200)
        self.assertEqual(detail["next_after"], seqs[-1])
        self.assertFalse(detail["more"])
        status, later = shots.Fake(world, NOW).answer("GET", f"/api/chats/{cid}?after={seqs[-1]}")
        self.assertEqual(later["records"], [])

    def test_an_unknown_world_or_chat_is_refused(self):
        with self.assertRaises(KeyError):
            shots.build_world("nope", NOW)
        status, _ = shots.Fake(shots.build_world("home-fresh", NOW), NOW).answer("GET", "/api/chats/c-0123456789abcdef")
        self.assertEqual(status, 404)

    def test_the_home_worlds_say_what_the_scenes_are_about(self):
        busy = shots.build_world("home-busy", NOW)
        self.assertEqual(len(busy.chats), 4)
        self.assertEqual(sum(1 for c in busy.chats if c["waiting"]), 1)
        self.assertEqual(len(busy.waiting), 1)
        who = shots.build_world("home-who", NOW)
        self.assertEqual(sum(1 for c in who.cards if c["can_chat"]), 3)
        self.assertEqual(sum(1 for c in who.cards if not c["can_chat"]), 1)
        self.assertEqual(shots.build_world("first-empty", NOW).profiles, [])
        self.assertEqual(shots.build_world("chat-limit", NOW).ledger["lamp"], "red")


class StaticTests(unittest.TestCase):
    def test_only_files_of_web_are_served(self):
        web = shots.WEB
        self.assertEqual(shots.static_path("/", web), web / "index.html")
        self.assertEqual(shots.static_path("/app.js", web), (web / "app.js").resolve())
        for bad in ("/../tools/shots_stub.py", "/%2e%2e/x", "/a/../../x", "/missing.js", "/vendor", "//etc/passwd", "/\\x"):
            self.assertIsNone(shots.static_path(bad, web), bad)


class ScenesTests(unittest.TestCase):
    def test_the_list_is_not_empty_and_has_the_scenes_of_the_plan(self):
        self.assertGreaterEqual(len(shots.SCENES), 10)
        slugs = [s.slug for s in shots.SCENES]
        self.assertEqual(len(slugs), len(set(slugs)))
        for needed in ("home-fresh", "home-busy-closed", "home-busy-open", "home-who", "chat-rich", "chat-rich-open", "chat-who", "chat-working", "chat-first", "chat-limit", "chat-list",
                       "first-empty-pick", "first-ready", "first-unknown", "settings", "templates-save", "drawer-open"):
            self.assertIn(needed, slugs)

    def test_every_scene_names_a_world_an_address_and_known_sizes(self):
        sizes = {s[0] for s in shots.SIZES}
        for scene in shots.SCENES:
            self.assertIn(scene.world, shots.WORLDS, scene.slug)
            self.assertTrue(scene.hash.startswith("#/"), scene.slug)
            self.assertTrue(set(scene.sizes) <= sizes, scene.slug)
            self.assertTrue(shots.sizes_of(scene), scene.slug)
            for step in scene.steps:
                self.assertIn(step[0], ("click", "fill", "js", "wait"), scene.slug)

    def test_the_sizes_are_the_three_of_the_plan(self):
        self.assertEqual([(s[1], s[2], s[3]) for s in shots.SIZES], [(1280, 800, "light"), (1280, 800, "dark"), (400, 800, "light")])

    def test_the_file_names_are_numbered_and_unique(self):
        names = [shots.shot_name(i, s, size[0]) for i, s in enumerate(shots.SCENES, 1) for size in shots.sizes_of(s)]
        self.assertEqual(len(names), len(set(names)))
        self.assertTrue(all(re.fullmatch(r"\d\d-[a-z0-9-]+-(desktop|phone)-(light|dark)\.png", n) for n in names), names[:3])

    def test_main_lists_and_refuses_an_unknown_scene(self):
        lines = []
        self.assertEqual(shots.main(["--list"], out=lines.append), 0)
        self.assertEqual(len(lines), len(shots.SCENES))
        refused = []
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(shots.main(["--tmp", tmp, "--out", tmp + "/o", "--only", "nope"], out=refused.append), 2)
        self.assertIn("no such scene", refused[0])


class ToolRulesTests(unittest.TestCase):
    def test_standard_library_only_and_nothing_of_the_product_is_imported(self):
        tree = ast.parse(SOURCE.read_text(encoding="utf-8"))
        names = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                names.update(a.name.split(".")[0] for a in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                names.add(node.module.split(".")[0])
        self.assertNotIn("vbear", names)
        stdlib = set(sys.stdlib_module_names)
        self.assertTrue(names <= stdlib, names - stdlib)

    def test_it_runs_no_outside_program_itself(self):
        source = SOURCE.read_text(encoding="utf-8")
        for word in ("subprocess", "os.system", "os.popen", "Popen("):
            self.assertNotIn(word, source, word)       # the browser is started by qa_p47's Browser, as in the other tools


if __name__ == "__main__":
    unittest.main()
