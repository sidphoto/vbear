"""The risk acceptance (design 10): a server-held preview, then a confirmation
that carries only its id (vbear/risk_acceptance.py). A fake host stands in for
the machine: no binary is run, no real login file is read."""

import json
import os
import re
import shutil
import stat
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from vbear import acceptance as acc
from vbear import flows, login_identity, previews as pv, risk_acceptance as ra, risk_text, tasks
from vbear.runtime import codex_constants as cc

CLAUDE_JSON = {"oauthAccount": {"accountUuid": "11111111-2222-3333-4444-555555555555",
                                "organizationUuid": "66666666-7777-8888-9999-000000000000"}}
AUTH = {"auth_mode": "chatgpt", "tokens": {"account_id": "acct-secret-0001"}}


class FakeHost(ra.Host):
    def __init__(self, root: Path):
        self.root = root
        self.claude = "2.1.292"
        self.codex = "0.160.0"
        self.claude_why = self.codex_why = ""

    def claude_version(self):
        return (self.claude, "") if self.claude else (None, self.claude_why or "沒有")

    def claude_json(self):
        return self.root / "claude.json"

    def codex_version(self):
        return (self.codex, "") if self.codex else (None, self.codex_why or "沒有")

    def codex_binary_path(self, version):
        return "/pinned/codex"


def roles(executor="anthropic", reviewers=("openai",)):
    return {"planner": {"name": "p", "family": "anthropic"}, "executor": {"name": "e", "family": executor},
            "reviewers": [{"name": f"r{i}", "family": f} for i, f in enumerate(reviewers)]}


class Case(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(os.path.realpath(tempfile.mkdtemp(prefix="vbra-", dir="/tmp")))
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.state = self.tmp / "st"
        self.state.mkdir(mode=0o700)
        env = mock.patch.dict(os.environ, {"VBEAR_HOME": str(self.state)})
        env.start()
        self.addCleanup(env.stop)
        self.host = FakeHost(self.tmp)
        self.write_claude()
        self.write_codex_login()
        self.store = pv.PreviewStore(self.state)
        verified = mock.patch("vbear.runtime.cli_versions.stream_verified_versions", return_value=("2.1.292",))
        verified.start()
        self.addCleanup(verified.stop)
        self.tid = tasks.save_task(None, {"title": "t"})["id"]
        self.fid = flows.create_flow({"task_id": self.tid, "roles": roles()}, lambda t: True)["id"]

    def write_claude(self, uuid="11111111-2222-3333-4444-555555555555"):
        (self.tmp / "claude.json").write_text(json.dumps({"oauthAccount": {
            "accountUuid": uuid, "organizationUuid": CLAUDE_JSON["oauthAccount"]["organizationUuid"]}}))

    def write_codex_login(self, account="acct-secret-0001"):
        home = self.state / "codex-home"
        home.mkdir(mode=0o700, exist_ok=True)
        (home / "auth.json").write_text(json.dumps({"auth_mode": "chatgpt", "tokens": {"account_id": account}}))
        os.chmod(home / "auth.json", 0o600)

    def preview(self, body=None, flow=None):
        return ra.preview(flow or self.fid, body, store=self.store, host=self.host)

    _DEFAULT = object()

    def confirm(self, preview_id, flow=None, body=_DEFAULT):
        return ra.confirm(flow or self.fid, {"preview_id": preview_id} if body is self._DEFAULT else body,
                          store=self.store, host=self.host)

    def error(self, fn, *a, **kw):
        with self.assertRaises(ra.AcceptanceError) as cm:
            fn(*a, **kw)
        return cm.exception

    def events(self):
        return [e for e in flows.get_flow(self.fid)["events"] if e["kind"] == "risk_acknowledged"]


class PreviewTests(Case):
    def test_the_preview_shows_what_will_be_recorded_and_hides_the_fingerprints(self):
        r = self.preview()
        v = r["values"]
        self.assertEqual((v["text_version"], v["codex_version"], v["review_model"], v["executor_claude_version"],
                          v["executor_model"]), (acc.RISK_TEXT_VERSION, "0.160.0", "gpt-6-luna", "2.1.292",
                                                  ra.DEFAULT_EXECUTOR_MODEL))
        key = login_identity.load_login_key(self.state)
        expect_claude = login_identity.claude_login_fingerprint(self.tmp / "claude.json", key).hmac
        expect_codex = login_identity.codex_login_fingerprint(self.state / "codex-home", key).hmac
        self.assertEqual((v["executor_account"], v["review_account"]), (expect_claude[:16], expect_codex[:16]))
        self.assertEqual(v["login_key_id"], key.key_id)
        text = json.dumps(r, ensure_ascii=False)
        self.assertNotRegex(text, r"[0-9a-f]{64}")                           # no whole fingerprint leaves the server
        for secret in ("acct-secret-0001", "11111111-2222", expect_claude, expect_codex):
            self.assertNotIn(secret, text)
        self.assertEqual([x["name"] for x in v["limits"]], list(acc.LIMITS))
        for x in v["limits"]:
            self.assertEqual((x["value"], x["default"], x["cap"]),
                             (acc.DEFAULT_LIMITS[x["name"]], acc.LIMITS[x["name"]][0], acc.LIMITS[x["name"]][1]))
        self.assertEqual(r["ttl_s"], 300.0)
        rec = self.store.get(r["preview_id"], kind="acceptance", flow_id=self.fid)
        self.assertEqual(rec["data"]["fields"]["login_fingerprint"], expect_codex)       # the record has the whole values

    def test_the_risk_text_is_the_versioned_text_in_both_languages(self):
        r = self.preview()
        for lang in ("zh", "en"):
            t = r["risk_text"][lang]
            self.assertEqual((t["version"], t["lang"]), (acc.RISK_TEXT_VERSION, lang))
            self.assertEqual([i["id"] for i in t["items"]], ["tools", "limits", "managed"])
            self.assertEqual(t, risk_text.render(lang))
        self.assertIn("SUBAGENT_ACTIVITY", r["risk_text"]["zh"]["items"][0]["body"])
        self.assertIn("explicitRequestOnly", r["risk_text"]["en"]["items"][0]["body"])

    def test_limits_start_from_the_defaults_and_follow_the_choice_within_the_caps(self):
        r = self.preview({"limits": {"max_reviews": 3, "executor_budget_usd": 7.5}, "executor_model": "claude-sonnet-5-5"})
        by = {x["name"]: x["value"] for x in r["values"]["limits"]}
        self.assertEqual((by["max_reviews"], by["executor_budget_usd"], by["max_dispatches"]), (3, 7.5, 20))
        self.assertEqual(r["values"]["executor_model"], "claude-sonnet-5-5")
        for bad in ({"max_reviews": 0}, {"max_reviews": 11}, {"max_reviews": True}, {"max_reviews": 2.5},
                    {"max_reviews": "3"}, {"executor_budget_usd": 0}, {"executor_budget_usd": 100.01},
                    {"executor_budget_usd": 1.005}, {"executor_budget_usd": float("nan")}, {"nope": 1}, []):
            with self.subTest(limits=bad):
                e = self.error(self.preview, {"limits": bad})
                self.assertEqual((e.status, e.code), (400, "bad_limits"))

    def test_bad_requests(self):
        for body in ({"x": 1}, {"executor_model": "haiku"}, {"executor_model": 5}, {"executor_model": "claude-"},
                     {"review_model": "gpt-other"}, {"review_model": None}, "text", [1]):
            with self.subTest(body=body):
                e = self.error(self.preview, body)
                self.assertEqual(e.status, 400)
        self.assertEqual(self.error(self.preview, None and {}, flow="flow-ffffffffffff").status, 404)

    def test_nothing_is_recorded_by_a_preview(self):
        self.preview()
        self.assertEqual(self.events(), [])

    def test_the_family_rule(self):
        flows.set_roles(self.fid, {"roles": roles(executor="openai")})
        self.assertEqual(self.error(self.preview).code, "family")
        flows.set_roles(self.fid, {"roles": roles(reviewers=("anthropic",))})
        self.assertEqual(self.error(self.preview).code, "family")

    def test_versions_that_are_not_verified_cannot_be_accepted(self):
        self.host.claude = "9.9.9"
        self.assertEqual(self.error(self.preview).code, "claude_unverified")
        self.host.claude = None
        self.assertEqual(self.error(self.preview).code, "claude_version")
        self.host.claude = "2.1.292"
        self.host.codex = "0.159.2"
        self.assertEqual(self.error(self.preview).code, "codex_unverified")
        self.host.codex = None
        self.assertEqual(self.error(self.preview).code, "codex_version")

    def test_a_missing_login_says_how_to_log_in_and_where(self):
        os.unlink(self.state / "codex-home" / "auth.json")
        e = self.error(self.preview)
        self.assertEqual((e.status, e.code), (409, "needs_login"))
        self.assertEqual(e.extra["login_command"],
                         f"CODEX_HOME={self.state / 'codex-home'} /pinned/codex login -c cli_auth_credentials_store=file")
        shutil.rmtree(self.state / "codex-home")
        self.assertEqual(self.error(self.preview).code, "needs_login")
        self.write_codex_login()
        os.chmod(self.state / "codex-home", 0o755)                             # not private: refused, with the same help
        self.assertEqual(self.error(self.preview).code, "needs_login")
        os.chmod(self.state / "codex-home", 0o700)
        (self.tmp / "claude.json").write_text("{}")
        self.assertEqual(self.error(self.preview).code, "no_claude_login")

    def test_the_key_is_made_when_missing_and_only_then(self):
        path = login_identity.key_path(self.state)
        self.assertFalse(path.exists())
        self.preview()
        self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)
        before = path.read_bytes()
        self.preview()
        self.assertEqual(path.read_bytes(), before)                            # a good key is never replaced

    def test_the_preview_store_being_full_is_reported(self):
        with mock.patch.object(pv, "MAX_PREVIEWS", 1):
            self.preview()
            e = self.error(self.preview)
            self.assertEqual((e.status, e.code), (429, "full"))


class ConfirmTests(Case):
    def test_confirm_records_the_stored_values_as_a_console_event(self):
        r = self.preview({"limits": {"max_dispatches": 5}})
        rec_fields = self.store.get(r["preview_id"], kind="acceptance", flow_id=self.fid)["data"]["fields"]
        flow = self.confirm(r["preview_id"])
        [event] = self.events()
        self.assertEqual((event["source"], event["note"], event["kind"]), ("console", "", "risk_acknowledged"))
        self.assertEqual(acc.acceptance_fields(event), rec_fields)
        self.assertEqual(event["limits"]["max_dispatches"], 5)
        self.assertEqual(flow["events"][-1]["seq"], event["seq"])
        key = login_identity.load_login_key(self.state)
        self.assertTrue(acc.is_valid_now(event, key.key_id))
        self.assertEqual(ra.status(flows.get_flow(self.fid))["state"], "valid")

    def test_only_the_id_is_accepted_nothing_the_browser_sends_is_recorded(self):
        r = self.preview()
        for body in ({}, {"preview_id": r["preview_id"], "limits": {"max_reviews": 10}},
                     {"preview_id": r["preview_id"], "codex_version": "0.1.0"}, {"preview_id": 5}, None, "x",
                     [r["preview_id"]], {"preview_id": r["preview_id"] + "x"}):
            with self.subTest(body=body):
                e = self.error(self.confirm, r["preview_id"], body=body)
                self.assertEqual(e.status, 400)
        self.assertEqual(self.events(), [])
        self.confirm(r["preview_id"])                                          # the preview was not spent by those
        self.assertEqual(len(self.events()), 1)

    def test_a_preview_is_good_for_one_confirmation(self):
        r = self.preview()
        self.confirm(r["preview_id"])
        e = self.error(self.confirm, r["preview_id"])
        self.assertEqual((e.status, e.code), (409, "consumed"))
        self.assertEqual(len(self.events()), 1)

    def test_unknown_expired_and_other_flows_previews(self):
        e = self.error(self.confirm, "0" * 32)
        self.assertEqual((e.status, e.code), (404, "not_found"))
        r = self.preview()
        task2 = tasks.save_task(None, {"title": "t2"})["id"]
        other = flows.create_flow({"task_id": task2, "roles": roles()}, lambda t: True)["id"]
        e = self.error(self.confirm, r["preview_id"], flow=other)
        self.assertEqual((e.status, e.code), (409, "mismatch"))
        self.assertEqual(self.events(), [])
        clock = mock.patch.object(self.store, "_clock", return_value=r["expires_at"] + 1)
        with clock:
            e = self.error(self.confirm, r["preview_id"])
        self.assertEqual((e.status, e.code), (409, "expired"))

    def drift(self, change, name):
        r = self.preview()
        change()
        e = self.error(self.confirm, r["preview_id"])
        self.assertEqual((e.status, e.code), (409, "conflict"), name)
        self.assertEqual(self.events(), [], name)
        again = self.error(self.confirm, r["preview_id"])
        self.assertEqual(again.code, "consumed", name)                           # the preview is void
        return e

    def test_anything_that_changed_since_the_preview_is_a_409(self):
        self.drift(lambda: self.write_codex_login("acct-secret-OTHER"), "the review account")
        self.drift(lambda: self.write_claude("99999999-2222-3333-4444-555555555555"), "the executor account")
        with mock.patch("vbear.runtime.cli_versions.stream_verified_versions", return_value=("2.1.292", "2.1.299")):
            self.drift(lambda: setattr(self.host, "claude", "2.1.299"), "claude version")
        self.host.claude = "2.1.292"

    def test_a_changed_codex_version_key_text_and_flow_are_each_a_409(self):
        with mock.patch.object(cc, "VERIFIED_VERSIONS", ("0.160.0", "0.161.0")), \
                mock.patch.dict(cc.VERSIONS, {"0.161.0": cc.VERSIONS["0.160.0"]}, clear=False):
            self.drift(lambda: setattr(self.host, "codex", "0.161.0"), "codex version")
            self.host.codex = "0.160.0"
        e = self.drift(lambda: os.unlink(login_identity.key_path(self.state)), "the key")
        self.assertIn("登入指紋金鑰", str(e))
        self.preview()                                                          # (a new key is made by this preview)
        with mock.patch.object(acc, "RISK_TEXT_VERSION", "2099-01-01.1"):
            r = self.preview()
        self.assertEqual(r["values"]["text_version"], "2099-01-01.1")
        e = self.error(self.confirm, r["preview_id"])                           # the text is the real one again
        self.assertEqual(e.code, "conflict")
        self.assertIn("text_version", str(e))
        self.drift(lambda: flows.set_roles(self.fid, {"roles": roles(executor="openai")}), "the families")

    def test_a_preview_whose_facts_come_back_the_same_still_confirms(self):
        r = self.preview()
        self.write_codex_login("acct-secret-0001")                              # rewritten, same account
        self.write_claude()
        self.confirm(r["preview_id"])
        self.assertEqual(len(self.events()), 1)

    def test_a_flow_that_vanished_is_a_404_and_the_event_limit_a_400(self):
        r = self.preview()
        self.assertEqual(self.error(self.confirm, r["preview_id"], flow="flow-ffffffffffff").status, 404)
        with mock.patch.object(flows, "MAX_EVENTS", 0):
            e = self.error(self.confirm, r["preview_id"])
        self.assertEqual(e.status, 400)
        self.assertEqual(self.events(), [])

    def test_the_manual_event_route_still_cannot_write_an_acceptance(self):
        with self.assertRaises(ValueError):
            flows.append_event(self.fid, {"kind": "risk_acknowledged"})
        with self.assertRaises(ValueError):
            flows.append_risk_acknowledged(self.fid, {"text_version": "x"})


class StatusTests(Case):
    def test_none_valid_and_stale(self):
        flow = lambda: flows.get_flow(self.fid)
        self.assertEqual(ra.status(flow())["state"], "none")
        self.confirm(self.preview()["preview_id"])
        s = ra.status(flow())
        self.assertEqual(s["state"], "valid")
        self.assertEqual(s["values"]["codex_version"], "0.160.0")
        self.assertNotRegex(json.dumps(s), r"[0-9a-f]{64}")
        with mock.patch.object(acc, "RISK_TEXT_VERSION", "2099-01-01.1"):
            s = ra.status(flow())
        self.assertEqual((s["state"], "風險文字已改版" in s["reason"]), ("stale", True))
        os.unlink(login_identity.key_path(self.state))
        s = ra.status(flow())
        self.assertEqual(s["state"], "stale")
        self.assertIn("金鑰", s["reason"])
        login_identity.create_login_key(self.state, valid_acceptances=0)         # another key: the old record's id differs
        self.assertIn("金鑰已更換", ra.status(flow())["reason"])

    def test_the_newest_acceptance_counts(self):
        self.confirm(self.preview({"limits": {"max_reviews": 2}})["preview_id"])
        self.confirm(self.preview({"limits": {"max_reviews": 4}})["preview_id"])
        limits = {x["name"]: x["value"] for x in ra.status(flows.get_flow(self.fid))["values"]["limits"]}
        self.assertEqual(limits["max_reviews"], 4)


if __name__ == "__main__":
    unittest.main()
