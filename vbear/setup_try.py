"""「試一下」 on the start-up page: one fixed short sentence to one AI tool, to see that it really answers.

What is sent, the same for every tool: ``TRY_SENTENCE``. How it is sent, for each tool (``argv_for``): headless (Claude Code
``-p``, Codex ``exec``, AGY ``-p``, Grok ``-p``, MCODE ``exec``), in a new empty scratch folder that is removed afterwards, in
a new process group that is ended however the call ends, with a time limit and a cap on what is read. Claude Code is asked
for no tools and no settings of the person's (``--safe-mode``, ``--setting-sources ""``, the same words the chat uses) and for
a small budget; Codex runs without the person's config and rules, read-only, with its shell and MCP tools off; MCODE with
``--permission off`` and one step; Grok with one turn and its web search, memory, plan and subagents off. AGY has no flag for
fewer tools that has been checked, so it gets only the sentence (see docs/evidence).

What comes back is read for one thing, whether the tool answered, and then dropped: the reply, and anything a tool prints
about the account, are never kept, logged or passed on. What the page gets is one of success, not_logged_in, timeout,
not_found, bad_reply (or not_ended, the group could not be confirmed gone), with a plain sentence.

The cost goes on the day's limit (``try_spend``, the same day as the meetings, the staffing meetings and the chats): what
Claude Code reports, else a fixed ``CHARGE`` (US$0.01). A try that has started a program is booked even if it fails; a try
for a tool that is not there costs nothing. When the day's limit cannot take another ``CHARGE``, or cannot be read, nothing starts.
"""

from __future__ import annotations

import json
import os
import threading
import time
from decimal import Decimal
from typing import Callable

from . import ai_tool_status, ai_tools, headless_cli, meetings as mt, try_spend
from .jsonstore import StoreError

TRY_SENTENCE = "請只回答 OK"
TRY_TIMEOUT_S = 60.0
MAX_OUTPUT = 1 << 20
CHARGE = Decimal("0.01")                # booked for a tool that reports no cost, and the most a try is counted at
CLAUDE_MODEL = "claude-haiku-5-5"       # the model the translations use: the cheapest one this build already depends on
CLAUDE_BUDGET = "0.02"
WORKER = "setup-try"
ESTIMATE_TEXT = "大約花不到 US$0.01"

RESULT_WORDS = {
    "success": "{name} 回應了，這個 AI 工具可以用。",
    "not_logged_in": "{name} 沒有成功回應，看起來還沒登入。請先按「登入」，登入好了再試一次。",
    "timeout": "等了 {secs} 秒，{name} 都沒有回應。可能是網路不通或它正在忙，稍後再試一次。",
    "not_found": "找不到 {name}。請先按「安裝」；剛裝好的話，可能要重新打開 VBear。",
    "bad_reply": "{name} 有回應，但回應的樣子 VBear 看不懂，沒辦法確認它正常。",
    "not_ended": "試的時候啟動的程式沒辦法確認已經結束，為了安全，VBear 先不再試。請重新打開 VBear。",
}


class TryRefused(Exception):
    """The try was not made (nothing was started, nothing was booked). ``status`` is the HTTP status the page gets."""

    def __init__(self, status: int, message: str):
        self.status = status
        super().__init__(message)


def argv_for(tool_id: str, binary: str, scratch: str) -> list[str]:
    """The headless call of one tool. The sentence is on stdin for Claude Code and Codex (``stdin_for``) and in the argv
    for the others; ``scratch`` is the empty folder the program is also started in."""
    if tool_id == "claude":
        return [binary, "-p", "--safe-mode", "--setting-sources", "", "--tools", "", "--strict-mcp-config",
                "--mcp-config", '{"mcpServers":{}}', "--model", CLAUDE_MODEL, "--output-format", "json",
                "--max-budget-usd", CLAUDE_BUDGET, "--no-session-persistence"]
    if tool_id == "codex":
        # --ask-for-approval is a top-level option of `codex` (`codex --help`); `codex exec --help` does not list it
        return [binary, "--ask-for-approval", "never", "exec", "--ignore-user-config", "--ignore-rules",
                "--skip-git-repo-check", "--ephemeral", "--sandbox", "read-only", "-c", 'web_search="disabled"',
                "--disable", "shell_tool", "--disable", "mcp", "--cd", scratch, "-"]
    if tool_id == "agy":
        return [binary, "-p", TRY_SENTENCE, "--output-format", "text", "--disable-slash-commands"]
    if tool_id == "grok":
        return [binary, "-p", TRY_SENTENCE, "--output-format", "plain", "--max-turns", "1", "--disable-web-search",
                "--no-memory", "--no-plan", "--no-subagents", "--cwd", scratch]
    if tool_id == "mcode":
        return [binary, "exec", TRY_SENTENCE, "--cwd", scratch, "--timeout", f"{int(TRY_TIMEOUT_S)}s", "--max-steps", "1",
                "--permission", "off", "--output-format", "text"]
    raise ValueError(f"沒有 {tool_id} 的試一下")


def stdin_for(tool_id: str) -> bytes:
    return TRY_SENTENCE.encode("utf-8") if tool_id in ("claude", "codex") else b""


def _reply(tool_id: str, out: bytes) -> tuple[bool, Decimal | None]:
    """(whether the tool answered, the cost it reported or None). The reply itself is looked at and dropped."""
    if tool_id == "claude":
        try:
            data = json.loads(out.decode("utf-8"))
        except (ValueError, RecursionError):
            return False, None
        if not isinstance(data, dict) or data.get("is_error") is not False:
            return False, None
        text = data.get("result")
        if not (isinstance(text, str) and text.strip()):
            return False, None
        cost = mt.money(data.get("total_cost_usd"))
        return True, cost
    return bool(out.decode("utf-8", "replace").strip()), None


def _result(tool: ai_tools.Tool, code: str, spent: Decimal) -> dict:
    words = RESULT_WORDS[code].format(name=tool.short, secs=int(TRY_TIMEOUT_S))
    return {"ok": True, "tool": tool.id, "success": code == "success", "result": code, "message": words,
            "spent_usd": mt.fmt(spent)}


def attempt(tool_id: str, ledger: Callable[[], dict], clock: Callable[[], float] = time.time) -> dict:
    """Try one tool once. ``ledger()`` is the day's ledger (meeting_runner.MeetingRunner.ledger): its spent_usd and
    daily_usd decide whether the day can take another CHARGE. -> the result for the page; TryRefused when nothing was made."""
    tool = next((t for t in ai_tools.REGISTRY if t.id == tool_id and t.id in ai_tools.setup_ids()), None)
    if tool is None:
        raise TryRefused(404, "沒有這個 AI 工具")
    binary = ai_tool_status.find_binary(tool.id)
    if binary is None:
        return _result(tool, "not_found", Decimal(0))
    try:
        fd = headless_cli.acquire_worker(WORKER)
    except headless_cli.HeadlessError as exc:
        if exc.code == "busy":
            raise TryRefused(409, "另一個 AI 工具正在試，等它結束再試。") from None
        raise TryRefused(409, "先前試的時候有程式沒辦法確認已經結束，VBear 為了安全不再試。請重新打開 VBear。") from None
    except OSError as exc:
        raise TryRefused(409, f"沒辦法開始試（{exc.strerror}）") from None
    try:
        try:
            led = ledger()
        except mt.MeetingError as exc:
            raise TryRefused(409, f"{exc}。為了不超過每天上限，現在不試。") from None
        spent, daily = mt.money(led.get("spent_usd")), mt.money(led.get("daily_usd"))
        if spent is None or daily is None:
            raise TryRefused(409, "VBear 無法確認今天已經花了多少，為了不超過每天上限，現在不試。")
        if spent + CHARGE > daily:
            raise TryRefused(409, f"今天已花 US${mt.fmt(spent)}，再試一次可能超過每天上限 US${mt.fmt(daily)}，所以今天不能再試了。"
                                  "可以明天再試，或到設定調高每天上限。")
        try:
            key = try_spend.start(tool.id, clock(), CHARGE)
        except StoreError as exc:
            raise TryRefused(409, f"{exc}。為了不超過每天上限，現在不試。") from None
        code, cost = "bad_reply", CHARGE
        try:
            run = headless_cli.run(lambda scratch: argv_for(tool.id, binary, scratch), stdin_for(tool.id), threading.Event(),
                                   timeout=TRY_TIMEOUT_S, max_output=MAX_OUTPUT, blocked_name=f"{WORKER}.blocked",
                                   prefix="vbear-setup-try-")
            answered, reported = _reply(tool.id, run.output)
            code = "success" if answered else "bad_reply"
            if answered and reported is not None:
                cost = reported
        except headless_cli.HeadlessError as exc:
            if exc.code == "timeout":
                code = "timeout"
            elif exc.code == "cli_failed":                  # a non-zero exit, or it ended before it read the sentence
                code = "not_logged_in"
            elif exc.code == "process_unconfirmed":
                code = "not_ended"
            else:
                code = "bad_reply"
        try:
            try_spend.finish(key, "done" if code == "success" else "failed", cost, clock())
        except StoreError:
            pass                    # the entry stays as a try that is still running: counted at its cap, never less
        ai_tool_status.invalidate()
        return _result(tool, code, cost)
    finally:
        os.close(fd)
