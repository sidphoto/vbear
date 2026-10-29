"""The role card's data: one Agent Profile with what VBear already knows about its role, its chosen skills and the
armor a launch would put on (design game-ui 4.1, 4.4, 6).

Read only, and nothing is fetched here: the caller passes what is already loaded (the profile, the static index if
it is in memory, the last live view if one was built, the last verification result) and this module arranges it.
It scans nothing, asks no runtime, probes no CLI and reads no work directory. A value that is not loaded is said
to be not loaded or unknown, never guessed. There is no attendance or "times used" for a role: usage records have no
Profile in them.
"""

from __future__ import annotations

from . import agent_launch, agent_profiles, position_guide
from .runtime import agent_sessions

NOT_KNOWN_AT_PREVIEW = "產生出發通行證時才知道"
INDEX_MISSING = "目前索引找不到此技能"
VERSION_BASIS = ("以已驗證設定為準：這是 VBear 有實測證據的那組設定會做到的程度；你這台 Mac 的 Claude Code 版本"
                 "實際守到什麼程度，要等出發通行證才知道")
CODEX_BASIS = ("以 VBear 已記錄的 Codex 驗證證據為準；證據不全的項目是「未知」。這台 Mac 的 Codex 版本"
               "實際守到什麼程度，要等出發通行證才知道")
ARMOR_NOT_APPLICABLE = {"shared": "shared 不是可啟動的工具，沒有防具",
                        "agy": "VBear 還不會啟動 AGY，沒有防具"}
CODEX_NOT_LAUNCHABLE = "目前無法從 VBear 啟動這個角色（Codex 的互動模式還不能安全地受管啟動）"
CODEX_SKILLS_NOTE = "VBear 目前不提供 Codex 角色的受管啟動，已選技能是你的挑選紀錄。"
CODEX_SKILLS_NOTE_LAUNCHABLE = "已選技能是你的挑選紀錄；VBear 沒有驗證 Codex 角色會載入或使用它們。"
SHARED_SKILLS_NOTE = "shared 不是可啟動的工具，已選技能是你的挑選紀錄。"
AGY_SKILLS_NOTE = ("VBear 還不會啟動 AGY，已選技能只是你的挑選紀錄，不代表 AGY 會載入；「AGY 不會讀」是依這台電腦的 "
                   "AGY 設定判斷的，AGY 的內建與外掛技能不在這裡。")
TOOLS_ONLY_CLAUDE = "VBear 目前只支援用角色卡啟動 Claude Code"
TOOLS_CODEX_NOT_RECORDED = "VBear 沒有記錄 Codex 角色的可用工具清單"
TOOLS_AGY_NOT_RECORDED = "VBear 還不會啟動 AGY，也沒有記錄 AGY 的可用工具清單"
ARMOR_FULL_MODE = ("完整模式：VBear 沒有限制這張卡，只剩工具自己的權限詢問，所以沒有防具可以列。"
                   "（這個版本還不能以完整模式出發。）")
LAUNCH_MODE_NOT_SET = "這張卡沒有設定出發方式（舊卡沒有這個欄位），一律當安全模式；沒有改動這張卡。"
TOOLS_SOURCE = "與 VBear 啟動 Claude Code 時傳入的 --tools／--disallowedTools 相同（同一組常數）"


def _sourced(value) -> dict:
    """A Sourced field as the index stored it: the value, where it came from, or not provided."""
    if isinstance(value, dict) and "origin" in value:
        present = value.get("value") not in (None, "", [], {})
        return {"value": value.get("value") if present else None,
                "origin": value.get("origin") if present else "missing",
                "detail": value.get("detail") or ""}
    return {"value": None, "origin": "missing", "detail": ""}


def _label_only(tool) -> str:
    return "職業只是標籤，不會把角色指示載入 " + ("Codex" if tool == "codex" else
                                                   "Claude Code" if tool == "claude" else
                                                   "AGY" if tool == "agy" else "任何工具")


def _derived(value, detail: str) -> dict:
    """A value VBear worked out itself (from where the skill sits, or from its text), with where from; missing
    when there is none."""
    present = value not in (None, "", [], {})
    return {"value": value if present else None, "origin": "derived" if present else "missing",
            "detail": detail if present else ""}


def _profession(profile: dict, static: dict | None, tool=None) -> dict:
    role_id = profile.get("profession_role_id")
    if not role_id:
        return {"state": "none", "role_id": None, "label_only": _label_only(tool)}
    if static is None:
        return {"state": "index_not_loaded", "role_id": role_id, "label_only": _label_only(tool)}
    role = next((r for r in static.get("roles", []) if r.get("role_id") == role_id), None)
    if role is None:
        return {"state": "not_in_index", "role_id": role_id, "note": "目前索引找不到這個職業",
                "label_only": _label_only(tool)}
    return {"state": "found", "role_id": role_id, "name": role.get("name"), "tool": role.get("tool"),
            "kind": role.get("kind"), "description": _sourced(role.get("description")),
            "capabilities": _sourced(role.get("capabilities")),
            "suitable_tasks": _sourced(role.get("suitable_tasks")),
            "label_only": _label_only(tool)}


def _observation(skill_id: str, live: dict | None) -> dict:
    """Whether the observed runs (the usage scan, over a window of days) show this skill. "none" is not "never
    used": the scan only sees what was recorded, and it can be off or not built yet."""
    base = {"source": "執行觀察", "origin": "runtime", "detail": "執行觀察"}
    usage = (live or {}).get("usage") if isinstance(live, dict) else None
    if not isinstance(usage, dict) or not isinstance(usage.get("sessions"), list):
        return {**base, "state": "unavailable", "window_days": None}
    window = usage.get("window_days") if isinstance(usage.get("window_days"), int) else None
    problems = usage.get("problems") or []
    last = None
    for sess in usage["sessions"]:
        for used in (sess.get("skills") or []) if isinstance(sess, dict) else []:
            if isinstance(used, dict) and skill_id in (used.get("skill_ids") or []):
                ts = used.get("last_ts")
                if isinstance(ts, (int, float)) and not isinstance(ts, bool):
                    last = ts if last is None else max(last, ts)
                elif last is None:
                    last = 0
    if last is not None:
        return {**base, "state": "observed", "window_days": window, "last_ts": last or None}
    if problems:
        return {**base, "state": "unavailable", "window_days": window}
    return {**base, "state": "none", "window_days": window}


def _will_load(tool, skill_id: str) -> bool:
    """Whether a launch of this role would load the chosen skill. The one place that answers it, and the answer
    is no for every tool today: a Claude Code launch passes the safe-mode flag, a Codex role is not launched at
    all, and shared is not a launchable tool. A card shows the solid "in effect" slot only when this says yes."""
    return False


def read_by(rec: dict) -> list:
    """The other tools whose own files say they read this skill (today only "agy"), as the scan stored them."""
    value = rec.get("read_by")
    return [t for t in value if isinstance(t, str) and len(t) <= 16][:8] if isinstance(value, list) else []


def agy_reads(rec: dict) -> bool:
    """Whether AGY reads this skill, by where it sits and what AGY's config lists. Not a promise that a launch loads it."""
    return rec.get("tool") == "agy" or "agy" in read_by(rec)


def _skill(skill_id: str, static: dict | None, live: dict | None, tool=None) -> dict:
    will_load = _will_load(tool, skill_id)
    # only an AGY card says whether AGY reads the skill; None is "the index cannot say"
    agy = {"agy_reads": None} if tool == "agy" else {}
    if static is None:
        return {"skill_id": skill_id, "state": "index_not_loaded", "effective": False, "will_load": will_load, **agy}
    rec = next((s for s in static.get("skills", []) if s.get("skill_id") == skill_id), None)
    if rec is None:
        return {"skill_id": skill_id, "state": "not_in_index", "effective": False, "will_load": will_load,
                "note": INDEX_MISSING, "indexed_at": static.get("generated_at"), **agy}
    refs = [r for r in (rec.get("referenced_files") or []) if isinstance(r, dict)]
    if tool == "agy":
        agy = {"agy_reads": agy_reads(rec)}
    return {
        **agy,
        "skill_id": skill_id, "state": "in_index", "effective": False, "will_load": will_load,
        "name": rec.get("name"), "invoke_name": rec.get("invoke_name"), "tool": rec.get("tool"),
        "scope": rec.get("scope"), "activation": rec.get("activation"),
        "description": _sourced(rec.get("description")), "when_to_use": _sourced(rec.get("when_to_use")),
        "categories": [{"label": c.get("label"), "keyword": c.get("keyword")}
                       for c in (rec.get("categories") or []) if isinstance(c, dict)],
        "referenced_files": {"count": len(refs),
                             "present": sum(1 for r in refs if r.get("status") == "present"),
                             "missing": len(rec.get("missing_files") or []),
                             "note": "VBear 不會執行這些檔案"},
        "warnings": [w for w in (rec.get("warnings") or []) if isinstance(w, str)][:5],
        "observed": _observation(skill_id, live),
    }


def _version_status(tool: str, verification: dict | None) -> dict:
    """What this console has verified itself in this run, or unknown. The installed version is not looked up
    here (that would run the CLI), so "unknown" is the usual answer. Only Claude Code has a verifier here: for
    any other tool the Claude result is not used and the answer is "unknown" with its own words."""
    if tool == "codex":
        return {"state": "unknown", "version": None, "source": "沒有載入的 Codex 驗證資料",
                "text": "未知（這個畫面不探測 Codex 版本）"}
    if tool != "claude":
        return {"state": "unknown", "version": None, "source": "不適用", "text": "不適用（這個工具不能由 VBear 啟動）"}
    v = verification if isinstance(verification, dict) else {}
    version = v.get("version") if isinstance(v.get("version"), str) else None
    source = "這個主控台剛驗證過的結果"
    if version and v.get("running") is False and v.get("result") == "passed":
        return {"state": "verified", "version": version, "source": source,
                "text": f"已驗證（Claude Code {version}；{source}）"}
    if version and v.get("running") is False and v.get("result") in ("failed", "error"):
        return {"state": "unverified", "version": version, "source": source,
                "text": f"未驗證（Claude Code {version}；{source}）"}
    return {"state": "unknown", "version": None, "source": "沒有載入的驗證資料",
            "text": "未知（這個畫面不探測 Claude Code；要到出發通行證才會讀取版本）"}


def _armor(tool: str, version_status: dict, mode: str = "safe") -> dict:
    if mode == "full":
        return {"applicable": False, "why": ARMOR_FULL_MODE}
    if tool not in ("claude", "codex"):
        return {"applicable": False, "why": ARMOR_NOT_APPLICABLE.get(tool, "此工具沒有受管啟動設定")}
    codex_ok = bool(agent_launch._codex_evidence_reference()) if tool == "codex" else False
    claude_verified = None
    if tool == "claude":
        # The baseline is the verified setting. Only a version this console itself found unverified is shown as
        # such; an unknown version is stated next to the baseline, not folded into it.
        claude_verified = False if version_status["state"] == "unverified" else True
    items = agent_launch.armor_items(tool, claude_verified, agent_launch.NETWORK_VERIFIED, codex_ok)
    rows = []
    for name, it in items.items():
        rows.append({
            "name": name, "level": it["level"], "note": it["note"], "group": it["group"],
            "path_scope": NOT_KNOWN_AT_PREVIEW if it["scope"] else "不適用",
            "evidence_refs": NOT_KNOWN_AT_PREVIEW if it["evidence"] else "不適用",
            "unknown_reason": (None if it["unknown_reason"] == "none" else
                               "這個版本尚未驗證" if it["unknown_reason"] == agent_launch.WHY_VERSION
                               else it["unknown_reason"]),
        })
    out = {"applicable": True, "basis": "verified_setting",
           "title": "防具（以已驗證設定為準）" if tool == "claude" else "防具（以 Codex 已記錄的驗證證據為準）",
           "basis_note": VERSION_BASIS if tool == "claude" else CODEX_BASIS,
           "preview_decides": "實際以出發通行證為準",
           # a Codex card never carries the Claude-only "this Claude Code version is unverified" wording
           "groups": agent_launch.armor_groups(tool),
           "items": rows}
    return out


def _skills_section(tool: str, codex_not_launchable: bool, items: list) -> dict:
    """The chosen skills with the statement that fits the tool. Only a Claude Code launch passes the safe-mode
    flag, so only there is the safe-mode statement made (and only as fact for the version it was checked on)."""
    # all_inactive is what the card reads to draw the dashed slots; it is worked out from the items, not from words
    all_inactive = all(it.get("will_load") is not True for it in items)
    out = {"title": "技能卡（收藏中：VBear 啟動時不載入）" if all_inactive else "技能卡",
           "items": items, "all_inactive": all_inactive}
    if tool == "claude":
        out["note"] = "VBear 啟動的角色不會載入這些技能；這份清單是你的挑選紀錄。"
        out["safe_mode"] = ("已傳入安全模式旗標；Claude Code 2.1.296 的說明指出安全模式會關閉技能，"
                            "其他版本是否停用技能未驗證")
    elif tool == "codex":
        out["note"] = CODEX_SKILLS_NOTE if codex_not_launchable else CODEX_SKILLS_NOTE_LAUNCHABLE
    elif tool == "agy":
        out["note"] = AGY_SKILLS_NOTE
    else:
        out["note"] = SHARED_SKILLS_NOTE
    return out


def _tools(tool, codex_not_launchable: bool) -> dict:
    """The tools a launch of this role offers: always an object. Only a Claude Code launch has a tool set VBear
    sets itself, and its two lists are the constants the argv is built from (agent_sessions), never text parsed
    from the armor. Anything else says why it is not known."""
    if tool == "claude":
        return {"known": True, "allowed": list(agent_sessions.CLAUDE_TOOLS_ALLOWED),
                "blocked": list(agent_sessions.CLAUDE_TOOLS_BLOCKED), "source": TOOLS_SOURCE}
    if tool == "codex":
        reason = CODEX_NOT_LAUNCHABLE if codex_not_launchable else TOOLS_CODEX_NOT_RECORDED
    elif tool == "agy":
        reason = TOOLS_AGY_NOT_RECORDED
    else:
        reason = TOOLS_ONLY_CLAUDE
    return {"known": False, "allowed": [], "blocked": [], "unknown_reason": reason}


def _launch_mode(profile: dict, tool, mode: str) -> dict:
    stored = profile.get("launch_mode") in agent_profiles.LAUNCH_MODES
    text = position_guide.mode_note(tool, mode) if stored else LAUNCH_MODE_NOT_SET + position_guide.mode_note(tool, mode)
    return {"mode": mode, "stored": stored, "label": position_guide.MODE_LABELS[mode], "text": text}


def _instructions(profile: dict) -> dict:
    """The card's instructions with where they go: nowhere by themselves, only to a paste the person makes."""
    got = agent_profiles.instructions_of(profile)
    return {"title": "這份指示會交到哪裡", "source": got["source"], "position": got["position"], "text": got["text"],
            "automatic": False, "where": position_guide.INSTRUCTIONS_WHERE}


def build(profile: dict, static: dict | None, live: dict | None, verification: dict | None) -> dict:
    """The loadout of one Profile from what is already loaded (see the module note)."""
    model = profile.get("model") if isinstance(profile.get("model"), dict) else {}
    tool = model.get("tool")
    mode = agent_profiles.effective_launch_mode(profile)
    version = _version_status(tool, verification)
    blockers = agent_launch.launch_blockers(profile, True, {"enabled": False, "approved_domains": []})
    codex_not_launchable = tool == "codex" and any(
        b.get("code") == "codex_interactive_flags_unsupported" for b in blockers)
    equipped = [s for s in (profile.get("equipped_skill_ids") or []) if isinstance(s, str)]
    return {
        "ok": True,
        "profile": {k: profile.get(k) for k in ("id", "name", "enabled", "created_at", "updated_at")} | {
            "tool": tool, "model_id": model.get("model_id") or None,
            "profession_role_id": profile.get("profession_role_id"),
            "permission_intents": profile.get("permission_intents") or {},
            "intents_note": "只是記錄，不會變成實際權限"},
        "index": {"loaded": static is not None, "generated_at": static.get("generated_at") if static else None},
        "profession": _profession(profile, static, tool),
        "skills": _skills_section(tool, codex_not_launchable, [_skill(sid, static, live, tool) for sid in equipped]),
        "version_status": version,
        "tools": _tools(tool, codex_not_launchable),
        "launch_mode": _launch_mode(profile, tool, mode),
        "instructions": _instructions(profile),
        "boundaries": position_guide.resolve(agent_profiles.position_of(profile), tool, mode),
        "armor": _armor(tool, version, mode) | ({"launch_note": CODEX_NOT_LAUNCHABLE} if codex_not_launchable else {}),
        "blockers": blockers,
        "blockers_note": "假設你已勾選知悉 commit、並維持關閉網路；實際以出發通行證為準",
    }


def _read_by_detail(rec: dict) -> str:
    evidence = rec.get("read_by_evidence")
    text = evidence.get("agy") if isinstance(evidence, dict) else None
    return text[:200] if isinstance(text, str) and text else "掃描位置與 AGY 設定檔判讀"


INSTALLED_STATES = frozenset({"active", "disabled", "superseded"})
MAX_CARD_REFS = 100


def skill_card(static: dict, skill_id: str, profiles, live: dict | None) -> dict | None:
    """The skill card's features (design game-ui 4.2) from the index in memory, the stored profiles and the last
    live view. None when the current index does not have the skill. Nothing is scanned or built; the raw
    SKILL.md is not read; no file under the skill is opened or run."""
    index = {s.get("skill_id"): s for s in static.get("skills", []) if isinstance(s, dict)}
    rec = index.get(skill_id)
    if rec is None:
        return None
    refs = [{"ref": r.get("ref"), "status": r.get("status")}
            for r in (rec.get("referenced_files") or []) if isinstance(r, dict)]
    roles = [{"id": p.get("id"), "name": p.get("name"), "enabled": bool(p.get("enabled", True))}
             for p in (profiles or []) if skill_id in (p.get("equipped_skill_ids") or [])]
    cats = [c for c in (rec.get("categories") or []) if isinstance(c, dict)]
    copies = []
    for other_id in rec.get("duplicate_of") or []:
        other = index.get(other_id)
        if other and other.get("activation") == "not_installed":
            copies.append({"skill_id": other_id, "tool": other.get("tool"), "scope": other.get("scope")})
    return {
        "ok": True,
        "index": {"loaded": True, "generated_at": static.get("generated_at")},
        "skill": {
            "skill_id": skill_id, "name": _derived(rec.get("name"), "技能檔案（掃描整理）"),
            "invoke_name": rec.get("invoke_name"),
            "tool": _derived(rec.get("tool"), "掃描位置判讀"), "scope": _derived(rec.get("scope"), "掃描位置判讀"),
            "read_by": _derived(read_by(rec), _read_by_detail(rec)),
            "activation": rec.get("activation"), "activation_reason": rec.get("activation_reason"),
            "installed": rec.get("activation") in INSTALLED_STATES,
            "status_source": {"origin": "derived", "detail": "掃描位置與設定檔判讀"},
            "description": _sourced(rec.get("description")), "when_to_use": _sourced(rec.get("when_to_use")),
            "inputs": _sourced(rec.get("inputs")), "outputs": _sourced(rec.get("outputs")),
            "dependencies": _sourced(rec.get("dependencies")),
            "categories": {**_derived([c.get("label") for c in cats if c.get("label")], "描述關鍵字"),
                           "matches": [{"label": c.get("label"), "keyword": c.get("keyword")} for c in cats]},
            "referenced_files": {"count": len(refs), "items": refs[:MAX_CARD_REFS],
                                 "truncated": len(refs) > MAX_CARD_REFS, "note": "VBear 不會執行這些檔案",
                                 "origin": "derived", "detail": "技能檔內容裡的引用"},
            "missing_files": {"items": [m for m in (rec.get("missing_files") or []) if isinstance(m, str)][:20],
                              "origin": "derived", "detail": "掃描結果"},
            "warnings": {"items": [w for w in (rec.get("warnings") or []) if isinstance(w, str)][:20],
                         "origin": "derived", "detail": "掃描結果"},
        },
        "added_to_roles": {"items": roles, "effective": False, "note": "已加入角色只是挑選紀錄，本次不生效",
                           "origin": "user", "detail": "主控台角色卡（使用者意圖）"},
        "observation": _observation(skill_id, live),
        "marketplace_copies": copies,
        "marketplace_source": {"origin": "derived", "detail": "市集掃描"},
        "effect_note": "效果是作者的描述，不是 VBear 驗證過的能力，只適用於你自己啟動並載入這張技能的工具",
    }
