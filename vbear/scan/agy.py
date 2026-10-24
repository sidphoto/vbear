"""Which skills Antigravity (AGY) reads, judged from files only. VBear never runs agy.

AGY looks for skills in three places that VBear can see (its documentation, antigravity.google/docs/skills):
a workspace's .agents/skills, ~/.gemini/antigravity-cli/skills, and every folder listed in
~/.gemini/config/skills.json. Each folder gives only the skills directly under it; with an include_only list
it gives only those listed (a listed path may be nested). AGY's built-in and plugin skills are not scanned.

The one config file read here is ~/.gemini/config/skills.json. Nothing else under ~/.gemini is opened or
listed except the global skills folder above. The file is capped in size and entries, parsed as plain JSON,
and every path in it must lead strictly inside the home folder by its real path; a symlink that leaves the
home folder is not followed. Anything unusable is skipped and reported, never guessed.

The result is two things: skills VBear already records get "agy" in read_by, and a folder VBear did not
scan yet becomes a new source of tool "agy". The old .agent/skills spelling is not scanned.
"""

from __future__ import annotations

import json
import os
import stat
from dataclasses import dataclass, field
from pathlib import Path

from .. import config as cfg
from ..model import ACT_ACTIVE, ACT_ARCHIVED, SkillRecord, stable_id
from . import claude, codex, walk

MAX_CONFIG_BYTES = 64 * 1024
MAX_ENTRIES = 50
MAX_INCLUDE_ITEMS = 200
MAX_INCLUDE_DEPTH = 4
MAX_CHILDREN = 1000
MAX_PATH_CHARS = 1024
# credential folders are never read as a skill folder, even when skills.json lists them
DENIED_HOME_DIRS = frozenset({".ssh", ".aws", ".gnupg"})

CONFIG_SHOWN = "~/.gemini/config/skills.json"
GLOBAL_SHOWN = "~/.gemini/antigravity-cli/skills"
CONFIG_ROW_ID = "agy-skills-json"

EVIDENCE_CONFIG = "AGY 的設定檔 ~/.gemini/config/skills.json 列出了這個技能所在的資料夾"
EVIDENCE_GLOBAL = "位於 AGY 的全域技能資料夾 ~/.gemini/antigravity-cli/skills"
EVIDENCE_PROJECT = "位於專案的 .agents/skills，AGY 會讀這個位置（AGY 官方文件）"
_NEW_REASON = ("位置判讀：{why}；VBear 沒有執行 AGY，看不到單一技能是否被停用，"
               "AGY 的內建與外掛技能不在這裡")


def HOME() -> Path:
    return Path.home()


@dataclass
class Folder:
    shown: str                 # the path as written, for the sources list
    lexical: Path              # the same path with ~ expanded, no symlinks resolved
    real: Path                 # the real folder
    include: list[str] | None  # None: every skill directly under it
    from_config: bool = False
    from_global: bool = False


@dataclass
class Config:
    present: bool = False
    accepted: int = 0
    issues: list[str] = field(default_factory=list)
    folders: list[Folder] = field(default_factory=list)


@dataclass
class Collected:
    new_skills: list[SkillRecord] = field(default_factory=list)
    rows: list[dict] = field(default_factory=list)
    problems: list[str] = field(default_factory=list)


def _under(path: str, base: str) -> bool:
    return path != base and path.startswith(base.rstrip("/") + "/")


# Config issues are stored as the config row lists them, under its own title and so without it; the overview
# problems list has no such title, so it adds this.
CONFIG_ISSUE_PREFIX = "AGY 設定檔 skills.json："


def resolve_folder(text: str) -> tuple[Folder | None, str]:
    """The folder a path in skills.json means, or (None, why not). Only absolute paths and ~ paths strictly
    below the home folder, with no '..', whose real path is also strictly below it."""
    if not isinstance(text, str) or not text.strip():
        return None, "path 不是文字，或是空的"
    if len(text) > MAX_PATH_CHARS or "\x00" in text:
        return None, "path 太長或含不合法字元"
    home_lex = os.path.normpath(str(HOME()))
    home_real = os.path.realpath(home_lex)
    if text == "~" or text.startswith("~/"):
        expanded = home_lex + text[1:]
    elif text.startswith("~"):
        return None, f"不支援「{text[:40]}」這種寫法，只接受 ~ 或 ~/ 開頭"
    elif text.startswith("/"):
        expanded = text
    else:
        return None, f"「{text[:60]}」不是絕對路徑，也不是 ~ 開頭"
    if ".." in expanded.split("/"):
        return None, f"「{text[:60]}」含 ..，未採用"
    lexical = os.path.normpath(expanded)
    if not (_under(lexical, home_lex) or _under(lexical, home_real)):
        return None, f"「{text[:60]}」不在家目錄之下，未採用"
    real = os.path.realpath(lexical)
    if not _under(real, home_real):
        return None, f"「{text[:60]}」經過符號連結後指向家目錄之外，未採用"
    if Path(real).relative_to(home_real).parts[0] in DENIED_HOME_DIRS:
        return None, f"「{text[:60]}」是憑證資料夾，未採用"
    if not os.path.isdir(real):
        return None, f"「{text[:60]}」資料夾不存在"
    return Folder(shown=text, lexical=Path(lexical), real=Path(real), include=None), ""


def _include_item(item: object) -> str | None:
    """A cleaned relative skill-folder path from include_only, or None when it is unusable."""
    if not isinstance(item, str) or "\x00" in item or "\\" in item or item.startswith("/"):
        return None
    parts = item.rstrip("/").split("/")
    if not parts or any(p in ("", ".", "..") for p in parts) or len(parts) > MAX_INCLUDE_DEPTH:
        return None
    return "/".join(parts)


def _read_config_bytes() -> tuple[bytes | None, str]:
    """The bytes of skills.json, or (None, why not). The file is opened by its real path, and that path must
    be a regular file strictly inside the home folder."""
    path = HOME() / ".gemini" / "config" / "skills.json"
    home_real = os.path.realpath(str(HOME()))
    real = os.path.realpath(str(path))
    if not _under(real, home_real):
        return None, "是符號連結，而且指向家目錄之外，未讀取"
    try:
        fd = os.open(real, os.O_RDONLY | os.O_NONBLOCK)
    except OSError as exc:
        return None, f"無法讀取（{exc.strerror or type(exc).__name__}）"
    try:
        with os.fdopen(fd, "rb") as fh:
            st = os.fstat(fh.fileno())
            if not stat.S_ISREG(st.st_mode):
                return None, "不是一般檔案，未讀取"
            if st.st_size > MAX_CONFIG_BYTES:
                return None, f"超過 {MAX_CONFIG_BYTES // 1024}KB，未讀取"
            data = fh.read(MAX_CONFIG_BYTES + 1)
    except OSError as exc:
        return None, f"無法讀取（{exc.strerror or type(exc).__name__}）"
    if len(data) > MAX_CONFIG_BYTES:
        return None, f"超過 {MAX_CONFIG_BYTES // 1024}KB，未讀取"
    return data, ""


def read_config() -> Config:
    """skills.json as folders. A file that cannot be used counts as no file, and says why."""
    conf = Config()
    if not os.path.lexists(HOME() / ".gemini" / "config" / "skills.json"):
        return conf
    conf.present = True
    raw, why = _read_config_bytes()
    if raw is None:
        conf.issues.append(why)
        return conf
    try:
        data = json.loads(raw.decode("utf-8"))
    except (ValueError, RecursionError):  # UnicodeDecodeError is a ValueError
        conf.issues.append("不是有效的 JSON，當成沒有這個檔")
        return conf
    if not isinstance(data, dict):
        conf.issues.append("最外層不是物件，當成沒有這個檔")
        return conf
    entries = data.get("entries")
    if entries is None:
        return conf
    if not isinstance(entries, list):
        conf.issues.append("entries 不是清單，當成沒有這個檔")
        return conf
    if len(entries) > MAX_ENTRIES:
        conf.issues.append(f"項目超過 {MAX_ENTRIES} 個上限，只讀前 {MAX_ENTRIES} 個")
    for n, entry in enumerate(entries[:MAX_ENTRIES], 1):
        if not isinstance(entry, dict):
            conf.issues.append(f"第 {n} 項不是物件，已略過")
            continue
        folder, why = resolve_folder(entry.get("path"))
        if folder is None:
            conf.issues.append(f"第 {n} 項已略過：{why}")
            continue
        include = _entry_include(entry, n, conf)
        if include is False:
            continue
        folder.include = include
        folder.from_config = True
        conf.folders.append(folder)
        conf.accepted += 1
    return conf


def _entry_include(entry: dict, n: int, conf: Config):
    """None: no include_only (every direct child). A list: only those. False: the entry is skipped, because an
    include_only that cannot be read must not turn into 'everything'."""
    if "include_only" not in entry:
        return None
    raw = entry["include_only"]
    if not isinstance(raw, list) or not all(isinstance(i, str) for i in raw):
        conf.issues.append(f"第 {n} 項的 include_only 不是文字清單，整項已略過")
        return False
    if len(raw) > MAX_INCLUDE_ITEMS:
        conf.issues.append(f"第 {n} 項的 include_only 超過 {MAX_INCLUDE_ITEMS} 個上限，只讀前 {MAX_INCLUDE_ITEMS} 個")
    include: list[str] = []
    for item in raw[:MAX_INCLUDE_ITEMS]:
        cleaned = _include_item(item)
        if cleaned is None:
            conf.issues.append(f"第 {n} 項的 include_only 有不能用的路徑，該路徑已略過")
        elif cleaned not in include:
            include.append(cleaned)
    return include


def global_folder() -> tuple[Folder | None, str]:
    """~/.gemini/antigravity-cli/skills when it is a folder inside the home folder. Absent is not a problem."""
    if not os.path.isdir(HOME() / ".gemini" / "antigravity-cli" / "skills"):
        return None, ""
    folder, why = resolve_folder("~/.gemini/antigravity-cli/skills")
    if folder is not None:
        folder.from_global = True
    return folder, why


def _merge(folders: list[Folder]) -> list[Folder]:
    merged: dict[str, Folder] = {}
    for f in folders:
        key = str(f.real)
        have = merged.get(key)
        if have is None:
            merged[key] = f
            continue
        have.from_config |= f.from_config
        have.from_global |= f.from_global
        if have.include is None or f.include is None:
            have.include = None
        else:
            have.include = have.include + [i for i in f.include if i not in have.include]
    return list(merged.values())


def skill_dirs(folder: Folder) -> list[tuple[Path, Path]]:
    """(lexical, real) skill folders AGY reads from `folder`: the direct children that hold a SKILL.md, or
    the include_only paths that do. No symlinked folder is followed."""
    out: list[tuple[Path, Path]] = []
    if folder.include is None:
        try:
            with os.scandir(folder.real) as it:
                names = []
                for n, entry in enumerate(it):
                    if n >= MAX_CHILDREN:
                        break
                    if entry.name in walk.SKIP_DIRS:
                        continue
                    try:
                        if entry.is_dir(follow_symlinks=False):
                            names.append(entry.name)
                    except OSError:
                        continue
        except OSError:
            return out
        wanted = [(name,) for name in sorted(names)]
    else:
        wanted = [tuple(item.split("/")) for item in folder.include]
    for parts in wanted:
        here = folder.real
        for part in parts:
            here = here / part
            try:
                if not stat.S_ISDIR(os.lstat(here).st_mode):
                    break
            except OSError:
                break
        else:
            if os.path.isfile(here / "SKILL.md"):
                out.append((folder.lexical.joinpath(*parts), here))
    return out


def mark(rec: SkillRecord, evidence: str) -> None:
    if "agy" not in rec.read_by:
        rec.read_by.append("agy")
    rec.read_by_evidence["agy"] = evidence


def mark_project_agents(src_path: Path, records: list[SkillRecord]) -> None:
    """A project's .agents/skills: AGY reads the skills directly under it. They stay Codex records."""
    for rec in records:
        p = Path(rec.path)
        if p.name == "SKILL.md" and p.parent.parent == src_path:
            mark(rec, EVIDENCE_PROJECT)


def _new_record(lex_dir: Path, folder: Folder) -> SkillRecord:
    skill_md = lex_dir / "SKILL.md"
    src = cfg.Source(source_id="agy", tool="codex", kind="skills", scope="user", path=str(folder.lexical))
    try:
        rec = codex._build_skill(skill_md, folder.lexical, src, {"skill_enabled": {}})
    except Exception as exc:  # one hostile file must not stop the scan
        rec = claude.failed_record("agy", skill_md, folder.lexical, exc)
    rec.tool = "agy"
    rec.skill_id = stable_id("agy", str(skill_md))
    if rec.activation == ACT_ACTIVE:
        why = "位於 AGY 的全域技能資料夾" if folder.from_global else "AGY 的設定檔 skills.json 列出此資料夾"
        rec.activation_reason = _NEW_REASON.format(why=why)
    elif rec.activation != ACT_ARCHIVED:
        rec.activation_reason = f"{rec.activation_reason}；{_NEW_REASON.format(why='位於 AGY 會讀的資料夾')}"
    return rec


def collect(skills: list[SkillRecord], source_roots: list[Path], disabled_roots: list[Path]) -> Collected:
    """Mark the skills AGY reads and make records for the ones VBear has not scanned. `skills` are the records
    so far; `source_roots` are every skill folder VBear already scans; `disabled_roots` are the ones the person
    turned off, which AGY's list does not override."""
    out = Collected()
    conf = read_config()
    folders = list(conf.folders)
    g_folder, g_why = global_folder()
    if g_folder is not None:
        folders.append(g_folder)
    elif g_why:
        out.problems.append(f"AGY 全域技能資料夾未採用：{g_why}")
    if conf.present:
        out.rows.append({"source_id": CONFIG_ROW_ID, "label": "AGY 設定檔 skills.json", "tool": "agy",
                         "kind": "config", "path": CONFIG_SHOWN, "enabled": True, "exists": True,
                         "count": conf.accepted, "scope": "user", "discovered": True, "issues": list(conf.issues)})
        # the overview list has no row title above it, so there each issue carries the name of the file
        out.problems.extend(CONFIG_ISSUE_PREFIX + issue for issue in conf.issues)
    by_dir: dict[str, list[SkillRecord]] = {}
    for rec in skills:
        by_dir.setdefault(os.path.realpath(os.path.dirname(rec.path)), []).append(rec)
    known_roots = {os.path.realpath(r) for r in source_roots}
    disabled = [os.path.realpath(r) for r in disabled_roots]
    made: set[str] = set()
    for folder in _merge(folders):
        evidence = EVIDENCE_GLOBAL if folder.from_global else EVIDENCE_CONFIG
        if any(str(folder.real) == r or str(folder.real).startswith(r + "/") for r in disabled):
            out.problems.append(f"AGY 設定檔列出的資料夾在已關閉的來源內，未掃描：{folder.shown}")
            continue
        count = 0
        for lex_dir, real_dir in skill_dirs(folder):
            key = str(real_dir)
            for rec in by_dir.get(key, []):
                mark(rec, evidence)
            if key in by_dir or key in made:
                continue
            made.add(key)
            rec = _new_record(lex_dir, folder)
            mark(rec, evidence)
            out.new_skills.append(rec)
            count += 1
        if str(folder.real) not in known_roots:
            out.rows.append({
                "source_id": f"agy:{stable_id(str(folder.real))}",
                "label": "AGY 全域技能資料夾" if folder.from_global else "AGY 設定檔列出的資料夾",
                "tool": "agy", "kind": "skills", "path": GLOBAL_SHOWN if folder.from_global else folder.shown,
                "enabled": True, "exists": True, "count": count, "scope": "user", "discovered": True})
    return out
