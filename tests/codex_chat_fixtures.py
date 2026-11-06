"""``codex app-server`` 0.163.0 transcripts recorded once with the real Codex (P38-0, a short probe in an isolated
temporary folder) and de-identified by the coordinator; tests/fixtures/codex-chat/ holds them. Each line is
``{"dir": "in"|"out"|"note", "line": ...}``: "in" is what was written to the server's stdin, "out" what it printed, "note"
the recorder's own remark (the command line, the end of the process).

a: initialize, two thread/start (the second with ``approvalPolicy: "untrusted"``), an MCP status list, then seven turns in
   one process: text; ``ls -a`` allowed; a command declined and the person's changed command asked again through
   ``turn/steer`` and allowed; ``rm`` declined; a file change allowed (it failed: the permission profile of that
   recording); one outside the work folder declined; two commands outside it allowed (the sandbox stopped both, and
   neither has an ``item/completed``).
b-resume: a new process, ``thread/resume``, the first token count repeated, a text turn and a file change, then
   ``thread/delete``.
c-legacy-sandbox: ``thread/start`` with the legacy ``workspace-write`` sandbox and a file change that succeeded.

The recordings hold what a person's own Codex setup brought in (an AGENTS.md in ``instructionSources``, MCP servers,
a sandbox with network access); ``clean`` turns those into what VBear's own CODEX_HOME and settings give, so that a
test can replay a chat as it will run and, without ``clean``, the chat as it must be stopped.

Paths and ids are the recorder's placeholders: WORK is the work folder, CODEX_HOME what ``initialize`` said, and
every thread id is one of the all-zero ids. The fake server (tests/fake_codex_app_server.py) puts in the real ones.
"""

from __future__ import annotations

import copy
import json
from dataclasses import dataclass, field
from pathlib import Path

DIR = Path(__file__).resolve().parent / "fixtures" / "codex-chat"
VERSION = "0.163.0"
NAMES = {"a": "codex-0.163.0-app-server-a", "b-resume": "codex-0.163.0-app-server-b-resume",
         "c-legacy-sandbox": "codex-0.163.0-app-server-c-legacy-sandbox"}
WORK = "/private/tmp/vbear-fake/work"
CODEX_HOME = "/Users/fake-user/.codex"

# The sensitive values the recordings carry in initialize and the account notifications (VBear must keep none).
SENSITIVE = ("/Users/fake-user/.codex", "vbear_probe", "fake_plan", "fake-host", "fake-limit", "fake-mcp",
             "00000000-0000-4000-8000-000000000001", "AGENTS.md", "userAgent", "codexHome", "installationId",
             "serverName", "planType", "credits", "platformOs", "instructionSources")

KINDS = {"initialize": "initialize", "thread/start": "thread_start", "thread/resume": "thread_resume",
         "mcpServerStatus/list": "mcp_list", "turn/start": "turn_start", "turn/steer": "turn_steer",
         "turn/interrupt": "turn_interrupt", "thread/delete": "thread_delete"}


def load(name: str) -> list[tuple[str, object]]:
    """[(dir, line)] of one transcript (``a``, ``b-resume`` or ``c-legacy-sandbox``), the recorder's notes left out."""
    rows = [json.loads(raw) for raw in (DIR / f"{NAMES[name]}.jsonl").read_text(encoding="utf-8").splitlines()]
    return [(r["dir"], r["line"]) for r in rows if r["dir"] != "note"]


def is_response(line) -> bool:
    return isinstance(line, dict) and "id" in line and "method" not in line


def is_request(line) -> bool:
    return isinstance(line, dict) and "id" in line and "method" in line


@dataclass
class Group:
    """One request VBear writes during the handshake with what the server printed around its answer."""
    request: dict
    pre: list = field(default_factory=list)          # printed after the request, before the answer
    response: dict = field(default_factory=dict)
    post: list = field(default_factory=list)         # printed right after the answer, up to VBear's next line


@dataclass
class Parsed:
    handshake: dict                                   # method -> Group (the last recorded one of each)
    turns: list                                       # per turn: [(dir, line)], the first being the turn/start
    delete: list                                      # the rows from thread/delete on ([] when not recorded)


def parse(name: str) -> Parsed:
    rows = load(name)
    first_turn = next(i for i, (d, ln) in enumerate(rows) if d == "in" and isinstance(ln, dict)
                      and ln.get("method") == "turn/start")
    handshake: dict[str, Group] = {}
    for i, (d, ln) in enumerate(rows[:first_turn]):
        if d != "in" or not is_request(ln):
            continue
        j = next(k for k in range(i + 1, first_turn) if rows[k][0] == "out" and is_response(rows[k][1])
                 and rows[k][1]["id"] == ln["id"])
        post, k = [], j + 1
        while k < first_turn and rows[k][0] != "in":
            post.append(rows[k])
            k += 1
        handshake[ln["method"]] = Group(ln, [r for r in rows[i + 1:j] if r[0] == "out"], rows[j][1], post)
    turns: list[list] = []
    delete: list = []
    for d, ln in rows[first_turn:]:
        if d == "in" and isinstance(ln, dict) and ln.get("method") == "turn/start":
            turns.append([])
        if d == "in" and isinstance(ln, dict) and ln.get("method") == "thread/delete":
            delete.append((d, ln))
        elif delete:
            delete.append((d, ln))
        else:
            turns[-1].append((d, ln))
    return Parsed(handshake, turns, delete)


def clean(line):
    """A recorded line as VBear's own CODEX_HOME and settings would have made it, or None when it would not exist:
    no MCP server, no instruction source, a sandbox without network access and without /tmp."""
    ln = copy.deepcopy(line)
    if not isinstance(ln, dict):
        return ln
    if ln.get("method") == "mcpServer/startupStatus/updated":
        return None
    body = ln.get("result") if isinstance(ln.get("result"), dict) else ln.get("params")
    if isinstance(body, dict):
        if "instructionSources" in body:
            body["instructionSources"] = []
        for key in ("sandbox", "sandboxPolicy"):
            if isinstance(body.get(key), dict) and body[key].get("type") == "workspaceWrite":
                body[key].update(networkAccess=False, excludeSlashTmp=True, excludeTmpdirEnvVar=True)
        if isinstance(body.get("threadSettings"), dict):
            sb = body["threadSettings"].get("sandboxPolicy")
            if isinstance(sb, dict) and sb.get("type") == "workspaceWrite":
                sb.update(networkAccess=False, excludeSlashTmp=True, excludeTmpdirEnvVar=True)
        if isinstance(body.get("data"), list) and "_scrubbed" in json.dumps(body["data"]):
            body["data"] = []                        # the answer to mcpServerStatus/list
    return ln


def linear(name: str, *, clean_it: bool = True) -> list[tuple[str, object]]:
    """The recording as one chat process would have it, in order: the handshake (initialize, the thread, the MCP list
    when recorded), then every turn. Rows of the first thread/start and the model list that VBear does not write are
    left out. ``clean_it`` applies ``clean``."""
    p = parse(name)
    rows: list[tuple[str, object]] = []
    for method in ("initialize", "thread/start", "thread/resume", "mcpServerStatus/list"):
        g = p.handshake.get(method)
        if g is None:
            continue
        rows.append(("in", g.request))
        rows += g.pre
        rows.append(("out", g.response))
        rows += g.post
        if method == "initialize":
            rows.append(("in", {"method": "initialized"}))
    for turn in p.turns:
        rows += turn
    rows += p.delete
    if not clean_it:
        return rows
    out = []
    for d, ln in rows:
        c = clean(ln)
        if c is not None:
            out.append((d, c))
    return out


def write_launcher(path, config_path) -> str:
    """An executable that runs tests/fake_codex_app_server.py with ``config_path`` as its configuration, the way
    tests/test_chat_daemon.py launches the fake Claude Code: the daemon gives the process a fixed environment, so the
    configuration cannot be found through HOME."""
    import os
    import sys
    repo = Path(__file__).resolve().parent.parent
    body = (f"#!{sys.executable} -I\nimport os, runpy, sys\nos.environ['FAKE_CODEX_CONFIG'] = {str(config_path)!r}\n"
            f"sys.path.insert(0, {str(repo)!r})\nrunpy.run_module('tests.fake_codex_app_server', run_name='__main__')\n")
    Path(path).write_text(body, encoding="utf-8")
    os.chmod(path, 0o755)
    return str(path)
