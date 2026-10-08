"""The executor's report (design 4): schema v1, checked by VBear's own code
(the CLI's --json-schema check is not trusted), then compared with the
repository's files.

A report only ever comes from a valid turn (stream_journal.turn_validity).
``problem`` is the schema check; ``verify`` reads the task work directory
(git_head for HEAD, git_objects for the commit object, never git). The
screen shows the executor's own words and VBear's file checks apart.
"""

from __future__ import annotations

import re

from . import git_head, git_objects
from .runtime.stream_protocol import UUID_RE

SCHEMA_VERSION = 1
COMMIT_RE = re.compile(r"^(?:[0-9a-f]{40}|[0-9a-f]{64})\Z")
STATUSES = ("done", "blocked", "needs_input")
TEST_RESULTS = ("passed", "failed", "not_run")
# design 4: tests.command at most 512 characters; summary 2 KiB and notes
# 4 KiB, counted in UTF-8 bytes.
COMMAND_CHARS = 512
SUMMARY_BYTES = 2048
NOTES_BYTES = 4096

# The --json-schema VBear passes to the CLI. It constrains the model; VBear
# still checks every report with ``problem`` below.
JSON_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["v", "dispatch_id", "status", "head", "tests", "notes"],
    "properties": {
        "v": {"type": "integer", "const": 1},
        "dispatch_id": {"type": "string"},
        "status": {"type": "string", "enum": list(STATUSES)},
        "head": {"type": "string"},
        "tests": {
            "type": "object", "additionalProperties": False, "required": ["command", "result", "summary"],
            "properties": {"command": {"type": "string", "maxLength": COMMAND_CHARS},
                           "result": {"type": "string", "enum": list(TEST_RESULTS)},
                           "summary": {"type": "string", "maxLength": SUMMARY_BYTES}},
        },
        "notes": {"type": "string", "maxLength": NOTES_BYTES},
    },
}


def _text(value, *, chars: int | None = None, utf8_bytes: int | None = None) -> bool:
    if not isinstance(value, str):
        return False
    try:
        size = len(value.encode("utf-8"))                  # a lone surrogate fails to encode
    except UnicodeEncodeError:
        return False
    return (chars is None or len(value) <= chars) and (utf8_bytes is None or size <= utf8_bytes)


def problem(report, dispatch_id) -> str | None:
    """None when ``report`` is exactly schema v1 for ``dispatch_id``."""
    if not isinstance(report, dict) or set(report) != {"v", "dispatch_id", "status", "head", "tests", "notes"}:
        return "欄位不符"
    if report["v"] != SCHEMA_VERSION or isinstance(report["v"], bool) or not isinstance(report["v"], int):
        return "v 不是 1"
    if not (isinstance(report["dispatch_id"], str) and UUID_RE.match(report["dispatch_id"])):
        return "dispatch_id 格式不符"
    if report["dispatch_id"] != dispatch_id:
        return "dispatch_id 與這一輪不同"
    if report["status"] not in STATUSES:
        return "status 不合法"
    if not (isinstance(report["head"], str) and COMMIT_RE.match(report["head"])):
        return "head 必須是 40 或 64 碼小寫十六進位"
    tests = report["tests"]
    if not isinstance(tests, dict) or set(tests) != {"command", "result", "summary"}:
        return "tests 欄位不符"
    if not _text(tests["command"], chars=COMMAND_CHARS):
        return "tests.command 不合法"
    if tests["result"] not in TEST_RESULTS:
        return "tests.result 不合法"
    if not _text(tests["summary"], utf8_bytes=SUMMARY_BYTES):
        return "tests.summary 不合法"
    if not _text(report["notes"], utf8_bytes=NOTES_BYTES):
        return "notes 不合法"
    return None


def verify(report: dict, workdir: str, *, reviewed_commit: str | None = None) -> list[str]:
    """Design 4's checks against the files (principle 8). Empty when they
    all pass. ``reviewed_commit``: after a NEEDS WORK, the commit that was
    reviewed; the new head must differ from it."""
    problems = []
    head = report.get("head") if isinstance(report, dict) else None
    current = git_head.read_head(workdir)
    if current.get("commit") is None:
        problems.append(f"讀不到任務工作目錄的 HEAD（{current.get('error') or '原因不明'}）")
    elif current["commit"] != head:
        problems.append("回報的 head 不是任務工作目錄目前的 commit")
    exists = git_objects.commit_exists(workdir, head)
    if exists is None:
        problems.append("無法核對回報的 commit 是否存在")
    elif exists is False:
        problems.append("回報的 commit 不存在")
    if reviewed_commit is not None and head == reviewed_commit:
        problems.append("NEEDS WORK 之後，回報的 head 仍是被審的 commit")
    return problems
