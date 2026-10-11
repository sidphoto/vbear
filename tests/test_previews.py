"""Server-side preview records (vbear/previews.py): one file each, 0600, five
minutes, one use, exactly their schema. A fake clock; no network, no daemon."""

import hashlib
import json
import os
import shutil
import stat
import tempfile
import threading
import unittest
import uuid
from pathlib import Path

from vbear import acceptance as acc
from vbear import previews as pv

FLOW = "flow-0123456789ab"
OTHER_FLOW = "flow-ffffffffffff"


def accept_fields(**over):
    f = {"text_version": acc.RISK_TEXT_VERSION, "codex_version": "0.160.0", "model": "gpt-6-luna",
         "executor_claude_version": "2.1.292", "executor_model": "claude-haiku-4-5-20251001",
         "executor_login_fingerprint": "a" * 64, "login_fingerprint": "b" * 64, "login_key_id": "c" * 16,
         "limits": dict(acc.DEFAULT_LIMITS)}
    f.update(over)
    return f


def dispatch_data(text="請完成工作", **over):
    try:
        digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
    except (UnicodeEncodeError, AttributeError):
        digest = "0" * 64                                      # a text that cannot be hashed is invalid anyway
    d = {"launch_id": "l-" + "0" * 16, "dispatch_id": str(uuid.uuid4()), "text": text, "text_sha256": digest}
    d.update(over)
    return d


class Clock:
    def __init__(self, t=1_791_000_000.0):
        self.t = t

    def __call__(self):
        return self.t


class Case(unittest.TestCase):
    def setUp(self):
        self.base = Path(os.path.realpath(tempfile.mkdtemp(prefix="vbpv-", dir="/tmp")))
        self.addCleanup(shutil.rmtree, self.base, True)
        os.chmod(self.base, 0o700)
        self.clock = Clock()
        self.store = pv.PreviewStore(self.base, clock=self.clock)

    @property
    def dir(self) -> Path:
        return self.base / pv.PREVIEWS_DIR

    def files(self):
        if not self.dir.exists():
            return []
        return sorted(p.name for p in self.dir.iterdir() if p.name != pv.LOCK_NAME)


class LifecycleTests(Case):
    def test_create_get_consume_for_both_kinds(self):
        for kind, data in (("acceptance", {"fields": accept_fields()}), ("dispatch", dispatch_data())):
            with self.subTest(kind=kind):
                rec = self.store.create(kind, FLOW, data)
                self.assertRegex(rec["preview_id"], r"^[0-9a-f]{32}$")
                self.assertEqual((rec["kind"], rec["flow_id"], rec["consumed"], rec["expires"] - rec["created"]),
                                 (kind, FLOW, False, 300.0))
                path = self.dir / f"{rec['preview_id']}.json"
                self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)
                self.assertEqual(json.loads(path.read_text())["data"], data)
                self.assertEqual(self.store.get(rec["preview_id"], kind=kind, flow_id=FLOW)["data"], data)
                done = self.store.consume(rec["preview_id"], kind=kind, flow_id=FLOW)
                self.assertTrue(done["consumed"])
                self.assertTrue(json.loads(path.read_text())["consumed"])             # on disk before it returned
        self.assertEqual(stat.S_IMODE(self.dir.stat().st_mode), 0o700)

    def test_a_record_is_good_for_one_use(self):
        rec = self.store.create("dispatch", FLOW, dispatch_data())
        self.store.consume(rec["preview_id"], kind="dispatch", flow_id=FLOW)
        for op in (lambda: self.store.consume(rec["preview_id"], kind="dispatch", flow_id=FLOW),
                   lambda: self.store.get(rec["preview_id"], kind="dispatch", flow_id=FLOW)):
            with self.assertRaises(pv.PreviewError) as cm:
                op()
            self.assertEqual((cm.exception.code, cm.exception.status), ("consumed", 409))

    def test_a_failed_check_voids_the_record_too(self):
        rec = self.store.create("acceptance", FLOW, {"fields": accept_fields()})

        def check(r):
            raise pv.PreviewError("conflict", "登入指紋已改變，請重新預覽")
        with self.assertRaises(pv.PreviewError) as cm:
            self.store.consume(rec["preview_id"], kind="acceptance", flow_id=FLOW, check=check)
        self.assertEqual((cm.exception.code, cm.exception.status), ("conflict", 409))
        with self.assertRaises(pv.PreviewError) as cm:
            self.store.consume(rec["preview_id"], kind="acceptance", flow_id=FLOW)
        self.assertEqual(cm.exception.code, "consumed")                                  # cannot be used again

    def test_the_check_sees_the_stored_record(self):
        rec = self.store.create("dispatch", FLOW, dispatch_data("原文"))
        seen = []
        self.store.consume(rec["preview_id"], kind="dispatch", flow_id=FLOW, check=seen.append)
        self.assertEqual(seen[0]["data"]["text"], "原文")

    def test_another_flow_or_kind_is_a_mismatch_and_does_not_use_it_up(self):
        rec = self.store.create("dispatch", FLOW, dispatch_data())
        for kind, flow in (("dispatch", OTHER_FLOW), ("acceptance", FLOW)):
            with self.assertRaises(pv.PreviewError) as cm:
                self.store.consume(rec["preview_id"], kind=kind, flow_id=flow)
            self.assertEqual(cm.exception.code, "mismatch")
        self.assertFalse(self.store.get(rec["preview_id"], kind="dispatch", flow_id=FLOW)["consumed"])

    def test_unknown_and_malformed_ids(self):
        with self.assertRaises(pv.PreviewError) as cm:
            self.store.consume("0" * 32, kind="dispatch", flow_id=FLOW)
        self.assertEqual((cm.exception.code, cm.exception.status), ("not_found", 404))
        for bad in ("", "x", "0" * 31, "0" * 33, "G" * 32, "../" + "0" * 29, None, 5, "0" * 32 + "\n"):
            with self.subTest(id=bad), self.assertRaises(pv.PreviewError) as cm:
                self.store.get(bad, kind="dispatch", flow_id=FLOW)
            self.assertEqual((cm.exception.code, cm.exception.status), ("invalid", 400))

    def test_only_one_of_two_racing_approvals_wins(self):
        rec = self.store.create("dispatch", FLOW, dispatch_data())
        results = []
        barrier = threading.Barrier(8)

        def go():
            barrier.wait()
            try:
                self.store.consume(rec["preview_id"], kind="dispatch", flow_id=FLOW)
                results.append("ok")
            except pv.PreviewError as exc:
                results.append(exc.code)
        threads = [threading.Thread(target=go) for _ in range(8)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        self.assertEqual(sorted(results), ["consumed"] * 7 + ["ok"])


class TimeTests(Case):
    def test_five_minutes_exactly(self):
        rec = self.store.create("dispatch", FLOW, dispatch_data())
        self.clock.t += 299.9
        self.assertEqual(self.store.get(rec["preview_id"], kind="dispatch", flow_id=FLOW)["preview_id"],
                         rec["preview_id"])
        self.clock.t += 0.1                                                           # 300.0: expired (boundary)
        with self.assertRaises(pv.PreviewError) as cm:
            self.store.consume(rec["preview_id"], kind="dispatch", flow_id=FLOW)
        self.assertEqual((cm.exception.code, cm.exception.status), ("expired", 409))
        self.assertEqual(self.files(), [])                                            # and removed

    def test_a_clock_set_back_voids_instead_of_extending(self):
        rec = self.store.create("dispatch", FLOW, dispatch_data())
        self.clock.t -= 3600
        with self.assertRaises(pv.PreviewError) as cm:
            self.store.get(rec["preview_id"], kind="dispatch", flow_id=FLOW)
        self.assertEqual(cm.exception.code, "expired")
        rec = self.store.create("dispatch", FLOW, dispatch_data())
        self.clock.t -= 30                                                            # within the slack: still fine
        self.store.get(rec["preview_id"], kind="dispatch", flow_id=FLOW)

    def test_a_record_cannot_be_given_a_longer_life(self):
        rec = self.store.create("dispatch", FLOW, dispatch_data())
        path = self.dir / f"{rec['preview_id']}.json"
        body = json.loads(path.read_text())
        body["expires"] += 86400
        path.write_text(json.dumps(body))
        os.chmod(path, 0o600)
        with self.assertRaises(pv.PreviewError) as cm:
            self.store.get(rec["preview_id"], kind="dispatch", flow_id=FLOW)
        self.assertEqual(cm.exception.code, "invalid")


class CapacityTests(Case):
    def test_200_live_records_and_no_more(self):
        for _ in range(pv.MAX_PREVIEWS):
            self.store.create("dispatch", FLOW, dispatch_data())
        with self.assertRaises(pv.PreviewError) as cm:
            self.store.create("dispatch", FLOW, dispatch_data())
        self.assertEqual((cm.exception.code, cm.exception.status), ("full", 429))
        self.assertEqual(len(self.files()), pv.MAX_PREVIEWS)
        self.clock.t += 301                                                           # all expired: room again
        self.store.create("dispatch", FLOW, dispatch_data())
        self.assertEqual(len(self.files()), 1)

    def test_a_record_over_128_kib_is_refused(self):
        big = dispatch_data("x" * (pv.MAX_TEXT_BYTES + 1))
        with self.assertRaises(pv.PreviewError) as cm:
            self.store.create("dispatch", FLOW, big)
        self.assertEqual(cm.exception.code, "invalid")
        ok = dispatch_data("x" * pv.MAX_TEXT_BYTES)
        self.assertTrue(self.store.create("dispatch", FLOW, ok)["preview_id"])
        self.assertLess((self.dir / self.files()[0]).stat().st_size, pv.MAX_BYTES)

    def test_a_text_with_many_escapes_cannot_pass_the_file_limit(self):
        # 64 KiB of characters that JSON writes as 6 bytes each
        text = "\u0001" * 10000 + "a" * 100
        data = dispatch_data(text)
        rec = self.store.create("dispatch", FLOW, data)
        self.assertLess((self.dir / f"{rec['preview_id']}.json").stat().st_size, pv.MAX_BYTES)


class SchemaTests(Case):
    def bad(self, kind, data, flow=FLOW):
        with self.assertRaises(pv.PreviewError) as cm:
            self.store.create(kind, flow, data)
        self.assertEqual(cm.exception.code, "invalid")
        self.assertEqual(self.files(), [])

    def test_kind_flow_and_data_are_exact(self):
        self.bad("nothing", {"fields": accept_fields()})
        self.bad("acceptance", {"fields": accept_fields()}, flow="flow-x")
        self.bad("acceptance", {"fields": accept_fields(), "extra": 1})
        self.bad("acceptance", {"fields": accept_fields(login_key_id="zz")})
        self.bad("acceptance", {"fields": {k: v for k, v in accept_fields().items() if k != "limits"}})
        self.bad("acceptance", {"fields": accept_fields(limits={**acc.DEFAULT_LIMITS, "max_reviews": 99})})
        self.bad("acceptance", {})
        self.bad("dispatch", {**dispatch_data(), "extra": 1})
        self.bad("dispatch", dispatch_data(launch_id="l-xyz"))
        self.bad("dispatch", dispatch_data(dispatch_id="not-a-uuid"))
        self.bad("dispatch", dispatch_data(text_sha256="0" * 64))                    # does not match the text
        self.bad("dispatch", dispatch_data(text=""))
        self.bad("dispatch", dispatch_data(text="\ud800"))                           # a lone surrogate
        self.bad("dispatch", dispatch_data(text=5))

    def test_files_that_are_not_exactly_a_record_are_never_used_and_are_removed(self):
        def mutate(change):
            rec = self.store.create("dispatch", FLOW, dispatch_data())
            path = self.dir / f"{rec['preview_id']}.json"
            body = json.loads(path.read_text())
            change(body, path)
            return rec["preview_id"], path, body
        cases = {
            "not json": lambda b, p: p.write_text("{"),
            "an extra key": lambda b, p: p.write_text(json.dumps({**b, "x": 1})),
            "a missing key": lambda b, p: p.write_text(json.dumps({k: v for k, v in b.items() if k != "consumed"})),
            "another id inside": lambda b, p: p.write_text(json.dumps({**b, "preview_id": "1" * 32})),
            "consumed not a boolean": lambda b, p: p.write_text(json.dumps({**b, "consumed": "no"})),
            "version 2": lambda b, p: p.write_text(json.dumps({**b, "v": 2})),
            "data tampered": lambda b, p: p.write_text(json.dumps({**b, "data": {**b["data"], "text": "改過"}})),
            "duplicate key": lambda b, p: p.write_text('{"v":1,"v":1}'),
            "an array": lambda b, p: p.write_text("[]"),
            "a group-readable mode": lambda b, p: os.chmod(p, 0o640),
        }
        for name, change in cases.items():
            with self.subTest(case=name):
                pid, path, _ = mutate(change)
                if name != "a group-readable mode":
                    os.chmod(path, 0o600)
                with self.assertRaises(pv.PreviewError) as cm:
                    self.store.consume(pid, kind="dispatch", flow_id=FLOW)
                self.assertEqual(cm.exception.code, "invalid")
                self.assertFalse(path.exists())                                       # and gone

    def test_a_symlink_is_not_followed(self):
        rec = self.store.create("dispatch", FLOW, dispatch_data())
        path = self.dir / f"{rec['preview_id']}.json"
        target = self.base / "elsewhere.json"
        shutil.move(path, target)
        os.symlink(target, path)
        with self.assertRaises(pv.PreviewError) as cm:
            self.store.get(rec["preview_id"], kind="dispatch", flow_id=FLOW)
        self.assertEqual(cm.exception.code, "invalid")
        self.assertTrue(target.exists())                                              # the target is not touched


class DirectoryTests(Case):
    def test_leftovers_and_damaged_files_go_with_the_expired_and_other_files_stay(self):
        rec = self.store.create("dispatch", FLOW, dispatch_data())
        (self.dir / f".{'1' * 32}.tmp").write_text("partial")
        (self.dir / f"{'2' * 32}.json").write_text("junk")
        (self.dir / "notes.txt").write_text("someone else's")
        self.assertEqual(self.store.purge(), 1)
        self.assertEqual(self.files(), [f"{rec['preview_id']}.json", "notes.txt"])

    def test_the_directory_must_be_ours_and_private(self):
        first = self.store.create("dispatch", FLOW, dispatch_data())
        os.chmod(self.dir, 0o755)
        with self.assertRaises(pv.PreviewError) as cm:
            self.store.create("dispatch", FLOW, dispatch_data())
        self.assertEqual((cm.exception.code, cm.exception.status), ("unavailable", 500))
        os.chmod(self.dir, 0o700)
        moved = self.base / "real-previews"
        os.rename(self.dir, moved)
        os.symlink(moved, self.dir)
        with self.assertRaises(pv.PreviewError) as cm:
            self.store.create("dispatch", FLOW, dispatch_data())
        self.assertEqual(cm.exception.code, "unavailable")
        self.assertEqual(sorted(os.listdir(moved)), [".lock", f"{first['preview_id']}.json"])   # nothing went through the link

    def test_a_missing_state_directory_is_unavailable_not_a_crash(self):
        store = pv.PreviewStore(self.base / "nope", clock=self.clock)
        with self.assertRaises(pv.PreviewError) as cm:
            store.create("dispatch", FLOW, dispatch_data())
        self.assertEqual(cm.exception.code, "unavailable")
        with self.assertRaises(pv.PreviewError) as cm:
            store.get("0" * 32, kind="dispatch", flow_id=FLOW)
        self.assertIn(cm.exception.code, ("unavailable", "not_found"))

    def test_nothing_is_created_by_a_read(self):
        with self.assertRaises(pv.PreviewError):
            self.store.get("0" * 32, kind="dispatch", flow_id=FLOW)
        self.assertFalse(self.dir.exists())
        self.assertEqual(self.store.purge(), 0)
        self.assertFalse(self.dir.exists())

    def test_void_removes_and_is_quiet_about_the_rest(self):
        rec = self.store.create("dispatch", FLOW, dispatch_data())
        self.store.void(rec["preview_id"])
        self.store.void(rec["preview_id"])
        self.store.void("not an id")
        self.assertEqual(self.files(), [])


if __name__ == "__main__":
    unittest.main()
