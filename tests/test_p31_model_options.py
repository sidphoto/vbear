"""P31: the model names the card wizard offers in its drop-down.

Everything here runs against a made-up home folder and made-up files. Nothing is run and nothing goes to the network:
the Codex list is read from the file Codex itself caches, and the Claude list is the aliases plus the names the usage
scan already saw.

Run: python3 -m unittest tests.test_p31_model_options -v
"""

from __future__ import annotations

import json
import os
os.environ["VBEAR_RUNTIME_AUTOSTART"] = "0"
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from vbear import model_options  # noqa: E402


def _entry(slug, name=None, visibility="list", priority=None, **extra):
    row = {"slug": slug, "display_name": name if name is not None else str(slug).upper(), "visibility": visibility}
    if priority is not None:
        row["priority"] = priority
    row.update(extra)
    return row


class CodexCacheTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory(prefix="vbear-p31-")
        self.addCleanup(self._tmp.cleanup)
        self.home = Path(self._tmp.name).resolve() / "home"
        (self.home / ".codex").mkdir(parents=True)
        self.cache = self.home / ".codex" / "models_cache.json"

    def write(self, models, **top):
        self.cache.write_text(json.dumps({"fetched_at": "2026-10-20T00:00:00Z", "models": models, **top}))

    def read(self):
        return model_options.codex_models(self.home)

    def test_only_listed_models_in_priority_order_with_only_slug_and_display_name(self):
        self.write([
            _entry("gpt-test-b", "Test B", priority=5, base_instructions="SECRET-TEXT", identity="SECRET-ID"),
            _entry("gpt-test-hidden", "Hidden", visibility="hide", priority=1),
            _entry("gpt-test-a", "Test A", priority=2),
            _entry("gpt-test-none", "No priority"),
        ], identity="SECRET-TOP", etag="x")
        options, problem = self.read()
        self.assertEqual(problem, "")
        self.assertEqual(options, [
            {"value": "gpt-test-a", "label": "Test A"},
            {"value": "gpt-test-b", "label": "Test B"},
            {"value": "gpt-test-none", "label": "No priority"}])
        self.assertNotIn("SECRET", json.dumps(options))

    def test_a_display_name_that_is_empty_or_odd_falls_back_to_the_slug(self):
        self.write([_entry("gpt-test-a", ""), _entry("gpt-test-b", "line\nbreak"), _entry("gpt-test-c", "x" * 200),
                    _entry("gpt-test-d", 7)])
        options, _ = self.read()
        self.assertEqual([o["label"] for o in options], ["gpt-test-a", "gpt-test-b", "gpt-test-c", "gpt-test-d"])

    def test_slugs_with_unsafe_characters_are_skipped_and_duplicates_kept_once(self):
        bad = ["a b", "a;b", "a\nb", "<x>", "../etc", "-flag", "x" * 101, "", "gpt‮-x", "gpt-é", 7, None, ["a"]]
        self.write([_entry(s) for s in bad] + [_entry("gpt-test.1:beta/x_y"), _entry("gpt-test.1:beta/x_y")])
        options, problem = self.read()
        self.assertEqual(problem, "")
        self.assertEqual([o["value"] for o in options], ["gpt-test.1:beta/x_y"])

    def test_visibility_must_be_exactly_list(self):
        self.write([_entry("gpt-a", visibility="List"), _entry("gpt-b", visibility=True), _entry("gpt-c", visibility=None),
                    {"slug": "gpt-d", "display_name": "D"}, _entry("gpt-e")])
        self.assertEqual([o["value"] for o in self.read()[0]], ["gpt-e"])

    def test_priority_that_is_not_a_plain_number_sorts_last(self):
        self.write([_entry("gpt-a", priority="1"), _entry("gpt-b", priority=True), _entry("gpt-c", priority=3),
                    _entry("gpt-d", priority=1.5)])
        self.assertEqual([o["value"] for o in self.read()[0]], ["gpt-d", "gpt-c", "gpt-a", "gpt-b"])

    def test_a_priority_too_big_for_a_float_sorts_last_and_does_not_crash(self):
        self.cache.write_text('{"models": [{"slug": "gpt-a", "visibility": "list", "priority": ' + "9" * 400
                              + '}, {"slug": "gpt-b", "visibility": "list", "priority": 2}]}')
        self.assertEqual([o["value"] for o in self.read()[0]], ["gpt-b", "gpt-a"])

    def test_the_list_is_capped(self):
        self.write([_entry(f"gpt-test-{i}", priority=i) for i in range(model_options.MAX_CODEX_SCANNED + 50)])
        options, _ = self.read()
        self.assertEqual(len(options), model_options.MAX_CODEX_OPTIONS)
        self.assertEqual(options[0]["value"], "gpt-test-0")

    def test_a_missing_file_is_an_empty_list_with_a_reason(self):
        self.cache.unlink() if self.cache.exists() else None
        options, problem = self.read()
        self.assertEqual(options, [])
        self.assertTrue(problem)

    def test_no_codex_folder_at_all(self):
        (self.home / ".codex").rmdir()
        options, problem = self.read()
        self.assertEqual((options, bool(problem)), ([], True))

    def test_a_file_over_the_size_limit_is_refused_unread(self):
        self.cache.write_text('{"models": [], "pad": "' + "x" * (model_options.MAX_CODEX_BYTES + 10) + '"}')
        options, problem = self.read()
        self.assertEqual(options, [])
        self.assertTrue(problem)

    def test_broken_or_odd_json_gives_an_empty_list(self):
        for text in ["{", "", "[]", "null", '{"models": 7}', '{"models": {"a": 1}}',
                     '{"models": [], "models": []}', '{"models": [NaN]}', '{"models": [' * 40 + "]}" * 40,
                     "\xff\xfe"]:
            with self.subTest(text=text[:30]):
                self.cache.write_bytes(text.encode("latin-1", "replace") if text == "\xff\xfe" else text.encode())
                options, problem = self.read()
                self.assertEqual(options, [])
                self.assertTrue(problem)

    def test_rows_that_are_not_objects_are_skipped(self):
        self.write([7, "gpt-a", None, [], _entry("gpt-ok")])
        self.assertEqual([o["value"] for o in self.read()[0]], ["gpt-ok"])

    def test_a_symlinked_cache_file_is_not_followed_even_inside_home(self):
        real = self.home / "elsewhere.json"
        real.write_text(json.dumps({"models": [_entry("gpt-linked")]}))
        self.cache.symlink_to(real)
        options, problem = self.read()
        self.assertEqual((options, bool(problem)), ([], True))

    def test_a_symlinked_cache_file_pointing_outside_home_is_not_followed(self):
        outside = Path(self._tmp.name).resolve() / "outside.json"
        outside.write_text(json.dumps({"models": [_entry("gpt-outside")]}))
        self.cache.symlink_to(outside)
        options, problem = self.read()
        self.assertEqual((options, bool(problem)), ([], True))

    def test_a_codex_folder_that_is_a_symlink_out_of_home_is_not_followed(self):
        outside = Path(self._tmp.name).resolve() / "other-codex"
        outside.mkdir()
        (outside / "models_cache.json").write_text(json.dumps({"models": [_entry("gpt-outside")]}))
        (self.home / ".codex" / "models_cache.json").unlink() if self.cache.exists() else None
        (self.home / ".codex").rmdir()
        (self.home / ".codex").symlink_to(outside)
        options, problem = self.read()
        self.assertEqual((options, bool(problem)), ([], True))

    def test_a_codex_folder_that_is_a_symlink_inside_home_is_followed(self):
        inside = self.home / "dotfiles-codex"
        inside.mkdir()
        (inside / "models_cache.json").write_text(json.dumps({"models": [_entry("gpt-inside")]}))
        (self.home / ".codex").rmdir()
        (self.home / ".codex").symlink_to(inside)
        self.assertEqual([o["value"] for o in self.read()[0]], ["gpt-inside"])

    def test_a_fifo_is_not_opened_for_reading(self):
        os.mkfifo(self.cache)
        options, problem = self.read()
        self.assertEqual((options, bool(problem)), ([], True))


class UsageNamesTests(unittest.TestCase):
    def sessions(self):
        return [
            {"tool": "claude", "last_ts": "2026-10-20T00:00:00Z", "models": {"claude-opus-5-5": 4, "claude-sonnet-5": 1, "<synthetic>": 9, "gpt-x": 3}},
            {"tool": "claude", "last_ts": "2026-10-21T00:00:00Z", "models": {"claude-sonnet-5": 5, "claude-bad name": 2, "claude-haiku-5-5": 1}},
            {"tool": "codex", "last_ts": "2026-10-21T00:00:00Z", "models": {"gpt-test-a": 2, "gpt a": 7, "<x>": 4}},
            "junk", {"tool": "claude", "models": "nope"}, {"tool": "claude", "models": {"claude-x": "many", "claude-y": True}},
        ]

    def test_claude_gets_the_aliases_then_the_full_names_seen_by_use_count(self):
        out = model_options.build(Path("/nonexistent-home"), self.sessions())
        claude = out["claude"]
        self.assertEqual([o["value"] for o in claude["latest"]], ["fable", "opus", "sonnet", "haiku"])
        self.assertEqual([o["value"] for o in claude["observed"]], ["claude-sonnet-5", "claude-opus-5-5", "claude-haiku-5-5"])
        self.assertEqual(claude["listed"], [])

    def test_the_alias_list_is_a_constant_that_names_its_source(self):
        self.assertEqual(model_options.CLAUDE_ALIASES, ("fable", "opus", "sonnet", "haiku"))
        self.assertIn("claude --help", Path(model_options.__file__).read_text())

    def test_without_usage_data_only_the_aliases_are_listed(self):
        for sessions in (None, [], "x"):
            out = model_options.build(Path("/nonexistent-home"), sessions)
            self.assertEqual(out["claude"]["observed"], [])
            self.assertEqual(len(out["claude"]["latest"]), 4)

    def test_observed_names_are_capped_and_deduped(self):
        many = {f"claude-test-{i}": 100 - i for i in range(60)}
        out = model_options.build(Path("/nonexistent-home"), [{"tool": "claude", "models": many}, {"tool": "claude", "models": many}])
        self.assertEqual(len(out["claude"]["observed"]), model_options.MAX_OBSERVED)
        self.assertEqual(out["claude"]["observed"][0]["value"], "claude-test-0")

    def test_a_name_that_is_also_an_alias_is_not_listed_twice(self):
        out = model_options.build(Path("/nonexistent-home"), [{"tool": "claude", "models": {"claude-opus": 3}}])
        self.assertEqual([o["value"] for o in out["claude"]["observed"]], ["claude-opus"])

    def test_codex_observed_skips_what_the_cache_already_lists_and_unsafe_names(self):
        with tempfile.TemporaryDirectory(prefix="vbear-p31-") as tmp:
            home = Path(tmp).resolve()
            (home / ".codex").mkdir()
            (home / ".codex" / "models_cache.json").write_text(json.dumps({"models": [_entry("gpt-test-a")]}))
            out = model_options.build(home, self.sessions())
        self.assertEqual([o["value"] for o in out["codex"]["listed"]], ["gpt-test-a"])
        self.assertEqual(out["codex"]["observed"], [])
        out = model_options.build(Path("/nonexistent-home"), self.sessions())
        self.assertEqual([o["value"] for o in out["codex"]["observed"]], ["gpt-test-a"])
        self.assertTrue(out["codex"]["problem"])

    def test_agy_and_shared_get_no_list(self):
        out = model_options.build(Path("/nonexistent-home"), None)
        self.assertEqual(set(out), {"claude", "codex"})


if __name__ == "__main__":
    unittest.main()
