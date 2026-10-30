"""P35-4: a staffing meeting from the preview to the chairman's adoption, over a real loopback server with a fake call: no
CLI runs, nothing leaves the machine, and every card, skill and task card is fictional. The steps are the requests the
adoption list on the page sends, in its fixed order (啟用 → 建新卡 → 插技能 → 帶到隊伍 → 記下), each to an endpoint that
already exists; flows.json is not touched until the team is saved."""
import json
import os
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from decimal import Decimal
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest import mock

from vbear import agent_profiles as ap, config as cfg, flows, meeting_runner as mr, server, staffing as st, staffing_runner as sr
from vbear import tasks
from vbear.index import Store

VERSION = "2.1.296"
EVIDENCE = {"cli_version": VERSION, "model_reported": "m", "tools_reported": ["StructuredOutput"], "mcp_servers_reported": [],
            "exit_code": 0, "duration_ms": 1}


def skill(sid, name, tool, cats):
    return {"skill_id": sid, "name": name, "invoke_name": name, "tool": tool, "read_by": [], "scope": "user",
            "activation": "active", "mtime": 1, "excerpt": "A fictional skill.", "description": "A fictional skill.", "categories": cats}


class AdoptionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="vbear-staffing-adopt-test-")
        self.addCleanup(self.tmp.cleanup)
        home = Path(self.tmp.name) / "home"
        home.mkdir()
        patch = mock.patch.dict(os.environ, {"HOME": str(home), "VBEAR_HOME": str(home / ".vbear"), "VBEAR_RUNTIME_AUTOSTART": "0"})
        patch.start()
        self.addCleanup(patch.stop)
        skills = [skill("s-front", "網站前端（虛構）", "claude", ["frontend"]), skill("s-check", "測試檢查（虛構）", "shared", ["quality"])]
        self.console = c = server.Console.__new__(server.Console)
        c.lock = threading.Lock()
        c.auth_token = "synthetic-test-token"
        c.store = Store()
        c.store._static = {"skills": skills, "roles": []}
        c.store.set_conf(cfg.load())
        c.meetings = mr.MeetingRunner(provider=lambda engine: ("unused", VERSION), call=self.answer)
        c.staffing = sr.StaffingRunner(provider=lambda engine: ("unused", VERSION), call=self.answer)
        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), None)
        c.port = self.httpd.server_address[1]
        self.httpd.RequestHandlerClass = server.make_handler(c)
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()
        self.addCleanup(self.httpd.server_close)
        self.addCleanup(self.httpd.shutdown)
        self.addCleanup(c.staffing.wait, 5)

        def card(name, position, tool="claude", **over):
            return ap.save_profile(None, {"name": name, "position": position, "model": {"tool": tool}, **over})["id"]
        self.ceo, self.pm, self.legal = card("虛構CEO", "planner"), card("虛構PM", "pm"), card("虛構法務", "legal", "agy")
        self.eng, self.rev = card("虛構工程師", "executor", equipped_skill_ids=["s-front"]), card("虛構審查", "reviewer", "codex")
        self.art = card("虛構藝術（停用）", "art", enabled=False)
        self.task_id = tasks.save_task(None, {"title": "官網改版（虛構）", "goal": "改首頁並確認圖片授權", "scope": ["前端頁面"]})["id"]

    def answer(self, spec, cancel):
        if spec.kind != "proposal":
            out = {"summary": "需要前端與法務（虛構）", "needs": [], "recommend": [], "skills": [], "skill_gaps": [], "risks": []}
            return mr.CallResult(out, dict(EVIDENCE), Decimal("0.01"))
        sent = st.load(st.record_ids()[0])["sent"]   # the aliases the meeting was given
        a = {c["profile_id"]: c["alias"] for c in sent["cards"]}
        s = {x["skill_id"]: x["alias"] for x in sent["skills"]}
        place = lambda slot, pid, skills=(): {"slot": slot, "pick": "existing", "card": a[pid], "new_ref": "", "reason": "合適（虛構）",
                                              "skills": [{"skill": s[k], "why": "要用到"} for k in skills]}
        out = {"summary": "照發言組隊（虛構）",
               "team": [place("planner", self.ceo), place("executor", self.eng, ("s-front", "s-check")), place("reviewer1", self.rev)],
               "staff": [{"position": "legal", "pick": "new", "card": "", "new_ref": "N1", "reason": "沒有 Claude 的法務", "skills": []},
                         {"position": "art", "pick": "existing", "card": a[self.art], "new_ref": "", "reason": "要畫圖", "skills": []}],
               "new_cards": [{"ref": "N1", "position": "legal", "tool": "claude", "model_alias": "sonnet", "name": "虛構法務新卡",
                              "reason": "沒有 Claude 的法務", "skills": [{"skill": s["s-check"], "why": "要會檢查"}]}],
               "skill_gaps": [], "risks": [], "questions_for_chairman": [], "opinions_used": []}
        return mr.CallResult(out, dict(EVIDENCE), Decimal("0.05"))

    def call(self, path, method="GET", body=None):
        hdr = {"Authorization": "Bearer synthetic-test-token", "X-VBear": "1",
               "Origin": f"http://127.0.0.1:{self.console.port}", "Content-Type": "application/json"}
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(f"http://127.0.0.1:{self.console.port}" + path, data=data, method=method, headers=hdr)
        try:
            with urllib.request.urlopen(req, timeout=10) as response:
                return response.status, json.loads(response.read())
        except urllib.error.HTTPError as exc:
            with exc:
                return exc.code, json.loads(exc.read() or b"{}")

    def ok(self, path, method="GET", body=None, status=200):
        got, out = self.call(path, method, body)
        self.assertEqual(got, status, out)
        return out

    def flows_bytes(self):
        path = flows.store.path()
        return path.read_bytes() if path.exists() else None

    def card(self, pid):
        return next(p for p in self.ok("/api/agent-profiles")["profiles"] if p["id"] == pid)

    def test_from_the_meeting_to_the_adoption_flows_json_waits_for_the_team(self):
        before = self.flows_bytes()
        # the meeting
        preview = self.ok("/api/staffing/preview", "POST", {"task_id": self.task_id, "chair_profile_id": self.ceo,
                                                            "speaker_profile_ids": [self.pm, self.legal]})
        sid = self.ok("/api/staffing", "POST", {"preview_id": preview["preview_id"]}, 202)["id"]
        self.console.staffing.wait(10)
        rec = self.ok(f"/api/staffing/{sid}")
        self.assertEqual((rec["status"], rec["chairman"]["state"]), ("ready", "pending"))
        self.assertEqual(self.flows_bytes(), before)
        # 1. 啟用: the switch only
        self.assertTrue(self.ok(f"/api/agent-profiles/{self.art}", "POST", {"enabled": True})["profile"]["enabled"])
        self.assertEqual(self.card(self.art)["name"], "虛構藝術（停用）")
        self.assertEqual(self.flows_bytes(), before, "啟用 does not touch the flows")
        # 2. 建新卡: what the wizard posts, filled from the proposal's new card and its skill
        made = self.ok("/api/agent-profiles", "POST", {"name": "虛構法務新卡", "position": "legal", "model": {"tool": "claude", "model_id": "sonnet"},
                                                       "equipped_skill_ids": ["s-check"], "enabled": True})["profile"]["id"]
        self.assertEqual(self.flows_bytes(), before, "a new card does not touch the flows")
        # 3. 插技能: the card's list before and the ticked ones added
        eng = self.ok(f"/api/agent-profiles/{self.eng}", "POST", {"equipped_skill_ids": ["s-front", "s-check"]})["profile"]
        self.assertEqual(eng["equipped_skill_ids"], ["s-front", "s-check"])
        self.assertEqual(self.flows_bytes(), before, "inserting a skill does not touch the flows")
        self.assertEqual(self.ok(f"/api/staffing/{sid}")["chairman"]["state"], "pending", "nothing is recorded by the steps")
        # 4. 帶到隊伍: the board's 建立隊伍, with the cards as they are now
        role = lambda pid, family: (lambda p: {"name": p["name"], "family": family, "profile_id": p["id"], "profile_snapshot": {
            "name": p["name"], "tool": p["model"]["tool"], "model_id": p["model"].get("model_id", ""), "revision": p["revision"]}})(self.card(pid))
        flow = self.ok("/api/flows", "POST", {"task_id": self.task_id, "roles": {"planner": role(self.ceo, "anthropic"),
                                              "executor": role(self.eng, "anthropic"), "reviewers": [role(self.rev, "openai")]}})["flow"]
        self.assertNotEqual(self.flows_bytes(), before, "saving the team is what writes flows.json")
        self.assertEqual(flow["roles"]["executor"]["profile_snapshot"]["revision"], self.card(self.eng)["revision"])
        # 5. 記下：採用, with what was adopted
        rows = [{"kind": "slot", "place": "planner", "profile_id": self.ceo, "new_ref": "", "skill_ids": []},
                {"kind": "slot", "place": "executor", "profile_id": self.eng, "new_ref": "", "skill_ids": ["s-front", "s-check"]},
                {"kind": "slot", "place": "reviewer1", "profile_id": self.rev, "new_ref": "", "skill_ids": []},
                {"kind": "staff", "place": "legal", "profile_id": made, "new_ref": "N1", "skill_ids": ["s-check"]},
                {"kind": "staff", "place": "art", "profile_id": self.art, "new_ref": "", "skill_ids": []}]
        kept = self.flows_bytes()
        out = self.ok(f"/api/staffing/{sid}/chairman", "POST", {"decision": "adopt", "note": "照這樣組隊（虛構）", "adopted": {"rows": rows}})
        self.assertEqual((out["status"], out["chairman"]["state"], out["chairman"]["adopted"]), ("adopted", "adopted", {"rows": rows}))
        self.assertEqual(st.load(sid)["chairman"]["adopted"], {"rows": rows})
        self.assertEqual(self.flows_bytes(), kept, "the record is a record: it does not change the team")
        self.assertEqual(self.ok(f"/api/staffing/{sid}/chairman", "POST", {"decision": "dismiss"}, 409)["code"], "already_decided")
        listed = self.ok(f"/api/staffing?task_id={self.task_id}")["staffing"]
        self.assertEqual([(x["id"], x["status"]) for x in listed], [(sid, "adopted")])

    def test_an_adoption_naming_a_new_card_the_ceo_did_not_propose_is_refused(self):
        preview = self.ok("/api/staffing/preview", "POST", {"task_id": self.task_id, "chair_profile_id": self.ceo,
                                                            "speaker_profile_ids": [self.pm]})
        sid = self.ok("/api/staffing", "POST", {"preview_id": preview["preview_id"]}, 202)["id"]
        self.console.staffing.wait(10)
        bad = {"rows": [{"kind": "staff", "place": "legal", "profile_id": self.legal, "new_ref": "N2", "skill_ids": []}]}
        got = self.ok(f"/api/staffing/{sid}/chairman", "POST", {"decision": "adopt", "adopted": bad}, 400)
        self.assertEqual(got["code"], "bad_request")
        self.assertEqual(st.load(sid)["chairman"]["state"], "pending")


if __name__ == "__main__":
    unittest.main()
