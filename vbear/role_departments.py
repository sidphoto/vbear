"""Which position a role template (a profession) probably fits, derived from its name and the first sentence of its
author's description.

This is automatic organisation, not an author claim, so every answer carries origin=derived and the keyword that
matched. The table is small and visible on purpose, like vbear/categories.py. The ids are the nine positions of
agent_profiles.POSITION_TABLE; a role that matches nothing has no department.

Matching is by whole word, so "builder" is not "ui", "latest" is not "test" and "smart" is not "art". A keyword that
ends in "*" is a stem: it matches the start of a word ("archiv*" is archive, archivist). Chinese keywords match as
a substring, since a Chinese name has no spaces. The name is looked at first, then the description's first sentence
(at most 200 characters); in each, the first position in PRIORITY with a match wins.
"""

from __future__ import annotations

import re

# first match wins, in this order
PRIORITY = ["reviewer", "qa", "research", "product", "business", "design", "records", "planner", "executor"]

KEYWORDS = {
    "reviewer": {
        "en": ["review", "reviews", "reviewer", "reviewers", "reviewing", "audit", "audits", "auditor", "auditors",
               "auditing", "security", "compliance", "critic"],
        "zh": ["審查", "稽核", "資安"]},
    "qa": {
        "en": ["qa", "test", "tests", "tester", "testers", "testing", "verif*", "checker", "benchmark*", "evidence",
               "acceptance", "quality"],
        "zh": ["測試", "驗證", "品質", "驗收"]},
    "research": {
        "en": ["research", "researcher", "researchers", "analy*", "trend", "trends", "scout", "evaluat*",
               "investigat*", "intel"],
        "zh": ["研究", "調查", "分析"]},
    "product": {
        "en": ["product", "prioritiz*", "feedback", "requirement", "requirements", "roadmap", "sprint"],
        "zh": ["產品", "需求"]},
    "business": {
        "en": ["business", "growth", "marketing", "brand", "sales", "pricing", "finance", "seo", "strategist",
               "tiktok", "instagram", "twitter", "reddit", "social", "community", "app store"],
        "zh": ["商業", "行銷", "品牌", "銷售", "定價", "社群"]},
    "design": {
        "en": ["design", "designer", "designers", "ui", "ux", "visual", "art", "artist", "illustrat*", "image",
               "logo", "whimsy"],
        "zh": ["設計", "美術", "視覺", "插畫"]},
    "records": {
        "en": ["archiv*", "secretary", "scribe", "record", "records", "recorder", "historian", "ledger", "changelog",
               "documentation", "ingest*", "summar*", "tracker", "minutes"],
        "zh": ["紀錄", "記錄", "秘書", "歸檔"]},
    "planner": {
        "en": ["orchestrat*", "coordinator", "planner", "plan", "producer", "shepherd", "chief", "lead", "leader",
               "manager", "director", "ceo", "dispatcher"],
        "zh": ["規劃", "統籌", "指揮", "主管"]},
    "executor": {
        "en": ["engineer", "engineers", "developer", "developers", "dev", "build", "builder", "coder", "programmer",
               "devops", "prototyp*", "implement*", "architect", "writer", "author", "creator", "editor", "maker",
               "maintainer"],
        "zh": ["工程", "開發", "實作", "寫手", "作者", "編輯"]},
}

DESCRIPTION_CHARS = 200

_CAMEL = re.compile(r"(?<=[a-z0-9])(?=[A-Z])")
_NOT_WORD = re.compile(r"[^A-Za-z0-9]+")
_SENTENCE_END = re.compile(r"(?<=[.!?])\s|[。！？\n]")


def _words(text: str) -> tuple[list[str], str]:
    """The words of a text two ways (split at capitals, and not), and the text as lower-case words in one line."""
    plain = [w for w in _NOT_WORD.split(text.lower()) if w]
    split = [w for w in _NOT_WORD.split(_CAMEL.sub(" ", text).lower()) if w]
    return plain + [w for w in split if w not in plain], " " + " ".join(split) + " "


def _hit(department: str, text: str) -> str | None:
    words, line = _words(text)
    entry = KEYWORDS[department]
    for kw in entry["en"]:
        if kw.endswith("*"):
            stem = kw[:-1]
            if any(w.startswith(stem) for w in words):
                return stem
        elif " " in kw:
            if f" {kw} " in line:
                return kw
        elif kw in words:
            return kw
    for kw in entry["zh"]:
        if kw in text:
            return kw
    return None


def _first_sentence(description) -> str:
    if not isinstance(description, str):
        return ""
    text = description.strip()[:DESCRIPTION_CHARS]
    return _SENTENCE_END.split(text, maxsplit=1)[0].strip()


def department(name, description=None) -> dict | None:
    """`{"id", "keyword", "origin": "derived"}` for the position this role probably fits, or None."""
    for source in (name if isinstance(name, str) else "", _first_sentence(description)):
        if not source:
            continue
        for dep in PRIORITY:
            kw = _hit(dep, source)
            if kw:
                return {"id": dep, "keyword": kw, "origin": "derived"}
    return None
