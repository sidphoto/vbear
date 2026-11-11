"""P40-2, P41-1, P42-2, P43-1: the things the chief of staff, the dispatch code, the group code, the memory code and the shared folder's
code never do, kept by the structure of the code (ADR 0003, 0006, 0007, 0008, 0009).

Never, whatever the person ticked in 「自己動手」:
  1. raise the daily limit (or any limit): no module here writes config.json;
  2. start a worker in full mode or open a terminal: no module here reaches the launch code, and every card it saves is safe mode;
  3. install a skill from the network: no module here reaches the skill code, and every card it saves has no skill;
  4. (P41-1) answer a question of a chat for the person: no module here calls the chat service's ``answer`` (or the daemon's
     ``chat_answer``, or names the route that does). Only the person's own press of 「允許這一次」 does, through the browser.
  5. (P42-2) save a word of memory on its own: the functions that write the memory (``add``, ``edit``, ``delete``, ``clear``,
     ``set_card``, ``export`` of vbear/memory.py, and its store) are called from vbear/server.py's /api/memory routes and from
     nowhere else, so that only the person's press in the browser (it carries ``X-VBear``) can change what every employee is told.
  (and 「自己動手」 itself is only ever turned on by the person, through POST /api/settings/autonomy)

  6. (P42-4) save a line of the person's memory: the modules of the memory suggestions (``memory_suggest*.py``) and the others do not
     import ``vbear.memory`` at all; its writing functions are the browser's routes' alone.
  7. (P43-1) open the shared folder to an employee on its own: the function that switches an employee on (``set_card`` of
     vbear/shared_folder.py, and its store) is called from vbear/server.py's /api/shared routes and from nowhere else, and the other
     scanned modules do not import ``vbear.shared_folder`` at all. The shared folder's own modules (``shared*.py``, ``runtime/shared*.py``)
     are held to every rule above: they never write config.json, start a terminal or a program, install a skill, make or change a role
     card, or answer a question of a chat.
  8. (P44-1, ADR 0010) save a skill of the person's on its own: the functions that write the skills (``add``, ``edit``, ``delete`` of
     vbear/skillbook.py, and its store) are called from vbear/server.py's /api/my-skills routes and from nowhere else, and the other
     scanned modules (the suggestions of skills, ``skillbook_suggest*.py``, included) do not import ``vbear.skillbook`` at all. The skills'
     own modules (``skillbook*.py``) are held to every rule above, and also never reach the skill cards of the AI tools (``scan``), the
     role cards, the chat service, a system prompt or the folders of the AI tools: a skill is only the words the person sends.

  8. (P44-2) a routine is made, changed, switched on or deleted by the person alone: the functions that do it (``create``, ``edit``,
     ``set_enabled``, ``delete``, ``set_settings`` of vbear/routines.py, and its store) are called from vbear/server.py's /api/routines routes
     and from nowhere else; the functions that record a run (``record_run``, ``new_run``, ``update_run``, ``run_store``) only from the
     routines' own modules and the console; the other scanned modules do not import ``vbear.routines`` or ``vbear.routine_runner`` at all;
     ``send_for_routine`` is named in vbear/chat_service.py and vbear/routine_runner.py and nowhere else; the routines' modules never make or
     change a role card. The routines' modules (``routine*.py``) are held to every rule above.
  9. (P44-2) a routine starts by itself only for 「自己動手」 item 3: vbear/routine_runner.py reads it with ``autonomy.read(...)["routines"]``
     in one place and never names ``autonomy`` as a key itself (the behaviour is tested in tests/test_routine_runner.py).

  11. (P44-4) a dispatch goes on by itself only for 「自己動手」 item 5: vbear/auto_continue.py reads it with ``autonomy.read(...)["auto_continue"]``
     in one place; only vbear/server.py imports ``auto_continue`` (the groups' modules do not: a group never goes on by itself), the only
     call that presses 「繼續」 as ``by="vbear"`` is the console's wiring, and the module reaches no chat (it is handed one function). The
     behaviour (item 5 off: ``resume`` is called 0 times) is tested in tests/test_auto_continue.py.
  12. (P44-3) the only program VBear starts that is not an AI tool is the one of vbear/keep_awake.py: ``routine*.py``, ``skillbook*.py`` and
     ``auto_continue.py`` stay under the ``subprocess`` / ``pty`` ban above (and start nothing by ``os.popen``, ``os.spawn*``, ``os.exec*``);
     no file of ``vbear/`` but keep_awake.py names the program; its argv is one constant list (the program, ``-i``, ``-w``, the console's own
     pid), passed without a shell; vbear/server.py is the only module that imports it and only ``serve()`` hands it to a console.

  13. (P45, ADR 0011) a team template is applied and saved by the person alone, and applying switches nothing on: the template modules
     (``template*.py``) are held to every rule above; the other scanned modules do not import them; they import no chat, no meeting, no
     network and no ``scan``, call no card-writing function, and every ``enabled`` they write is the plain ``False``; the routes of the
     templates are named in vbear/server.py and nowhere else in the package. (13d, 13e: the write functions of the applies and of the
     person's own templates, added by P45-2 and P45-3; the behaviour is tested in tests/test_templates_apply.py.)

  14. (P46, ADR 0012) an AGY chat asks every time, always runs in AGY's sandbox, and reads and changes nothing of the person's AGY settings:
     14a, 14b, 14c (P46-1: the protocol module's answers, its argv and settings, and ``BypassSandbox``; 14b also holds the AGY settings the
     chat environment writes and the launch records to the protocol's one table); 14d, 14g, 14h (P46-3: the six variables of the process
     environment, nothing of the person's own AGY folders read or changed by a whole fake chat, no ``session/set_mode``,
     ``session/set_config_option`` or ``session/load`` and a model only from the table); 14e, 14f (P46-5: no feature module reaches the AGY chat code, the AGY
     code reaches no feature's writer, and memory and the shared folder are off for an AGY employee until the person says yes to Google).
     The behaviour is tested in tests/test_agy_chat_protocol.py, tests/test_p46_agy_chat_daemon.py and tests/test_p46_features.py.

  15. (P47, ADR 0013) the plain navigation of v0.21.0 changes only what the screen shows. Five rules, tested where the thing is:
     15a  the advanced mode (settings, ``advanced_mode``) is only a display: in ``vbear/`` only ``config.py`` (its default) and ``server.py``
          (``CONFIG_WRITABLE`` and the line that makes it a boolean) name it, so no Python reads it to decide a behaviour; switching it changes
          none of the autonomy settings, the spending limits, the chat limits or the launch mode of an employee; ``web/app.js`` names it only to
          read it (``conf.advanced_mode``) and as the body of the settings switch's POST to /api/config. (This file, ``AdvancedModeIsADisplay`` and ``AdvancedModeChangesNothingElse``.)
     15b  nothing new is asked of the server and nothing about the data changes: the ``/api/`` paths ``web/app.js`` uses are a subset of those
          of v0.20.0, the routes of ``vbear/server.py`` are those of v0.20.0, and the kinds of a chat's record (``chat_store.KINDS``,
          ``_OPTIONAL``, ``_ALTERNATIVES``) and their fields are those of v0.20.0. (This file, ``NothingNewIsAsked``.)
     15c  the home page sends nothing by itself: only the press of 「送出」 sends one message (P47-2, tests/frontend/p47_home.cjs).
     15d  the spending limit and a routine are changed only by the person's press: the settings page sends nothing when it loads, the limit is
          saved by 「儲存」 alone, a routine kept on goes through ``confirmInPage`` when 「自己動手」 item 3 is on (P47-3, tests/frontend/p47_settings.cjs).
     15e  the lighter chat page keeps every confirmation and warning, and a spending limit that stops a message is said in plain words with a way to
          raise it, the person's words kept in the box (P47-4, tests/frontend/p47_chat.cjs).
     P47-6's documentation test checks that the five files exist and carry the number of their rule.

  16. (P48, ADR 0014) the easy start of v0.22.0 asks, shows and tells; it decides, logs in and spends nothing on its own. Seven rules, tested where the thing is:
     16a  the chat safety check is still asked for by a press and told with its full cost first; the confirm area is the only thing that sends it, and a
          check that passed is not carried to another version (P48-1, tests/frontend/p48_setup.cjs).
     16b  the picker logs nobody in and decides nothing: no card is preselected, labelled 建議 or put first; the pick is written only by 「選這個」 and 「換一家」
          writes nothing (P48-1, tests/frontend/p48_setup.cjs).
     16c  the home page says 載入中 while data is missing and never "nothing waits" or a number before the data is there (P48-2, tests/frontend/p48_home.cjs).
     16d  a chat with a card that waits is a row of its own; the page title is the number only and the app is handed the count and nothing else; the chat list is read at most
          every 30 seconds (P48-2, tests/frontend/p48_home.cjs).
     16e  the notification is local, count-only and off by default: the Mac app opens no connection and asks the system for the allowance in one place, only the person's
          press on the switch asks, the only new browser storage key besides the pick is ``vbear-notify`` (P48-4, tests/frontend/p48_notify.cjs,
          macos/test_waiting_bridge.sh, tests/test_p48_notify_static.py).
     16f  deleting a meeting, a proposal or a plan (and a chat, which kept its cost before) never lowers the day's bill: the cost stays for two days in ``spend-keep/`` and a bad file makes the day unknown
          (P48-5, this file, ``DeletingNeverLowersTheDay``, with tests/test_p48_spend_keep.py).
     16g  an opening choice and the chief-of-staff hint only put words in the box or ask for a preview; nothing is sent and nothing is spent by them (P48-3, tests/frontend/p48_chat.cjs).
     P48-7's documentation test (tests/test_p48_docs.py) checks that these files exist and carry the number of their rule; the first-CEO tool pick
     (``?tool=``, tests/test_p38_first_ceo.py ``WantedToolTests``) and the small fixes (tests/frontend/p48_sweep.cjs) are not rules but are tested beside them.

  17. (P50, ADR 0015) the chat-first home of v0.23.0 changes only what the screen shows: a greeting, one box, a side bar of recent employees and neutral colours; it sends nothing,
     reads nothing and decides nothing on its own. Three rules about the page's source, tested here on ``web/app.js`` (each with a made-up bad source that must fire), and where the thing is:
     17a  an example sentence only puts its words in the home box and puts the cursor there: the function that handles it makes no request and calls no send; the button's click
          calls only that function (P50-1, this file, ``ChatFirstHomeRules``, with tests/frontend/p50_home.cjs).
     17b  the side bar's 最近 asks for nothing and has no timer: the part of the page that draws it never calls ``api`` or names ``/api/chats``, and sets no ``setInterval`` or
          ``setTimeout``; it is drawn from the chat list the home page had already read (P50-2, this file, with tests/frontend/p50_nav.cjs).
     17c  only Cmd/Ctrl + Enter sends from the home box: the box's keydown handler calls the send function in that one case, and nothing else of the box (keypress, keyup, a form's
          submit) sends (P50-1, this file, with tests/frontend/p50_home.cjs).
     15b is not changed and still passes: v0.23.0 uses no ``/api/`` path that v0.20.0 did not. tests/test_p50_docs.py checks that these files exist and carry the number of their rule.

  18. (P51, ADR 0016) the chat page of v0.24.0 reads like text and lets you change whom you talk to; it is only what the screen shows. Four rules about the page's source, tested here on
     ``web/app.js`` (each with a made-up bad source that must fire), and where the thing is:
     18a  a fold on the chat page holds only tool, result, auto-allowed, cost and process lines: the card that waits, its decision, a refusal, an error, an odd message and the words said
          (yours and the employee's) are never in one, and a fold drops no line (P51-1, this file, ``ChatReadsLikeTextRules``, with tests/frontend/p51_chat.cjs).
     18b  changing whom you talk to sends nothing and writes nothing: the handlers of a pick call no send or request function, make no POST, PUT or DELETE and do not read ``/api/chats``;
          they only go to a page (or change whom the home box is for) and keep the unsent words in the page's memory (P51-2, this file, with tests/frontend/p51_who.cjs).
     18c  only Cmd/Ctrl + Enter sends from the chat page's box: its keydown handler calls ``send`` in that one case, and nothing else of the page (keypress, keyup, a form's submit) does
          (P51-2, this file, with tests/frontend/p51_who.cjs and tests/frontend/chat.cjs).
     18d  the line over a fold has no money: ``chatQuietSummary`` is only counts of kinds, and nothing else writes into it (ADR 0013 point 5; P51-1, this file, with tests/frontend/p51_chat.cjs).
     15b is not changed and still passes: v0.24.0 uses no ``/api/`` path that v0.20.0 did not. tests/test_p51_docs.py checks that these files exist and carry the number of their rule.

The scan reads the syntax tree (imports and calls) of every ``vbear/chief*.py``, ``vbear/dispatch*.py``, ``vbear/group*.py``,
``vbear/memory*.py``, ``vbear/runtime/memory*.py``, ``vbear/shared*.py``, ``vbear/runtime/shared*.py``, ``vbear/skillbook*.py`` and ``vbear/autonomy.py`` that exists, so the later modules of the chief of
staff, of dispatch, of groups and of memory (the suggestions, P42-4) are held to it the day they are added. The rules are below, as a table; the tests at the bottom run the scan on small made-up sources to show each rule fires,
so the scan cannot go quiet.
"""

from __future__ import annotations

import ast
import json
import os
import re
import unittest
from pathlib import Path
from unittest import mock

from vbear.runtime import cli_versions

PACKAGE = Path(__file__).resolve().parents[1] / "vbear"
PATTERNS = ("chief*.py", "dispatch*.py", "group*.py", "autonomy.py", "memory*.py", "runtime/memory*.py", "shared*.py", "runtime/shared*.py",
            "skillbook*.py", "routine*.py")

PATTERNS = PATTERNS + ("auto_continue.py",)    # (P44-4) item 5's module is held to every rule below
PATTERNS = PATTERNS + ("template*.py",)        # (P45-1, rule 13a) the team template modules are held to every rule below

# --- the table: (what it keeps from happening) -> what is not allowed -------------------------------------------------------

# modules that may not be imported at all (matched on the module and everything under it; the name is relative to ``vbear``)
BANNED_MODULES = {
    # 1. raising a limit: the only code that moves limits as a whole
    "daily_limit": "the daily limit (moves every limit at once)",
    "server": "the console's routes (they write config.json)",
    # 2. full mode / terminals / starting a worker by hand
    "agent_launch": "the launch of a card (full mode starts here)",
    "runtime.native": "terminals and native sessions",
    "runtime.agent_sessions": "the launch boundary",
    "runtime.proctrack": "the launch boundary",
    "runtime.daemon": "the launch boundary",
    "flow_executor": "the flow executor (full-mode style launch)",
    "risk_acceptance": "the acceptance of a risk",
    # 3. skills from the network
    "armory": "the skill store (installs)",
    "loadout": "equipping skills",
    "skill_fit": "skill search and install",
    # 5. the person's memory file: only the browser's /api/memory routes in server.py write it
    "memory": "the person's memory file (its writing functions are the browser's routes' alone)",
    # 7. the shared folder's switches: only the browser's /api/shared routes in server.py write them
    "shared_folder": "the shared folder's switches (its writing functions are the browser's routes' alone)",
    # 8. (P44-1) the person's skills file: only the browser's /api/my-skills routes in server.py write it, and the suggestions of skills
    # (skillbook_suggest*.py) only make a proposal, so none of the scanned modules imports it
    "skillbook": "the person's skills file (its writing functions are the browser's routes' alone)",
    # processes and dynamic code
    "subprocess": "starting a program",
    "pty": "starting a terminal",
    "importlib": "an import this scan cannot see",
}
# names a module-level ``from x import name`` or a call may not use, whatever they hang from
BANNED_CALLS = {
    "set_conf": "writes the console's config in memory and on disk",
    "write_private": "writes a private file (config.json is one)",
    "config_path": "the path of config.json",
    "__import__": "an import this scan cannot see",
    "exec": "code this scan cannot see",
    "eval": "code this scan cannot see",
    "system": "starting a program",
    "Popen": "starting a program",
}
# ``<anything resolved to vbear.config>.save`` (cfg.save, config.save, from .config import save as s)
CONFIG_MODULE = "config"
# the cards saved here: these keys must be a safe mode / no skill, written out
CARD_KEYS = {"launch_mode": lambda v: isinstance(v, ast.Constant) and v.value == "safe",
             "equipped_skill_ids": lambda v: isinstance(v, ast.List) and not v.elts}
BANNED_STRINGS = ("/api/native/", "/api/settings/autonomy", "/api/config", "/api/setup/daily-limit", "acceptForSession", "/answer",
                  "/api/templates")        # (13c) no scanned module names the routes of the team templates
# 4. answering a card of a chat: the chat service's method, the daemon's op, in a call, a reference, an import or a string
ANSWER_NAMES = {"answer": "answers a question of a chat for the person", "chat_answer": "the daemon's answer to a question of a chat"}


# 5. who may change the memory: the module's writers, and the only modules that may name them
MEMORY_MODULE = "memory"
MEMORY_WRITERS = {"add", "edit", "delete", "clear", "set_card", "export", "store"}
MEMORY_WRITER_HOMES = {"server.py", "memory.py"}          # the routes, and the module itself


def writer_uses(source: str, label: str, module: str, writers) -> list[str]:
    """Every place this source reaches one of ``writers`` of vbear/<module>.py: ``<the module>.add(...)`` however the module is named
    (``from . import memory as m``, ``import vbear.memory``, ``vbear.memory.add``), ``from .memory import add``, a ``getattr`` of
    one, and a star import of the module."""
    tree = ast.parse(source, filename=label)
    found: list[str] = []
    aliases: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            mod = node.module or ""
            if mod in ("", "vbear") or (node.level and mod == ""):
                aliases |= {a.asname or a.name for a in node.names if a.name == module}
            if mod.split(".")[-1] == module:
                for a in node.names:
                    if a.name == "*" or a.name in writers:
                        found.append(f"{label}:{node.lineno}: imports {module}.{a.name}")
        elif isinstance(node, ast.Import):
            aliases |= {a.asname for a in node.names if a.name in (f"vbear.{module}",) and a.asname}
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute) and node.attr in writers:
            base = node.value
            chain = (isinstance(base, ast.Attribute) and base.attr == module and isinstance(base.value, ast.Name)
                     and base.value.id == "vbear")
            if (isinstance(base, ast.Name) and base.id in aliases) or chain:
                found.append(f"{label}:{node.lineno}: reaches {module}.{node.attr}")
        elif (isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "getattr"
              and len(node.args) >= 2 and isinstance(node.args[0], ast.Name) and node.args[0].id in aliases
              and not (isinstance(node.args[1], ast.Constant) and node.args[1].value not in writers)):
            found.append(f"{label}:{node.lineno}: getattr of the {module} module")
    return found


def memory_writer_uses(source: str, label: str = "<source>") -> list[str]:
    return writer_uses(source, label, MEMORY_MODULE, MEMORY_WRITERS)


# 7. who may switch the shared folder on for an employee: the module's writers, and the only modules that may name them
SHARED_MODULE = "shared_folder"
# (P43-3) the person's ticks on the new-group dialog and on a dispatch's proposal card go through these; they all end in ``set_card``
SHARED_WRITERS = {"set_card", "store", "open_cards", "close_cards", "mark_dispatch", "open_for_dispatch"}
SHARED_WRITER_HOMES = {"server.py", "shared_folder.py"}          # the routes, and the module itself


def shared_writer_uses(source: str, label: str = "<source>") -> list[str]:
    return writer_uses(source, label, SHARED_MODULE, SHARED_WRITERS)


# 8. (P44-1) who may save a skill: the module's writers, and the only modules that may name them
SKILLBOOK_MODULE = "skillbook"
SKILLBOOK_WRITERS = {"add", "edit", "delete", "store"}
SKILLBOOK_WRITER_HOMES = {"server.py", "skillbook.py"}          # the routes, and the module itself
# what the modules of the skills (skillbook*.py) never reach, on top of the table above: the skill files and the role cards of the AI
# tools, the chat service, and every way into a system prompt or an AI tool's own folders (a skill is only the person's words)
SKILLBOOK_BANNED_MODULES = ("scan", "agent_profiles", "chat_service", "chat_protocol", "codex_chat_protocol", "runtime.chat_protocol",
                            "runtime.codex_chat_protocol", "runtime.daemon_chat", "runtime.native", "agent_sessions")
SKILLBOOK_BANNED_NAMES = ("combine", "prompt_sha", "save_profile", "create_profile", "update_profile", "delete_profile")
SKILLBOOK_BANNED_STRINGS = ("--append-system-prompt", "developerInstructions", "append-system-prompt", ".claude", ".codex", ".agents",
                            "codex-chat-home", "grok-chat-home", "SKILL.md", "skills.include_instructions")


def skillbook_writer_uses(source: str, label: str = "<source>") -> list[str]:
    return writer_uses(source, label, SKILLBOOK_MODULE, SKILLBOOK_WRITERS)


def skillbook_reaches(source: str, label: str = "<source>") -> list[str]:
    """What a module of the skills (skillbook*.py) reaches that it never may (P44-1): the modules and names above, and the folders of
    the AI tools, outside its docstrings."""
    tree = ast.parse(source, filename=label)
    docstrings = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) and node.body:
            first = node.body[0]
            if isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant) and isinstance(first.value.value, str):
                docstrings.add(id(first.value))
    found: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            for name in _module_of(node):
                for banned in SKILLBOOK_BANNED_MODULES:
                    if name == banned or name.startswith(banned + "."):
                        found.append(f"{label}:{node.lineno}: imports {name}")
            for a in node.names:
                if a.name in SKILLBOOK_BANNED_NAMES:
                    found.append(f"{label}:{node.lineno}: imports {a.name}")
        elif isinstance(node, ast.Attribute) and node.attr in SKILLBOOK_BANNED_NAMES:
            found.append(f"{label}:{node.lineno}: uses .{node.attr}")
        elif isinstance(node, ast.Name) and node.id in SKILLBOOK_BANNED_NAMES:
            found.append(f"{label}:{node.lineno}: uses {node.id}")
        elif isinstance(node, ast.Constant) and isinstance(node.value, str) and id(node) not in docstrings:
            for bad in SKILLBOOK_BANNED_STRINGS:
                if bad in node.value:
                    found.append(f"{label}:{node.lineno}: names {bad}")
    return found


# 9. (P44-2) who may change the routines: the module's writers, and the only modules that may name them
ROUTINES_MODULE = "routines"
ROUTINE_WRITERS = {"create", "edit", "set_enabled", "delete", "set_settings", "store", "settings_store"}
ROUTINE_WRITER_HOMES = {"server.py", "routines.py"}                   # the routes, and the module itself
ROUTINE_RUN_WRITERS = {"record_run", "new_run", "update_run", "run_store", "write_heartbeat"}
ROUTINE_RUN_HOMES = {"routines.py", "routine_runner.py", "server.py"}  # the module, the runner, and the routes of the person's decision
ROUTINE_ONLY_NAMES = {"send_for_routine": {"chat_service.py", "routine_runner.py"}}


def routine_writer_uses(source: str, label: str = "<source>") -> list[str]:
    return writer_uses(source, label, ROUTINES_MODULE, ROUTINE_WRITERS)


def routine_run_writer_uses(source: str, label: str = "<source>") -> list[str]:
    return writer_uses(source, label, ROUTINES_MODULE, ROUTINE_RUN_WRITERS)


def named_uses(source: str, label: str, name: str) -> list[str]:
    """Every place a source names ``name``: a call, an attribute, a plain name, an import, or a string."""
    tree = ast.parse(source, filename=label)
    found = []
    for node in ast.walk(tree):
        hit = ((isinstance(node, ast.Attribute) and node.attr == name) or (isinstance(node, ast.Name) and node.id == name)
               or (isinstance(node, ast.alias) and node.name == name) or (isinstance(node, ast.FunctionDef) and node.name == name)
               or (isinstance(node, ast.Constant) and node.value == name))
        if hit:
            found.append(f"{label}:{getattr(node, 'lineno', '?')}: names {name}")
    return found


# a role card is made or changed through these (the routines' modules never call them)
CARD_WRITERS = {"save_profile", "create_profile", "delete_profile", "duplicate_profile", "set_profile_enabled"}


def card_writer_calls(source: str, label: str = "<source>") -> list[str]:
    tree = ast.parse(source, filename=label)
    found = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            fn = node.func
            name = fn.id if isinstance(fn, ast.Name) else fn.attr if isinstance(fn, ast.Attribute) else None
            if name in CARD_WRITERS:
                found.append(f"{label}:{node.lineno}: calls {name}")
        elif isinstance(node, ast.ImportFrom):
            found += [f"{label}:{node.lineno}: imports {a.name}" for a in node.names if a.name in CARD_WRITERS]
    return found


def package_files() -> list[Path]:
    return sorted(p for p in PACKAGE.rglob("*.py") if "__pycache__" not in p.parts)


def scanned_files() -> list[Path]:
    seen: dict[str, Path] = {}
    for pattern in PATTERNS:
        for path in PACKAGE.glob(pattern):
            seen[path.name] = path
    return [seen[name] for name in sorted(seen)]


def _module_of(node, level_package: str = "vbear") -> list[str]:
    """The modules a import statement names, relative to the ``vbear`` package ("runtime.native", "daily_limit")."""
    if isinstance(node, ast.Import):
        return [a.name[len("vbear."):] if a.name.startswith("vbear.") else a.name for a in node.names]
    base = node.module or ""
    if node.level:  # ``from . import x`` / ``from .runtime import y`` inside vbear
        base = base if node.level == 1 else "?" + base
        out = [base] if base else []
        out += [f"{base}.{a.name}" if base else a.name for a in node.names]
        return out
    if base == "vbear" or base.startswith("vbear."):
        base = base[len("vbear."):] if base != "vbear" else ""
    out = [base] if base else []
    out += [f"{base}.{a.name}" if base else a.name for a in node.names]
    return out


def _banned_module(name: str):
    for banned, why in BANNED_MODULES.items():
        if name == banned or name.startswith(banned + "."):
            return why
    return None


def scan_source(source: str, label: str = "<source>") -> list[str]:
    """Every rule this source breaks, as readable lines (empty = clean)."""
    tree = ast.parse(source, filename=label)
    found: list[str] = []
    docstrings = set()  # prose may name a route; code may not
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) and node.body:
            first = node.body[0]
            if isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant) and isinstance(first.value.value, str):
                docstrings.add(id(first.value))
    config_names: set[str] = set()   # names that stand for vbear.config, or for config's save
    config_saves: set[str] = set()

    def add(node, text):
        found.append(f"{label}:{getattr(node, 'lineno', '?')}: {text}")

    for node in ast.walk(tree):
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            for name in _module_of(node):
                why = _banned_module(name)
                if why:
                    add(node, f"imports {name}: {why}")
            for a in node.names:
                if a.name in ANSWER_NAMES:
                    add(node, f"imports {a.name}: {ANSWER_NAMES[a.name]}")
            if isinstance(node, ast.Import):
                for a in node.names:
                    if a.name in ("vbear.config", CONFIG_MODULE):
                        config_names.add(a.asname or a.name.split(".")[-1])
            else:
                mod = (node.module or "")
                relative_root = node.level >= 1 and mod == ""
                for a in node.names:
                    if (relative_root or mod == "vbear") and a.name == CONFIG_MODULE:
                        config_names.add(a.asname or a.name)
                    if mod in (CONFIG_MODULE, "vbear.config") and a.name == "save":
                        config_saves.add(a.asname or a.name)
                    if a.name in BANNED_CALLS:
                        add(node, f"imports {a.name}: {BANNED_CALLS[a.name]}")
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute) and node.attr in ANSWER_NAMES:
            add(node, f"uses .{node.attr}: {ANSWER_NAMES[node.attr]}")
        if isinstance(node, ast.Call):
            fn = node.func
            name = fn.id if isinstance(fn, ast.Name) else fn.attr if isinstance(fn, ast.Attribute) else None
            if name in BANNED_CALLS:
                add(node, f"calls {name}: {BANNED_CALLS[name]}")
            if isinstance(fn, ast.Name) and fn.id in ANSWER_NAMES:
                add(node, f"calls {fn.id}: {ANSWER_NAMES[fn.id]}")
            if isinstance(fn, ast.Name) and fn.id in config_saves:
                add(node, "calls config.save: writes config.json")
            if (isinstance(fn, ast.Attribute) and fn.attr == "save" and isinstance(fn.value, ast.Name)
                    and fn.value.id in config_names):
                add(node, "calls config.save: writes config.json")
            for kw in node.keywords:
                if kw.arg in CARD_KEYS and not CARD_KEYS[kw.arg](kw.value):
                    add(node, f"{kw.arg} is not the fixed safe value")
        elif isinstance(node, ast.Dict):
            for key, value in zip(node.keys, node.values):
                if isinstance(key, ast.Constant) and key.value in CARD_KEYS and not CARD_KEYS[key.value](value):
                    add(node, f"{key.value} is not the fixed safe value")
        elif isinstance(node, (ast.Subscript,)) and isinstance(node.ctx, (ast.Store, ast.Del)):
            index = node.slice
            if isinstance(index, ast.Constant) and index.value in ("autonomy", "launch_mode", "equipped_skill_ids", "daily_usd",
                                                                    "meeting_limits", "chat_limits", "staffing_limits"):
                add(node, f"writes the setting {index.value!r}")
        elif isinstance(node, ast.Constant) and isinstance(node.value, str) and id(node) not in docstrings:
            for bad in BANNED_STRINGS:
                if bad in node.value:
                    add(node, f"names {bad}")
            if node.value in ANSWER_NAMES:
                add(node, f"names {node.value}: {ANSWER_NAMES[node.value]}")
    return found


class GuardOverTheRealModules(unittest.TestCase):
    def test_the_scan_covers_the_module_that_exists_and_every_chief_dispatch_and_group_module(self):
        names = [p.name for p in scanned_files()]
        self.assertIn("autonomy.py", names)
        for path in PACKAGE.iterdir():
            if path.suffix == ".py" and path.name.startswith(("chief", "dispatch", "group", "memory")):
                self.assertIn(path.name, names, "a chief, dispatch, group or memory module the scan does not cover")

    def test_the_groups_modules_are_there_to_be_scanned(self):
        names = [p.name for p in scanned_files()]
        self.assertIn("groups.py", names)
        self.assertIn("group_runner.py", names)


    def test_the_memory_modules_are_scanned(self):
        names = [p.name for p in scanned_files()]
        self.assertIn("memory.py", names)
        self.assertIn("memory_rules.py", names, "vbear/runtime/memory_rules.py")
        for path in PACKAGE.rglob("*.py"):
            if path.name.startswith("memory") and "__pycache__" not in path.parts:
                self.assertIn(path.name, names, "a memory module the scan does not cover")

    def test_only_the_memory_routes_of_the_console_write_the_memory(self):
        problems: list[str] = []
        for path in package_files():
            if path.name not in MEMORY_WRITER_HOMES:
                problems += memory_writer_uses(path.read_text(encoding="utf-8"), str(path.relative_to(PACKAGE)))
        self.assertEqual(problems, [], "\n".join(problems))

    def test_the_shared_folder_modules_are_scanned(self):
        names = [p.name for p in scanned_files()]
        self.assertIn("shared_folder.py", names)
        self.assertIn("shared_rules.py", names, "vbear/runtime/shared_rules.py")
        for path in PACKAGE.rglob("*.py"):
            if path.name.startswith("shared_") and "__pycache__" not in path.parts:
                self.assertIn(path.name, names, "a shared folder module the scan does not cover")

    def test_only_the_shared_routes_of_the_console_switch_an_employee_on(self):
        problems: list[str] = []
        for path in package_files():
            if path.name not in SHARED_WRITER_HOMES:
                problems += shared_writer_uses(path.read_text(encoding="utf-8"), str(path.relative_to(PACKAGE)))
        self.assertEqual(problems, [], "\n".join(problems))

    def test_the_console_does_call_the_writer_so_the_shared_rule_is_not_empty(self):
        source = (PACKAGE / "server.py").read_text(encoding="utf-8")
        self.assertIn("shared_folder.set_card(", source)
        self.assertNotEqual(shared_writer_uses(source, "server.py"), [])

    def test_the_chat_service_only_reads_the_shared_switches(self):
        calls = {m.group(1) for m in re.finditer(r"shared_folder\.(\w+)", (PACKAGE / "chat_service.py").read_text(encoding="utf-8"))}
        self.assertEqual(calls - {"py"}, {"for_card"})

    def test_the_console_does_call_every_writer_so_the_rule_is_not_empty(self):
        calls = {m.group(1) for m in re.finditer(r"memory_mod\.(\w+)", (PACKAGE / "server.py").read_text(encoding="utf-8"))}
        self.assertEqual(calls & (MEMORY_WRITERS - {"store"}), MEMORY_WRITERS - {"store"})
        self.assertEqual(memory_writer_uses((PACKAGE / "server.py").read_text(encoding="utf-8"), "server.py") != [], True)

    def test_the_memory_modules_are_there_to_be_scanned(self):
        names = [p.name for p in scanned_files()]
        for name in ("memory.py", "memory_suggest.py", "memory_suggest_runner.py"):
            self.assertIn(name, names)

    def test_the_skillbook_modules_are_scanned(self):
        names = [p.name for p in scanned_files()]
        self.assertIn("skillbook.py", names)
        for path in PACKAGE.rglob("*.py"):
            if path.name.startswith("skillbook") and "__pycache__" not in path.parts:
                self.assertIn(path.name, names, "a skillbook module the scan does not cover")

    def test_only_the_skill_routes_of_the_console_save_a_skill(self):
        problems: list[str] = []
        for path in package_files():
            if path.name not in SKILLBOOK_WRITER_HOMES:
                problems += skillbook_writer_uses(path.read_text(encoding="utf-8"), str(path.relative_to(PACKAGE)))
        self.assertEqual(problems, [], "\n".join(problems))

    def test_the_console_does_call_every_skill_writer_so_the_rule_is_not_empty(self):
        source = (PACKAGE / "server.py").read_text(encoding="utf-8")
        calls = {m.group(1) for m in re.finditer(r"skillbook_mod\.(\w+)", source)}
        self.assertEqual(calls & (SKILLBOOK_WRITERS - {"store"}), SKILLBOOK_WRITERS - {"store"})
        self.assertNotEqual(skillbook_writer_uses(source, "server.py"), [])

    def test_the_skillbook_modules_reach_no_skill_card_no_role_card_and_no_system_prompt(self):
        problems: list[str] = []
        for path in PACKAGE.glob("skillbook*.py"):
            problems += skillbook_reaches(path.read_text(encoding="utf-8"), path.name)
        self.assertEqual(problems, [], "\n".join(problems))

    def test_the_suggestions_of_skills_only_propose(self):
        for path in PACKAGE.glob("skillbook_suggest*.py"):
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if isinstance(node, (ast.Import, ast.ImportFrom)):
                    self.assertNotIn("skillbook", _module_of(node), f"{path.name} imports the skills file")

    def test_the_chat_service_and_the_runtime_know_nothing_of_skills(self):
        for module in ("chat_service.py", "runtime/daemon_chat.py", "runtime/chat_protocol.py", "runtime/codex_chat_protocol.py",
                       "runtime/agent_sessions.py", "runtime/memory_rules.py"):
            source = (PACKAGE / module).read_text(encoding="utf-8")
            self.assertNotIn("skillbook", source, module)
            self.assertNotIn("my-skills", source, module)

    def test_no_module_breaks_a_rule(self):
        problems: list[str] = []
        for path in scanned_files():
            problems += scan_source(path.read_text(encoding="utf-8"), path.name)
        self.assertEqual(problems, [], "\n".join(problems))


class ScanFiresOnEachRule(unittest.TestCase):
    """The scan is only worth something if it fires: one made-up source per rule."""

    def assertCaught(self, source: str, *needles: str):
        found = " | ".join(scan_source(source))
        self.assertTrue(found, f"nothing found in:\n{source}")
        for needle in needles:
            self.assertIn(needle, found)

    def test_raising_a_limit_or_writing_the_config(self):
        self.assertCaught("from . import config as cfg\ncfg.save({})\n", "config.save")
        self.assertCaught("from . import config\nconfig.save({})\n", "config.save")
        self.assertCaught("import vbear.config as c\nc.save({})\n", "config.save")
        self.assertCaught("from .config import save as s\ns({})\n", "config.save")
        self.assertCaught("from . import daily_limit\n", "daily_limit")
        self.assertCaught("from vbear import daily_limit\n", "daily_limit")
        self.assertCaught("from vbear.daily_limit import below_the_day\n", "daily_limit")
        self.assertCaught("def f(c):\n    c['meeting_limits'] = {}\n", "meeting_limits")
        self.assertCaught("def f(c):\n    c['autonomy'] = {'dispatch': True}\n", "autonomy")
        self.assertCaught("def f(console, c):\n    console.store.set_conf(c)\n", "set_conf")
        self.assertCaught("from .jsonstore import write_private\n", "write_private")
        self.assertCaught("def f(p):\n    p.write_private('x')\n", "write_private")
        self.assertCaught("from . import server\n", "server")
        self.assertCaught("URL = '/api/setup/daily-limit'\n", "daily-limit")
        self.assertCaught("URL = '/api/settings/autonomy'\n", "autonomy")
        self.assertCaught("URL = '/api/config'\n", "/api/config")

    def test_full_mode_and_terminals(self):
        self.assertCaught("from . import agent_launch\n", "agent_launch")
        self.assertCaught("from .agent_launch import launch\n", "agent_launch")
        self.assertCaught("from .runtime import native\n", "runtime.native")
        self.assertCaught("from .runtime import agent_sessions\n", "agent_sessions")
        self.assertCaught("from .runtime import proctrack\n", "proctrack")
        self.assertCaught("from .runtime.daemon import Daemon\n", "runtime.daemon")
        self.assertCaught("from .flow_executor import FlowExecutor\n", "flow_executor")
        self.assertCaught("from . import risk_acceptance\n", "risk_acceptance")
        self.assertCaught("import subprocess\n", "subprocess")
        self.assertCaught("import pty\n", "pty")
        self.assertCaught("import importlib\n", "importlib")
        self.assertCaught("import os\nos.system('x')\n", "system")
        self.assertCaught("X = __import__('os')\n", "__import__")
        self.assertCaught("URL = '/api/native/agent-launches'\n", "/api/native/")
        self.assertCaught("def f(ap):\n    ap.save_profile(launch_mode='full')\n", "launch_mode")
        self.assertCaught("def f(ap, m):\n    ap.save_profile(launch_mode=m)\n", "launch_mode")
        self.assertCaught("CARD = {'launch_mode': 'full'}\n", "launch_mode")
        self.assertCaught("def f(c):\n    c['launch_mode'] = 'full'\n", "launch_mode")
        self.assertCaught("REPLY = 'acceptForSession'\n", "acceptForSession")

    def test_skills_from_the_network(self):
        self.assertCaught("from . import armory\n", "armory")
        self.assertCaught("from .armory import install\n", "armory")
        self.assertCaught("from . import loadout\n", "loadout")
        self.assertCaught("from . import skill_fit\n", "skill_fit")
        self.assertCaught("def f(ap, ids):\n    ap.save_profile(equipped_skill_ids=ids)\n", "equipped_skill_ids")
        self.assertCaught("CARD = {'equipped_skill_ids': ['s-1']}\n", "equipped_skill_ids")

    def test_answering_a_question_of_a_chat_for_the_person(self):
        self.assertCaught("def f(chats, body):\n    return chats.answer('c-1', body)\n", "answer")
        self.assertCaught("def f(svc):\n    reply = svc.answer\n    return reply\n", ".answer")
        self.assertCaught("def f(svc):\n    return getattr(svc, 'answer')\n", "answer")
        self.assertCaught("from .chat_service import answer\n", "answer")
        self.assertCaught("def f(svc):\n    return svc._call('chat_answer', chat_id='c-1')\n", "chat_answer")
        self.assertCaught("def f(svc):\n    return svc.chat_answer('c-1')\n", "chat_answer")
        self.assertCaught("URL = '/api/chats/c-1/answer'\n", "/answer")
        self.assertCaught("def f(answer):\n    return answer('x')\n", "answer")


    def test_writing_the_memory_from_anywhere_but_the_console_routes(self):
        self.assertWrites("from . import memory\nmemory.add({'kind': 'work', 'text': 'x'})\n", "memory.add")
        self.assertWrites("from . import memory as m\ndef f(b):\n    return m.edit('m-1', b)\n", "memory.edit")
        self.assertWrites("from . import memory as memory_store\nmemory_store.delete('m-1')\n", "memory.delete")
        self.assertWrites("from .. import memory\nmemory.clear({'confirm': 'x'})\n", "memory.clear")
        self.assertWrites("from vbear import memory\nmemory.set_card({}, [])\n", "memory.set_card")
        self.assertWrites("from . import memory\nmemory.export()\n", "memory.export")
        self.assertWrites("from . import memory\nmemory.store.save({})\n", "memory.store")
        self.assertWrites("import vbear.memory\nvbear.memory.add({})\n", "memory.add")
        self.assertWrites("from .memory import add\n", "imports memory.add")
        self.assertWrites("from .memory import add as save_line\n", "imports memory.add")
        self.assertWrites("from vbear.memory import store\n", "imports memory.store")
        self.assertWrites("from .memory import *\n", "imports memory.*")
        self.assertWrites("from . import memory\nf = getattr(memory, 'add')\n", "getattr")
        self.assertWrites("from . import memory\nf = getattr(memory, name)\n", "getattr")

    def test_reading_the_memory_and_other_modules_with_the_same_names_are_allowed(self):
        self.assertEqual(memory_writer_uses(
            "from . import memory as memory_store\n"
            "def f(profile_id, engine):\n"
            "    got = memory_store.for_card(profile_id, engine)\n"
            "    return got, memory_store.view(), memory_store.cards_view([], [], [])\n"), [])
        self.assertEqual(memory_writer_uses(
            "from . import groups, memory_suggest\n"
            "def f(g, x):\n"
            "    groups.add(x)\n    g.delete(x)\n    memory_suggest.add(x)\n    return x.edit(1), x.clear()\n"), [])
        self.assertEqual(memory_writer_uses("import memory_mod\nmemory_mod.add({})\n"), [], "only the memory module, however it is named")

    def test_switching_an_employee_on_from_anywhere_but_the_console_routes(self):
        self.assertSwitches("from . import shared_folder\nshared_folder.set_card({}, [])\n", "shared_folder.set_card")
        self.assertSwitches("from . import shared_folder as sf\ndef f(b, cards):\n    return sf.set_card(b, cards, 'group')\n", "shared_folder.set_card")
        self.assertSwitches("from .. import shared_folder\nshared_folder.set_card({}, [])\n", "shared_folder.set_card")
        self.assertSwitches("from vbear import shared_folder\nshared_folder.set_card({}, [])\n", "shared_folder.set_card")
        self.assertSwitches("from . import shared_folder\nshared_folder.store.save({})\n", "shared_folder.store")
        self.assertSwitches("import vbear.shared_folder\nvbear.shared_folder.set_card({}, [])\n", "shared_folder.set_card")
        self.assertSwitches("from .shared_folder import set_card\n", "imports shared_folder.set_card")
        self.assertSwitches("from .shared_folder import set_card as open_it\n", "imports shared_folder.set_card")
        self.assertSwitches("from vbear.shared_folder import store\n", "imports shared_folder.store")
        self.assertSwitches("from .shared_folder import *\n", "imports shared_folder.*")
        self.assertSwitches("from . import shared_folder\nf = getattr(shared_folder, 'set_card')\n", "getattr")
        self.assertSwitches("from . import shared_folder\nf = getattr(shared_folder, name)\n", "getattr")

    def test_the_ticks_of_the_group_and_dispatch_dialogs_are_the_consoles_routes_alone(self):
        for name in ("open_cards", "close_cards", "mark_dispatch", "open_for_dispatch"):
            self.assertSwitches(f"from . import shared_folder\nshared_folder.{name}([], [], 'group')\n", f"shared_folder.{name}")
            self.assertSwitches(f"from .shared_folder import {name}\n", f"imports shared_folder.{name}")
            self.assertSwitches(f"from . import shared_folder as sf\ndef f(x):\n    return sf.{name}(x)\n", f"shared_folder.{name}")

    def test_the_console_calls_each_tick_function_and_the_modules_that_run_groups_and_dispatches_do_not_name_them(self):
        server_source = (PACKAGE / "server.py").read_text(encoding="utf-8")
        for name in ("open_cards", "close_cards", "mark_dispatch", "open_for_dispatch"):
            self.assertIn(f"shared_folder.{name}(", server_source)
            for module in ("groups.py", "group_runner.py", "dispatch.py", "dispatch_runner.py", "chief.py", "chief_runner.py",
                           "shared_changes.py", "chat_service.py"):
                self.assertNotIn(name, (PACKAGE / module).read_text(encoding="utf-8"), f"{module} names {name}")

    def test_an_employee_a_dispatch_makes_is_opened_only_by_the_consoles_hook(self):
        source = (PACKAGE / "server.py").read_text(encoding="utf-8")
        hook = source[source.index("def _on_new_employee"):]
        hook = hook[:hook.index("\n    def ", 10)]
        self.assertIn("shared_folder.open_for_dispatch(", hook)
        self.assertEqual(source.count("shared_folder.open_for_dispatch("), 1, "nowhere else")
        # the dispatcher is handed the hook and calls it with two ids; it knows nothing of the folder
        dispatch_source = (PACKAGE / "dispatch.py").read_text(encoding="utf-8")
        self.assertIn("self.on_new_employee(", dispatch_source)
        self.assertNotIn("shared_folder", dispatch_source)

    def test_the_modules_that_hand_file_names_on_only_read_the_folders_names(self):
        for module in ("shared_changes.py", "runtime/shared_rules.py"):
            tree = ast.parse((PACKAGE / module).read_text(encoding="utf-8"))
            names = {n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)} | {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)}
            self.assertFalse(names & {"set_card", "answer", "chat_answer", "save_profile", "set_conf", "write_private", "Popen", "system"}, module)

    def test_reading_the_switches_and_other_modules_with_the_same_names_are_allowed(self):
        self.assertEqual(shared_writer_uses(
            "from . import shared_folder\n"
            "def f(profile_id, engine):\n"
            "    return shared_folder.for_card(profile_id, engine), shared_folder.view([]), shared_folder.reveal(None)\n"), [])
        self.assertEqual(shared_writer_uses("from . import memory\ndef f(b, c):\n    return memory.set_card(b, c)\n"), [],
                         "the memory's own set_card is the memory rule's business")
        self.assertEqual(shared_writer_uses("import other\nother.set_card({}, [])\n"), [], "only the shared folder module")

    def assertSwitches(self, source: str, *needles: str):
        found = " | ".join(shared_writer_uses(source))
        self.assertTrue(found, f"nothing found in:\n{source}")
        for needle in needles:
            self.assertIn(needle, found)

    def test_the_other_modules_may_not_import_the_shared_folder_module_at_all(self):
        self.assertCaught("from . import shared_folder\n", "shared_folder")
        self.assertCaught("from .shared_folder import for_card\n", "shared_folder")
        self.assertCaught("from vbear import shared_folder\n", "shared_folder")
        self.assertCaught("import vbear.shared_folder as sf\n", "shared_folder")

    def test_the_shared_folder_modules_obey_the_rules_of_the_others(self):
        self.assertCaught("from . import config as cfg\ncfg.save({})\n", "config.save")           # the same table, now over shared*.py
        self.assertCaught("from .runtime import daemon\n", "runtime.daemon")
        self.assertCaught("import subprocess\nsubprocess.run(['/usr/bin/open', '/x'])\n", "subprocess")
        self.assertCaught("def f(svc):\n    return svc.answer('c-1', {})\n", "answer")
        self.assertCaught("def f(ap):\n    ap.save_profile(launch_mode='full')\n", "launch_mode")
        self.assertCaught("from . import armory\n", "armory")

    def test_the_memory_modules_obey_the_rules_of_the_others(self):
        self.assertCaught("from . import config as cfg\ncfg.save({})\n", "config.save")      # the same table, now over memory*.py
        self.assertCaught("from .runtime import daemon\n", "runtime.daemon")

    def assertWrites(self, source: str, *needles: str):
        found = " | ".join(memory_writer_uses(source))
        self.assertTrue(found, f"nothing found in:\n{source}")
        for needle in needles:
            self.assertIn(needle, found)

    def test_saving_a_line_of_memory(self):
        self.assertCaught("from . import memory\n", "memory")
        self.assertCaught("from .memory import add\n", "memory")
        self.assertCaught("from vbear import memory\n", "memory")
        self.assertCaught("from vbear.memory import for_card\n", "memory")
        self.assertCaught("import vbear.memory as m\n", "memory")

    def assertSkillWrites(self, source: str, *needles: str):
        found = " | ".join(skillbook_writer_uses(source))
        self.assertTrue(found, f"nothing found in:\n{source}")
        for needle in needles:
            self.assertIn(needle, found)

    def test_saving_a_skill_from_anywhere_but_the_console_routes(self):
        self.assertSkillWrites("from . import skillbook\nskillbook.add({'name': 'x', 'text': 'y'})\n", "skillbook.add")
        self.assertSkillWrites("from . import skillbook as book\ndef f(b):\n    return book.edit('k-1', b)\n", "skillbook.edit")
        self.assertSkillWrites("from .. import skillbook\nskillbook.delete('k-1')\n", "skillbook.delete")
        self.assertSkillWrites("from vbear import skillbook\nskillbook.store.save({})\n", "skillbook.store")
        self.assertSkillWrites("import vbear.skillbook\nvbear.skillbook.add({})\n", "skillbook.add")
        self.assertSkillWrites("from .skillbook import add\n", "imports skillbook.add")
        self.assertSkillWrites("from .skillbook import delete as drop\n", "imports skillbook.delete")
        self.assertSkillWrites("from vbear.skillbook import store\n", "imports skillbook.store")
        self.assertSkillWrites("from .skillbook import *\n", "imports skillbook.*")
        self.assertSkillWrites("from . import skillbook\nf = getattr(skillbook, 'add')\n", "getattr")
        self.assertSkillWrites("from . import skillbook\nf = getattr(skillbook, name)\n", "getattr")

    def test_reading_the_skills_and_other_modules_with_the_same_names_are_allowed(self):
        self.assertEqual(skillbook_writer_uses("from . import skillbook\ndef f():\n    return skillbook.view()\n"), [])
        self.assertEqual(skillbook_writer_uses("from . import memory, groups\ndef f(b, g):\n    memory.add(b)\n    groups.edit(g)\n"), [],
                         "the memory's own writers are the memory rule's business")
        self.assertEqual(skillbook_writer_uses("import other\nother.add({})\n"), [], "only the skills module")

    def test_the_other_modules_may_not_import_the_skills_module_at_all(self):
        self.assertCaught("from . import skillbook\n", "skillbook")
        self.assertCaught("from .skillbook import view\n", "skillbook")
        self.assertCaught("from vbear import skillbook\n", "skillbook")
        self.assertCaught("import vbear.skillbook as k\n", "skillbook")

    def test_the_skillbook_modules_obey_the_rules_of_the_others(self):
        self.assertCaught("from . import config as cfg\ncfg.save({})\n", "config.save")           # the same table, now over skillbook*.py
        self.assertCaught("import subprocess\nsubprocess.run(['x'])\n", "subprocess")
        self.assertCaught("from .runtime import daemon\n", "runtime.daemon")
        self.assertCaught("def f(svc):\n    return svc.answer('c-1', {})\n", "answer")
        self.assertCaught("def f(ap):\n    ap.save_profile(launch_mode='full')\n", "launch_mode")
        self.assertCaught("from . import armory\n", "armory")
        self.assertCaught("from . import loadout\n", "loadout")
        self.assertCaught("from . import skill_fit\n", "skill_fit")

    def test_the_skillbook_modules_never_reach_the_skill_files_the_role_cards_or_a_system_prompt(self):
        for source, needle in (("from . import scan\n", "imports scan"), ("from .scan.document import redact\n", "imports scan.document"),
                               ("from . import agent_profiles\n", "imports agent_profiles"), ("from .chat_service import ChatService\n", "imports chat_service"),
                               ("from .runtime import memory_rules\nmemory_rules.combine(None, None)\n", "uses .combine"),
                               ("from .runtime.memory_rules import prompt_sha\n", "imports prompt_sha"),
                               ("def f(ap):\n    return ap.save_profile({})\n", "uses .save_profile"),
                               ("def f(ap):\n    return ap.create_profile({})\n", "uses .create_profile"),
                               ("ARG = '--append-system-prompt'\n", "append-system-prompt"), ("KEY = 'developerInstructions'\n", "developerInstructions"),
                               ("DIR = '~/.claude/skills'\n", ".claude"), ("DIR = '~/.codex/skills'\n", ".codex"), ("DIR = '~/.agents'\n", ".agents"),
                               ("DIR = 'codex-chat-home'\n", "codex-chat-home"), ("NAME = 'SKILL.md'\n", "SKILL.md")):
            with self.subTest(source=source):
                found = " | ".join(skillbook_reaches(source))
                self.assertIn(needle, found, f"nothing found in:\n{source}")
        self.assertEqual(skillbook_reaches('"""A docstring may say .claude and SKILL.md."""\nfrom . import config as cfg\n'), [])

    def test_what_is_allowed_is_clean(self):
        clean = (
            "from . import agent_profiles as ap, autonomy, config as cfg, meetings\n"
            "from .runtime import chat_store\n"
            "from .chat_service import ChatService\n"
            "from .runtime import memory_rules\n"
            "from . import memory_suggest\n"
            "def f(conf):\n"
            "    limits = cfg.load()\n"
            "    on = autonomy.read(conf)\n"
            "    return ap.save_profile({'launch_mode': 'safe', 'equipped_skill_ids': []}), ap.save_profile(launch_mode='safe', equipped_skill_ids=[])\n"
            "def g(chats, chat_id, text):\n"
            "    got = chats.get(chat_id, 0)\n"
            "    chats.send_for_group(chat_id, text)\n"
            "    return got, chats.stop(chat_id, {}), chats.close(chat_id), 'The answer never came'\n"
        )
        self.assertEqual(scan_source(clean), [])


# 8b. (P44-5) the suggestions of skills only propose: they do not name the skills' file or its routes, and the console's functions that serve
# them never touch the skills module (the person's own press of 「存」 in the browser is what calls POST /api/my-skills)
SKILL_SUGGEST_BANNED_STRINGS = ("skills.json", "/api/my-skills", "skillbook_mod")
SKILL_SUGGEST_SERVERS = ("_skill_suggest_call", "_skill_suggest_sources")


def skill_suggest_names(source: str, label: str = "<source>") -> list[str]:
    """What a module of the suggestions of skills names that it never may: the skills' file, the skills' routes, the console's alias of the
    skills module (docstrings and comments are not code, so they may talk about them)."""
    tree = ast.parse(source, filename=label)
    docstrings = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) and node.body:
            first = node.body[0]
            if isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant) and isinstance(first.value.value, str):
                docstrings.add(id(first.value))
    found: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str) and id(node) not in docstrings:
            found += [f"{label}:{node.lineno}: names {bad}" for bad in SKILL_SUGGEST_BANNED_STRINGS if bad in node.value]
        elif isinstance(node, ast.Name) and node.id in ("skillbook", "skillbook_mod"):
            found.append(f"{label}:{node.lineno}: uses {node.id}")
        elif isinstance(node, ast.Attribute) and node.attr in ("skillbook", "skillbook_mod"):
            found.append(f"{label}:{node.lineno}: uses .{node.attr}")
    return found


def console_functions_touching_skills(source: str, names=SKILL_SUGGEST_SERVERS) -> list[str]:
    """The functions of the console named ``names`` that touch the skills module (``skillbook_mod``, ``skillbook``)."""
    found: list[str] = []
    for node in ast.walk(ast.parse(source, filename="server.py")):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name in names:
            for sub in ast.walk(node):
                if (isinstance(sub, ast.Name) and sub.id in ("skillbook_mod", "skillbook")) or (
                        isinstance(sub, ast.Attribute) and sub.attr in ("skillbook_mod", "skillbook")):
                    found.append(f"{node.name}:{sub.lineno}: touches the skills module")
    return found


class SkillSuggestRules(unittest.TestCase):
    def test_the_suggestion_modules_exist_and_are_scanned_by_every_rule(self):
        names = {p.name for p in PACKAGE.glob("skillbook_suggest*.py")}
        self.assertEqual(names, {"skillbook_suggest.py", "skillbook_suggest_runner.py"})
        scanned = {p.name for p in scanned_files()}
        self.assertLessEqual(names, scanned)

    def test_they_name_neither_the_skills_file_nor_its_routes(self):
        problems: list[str] = []
        for path in PACKAGE.glob("skillbook_suggest*.py"):
            problems += skill_suggest_names(path.read_text(encoding="utf-8"), path.name)
        self.assertEqual(problems, [], "\n".join(problems))

    def test_the_consoles_suggestion_functions_never_touch_the_skills_module(self):
        source = (PACKAGE / "server.py").read_text(encoding="utf-8")
        self.assertEqual(console_functions_touching_skills(source), [])
        defined = {n.name for n in ast.walk(ast.parse(source)) if isinstance(n, ast.FunctionDef)}
        self.assertTrue(set(SKILL_SUGGEST_SERVERS) <= defined, "the functions this rule is about are not there any more")

    def test_the_rule_fires_on_small_made_up_sources(self):
        self.assertIn("skills.json", " ".join(skill_suggest_names("PATH = 'skillbook/skills.json'\n")))
        self.assertIn("/api/my-skills", " ".join(skill_suggest_names("URL = '/api/my-skills'\n")))
        self.assertIn("skillbook_mod", " ".join(skill_suggest_names("def f(c):\n    return skillbook_mod.add(c)\n")))
        self.assertEqual(skill_suggest_names('"""talks of skills.json"""\nX = 1\n'), [])
        self.assertNotEqual(console_functions_touching_skills("def _skill_suggest_call(self):\n    return skillbook_mod.add({})\n"), [])
        self.assertEqual(console_functions_touching_skills("def other(self):\n    return skillbook_mod.add({})\n"), [])
        self.assertEqual(console_functions_touching_skills("def _skill_suggest_call(self):\n    return 1\n"), [])


class RoutineRules(unittest.TestCase):
    """P44-2: rules 8 and 9 over the real modules, and the small made-up sources that show the scan fires."""

    def test_the_routines_modules_are_scanned(self):
        names = [p.name for p in scanned_files()]
        for name in ("routine_rules.py", "routines.py", "routine_runner.py"):
            self.assertIn(name, names)
        for path in PACKAGE.rglob("routine*.py"):
            self.assertIn(path.name, names, "a routines module the scan does not cover")

    def test_only_the_routes_of_the_console_change_a_routine(self):
        problems: list[str] = []
        for path in package_files():
            if path.name not in ROUTINE_WRITER_HOMES:
                problems += routine_writer_uses(path.read_text(encoding="utf-8"), str(path.relative_to(PACKAGE)))
        self.assertEqual(problems, [], "\n".join(problems))

    def test_the_console_does_call_each_writer_so_the_rule_is_not_empty(self):
        source = (PACKAGE / "server.py").read_text(encoding="utf-8")
        used = {m.group(1) for m in re.finditer(r"routines_mod\.(\w+)", source)}
        self.assertEqual(used & {"create", "edit", "delete", "set_settings"}, {"create", "edit", "delete", "set_settings"})
        self.assertNotEqual(routine_writer_uses(source, "server.py"), [])

    def test_only_the_routines_own_modules_and_the_console_record_a_run(self):
        problems: list[str] = []
        for path in package_files():
            if path.name not in ROUTINE_RUN_HOMES:
                problems += routine_run_writer_uses(path.read_text(encoding="utf-8"), str(path.relative_to(PACKAGE)))
        self.assertEqual(problems, [], "\n".join(problems))
        runner = (PACKAGE / "routine_runner.py").read_text(encoding="utf-8")
        self.assertNotEqual(routine_run_writer_uses(runner, "routine_runner.py"), [], "the runner does record runs, so the rule is not empty")

    def test_the_other_scanned_modules_do_not_import_the_routines_at_all(self):
        problems: list[str] = []
        for path in scanned_files():
            if path.name.startswith("routine"):
                continue
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if isinstance(node, (ast.Import, ast.ImportFrom)) and any(
                        n == m or n.startswith(m + ".") for n in _module_of(node) for m in ("routines", "routine_runner", "routine_rules")):
                    problems.append(f"{path.name}:{node.lineno}: imports the routines")
        self.assertEqual(problems, [], "\n".join(problems))

    def test_send_for_routine_is_named_only_by_the_chat_service_and_the_runner(self):
        problems: list[str] = []
        seen: set[str] = set()
        for path in package_files():
            hits = named_uses(path.read_text(encoding="utf-8"), path.name, "send_for_routine")
            if hits:
                seen.add(path.name)
                if path.name not in ROUTINE_ONLY_NAMES["send_for_routine"]:
                    problems += hits
        self.assertEqual(problems, [], "\n".join(problems))
        self.assertEqual(seen, {"chat_service.py", "routine_runner.py"})

    def test_the_routines_modules_never_make_or_change_a_role_card(self):
        problems: list[str] = []
        for path in PACKAGE.glob("routine*.py"):
            problems += card_writer_calls(path.read_text(encoding="utf-8"), path.name)
        self.assertEqual(problems, [], "\n".join(problems))

    def test_the_routines_modules_never_name_a_chat_answer_or_the_config(self):
        for path in PACKAGE.glob("routine*.py"):
            tree = ast.parse(path.read_text(encoding="utf-8"))
            names = {n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)} | {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)}
            self.assertFalse(names & {"answer", "chat_answer", "set_conf", "write_private", "config_path", "Popen", "system", "subprocess"}, path.name)

    def test_item_3_is_read_in_one_place_and_the_runner_never_names_the_autonomy_block(self):
        source = (PACKAGE / "routine_runner.py").read_text(encoding="utf-8")
        self.assertEqual(len(re.findall(r"autonomy\.read\(", source)), 1)
        self.assertIn('["routines"]', source)
        tree = ast.parse(source)
        docstrings = {id(n.body[0].value) for n in ast.walk(tree) if isinstance(n, (ast.Module, ast.FunctionDef, ast.ClassDef)) and n.body
                      and isinstance(n.body[0], ast.Expr) and isinstance(n.body[0].value, ast.Constant)}
        strings = [n.value for n in ast.walk(tree) if isinstance(n, ast.Constant) and isinstance(n.value, str) and id(n) not in docstrings]
        self.assertNotIn("autonomy", strings, "the block is read through autonomy.read and no other way")
        self.assertNotIn("auto_continue", strings)

    # ---- the made-up sources: each rule fires ----------------------------------------------------------------------------

    def test_changing_a_routine_from_anywhere_but_the_console_routes(self):
        for name in sorted(ROUTINE_WRITERS):
            self.assertTrue(routine_writer_uses(f"from . import routines\nroutines.{name}()\n"), name)
            self.assertTrue(routine_writer_uses(f"from . import routines as rt\ndef f(x):\n    return rt.{name}(x)\n"), name)
            self.assertTrue(routine_writer_uses(f"from .routines import {name}\n"), name)
        self.assertTrue(routine_writer_uses("import vbear.routines\nvbear.routines.create({})\n"))
        self.assertTrue(routine_writer_uses("from .routines import *\n"))
        self.assertTrue(routine_writer_uses("from . import routines\nf = getattr(routines, name)\n"))
        self.assertTrue(routine_writer_uses("from . import routines\nroutines.store.save({})\n"))

    def test_reading_the_routines_is_allowed(self):
        self.assertEqual(routine_writer_uses("from . import routines\ndef f():\n    return routines.read_routines(), routines.chat_titles(), routines.starting_chat('c')\n"), [])
        self.assertEqual(routine_writer_uses("from . import groups\ngroups.create({})\ngroups.delete('g')\n"), [], "other modules with the same names")

    def test_recording_a_run_from_anywhere_else(self):
        for name in sorted(ROUTINE_RUN_WRITERS):
            self.assertTrue(routine_run_writer_uses(f"from . import routines\nroutines.{name}\n"), name)
        self.assertTrue(routine_run_writer_uses("from .routines import new_run\n"))
        self.assertEqual(routine_run_writer_uses("from . import routines\nroutines.read_runs()\n"), [])

    def test_naming_send_for_routine_elsewhere(self):
        for source in ("def f(chats, c):\n    return chats.send_for_routine(c, 'x')\n", "from .chat_service import send_for_routine\n",
                       "f = getattr(chats, 'send_for_routine')\n", "send_for_routine = 1\n", "def send_for_routine(self):\n    pass\n"):
            self.assertTrue(named_uses(source, "x.py", "send_for_routine"), source)
        self.assertEqual(named_uses("def f(chats):\n    return chats.send_for_group(1, 'x')\n", "x.py", "send_for_routine"), [])

    def test_making_a_role_card_from_the_routines_modules(self):
        for source in ("from . import agent_profiles as ap\nap.save_profile(None, {})\n", "from .agent_profiles import create_profile\n",
                       "def f(ap):\n    ap.delete_profile('x')\n"):
            self.assertTrue(card_writer_calls(source), source)
        self.assertEqual(card_writer_calls("def f(ap):\n    return ap.get_profile_readonly('x')\n"), [])

    def test_the_routines_modules_obey_the_rules_of_the_others(self):
        self.assertCaughtHere("from . import config as cfg\ncfg.save({})\n", "config.save")
        self.assertCaughtHere("import subprocess\n", "subprocess")
        self.assertCaughtHere("from . import agent_launch\n", "agent_launch")
        self.assertCaughtHere("def f(svc):\n    return svc.answer('c-1', {})\n", "answer")
        self.assertCaughtHere("from . import armory\n", "armory")
        self.assertCaughtHere("from . import server\n", "server")
        self.assertCaughtHere("def f(c):\n    c['autonomy'] = {'routines': True}\n", "autonomy")
        self.assertCaughtHere("def f(c):\n    c['daily_usd'] = 1\n", "daily_usd")
        self.assertCaughtHere("URL = '/api/settings/autonomy'\n", "autonomy")
        self.assertCaughtHere("import os\nos.system('caffeinate')\n", "system")

    def assertCaughtHere(self, source: str, needle: str):
        found = " | ".join(scan_source(source))
        self.assertTrue(found, source)
        self.assertIn(needle, found)


# 13. (P45, ADR 0011) the team templates: who may import them, what they may import, and the one thing they may never write as true
TEMPLATE_MODULES = ("templates", "templates_builtin", "templates_apply", "templates_mine")
TEMPLATE_BANNED_IMPORTS = ("chat_service", "meeting_runner", "board_engine", "headless_cli", "auto_continue", "keep_awake", "scan",
                           "urllib", "http", "socket", "chief", "chief_runner", "dispatch", "dispatch_runner", "groups", "group_runner")


def imports_of(source: str, names, label: str = "<source>") -> list[str]:
    """Every import in ``source`` of one of ``names`` (a module or anything under it, ``vbear.`` and relative forms alike)."""
    tree = ast.parse(source, filename=label)
    found = []
    for node in ast.walk(tree):
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            for module in _module_of(node):
                if any(module == n or module.startswith(n + ".") for n in names):
                    found.append(f"{label}:{node.lineno}: imports {module}")
    return found


def enabled_not_false(source: str, label: str = "<source>") -> list[str]:
    """Every place a source gives ``enabled`` a value that is not the plain ``False``: a dict key, a keyword, or a subscript assignment."""
    is_false = lambda v: isinstance(v, ast.Constant) and v.value is False
    tree = ast.parse(source, filename=label)
    found = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Dict):
            for key, value in zip(node.keys, node.values):
                if isinstance(key, ast.Constant) and key.value == "enabled" and not is_false(value):
                    found.append(f"{label}:{node.lineno}: enabled is not False")
        elif isinstance(node, ast.keyword) and node.arg == "enabled" and not is_false(node.value):
            found.append(f"{label}:{node.value.lineno}: enabled is not False")
        elif isinstance(node, ast.Assign):
            for target in node.targets:
                if (isinstance(target, ast.Subscript) and isinstance(target.slice, ast.Constant) and target.slice.value == "enabled"
                        and not is_false(node.value)):
                    found.append(f"{label}:{node.lineno}: enabled is not False")
        elif isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr in ("update", "setdefault"):
            for arg in node.args:
                if isinstance(arg, ast.Dict):
                    for key, value in zip(arg.keys, arg.values):
                        if isinstance(key, ast.Constant) and key.value == "enabled" and not is_false(value):
                            found.append(f"{label}:{node.lineno}: enabled is not False")
    return found


def string_uses(source: str, needle: str, label: str = "<source>") -> list[str]:
    """Every string constant of the code (not a docstring) that holds ``needle``."""
    tree = ast.parse(source, filename=label)
    docstrings = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) and node.body:
            first = node.body[0]
            if isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant) and isinstance(first.value.value, str):
                docstrings.add(id(first.value))
    return [f"{label}:{n.lineno}: names {needle}" for n in ast.walk(tree)
            if isinstance(n, ast.Constant) and isinstance(n.value, str) and id(n) not in docstrings and needle in n.value]


class TemplateRules(unittest.TestCase):
    """P45-1, rules 13a to 13c over the real modules, and the small made-up sources that show the scan fires. 13d and 13e (the write
    functions of the applies and of the person's own templates) are added with those write functions."""

    def template_files(self):
        return sorted(PACKAGE.glob("template*.py"))

    # 13a: scanned like the others
    def test_every_template_module_is_scanned(self):
        names = [p.name for p in scanned_files()]
        self.assertIn("templates.py", names)
        self.assertIn("templates_builtin.py", names)
        for path in PACKAGE.rglob("template*.py"):
            self.assertIn(path.name, names, "a team template module the scan does not cover")
        self.assertEqual({p.name for p in self.template_files()} - {m + ".py" for m in TEMPLATE_MODULES}, set(), "a module the table does not name")

    def test_the_template_modules_obey_the_rules_of_the_others(self):
        for source, needle in (("from . import skillbook\n", "skillbook"), ("from . import memory\n", "memory"), ("from . import shared_folder\n", "shared_folder"),
                               ("from . import config as cfg\ncfg.save({})\n", "config.save"), ("import subprocess\n", "subprocess"),
                               ("from . import agent_launch\n", "agent_launch"), ("from . import server\n", "server"), ("from . import armory\n", "armory"),
                               ("from . import loadout\n", "loadout"), ("from . import skill_fit\n", "skill_fit"), ("from . import daily_limit\n", "daily_limit"),
                               ("CARD = {'launch_mode': 'full'}\n", "launch_mode"), ("CARD = {'equipped_skill_ids': ['s-1']}\n", "equipped_skill_ids"),
                               ("def f(s):\n    return s.answer('c', {})\n", "answer"), ("URL = '/api/config'\n", "/api/config"),
                               ("def f(c):\n    c['autonomy'] = {}\n", "autonomy"), ("URL = '/api/templates/preview'\n", "/api/templates")):
            found = " | ".join(scan_source(source))
            self.assertIn(needle, found, source)

    # 13b: nobody else imports them; they import nothing that talks, and call no card writer
    def test_the_other_scanned_modules_do_not_import_the_template_modules(self):
        problems: list[str] = []
        for path in scanned_files():
            if path.name.startswith("template"):
                continue
            problems += imports_of(path.read_text(encoding="utf-8"), TEMPLATE_MODULES, path.name)
        self.assertEqual(problems, [], "\n".join(problems))
        self.assertNotEqual(imports_of((PACKAGE / "server.py").read_text(encoding="utf-8"), TEMPLATE_MODULES, "server.py"), [],
                            "the console does import them, so the rule is not empty")

    def test_the_template_modules_import_no_chat_no_meeting_no_network_and_no_scan(self):
        problems: list[str] = []
        for path in self.template_files():
            problems += imports_of(path.read_text(encoding="utf-8"), TEMPLATE_BANNED_IMPORTS, path.name)
        self.assertEqual(problems, [], "\n".join(problems))

    def test_the_template_modules_call_no_card_writer(self):
        problems: list[str] = []
        for path in self.template_files():
            problems += card_writer_calls(path.read_text(encoding="utf-8"), path.name)
        self.assertEqual(problems, [], "\n".join(problems))

    # 13c: nothing is switched on, and the routes are the console's alone
    def test_every_enabled_a_template_module_writes_is_false(self):
        problems: list[str] = []
        for path in self.template_files():
            problems += enabled_not_false(path.read_text(encoding="utf-8"), path.name)
        self.assertEqual(problems, [], "\n".join(problems))
        self.assertEqual(enabled_not_false((PACKAGE / "templates.py").read_text(encoding="utf-8")), [])
        self.assertIn('"enabled": False', (PACKAGE / "templates.py").read_text(encoding="utf-8"), "the routine's body does say it, so the rule is not empty")

    def test_the_routes_of_the_templates_are_named_in_the_console_and_nowhere_else_of_the_package(self):
        problems: list[str] = []
        for path in package_files():
            if path.name != "server.py":
                problems += string_uses(path.read_text(encoding="utf-8"), "/api/templates", path.name)
        self.assertEqual(problems, [], "\n".join(problems))
        self.assertNotEqual(string_uses((PACKAGE / "server.py").read_text(encoding="utf-8"), "/api/templates", "server.py"), [])

    # the made-up sources: each part fires
    def test_importing_the_template_modules_from_another_module_is_caught(self):
        for source in ("from . import templates\n", "from .templates import plan\n", "from . import templates_builtin as tb\n",
                       "import vbear.templates_apply\n", "from vbear import templates_mine\n", "from vbear.templates import card_body\n"):
            self.assertTrue(imports_of(source, TEMPLATE_MODULES), source)
        self.assertEqual(imports_of("from . import template_text, groups\n", TEMPLATE_MODULES), [], "other names that start the same")

    def test_a_template_module_importing_a_chat_a_meeting_a_network_or_a_scan_is_caught(self):
        for source in ("from . import chat_service\n", "from .chat_service import ChatService\n", "from . import meeting_runner\n",
                       "from . import board_engine\n", "from . import headless_cli\n", "from . import auto_continue\n", "from . import keep_awake\n",
                       "from .scan import claude\n", "from . import scan\n", "import urllib.request\n", "from urllib import parse\n",
                       "import http.client\n", "import socket\n", "from . import chief\n", "from .dispatch import Dispatcher\n", "from . import groups\n",
                       "from . import group_runner\n", "from . import dispatch_runner\n", "from . import chief_runner\n"):
            self.assertTrue(imports_of(source, TEMPLATE_BANNED_IMPORTS), source)
        self.assertEqual(imports_of("from . import agent_profiles, model_options\nfrom .runtime import memory_rules\n", TEMPLATE_BANNED_IMPORTS), [])

    def test_a_template_module_calling_a_card_writer_is_caught(self):
        for source in ("def f(ap):\n    return ap.save_profile(None, {})\n", "from .agent_profiles import delete_profile\n",
                       "def f(ap):\n    return ap.duplicate_profile('x')\n"):
            self.assertTrue(card_writer_calls(source), source)

    def test_an_enabled_that_is_not_false_is_caught(self):
        for source in ("X = {'enabled': True}\n", "def f(on):\n    return {'enabled': on}\n", "def f(r):\n    return dict(r, enabled=True)\n",
                       "def f(r):\n    r['enabled'] = True\n", "def f(r, on):\n    r['enabled'] = on\n", "def f(r):\n    r.update({'enabled': True})\n",
                       "def f(r):\n    return {**r, 'enabled': not r['enabled']}\n", "X = dict(enabled=1)\n"):
            self.assertTrue(enabled_not_false(source), source)
        for source in ("X = {'enabled': False}\n", "def f(r):\n    r['enabled'] = False\n", "X = dict(enabled=False)\n", "X = {'enabled_at': None}\n"):
            self.assertEqual(enabled_not_false(source), [], source)

    def test_naming_the_templates_route_outside_a_docstring_is_caught(self):
        self.assertTrue(string_uses("URL = '/api/templates/preview'\n", "/api/templates"))
        self.assertTrue(string_uses("def f():\n    return '/api/templates'\n", "/api/templates"))
        self.assertEqual(string_uses('"""The route /api/templates is the console\'s."""\nX = 1\n', "/api/templates"), [])


# 13d. (P45-2) who may write the record of the applies of the team templates, and the one thing that was NOT made an exception: the write
# functions of the cards, the skills and the routines. The apply and the undo are made by the console (server.py) with the ordinary write functions
# of the person's own presses; vbear/templates_apply.py is the notebook and the rule book, so it needs no exception to rule 13b, and none was made.
TEMPLATE_APPLY_MODULE = "templates_apply"
TEMPLATE_APPLY_WRITERS = {"begin_apply", "record_item", "end_apply", "record_undo", "log_undo", "recover", "applies_store"}
TEMPLATE_APPLY_HOMES = {"server.py", "templates_apply.py"}          # the routes, and the module itself
TEMPLATE_APPLY_FUNCTIONS = ("_templates_apply", "_templates_make", "_templates_undo", "_templates_undo_preview", "_templates_facts",
                            "_templates_undo_find", "_templates_undo_shown", "_templates_refuse", "_save_card")
# what the apply and the undo of the console never name: a switch, a chat, a launch, the configuration, the ledger, a program
TEMPLATE_APPLY_NEVER = {"memory_mod", "shared_folder", "autonomy", "set_card", "open_cards", "close_cards", "on_new_employee", "send", "send_for_routine",
                        "answer", "chat_answer", "set_conf", "write_private", "config_path", "meeting_runner", "runtime", "subprocess", "Popen", "dispatcher",
                        "dispatch_runner", "group_service", "group_runner", "routine_runner", "chief_tools", "launch", "keep_awake_command"}


def template_apply_writer_uses(source: str, label: str = "<source>") -> list[str]:
    return writer_uses(source, label, TEMPLATE_APPLY_MODULE, TEMPLATE_APPLY_WRITERS)


def functions_named(source: str, names) -> list:
    return [n for n in ast.walk(ast.parse(source)) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name in names]


class TemplateApplyRules(unittest.TestCase):
    """P45-2, rule 13d. The behaviour (safe mode, no skill card, switched off, config and memory unchanged, no AI) is proved in
    tests/test_templates_apply_api.py and tests/test_templates_undo.py, over the real stores."""

    def test_only_the_console_and_the_module_itself_name_the_writers_of_the_record(self):
        problems: list[str] = []
        for path in package_files():
            if path.name not in TEMPLATE_APPLY_HOMES:
                problems += template_apply_writer_uses(path.read_text(encoding="utf-8"), str(path.relative_to(PACKAGE)))
        self.assertEqual(problems, [], "\n".join(problems))

    def test_the_console_does_call_each_writer_so_the_rule_is_not_empty(self):
        source = (PACKAGE / "server.py").read_text(encoding="utf-8")
        used = {m.group(1) for m in re.finditer(r"templates_apply_mod\.(\w+)", source)}
        self.assertGreaterEqual(used, {"begin_apply", "record_item", "end_apply", "record_undo", "log_undo", "recover"})
        self.assertNotEqual(template_apply_writer_uses(source, "server.py"), [])

    def test_changing_the_record_from_anywhere_else_is_caught(self):
        for name in sorted(TEMPLATE_APPLY_WRITERS):
            self.assertTrue(template_apply_writer_uses(f"from . import templates_apply\ntemplates_apply.{name}()\n"), name)
            self.assertTrue(template_apply_writer_uses(f"from . import templates_apply as ta\ndef f(x):\n    return ta.{name}(x)\n"), name)
            self.assertTrue(template_apply_writer_uses(f"from .templates_apply import {name}\n"), name)
        self.assertTrue(template_apply_writer_uses("import vbear.templates_apply\nvbear.templates_apply.begin_apply('claude')\n"))
        self.assertTrue(template_apply_writer_uses("from .templates_apply import *\n"))
        self.assertTrue(template_apply_writer_uses("from . import templates_apply\nf = getattr(templates_apply, name)\n"))
        self.assertTrue(template_apply_writer_uses("from . import templates_apply\ntemplates_apply.applies_store.save({})\n"))

    def test_reading_the_record_and_asking_the_rules_is_allowed(self):
        source = ("from . import templates_apply\ndef f(a, facts):\n    return (templates_apply.read_applies(), templates_apply.public(a, {}),\n"
                  "            templates_apply.undo_plan(a, facts), templates_apply.fingerprint('card', {}), templates_apply.card_mentions('/x', []))\n")
        self.assertEqual(template_apply_writer_uses(source), [])

    # -- no exception to 13b was made: nothing of the template modules may call a write function of the cards, the skills, the routines --
    def test_the_notebook_has_no_exception_it_calls_no_write_function_of_anything_it_keeps_a_record_of(self):
        path = PACKAGE / "templates_apply.py"
        source = path.read_text(encoding="utf-8")
        self.assertEqual(card_writer_calls(source, path.name), [])
        self.assertEqual(skillbook_writer_uses(source, path.name), [])
        self.assertEqual(routine_writer_uses(source, path.name), [])
        self.assertEqual(memory_writer_uses(source, path.name), [])
        self.assertEqual(shared_writer_uses(source, path.name), [])
        self.assertEqual(imports_of(source, ("skillbook", "routines", "routine_rules", "routine_runner", "memory", "shared_folder", "agent_launch",
                                             "groups", "dispatch", "chief", "autonomy", "daily_limit", "server")), [])
        self.assertEqual(scan_source(source, path.name), [], "the notebook meets every rule of the others")

    def test_no_home_of_a_write_function_names_a_template_module_and_the_lists_of_writers_are_whole(self):
        for homes in (MEMORY_WRITER_HOMES, SHARED_WRITER_HOMES, SKILLBOOK_WRITER_HOMES, ROUTINE_WRITER_HOMES, ROUTINE_RUN_HOMES):
            self.assertFalse({h for h in homes if h.startswith("template")}, homes)
        self.assertEqual(CARD_WRITERS, {"save_profile", "create_profile", "delete_profile", "duplicate_profile", "set_profile_enabled"})
        self.assertEqual(SKILLBOOK_WRITERS, {"add", "edit", "delete", "store"})
        self.assertEqual(ROUTINE_WRITERS, {"create", "edit", "set_enabled", "delete", "set_settings", "store", "settings_store"})
        self.assertGreaterEqual(set(TEMPLATE_BANNED_IMPORTS), {"chat_service", "meeting_runner", "board_engine", "headless_cli", "auto_continue", "keep_awake", "scan",
                                                               "urllib", "http", "socket"})

    def test_the_same_calls_in_a_template_module_or_any_other_module_are_still_caught(self):
        for label in ("templates_apply.py", "templates.py", "templates_mine.py", "groups.py", "chief.py", "dispatch.py", "routine_runner.py", "memory.py"):
            self.assertTrue(card_writer_calls("def f(ap):\n    return ap.save_profile(None, {})\n", label), label)
            self.assertTrue(card_writer_calls("def f(ap):\n    return ap.delete_profile('x')\n", label), label)
            self.assertTrue(skillbook_writer_uses("from . import skillbook\nskillbook.add({})\n", label), label)
            self.assertTrue(skillbook_writer_uses("from . import skillbook\nskillbook.delete('k')\n", label), label)
            self.assertTrue(routine_writer_uses("from . import routines\nroutines.create({}, [])\n", label), label)
            self.assertTrue(routine_writer_uses("from . import routines\nroutines.delete('r')\n", label), label)
        for label in ("templates_apply.py", "groups.py"):
            self.assertTrue(imports_of("from . import skillbook\n", ("skillbook",), label))
            self.assertIn("skillbook", " | ".join(scan_source("from . import skillbook\n", label)))

    # -- the apply and the undo of the console switch nothing on and start nothing --
    def test_the_apply_and_the_undo_name_no_switch_no_chat_no_launch_no_configuration_and_no_ledger(self):
        source = (PACKAGE / "server.py").read_text(encoding="utf-8")
        found = functions_named(source, TEMPLATE_APPLY_FUNCTIONS)
        self.assertEqual({f.name for f in found}, set(TEMPLATE_APPLY_FUNCTIONS), "the functions the rule is about are there")
        problems = []
        for fn in found:
            for node in ast.walk(fn):
                name = node.attr if isinstance(node, ast.Attribute) else node.id if isinstance(node, ast.Name) else None
                if name in TEMPLATE_APPLY_NEVER:
                    problems.append(f"{fn.name}:{node.lineno}: names {name}")
                if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Call):
                    call = node.value.func
                    if isinstance(call, ast.Attribute) and call.attr == "chat_service" and node.attr != "cards":
                        problems.append(f"{fn.name}:{node.lineno}: asks the chat service for {node.attr}")
                if isinstance(node, ast.Attribute) and node.attr in ("save", "set_conf") and isinstance(node.value, ast.Name) and node.value.id in ("cfg", "config"):
                    problems.append(f"{fn.name}:{node.lineno}: writes the configuration")
        self.assertEqual(problems, [], "\n".join(problems))

    def test_each_ordinary_write_function_is_called_in_the_console_by_the_apply_and_by_the_undo(self):
        source = (PACKAGE / "server.py").read_text(encoding="utf-8")

        def attrs(name):
            (fn,) = functions_named(source, (name,))
            return {(n.value.id, n.attr) for n in ast.walk(fn) if isinstance(n, ast.Attribute) and isinstance(n.value, ast.Name)}
        self.assertIn(("agent_profiles", "save_profile"), attrs("_save_card"))
        self.assertIn(("skillbook_mod", "add"), attrs("_templates_make"))
        self.assertIn(("routines_mod", "create"), attrs("_templates_make"))
        self.assertIn(("self", "_save_card"), attrs("_templates_make"))
        undo = attrs("_templates_undo")
        self.assertTrue({("routines_mod", "delete"), ("skillbook_mod", "delete"), ("agent_profiles", "delete_profile")} <= undo)
        for name in TEMPLATE_APPLY_FUNCTIONS:
            self.assertFalse({a for a in attrs(name) if a[1] in ("edit", "set_enabled", "duplicate_profile", "create_profile", "set_profile_enabled")
                              and a[0] in ("routines_mod", "skillbook_mod", "agent_profiles")}, name)

    def test_a_routine_is_made_only_with_the_template_modules_body_which_says_false(self):
        source = (PACKAGE / "server.py").read_text(encoding="utf-8")
        for fn in functions_named(source, TEMPLATE_APPLY_FUNCTIONS):
            self.assertEqual(enabled_not_false(ast.unparse(fn), fn.name), [], fn.name)
            self.assertNotIn("launch_mode", ast.unparse(fn))
            self.assertNotIn("equipped_skill_ids", ast.unparse(fn))


# 13e. (P45-3) who may save, rename or delete the person's own team templates: the module's writers, and the only modules that may name them
TEMPLATE_MINE_MODULE = "templates_mine"
TEMPLATE_MINE_WRITERS = {"save_mine", "rename_mine", "delete_mine", "mine_store"}
TEMPLATE_MINE_HOMES = {"server.py", "templates_mine.py"}          # the routes, and the module itself


def template_mine_writer_uses(source: str, label: str = "<source>") -> list[str]:
    return writer_uses(source, label, TEMPLATE_MINE_MODULE, TEMPLATE_MINE_WRITERS)


class TemplateMineRules(unittest.TestCase):
    """P45-3, rule 13e: only the browser's /api/templates/mine routes of the console save, rename or delete a team template of the person's own.
    What the saved copy holds (and what it never holds), and that nothing is written in the other places, is in tests/test_templates_mine.py and
    tests/test_templates_mine_api.py; the module being under rules 1 to 13c is TemplateRules."""

    def test_the_module_is_scanned_and_named_in_the_table(self):
        self.assertIn("templates_mine.py", [p.name for p in scanned_files()])
        self.assertIn(TEMPLATE_MINE_MODULE, TEMPLATE_MODULES)

    def test_only_the_console_and_the_module_itself_name_a_writer(self):
        problems: list[str] = []
        for path in package_files():
            if path.name not in TEMPLATE_MINE_HOMES:
                problems += template_mine_writer_uses(path.read_text(encoding="utf-8"), str(path.relative_to(PACKAGE)))
        self.assertEqual(problems, [], "\n".join(problems))

    def test_the_console_does_call_every_writer_so_the_rule_is_not_empty(self):
        source = (PACKAGE / "server.py").read_text(encoding="utf-8")
        calls = {m.group(1) for m in re.finditer(r"templates_mine_mod\.(\w+)", source)}
        self.assertEqual(calls & (TEMPLATE_MINE_WRITERS - {"mine_store"}), TEMPLATE_MINE_WRITERS - {"mine_store"})
        self.assertNotEqual(template_mine_writer_uses(source, "server.py"), [])

    def test_the_module_writes_no_card_no_skill_no_routine_and_no_config(self):
        tree = ast.parse((PACKAGE / "templates_mine.py").read_text(encoding="utf-8"))
        names = {n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)} | {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)}
        for banned in ("save_profile", "delete_profile", "duplicate_profile", "set_enabled", "send", "send_for_routine", "answer", "set_conf",
                       "write_private", "Popen", "urlopen", "connect"):
            self.assertNotIn(banned, names, banned)
        modules = _module_of_all(tree)
        for banned in ("skillbook", "routines", "memory", "shared_folder", "chat_service", "urllib", "http", "socket", "subprocess", "shutil", "zipfile"):
            self.assertFalse([m for m in modules if m.split(".")[0] == banned], banned)

    def test_the_module_has_no_export_import_upload_or_download(self):
        tree = ast.parse((PACKAGE / "templates_mine.py").read_text(encoding="utf-8"))
        defined = {n.name for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef, ast.ClassDef))}
        self.assertEqual({n for n in defined if re.search(r"export|import|upload|download|send|fetch", n)}, set())

    # the made-up sources: each part fires
    def test_naming_a_writer_from_another_module_is_caught(self):
        for source in ("from . import templates_mine\ndef f(b):\n    return templates_mine.save_mine(b)\n",
                       "from . import templates_mine as m\ndef f(t):\n    return m.delete_mine(t, {})\n",
                       "from .templates_mine import rename_mine\n", "from vbear.templates_mine import mine_store\n",
                       "from . import templates_mine as m\nx = m.mine_store\n", "from .templates_mine import *\n",
                       "from . import templates_mine as m\nf = getattr(m, 'save_mine')\n"):
            self.assertTrue(template_mine_writer_uses(source), source)
        self.assertEqual(template_mine_writer_uses("from . import templates_mine as m\nx = m.read_mine()\n"), [], "reading is not writing")
        self.assertEqual(template_mine_writer_uses("from . import templates as t\nx = t.plan\n"), [])


class AutoContinueRules(unittest.TestCase):
    """P44-4, rule 11: a dispatch goes on by itself only for item 5; a group never does."""

    MODULE = "auto_continue"

    @staticmethod
    def imports_module(source: str, name: str = "auto_continue") -> list[str]:
        tree = ast.parse(source)
        return [f"line {node.lineno}" for node in ast.walk(tree) if isinstance(node, (ast.Import, ast.ImportFrom))
                and any(n == name or n.startswith(name + ".") for n in _module_of(node))]

    @staticmethod
    def vbear_presses(source: str, label: str = "<source>") -> list[str]:
        """Every call of ``resume_dispatch`` that says ``by="vbear"``, and every call that gives ``by`` something this scan cannot read."""
        found = []
        for node in ast.walk(ast.parse(source)):
            if isinstance(node, ast.Call) and isinstance(node.func, (ast.Attribute, ast.Name)):
                name = node.func.attr if isinstance(node.func, ast.Attribute) else node.func.id
                if name != "resume_dispatch":
                    continue
                for kw in node.keywords:
                    if kw.arg == "by" and not (isinstance(kw.value, ast.Constant) and kw.value.value == "you"):
                        found.append(f"{label}:{node.lineno}: resume_dispatch by something that is not the person")
                if len(node.args) >= 2:
                    found.append(f"{label}:{node.lineno}: resume_dispatch with a positional by")
        return found

    def test_the_module_is_scanned_by_the_table(self):
        self.assertIn("auto_continue.py", [p.name for p in scanned_files()])

    def test_only_the_console_imports_it_and_no_group_module_does(self):
        problems = []
        for path in package_files():
            if path.name in ("server.py", "auto_continue.py"):
                continue
            problems += [f"{path.name}:{hit}" for hit in self.imports_module(path.read_text(encoding="utf-8"))]
        self.assertEqual(problems, [], "\n".join(problems))
        self.assertNotEqual(self.imports_module((PACKAGE / "server.py").read_text(encoding="utf-8")), [], "the console does wire it")
        for path in PACKAGE.glob("group*.py"):
            text = path.read_text(encoding="utf-8")
            self.assertNotIn("auto_continue", text, f"{path.name} names item 5's module")
            self.assertNotIn("resume_dispatch", text, f"{path.name} presses a dispatch's 繼續")

    def test_item_5_is_read_in_one_place(self):
        source = (PACKAGE / "auto_continue.py").read_text(encoding="utf-8")
        tree = ast.parse(source)
        reads = [n for n in ast.walk(tree) if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and n.func.attr == "read"
                 and isinstance(n.func.value, ast.Name) and n.func.value.id == "autonomy"]
        self.assertEqual(len(reads), 1)
        self.assertIn('["auto_continue"]', source)
        docstrings = {id(n.body[0].value) for n in ast.walk(tree) if isinstance(n, (ast.Module, ast.FunctionDef, ast.ClassDef)) and n.body
                      and isinstance(n.body[0], ast.Expr) and isinstance(n.body[0].value, ast.Constant)}
        strings = [n.value for n in ast.walk(tree) if isinstance(n, ast.Constant) and isinstance(n.value, str) and id(n) not in docstrings]
        self.assertNotIn("autonomy", strings, "the block is read through autonomy.read and no other way")

    def test_only_the_console_presses_continue_as_vbear(self):
        problems = []
        for path in package_files():
            if path.name == "server.py":
                continue
            problems += self.vbear_presses(path.read_text(encoding="utf-8"), path.name)
        self.assertEqual(problems, [], "\n".join(problems))
        wiring = (PACKAGE / "server.py").read_text(encoding="utf-8")
        self.assertIn('resume_dispatch(did, by="vbear"', wiring, "the console hands the press to item 5's module")

    def test_the_module_reaches_no_chat_no_card_and_no_config(self):
        tree = ast.parse((PACKAGE / "auto_continue.py").read_text(encoding="utf-8"))
        names = {n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)} | {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)}
        for banned in ("send", "send_for_dispatch", "send_for_group", "send_for_routine", "answer", "chat_answer",
                       "save_profile", "create_profile", "set_conf", "write_private", "config_path", "Popen", "system", "subprocess", "resume_dispatch"):
            self.assertNotIn(banned, names, banned)
        self.assertFalse([m for m in _module_of_all(tree) if m.split(".")[0] in ("chat_service", "routines", "routine_runner", "skillbook", "agent_profiles")])

    def test_importing_it_from_a_group_module_is_caught(self):
        for source in ("from . import auto_continue\n", "from .auto_continue import AutoContinue\n", "import vbear.auto_continue as a\n",
                       "from vbear import auto_continue\n"):
            self.assertTrue(self.imports_module(source), source)
        self.assertEqual(self.imports_module("from . import dispatch, countdown\n"), [])

    def test_pressing_continue_as_vbear_from_anywhere_else_is_caught(self):
        for source in ('def f(r, d):\n    return r.resume_dispatch(d, by="vbear")\n', 'def f(r, d, b):\n    return r.resume_dispatch(d, by=b)\n',
                       'def f(r, d):\n    return r.resume_dispatch(d, "vbear")\n'):
            self.assertTrue(self.vbear_presses(source), source)
        self.assertEqual(self.vbear_presses('def f(r, d):\n    return r.resume_dispatch(d)\n'), [])
        self.assertEqual(self.vbear_presses('def f(r, d):\n    return r.resume_dispatch(d, by="you")\n'), [])

    def test_the_module_obeys_the_rules_of_the_others(self):
        for source, needle in (("from . import config as cfg\ncfg.save({})\n", "config.save"), ("import subprocess\n", "subprocess"),
                               ("from .runtime import daemon\n", "runtime.daemon"), ("def f(s):\n    return s.answer('c', {})\n", "answer"),
                               ("def f(c):\n    c['autonomy'] = {'auto_continue': True}\n", "autonomy"),
                               ("URL = '/api/settings/autonomy'\n", "autonomy"), ("from . import agent_launch\n", "agent_launch")):
            found = " | ".join(scan_source(source))
            self.assertIn(needle, found, source)


def _module_of_all(tree) -> list[str]:
    out: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            out += _module_of(node)
    return out


# 12. (P44-3) the one program: the name, where it may be, and the other ways to start a program
PROGRAM_NAME = "caffeinate"
PROGRAM_HOME = "keep_awake.py"
START_NAMES = {"popen", "system", "startfile", "execv", "execve", "execvp", "execvpe", "execl", "execle", "execlp", "execlpe",
               "spawnv", "spawnve", "spawnvp", "spawnvpe", "spawnl", "spawnle", "spawnlp", "spawnlpe", "posix_spawn", "posix_spawnp", "fork", "forkpty"}
NO_PROGRAM_PATTERNS = ("routine*.py", "skillbook*.py", "auto_continue.py")


def program_mentions(source: str, label: str = "<source>") -> list[str]:
    """Every line that names the program, in code, comment or docstring."""
    return [f"{label}:{n}: names {PROGRAM_NAME}" for n, line in enumerate(source.splitlines(), 1) if PROGRAM_NAME in line.lower()]


def start_calls(source: str, label: str = "<source>") -> list[str]:
    """Every way of starting a program that is not ``subprocess`` (which the table above bans by import): os.popen/os.spawn*/os.exec*/..."""
    found = []
    for node in ast.walk(ast.parse(source, filename=label)):
        name = None
        if isinstance(node, ast.Call):
            fn = node.func
            name = fn.id if isinstance(fn, ast.Name) else fn.attr if isinstance(fn, ast.Attribute) else None
        elif isinstance(node, ast.ImportFrom) and (node.module or "") in ("os", "posix"):
            name = next((a.name for a in node.names if a.name.lower() in START_NAMES), None)
        if name and name.lower() in START_NAMES:
            found.append(f"{label}:{node.lineno}: starts a program with {name}")
    return found


def argv_problems(source: str) -> list[str]:
    """What is wrong with the argv of keep_awake.py: it must be exactly one list ["/usr/bin/caffeinate", "-i", "-w", str(os.getpid())], and
    the program may be started only with a call of ``argv()`` and without ``shell``."""
    tree = ast.parse(source)
    docstrings = {id(n.body[0].value) for n in ast.walk(tree) if isinstance(n, (ast.Module, ast.FunctionDef, ast.ClassDef)) and n.body
                  and isinstance(n.body[0], ast.Expr) and isinstance(n.body[0].value, ast.Constant)}
    problems = []
    named = [n for n in ast.walk(tree) if isinstance(n, ast.Constant) and isinstance(n.value, str) and id(n) not in docstrings
             and PROGRAM_NAME in n.value]
    lists = [n for n in ast.walk(tree) if isinstance(n, ast.List) and n.elts and isinstance(n.elts[0], ast.Constant) and PROGRAM_NAME in str(n.elts[0].value)]
    if len(named) != 1 or len(lists) != 1:
        return ["the program must be named once, as the first word of one list"]
    elts = lists[0].elts
    words = [e.value if isinstance(e, ast.Constant) else ast.dump(e) for e in elts]
    expected = ["/usr/bin/caffeinate", "-i", "-w", ast.dump(ast.parse("str(os.getpid())", mode="eval").body)]
    if words != expected:
        problems.append(f"the argv is not the fixed one: {words}")
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            fn = node.func
            if isinstance(fn, ast.Attribute) and fn.attr == "Popen":
                first = node.args[0] if node.args else None
                if not (isinstance(first, ast.Call) and isinstance(first.func, ast.Name) and first.func.id == "argv" and not first.args):
                    problems.append("Popen is not given argv()")
                if any(kw.arg in ("shell", "executable", "env", "cwd") for kw in node.keywords):
                    problems.append("Popen is given a keyword that changes what runs")
    return problems


class KeepAwakeRules(unittest.TestCase):
    """P44-3, rule 12."""

    def test_no_file_of_the_package_but_the_one_names_the_program(self):
        problems: list[str] = []
        for path in package_files():
            if path.name != PROGRAM_HOME:
                problems += program_mentions(path.read_text(encoding="utf-8"), str(path.relative_to(PACKAGE)))
        self.assertEqual(problems, [], "\n".join(problems))
        self.assertNotEqual(program_mentions((PACKAGE / PROGRAM_HOME).read_text(encoding="utf-8")), [], "the rule is not empty")

    def test_the_argv_is_one_constant_list_started_without_a_shell(self):
        self.assertEqual(argv_problems((PACKAGE / PROGRAM_HOME).read_text(encoding="utf-8")), [])

    def test_the_modules_of_routines_skills_and_continuation_start_no_program(self):
        problems: list[str] = []
        files = {p.name: p for pattern in NO_PROGRAM_PATTERNS for p in PACKAGE.glob(pattern)}
        self.assertTrue({"routine_runner.py", "routines.py", "routine_rules.py", "skillbook.py"} <= set(files))
        for name, path in sorted(files.items()):
            source = path.read_text(encoding="utf-8")
            problems += start_calls(source, name)
            problems += scan_source(source, name)
            tree = ast.parse(source)
            for node in ast.walk(tree):
                if isinstance(node, (ast.Import, ast.ImportFrom)) and any(n.split(".")[0] in ("subprocess", "pty", "keep_awake") for n in _module_of(node)):
                    problems.append(f"{name}:{node.lineno}: imports a way to start a program")
        self.assertEqual(problems, [], "\n".join(problems))

    def test_only_the_console_imports_the_module_and_only_serve_hands_it_over(self):
        for path in package_files():
            if path.name in (PROGRAM_HOME, "server.py"):
                continue
            for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
                if isinstance(node, (ast.Import, ast.ImportFrom)):
                    self.assertNotIn("keep_awake", [n.split(".")[-1] for n in _module_of(node)], f"{path.name} imports keep_awake")
        source = (PACKAGE / "server.py").read_text(encoding="utf-8")
        tree = ast.parse(source)
        launches = [n for n in ast.walk(tree) if isinstance(n, ast.Attribute) and n.attr == "launch" and isinstance(n.value, ast.Name) and n.value.id == "keep_awake_mod"]
        self.assertEqual(len(launches), 1)
        serve = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "serve")
        self.assertTrue(any(n is launches[0] for n in ast.walk(serve)), "only serve() hands the launch to a console")
        assigns = [n for n in ast.walk(tree) if isinstance(n, ast.Assign) and any(isinstance(t, ast.Attribute) and t.attr == "keep_awake_command" for t in n.targets)]
        self.assertEqual(len(assigns), 2, "the empty default in Console and the one in serve()")

    def test_the_runner_only_tells_the_machine_whether_anyone_works(self):
        source = (PACKAGE / "routine_runner.py").read_text(encoding="utf-8")
        tree = ast.parse(source)
        calls = {n.func.attr for n in ast.walk(tree) if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
                 and isinstance(n.func.value, ast.Attribute) and n.func.value.attr == "keep_awake"}
        self.assertEqual(calls, {"update", "close"})

    # ---- the made-up sources: each part of the rule fires ------------------------------------------------------------------

    def test_naming_the_program_elsewhere(self):
        self.assertTrue(program_mentions("ARGV = ['/usr/bin/caffeinate', '-i']\n"))
        self.assertTrue(program_mentions("# runs Caffeinate when it is time\n"))
        self.assertTrue(program_mentions('"""keeps the Mac up with CAFFEINATE"""\n'))
        self.assertEqual(program_mentions("KEEP = 'keep_awake'\n"), [])

    def test_other_ways_to_start_a_program(self):
        for source in ("import os\nos.popen('x')\n", "import os\nos.system('x')\n", "import os\nos.execv('/bin/x', ['x'])\n",
                       "import os\nos.spawnl(0, '/bin/x', 'x')\n", "import os\nos.posix_spawn('/bin/x', ['x'], {})\n",
                       "from os import popen\n", "import os\nos.fork()\n"):
            self.assertTrue(start_calls(source), source)
        self.assertEqual(start_calls("import os\nos.getpid()\nos.path.join('a', 'b')\n"), [])

    def test_an_argv_that_is_not_the_fixed_one(self):
        good = ("import os, subprocess\n"
                "def argv():\n    return ['/usr/bin/caffeinate', '-i', '-w', str(os.getpid())]\n"
                "def launch(c):\n    return subprocess.Popen(argv(), stdin=subprocess.DEVNULL)\n")
        self.assertEqual(argv_problems(good), [])
        bad = {
            "another flag": good.replace("'-i'", "'-d'"),
            "an extra word": good.replace("str(os.getpid())]", "str(os.getpid()), 'x']"),
            "a word from a variable": good.replace("'-i'", "WORD"),
            "a shell": good.replace("stdin=subprocess.DEVNULL", "shell=True"),
            "not argv()": good.replace("Popen(argv()", "Popen(c"),
            "an env": good.replace("stdin=subprocess.DEVNULL", "env={}"),
            "named twice": good + "OTHER = ['/usr/bin/caffeinate', '-i']\n",
        }
        for why, source in bad.items():
            self.assertTrue(argv_problems(source), why)


# 14. (P46, ADR 0012) the AGY chat: every request asked, only "allow once" or "reject once" ever answered, argv and settings fixed
AGY_PATTERNS = ("agy*.py", "runtime/agy*.py")
AGY_BANNED_PATTERNS = AGY_PATTERNS + ("runtime/agent_sessions.py",)
AGY_NEVER_CHOSEN = ("allow_always", "reject_always")
AGY_NEVER_CHOSEN_HOME = "NEVER_CHOSEN_OPTION_KINDS"        # the one constant in which the two words of a kind VBear never chooses may stand
AGY_BANNED_FLAGS = ("--dangerously-skip-permissions", "--login", "--app-data-dir", "--process-per-session",
                    "--include-default-customizations")


def agy_files(patterns=AGY_PATTERNS) -> list[Path]:
    return sorted({p for pattern in patterns for p in PACKAGE.glob(pattern)})


def _docstring_ids(tree) -> set:
    return {id(n.body[0].value) for n in ast.walk(tree) if isinstance(n, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
            and n.body and isinstance(n.body[0], ast.Expr) and isinstance(n.body[0].value, ast.Constant)}


def never_chosen_uses(source: str, label: str = "<source>") -> list[str]:
    """Every string in code that holds the name of a kind of option VBear never chooses (``allow_always``, ``reject_always``), except in the
    one constant that names them (and docstrings): the words may not be a value to send."""
    tree = ast.parse(source, filename=label)
    docs = _docstring_ids(tree)
    allowed: set = set()
    for node in ast.walk(tree):
        targets = node.targets if isinstance(node, ast.Assign) else [node.target] if isinstance(node, ast.AnnAssign) else []
        if any(isinstance(t, ast.Name) and t.id == AGY_NEVER_CHOSEN_HOME for t in targets):
            allowed |= {id(n) for n in ast.walk(node)}
    found = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str) and id(node) not in docs and id(node) not in allowed \
                and any(word in node.value for word in AGY_NEVER_CHOSEN):
            found.append(f"{label}:{node.lineno}: holds a kind of option VBear never chooses")
    return found


def banned_flag_uses(source: str, label: str = "<source>") -> list[str]:
    """Every line (code, comment or docstring) that names a switch the AGY chat never passes."""
    return [f"{label}:{n}: names {flag}" for n, line in enumerate(source.splitlines(), 1) for flag in AGY_BANNED_FLAGS if flag in line]


AGY_ACCOUNT_PREFIXES = ("ANTIGRAVITY_", "GEMINI_", "GOOGLE_")      # variables of the person's account or keys: never named in code
AGY_BANNED_METHODS = ("session/set_mode", "session/set_config_option", "session/load")


def account_variable_uses(source: str, label: str = "<source>") -> list[str]:
    """Every string in code (not a docstring) that starts with the name of a variable of the person's AGY or Google account."""
    tree = ast.parse(source, filename=label)
    docs = _docstring_ids(tree)
    return [f"{label}:{n.lineno}: names {n.value}" for n in ast.walk(tree)
            if isinstance(n, ast.Constant) and isinstance(n.value, str) and id(n) not in docs
            and any(n.value.startswith(prefix) for prefix in AGY_ACCOUNT_PREFIXES)]


def banned_method_uses(source: str, label: str = "<source>") -> list[str]:
    """Every line (code, comment or docstring) that names a message the AGY chat never writes. ``session/set_model`` is not
    ``session/set_mode``: the name ends there."""
    return [f"{label}:{i}: names {method}" for i, line in enumerate(source.splitlines(), 1) for method in AGY_BANNED_METHODS
            if re.search(re.escape(method) + r"(?![A-Za-z0-9_])", line)]


class AgyChatRules(unittest.TestCase):
    """P46-1, rules 14a-14c; P46-3, rules 14b (the one table), 14d and 14h."""

    def agy_protocol(self):
        from vbear.runtime import agy_chat_protocol as acp
        return acp

    def test_the_protocol_module_is_scanned(self):
        self.assertIn("agy_chat_protocol.py", [p.name for p in agy_files()])

    # 14a: only "allow once" and "reject once" are ever answered
    def test_14a_no_agy_module_holds_an_always_kind_outside_the_one_constant(self):
        problems = []
        for path in agy_files():
            problems += never_chosen_uses(path.read_text(encoding="utf-8"), str(path.relative_to(PACKAGE)))
        self.assertEqual(problems, [], "\n".join(problems))

    def test_14a_the_constant_that_names_them_exists_and_is_not_among_the_kinds_chosen(self):
        acp = self.agy_protocol()
        self.assertEqual(acp.NEVER_CHOSEN_OPTION_KINDS, frozenset(AGY_NEVER_CHOSEN))
        tree = ast.parse((PACKAGE / "runtime" / "agy_chat_protocol.py").read_text(encoding="utf-8"))
        named = [n for n in ast.walk(tree) if isinstance(n, ast.Assign) and any(isinstance(t, ast.Name) and t.id == AGY_NEVER_CHOSEN_HOME
                                                                                for t in n.targets)]
        self.assertEqual(len(named), 1)
        for consts in acp.VERSIONS.values():
            self.assertTrue(set(AGY_NEVER_CHOSEN).isdisjoint({consts.allow_option_kind, consts.reject_option_kind}))

    def test_14a_the_scan_fires_on_small_made_up_sources(self):
        for source in ('KIND = "allow_always"\n', 'def f():\n    return {"optionId": "x", "kind": "reject_always"}\n',
                       'CHOICES = ("allow_once", "allow_always")\n', 'X = f"{1}allow_always"\n',
                       'OTHER = frozenset({"allow_always"})\n'):
            self.assertTrue(never_chosen_uses(source), source)
        for source in ('NEVER_CHOSEN_OPTION_KINDS = frozenset({"allow_always", "reject_always"})\n',
                       'NEVER_CHOSEN_OPTION_KINDS: frozenset = frozenset({"allow_always"})\n',
                       '"""Mentions allow_always in prose."""\ndef f():\n    """And reject_always here."""\n    return 1\n',
                       'KIND = "allow_once"\n'):
            self.assertEqual(never_chosen_uses(source), [], source)

    def test_14a_answers_only_ever_select_allow_once_or_reject_once(self):
        acp = self.agy_protocol()
        mixed = [{"optionId": "a-always", "kind": "allow_always"}, {"optionId": "allow", "kind": "allow_once"},
                 {"optionId": "r-always", "kind": "reject_always"}, {"optionId": "deny", "kind": "reject_once"},
                 {"optionId": "other", "kind": "something_else"}]
        for options in (mixed, mixed[::-1], mixed[:1] + mixed[2:3], mixed[::2]):
            for decision in ("allow", "deny", "cancelled"):
                try:
                    line = json.loads(acp.answer_line(1, options, decision))
                except ValueError:
                    continue                                   # an "allow" it cannot give is an error, never another option
                chosen = line["result"]["outcome"].get("optionId")
                self.assertIn(chosen, (None, "allow", "deny"), (options, decision))
        for decision in ("allow_always", "reject_always", "accept", "allow_once", "reject_once"):
            with self.assertRaises(ValueError, msg=decision):
                acp.answer_line(1, mixed, decision)
        self.assertEqual(acp.DECISIONS, ("allow", "deny", "cancelled"))

    # 14b: the argv, the switches that are never passed, and the settings
    def test_14b_the_argv_tail_is_the_fixed_one(self):
        acp = self.agy_protocol()
        for consts in acp.VERSIONS.values():
            self.assertEqual(acp.argv_for(consts, "/s/agy-chat-home"),
                             ["acp", "--gemini-dir", "/s/agy-chat-home", "--sandbox", "--disable-telemetry"])
            self.assertEqual(acp.argv_for(consts, "/s/agy-chat-home", shared="/s/shared"),
                             ["acp", "--gemini-dir", "/s/agy-chat-home", "--sandbox", "--disable-telemetry", "--add-dir", "/s/shared"])

    def test_14b_no_file_that_builds_the_command_names_a_switch_that_is_never_passed(self):
        problems = []
        files = agy_files(AGY_BANNED_PATTERNS)
        self.assertIn("agent_sessions.py", [p.name for p in files])
        for path in files:
            problems += banned_flag_uses(path.read_text(encoding="utf-8"), str(path.relative_to(PACKAGE)))
        self.assertEqual(problems, [], "\n".join(problems))

    def test_14b_the_scan_fires_on_small_made_up_sources(self):
        for flag in AGY_BANNED_FLAGS:
            self.assertTrue(banned_flag_uses(f'ARGV = ["acp", "{flag}"]\n'), flag)
            self.assertTrue(banned_flag_uses(f"# add {flag} to go faster\n"), flag)
        self.assertEqual(banned_flag_uses('ARGV = ["acp", "--sandbox", "--disable-telemetry", "--add-dir"]\n'), [])

    def test_14b_the_settings_are_exactly_the_five_keys_and_values_of_the_design(self):
        acp = self.agy_protocol()
        for consts in acp.VERSIONS.values():
            settings = consts.settings
            self.assertEqual(sorted(settings), ["allowNonWorkspaceAccess", "enableTerminalSandbox", "permissions", "toolPermission",
                                                "useG1Credits"])
            self.assertEqual(settings["toolPermission"], "request-review")
            self.assertIs(settings["enableTerminalSandbox"], True)
            self.assertIs(settings["allowNonWorkspaceAccess"], False)
            self.assertIs(settings["useG1Credits"], False)
            self.assertEqual(settings["permissions"], {"allow": [], "ask": [], "deny": []})
            self.assertEqual(json.loads(acp.settings_bytes(consts)), settings)

    def announce(self, tracker, fx, kind="execute", cid="c-1"):
        """The order AGY 1.5.3 really sends before it asks: tool_call in_progress, then tool_call_update pending."""
        tracker.on_message({"jsonrpc": "2.0", "method": "session/update", "params": {"sessionId": fx.SESSION, "update": {
            "sessionUpdate": "tool_call", "toolCallId": cid, "title": "T", "kind": kind, "status": "in_progress"}}})
        tracker.on_message({"jsonrpc": "2.0", "method": "session/update", "params": {"sessionId": fx.SESSION, "update": {
            "sessionUpdate": "tool_call_update", "toolCallId": cid, "status": "pending"}}})

    # 14c: BypassSandbox is refused by VBear, with no card
    def test_14c_a_request_with_bypass_sandbox_is_refused_with_no_card_for_true_a_string_and_a_number(self):
        from tests import agy_chat_fixtures as fx
        acp = self.agy_protocol()
        consts = acp.VERSIONS["1.5.3"]
        for value in (True, "true", 1):
            tracker = acp.AgyTracker(consts, workdir="/made/up/work", session_id=fx.SESSION)
            self.announce(tracker, fx)
            out = tracker.on_message({"jsonrpc": "2.0", "id": 4, "method": "session/request_permission", "params": {
                "sessionId": fx.SESSION, "options": [{"optionId": "allow", "kind": "allow_once"}, {"optionId": "deny", "kind": "reject_once"}],
                "toolCall": {"toolCallId": "c-1", "title": "T", "kind": "execute", "status": "pending",
                             "rawInput": {"BypassSandbox": value, "CommandLine": "echo x"}}}})
            request = [d for k, d in out if k == "permission_request"]
            self.assertEqual(len(request), 1, value)
            self.assertEqual((request[0]["action"], request[0]["bypass"]), ("deny", True), value)
            with self.assertRaises(ValueError):
                tracker.answered(4, "allow")                   # there is no way to allow it

    def test_14c_a_request_without_it_is_asked_and_one_with_false_is_too(self):
        from tests import agy_chat_fixtures as fx
        acp = self.agy_protocol()
        for raw in ({"CommandLine": "echo x"}, {"CommandLine": "echo x", "BypassSandbox": False}):
            tracker = acp.AgyTracker(acp.VERSIONS["1.5.3"], workdir="/made/up/work", session_id=fx.SESSION)
            self.announce(tracker, fx)
            out = tracker.on_message({"jsonrpc": "2.0", "id": 4, "method": "session/request_permission", "params": {
                "sessionId": fx.SESSION, "options": [{"optionId": "allow", "kind": "allow_once"}, {"optionId": "deny", "kind": "reject_once"}],
                "toolCall": {"toolCallId": "c-1", "title": "T", "kind": "execute", "status": "pending", "rawInput": raw}}})
            self.assertEqual([d["action"] for k, d in out if k == "permission_request"], ["ask"], raw)

    def test_14b_the_settings_the_chat_environment_writes_and_the_launch_records_are_the_one_table(self):
        from vbear.runtime import agent_sessions, agy_chat_env
        acp = self.agy_protocol()
        newest = acp.VERSIONS[tuple(acp.VERSIONS)[-1]]
        self.assertIs(agy_chat_env.SETTINGS, newest.settings)
        self.assertEqual(agy_chat_env.SETTINGS_BYTES, acp.settings_bytes(newest))
        for version, consts in acp.VERSIONS.items():
            recorded = agent_sessions.agy_chat_settings(version, "/s/agy-chat-home")
            self.assertEqual(recorded["settings"], consts.settings)
            self.assertEqual((recorded["model"], recorded["sandbox"], recorded["argv"]),
                             (consts.model_id, True, acp.argv_for(consts, "/s/agy-chat-home")))
        # no file but the protocol module spells a value of the settings out
        for path in agy_files(AGY_PATTERNS):
            if path.name == "agy_chat_protocol.py":
                continue
            text = path.read_text(encoding="utf-8")
            # (the session reads ``toolPermission`` out of the table for the record's permission_mode: a key read, not a value spelled out)
            for word in ("request-review", "enableTerminalSandbox", "allowNonWorkspaceAccess", "useG1Credits"):
                code = [n.value for n in ast.walk(ast.parse(text)) if isinstance(n, ast.Constant) and isinstance(n.value, str)
                        and n.value == word]
                self.assertEqual(code, [], f"{path.name} spells {word} out")

    # 14d: the environment of the process is the six variables of the table and nothing of the account, however polluted the daemon's is
    def test_14d_the_environment_is_exactly_the_six_variables_whatever_the_source_holds(self):
        from vbear.runtime import agent_sessions
        acp = self.agy_protocol()
        polluted = {"PATH": "/usr/bin", "USER": "someone", "LOGNAME": "someone", "LANG": "C", "TMPDIR": "/var/tmp/x", "HOME": "/real/home",
                    "ANTIGRAVITY_PERM_GRANTS": "must-not-pass", "GEMINI_API_KEY": "must-not-pass", "GOOGLE_API_KEY": "must-not-pass",
                    "GOOGLE_APPLICATION_CREDENTIALS": "must-not-pass", "GOOGLE_CLOUD_PROJECT": "must-not-pass", "OPENAI_API_KEY": "x",
                    "ANTHROPIC_API_KEY": "x", "TERM": "xterm", "SSH_AUTH_SOCK": "/x", "CODEX_HOME": "/x"}
        for version, consts in acp.VERSIONS.items():
            self.assertEqual(consts.env_keys, ("PATH", "USER", "LOGNAME", "LANG", "TMPDIR", "HOME"))
            got = agent_sessions.agy_chat_env({"cli_version": version}, polluted)
            self.assertEqual(sorted(got), sorted(consts.env_keys))
            self.assertEqual(got, {k: polluted[k] for k in consts.env_keys})
            self.assertNotIn("must-not-pass", json.dumps(got))

    def test_14d_no_agy_file_names_a_variable_of_the_account_in_code(self):
        problems = []
        for path in agy_files(AGY_BANNED_PATTERNS):
            problems += account_variable_uses(path.read_text(encoding="utf-8"), str(path.relative_to(PACKAGE)))
        self.assertEqual(problems, [], "\n".join(problems))

    def test_14d_the_scan_fires_on_small_made_up_sources(self):
        for source in ('KEYS = ["ANTIGRAVITY_PERM_GRANTS"]\n', 'env["GEMINI_API_KEY"] = os.environ["GEMINI_API_KEY"]\n',
                       'X = {"GOOGLE_API_KEY": 1}\n', 'def f(env):\n    env.pop("GOOGLE_APPLICATION_CREDENTIALS")\n'):
            self.assertTrue(account_variable_uses(source), source)
        for source in ('"""Says ANTIGRAVITY_* and GEMINI_* in prose."""\nX = 1\n', 'KEYS = ("PATH", "USER", "LOGNAME", "LANG", "TMPDIR", "HOME")\n'):
            self.assertEqual(account_variable_uses(source), [], source)

    # 14h: nothing writes a message that changes the mode, the settings of the session or loads one, and the model comes only from the table
    def test_14h_no_agy_file_names_a_message_that_changes_the_mode_or_the_config_or_loads_a_session(self):
        problems = []
        files = agy_files(AGY_BANNED_PATTERNS)
        self.assertIn("agy_chat_session.py", [p.name for p in files])
        for path in files:
            problems += banned_method_uses(path.read_text(encoding="utf-8"), str(path.relative_to(PACKAGE)))
        self.assertEqual(problems, [], "\n".join(problems))

    def test_14h_the_scan_fires_on_small_made_up_sources(self):
        for method in AGY_BANNED_METHODS:
            self.assertTrue(banned_method_uses(f'LINE = {{"method": "{method}"}}\n'), method)
            self.assertTrue(banned_method_uses(f"# {method} would switch it\n"), method)
        self.assertEqual(banned_method_uses('LINE = {"method": "session/set_model"}\n# session/set_model after every start\n'), [])
        self.assertEqual(banned_method_uses('X = "session/loaded"\n'), [])

    def test_14h_the_protocol_has_a_function_for_each_message_it_writes_and_for_no_other(self):
        acp = self.agy_protocol()
        names = sorted(n for n in dir(acp) if n.endswith("_line") and not n.startswith("_") and callable(getattr(acp, n)))
        self.assertEqual(names, ["answer_line", "cancel_line", "error_line", "initialize_line", "prompt_line", "session_new_line",
                                 "session_resume_line", "set_model_line"])

    def test_14h_the_only_methods_written_are_the_known_ones_and_the_model_is_the_tables(self):
        acp = self.agy_protocol()
        consts = acp.VERSIONS["1.5.3"]
        sid = "00000000-0000-4000-8000-0000000000a1"
        options = [{"optionId": "a", "kind": "allow_once"}, {"optionId": "d", "kind": "reject_once"}]
        lines = [acp.initialize_line(1), acp.session_new_line(2, cwd="/w"), acp.session_resume_line(3, sid, cwd="/w"),
                 acp.set_model_line(4, sid, consts), acp.prompt_line(5, sid, "hi"), acp.cancel_line(sid)]
        methods = [json.loads(x)["method"] for x in lines]
        self.assertEqual(methods, ["initialize", "session/new", "session/resume", "session/set_model", "session/prompt", "session/cancel"])
        self.assertEqual(json.loads(acp.set_model_line(4, sid, consts))["params"]["modelId"], consts.model_id)
        self.assertNotIn("method", json.loads(acp.answer_line(6, options, "allow")))              # an answer, not a request
        import inspect
        self.assertEqual(list(inspect.signature(acp.set_model_line).parameters), ["request_id", "session_id", "consts"])


# 14g: a whole fake chat reads and changes nothing of the person's own AGY folders; 14d end to end
from tests.test_p46_agy_chat_daemon import AgyCase, file_call, permission      # noqa: E402


class AgyChatHomeIsLeftAlone(AgyCase):
    DECOYS = (".gemini/antigravity-cli/settings.json", ".gemini/GEMINI.md", ".gemini/config/hooks.json",
              ".agents/skills/decoy-skill/SKILL.md", ".agents/skills/decoy-skill/run.sh", ".agents/workflows/decoy.md",
              ".agents/agents.json")

    def snapshot(self):
        out = {}
        for root, dirs, files in os.walk(self.home):
            for name in dirs + files:
                full = Path(root) / name
                if name.startswith("fake-agy.json"):
                    continue
                st = os.lstat(full)
                out[str(full.relative_to(self.home))] = (st.st_mode, st.st_size, st.st_mtime_ns, st.st_ino)
        return out

    def test_14g_a_whole_chat_with_an_allow_a_deny_and_the_shared_folder_leaves_the_persons_agy_folders_alone(self):
        decoys = []
        for rel in self.DECOYS:
            path = self.home / rel
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("decoy " + rel)
            decoys.append(path)
        os.chmod(self.home / ".agents" / "skills" / "decoy-skill" / "run.sh", 0o755)
        for path in decoys:                                    # nothing may open one: a try would fail, and is seen below
            path.chmod(0o000)
        before = self.snapshot()
        opened = []
        real_open, real_listdir, real_scandir = os.open, os.listdir, os.scandir

        def under_decoys(path) -> bool:
            try:
                text = os.fspath(path)
            except TypeError:
                return False
            return str(self.home / ".gemini") in text or str(self.home / ".agents") in text

        def watch_open(path, *args, **kwargs):
            if under_decoys(path):
                opened.append(("open", os.fspath(path)))
            return real_open(path, *args, **kwargs)

        def watch_listdir(path=".", *args, **kwargs):
            if under_decoys(path):
                opened.append(("listdir", os.fspath(path)))
            return real_listdir(path, *args, **kwargs)

        def watch_scandir(path=".", *args, **kwargs):
            if under_decoys(path):
                opened.append(("scandir", os.fspath(path)))
            return real_scandir(path, *args, **kwargs)

        with mock.patch("os.open", watch_open), mock.patch("os.listdir", watch_listdir), mock.patch("os.scandir", watch_scandir), \
                mock.patch("builtins.open", side_effect=self.refuse_decoys(open)):
            with mock.patch.object(cli_versions, "shared_verified", return_value=True):
                self.configure("permission", permission(**file_call()), "permission")
                first = self.open_chat("emp-1")
                self.assertTrue(self.send(first, shared=True)["ok"])
                self.assertTrue(self.answer(first, self.wait_card(first), "allow")["ok"])
                self.wait_turn(first, 1)
                self.rpc("chat_close", chat_id=first)
                self.wait_gone(first)
                second = self.open_chat("emp-2")
                self.assertTrue(self.send(second)["ok"])
                self.assertTrue(self.answer(second, self.wait_card(second), "deny")["ok"])
                self.wait_turn(second, 1)
        self.assertEqual(opened, [])
        for path in decoys:
            path.chmod(0o000)                                   # unchanged
        self.assertEqual(self.snapshot(), before, "nothing in the persons HOME was made, changed or removed")
        self.assertEqual(len(self.starts()), 2)

    def refuse_decoys(self, real):
        def guarded(file, *args, **kwargs):
            text = os.fspath(file) if isinstance(file, (str, bytes, os.PathLike)) else ""
            if str(self.home / ".gemini") in text or str(self.home / ".agents") in text:
                raise AssertionError(f"opened {text}")
            return real(file, *args, **kwargs)
        return guarded

    def test_14g_the_hooks_name_is_only_looked_at(self):
        hooks = self.home / ".agents" / "hooks.json"
        hooks.parent.mkdir()
        hooks.write_text("{}")
        before = (hooks.stat().st_mtime_ns, hooks.read_bytes())
        self.configure("text")
        chat_id = self.open_chat()
        with mock.patch("builtins.open", side_effect=self.refuse_decoys(open)):
            self.assertEqual(self.send(chat_id)["error"]["code"], "agy_hooks")
        self.assertEqual((hooks.stat().st_mtime_ns, hooks.read_bytes()), before)
        self.assertEqual(self.fake_log(), [])

    def test_14d_a_daemon_that_holds_the_variables_of_the_account_passes_none_of_them_on(self):
        polluted = {"ANTIGRAVITY_PERM_GRANTS": "must-not-pass", "GEMINI_API_KEY": "must-not-pass", "GOOGLE_API_KEY": "must-not-pass",
                    "GOOGLE_APPLICATION_CREDENTIALS": "must-not-pass", "OPENAI_API_KEY": "must-not-pass"}
        self.configure("text")
        chat_id = self.open_chat()
        with mock.patch.dict(os.environ, polluted):
            self.assertTrue(self.send(chat_id)["ok"])
            self.wait_turn(chat_id, 1)
        self.assertEqual(sorted(self.starts()[0]["env_keys"]), sorted(["PATH", "USER", "LOGNAME", "LANG", "TMPDIR", "HOME"]))

    def test_14h_a_whole_fake_chat_writes_only_the_known_methods(self):
        self.configure("permission")
        chat_id = self.open_chat()
        self.assertTrue(self.send(chat_id)["ok"])
        self.wait_card(chat_id)
        self.assertTrue(self.rpc("chat_stop", chat_id=chat_id)["result"]["stopped"])
        self.wait_turn(chat_id, 1)
        self.assertEqual(self.methods().count("session/prompt"), 1)
        self.assertLessEqual(set(self.methods()), {"initialize", "session/new", "session/set_model", "session/prompt", "session/cancel"})


# 14e (P46-5): the feature modules never reach the code of the AGY chat, and the AGY code never reaches a feature's writer
AGY_CHAT_MODULES = ("agy_chat_env", "agy_chat_session", "agy_chat_protocol", "agy_chat_check", "agy_verify",
                    "runtime.agy_chat_env", "runtime.agy_chat_session", "runtime.agy_chat_protocol")
AGY_FEATURE_MODULES = ("memory", "shared_folder", "skillbook", "routines", "groups", "group_runner", "chief", "chief_runner", "dispatch",
                       "dispatch_runner", "autonomy", "auto_continue", "templates", "templates_apply", "templates_mine", "agent_profiles")


def agy_feature_uses(source: str, label: str = "<source>") -> list[str]:
    """What an AGY module (agy*.py, runtime/agy*.py) reaches that belongs to a feature of the person: the writers of the memory, the shared
    folder's switches, the skills, the routines, the role cards, config.json, and the feature modules themselves."""
    found = []
    for check in (memory_writer_uses, shared_writer_uses, skillbook_writer_uses, routine_writer_uses, routine_run_writer_uses, card_writer_calls):
        found += check(source, label)
    found += imports_of(source, AGY_FEATURE_MODULES, label)
    found += [line for line in scan_source(source, label) if "config" in line or "set_conf" in line or "/api/" in line]
    return found


class AgyFeatureRules(unittest.TestCase):
    """P46-5, rules 14e and 14f."""

    def test_14e_no_feature_module_imports_the_code_of_the_agy_chat(self):
        files = scanned_files()
        self.assertTrue(files)
        found = [line for path in files for line in imports_of(path.read_text(encoding="utf-8"), AGY_CHAT_MODULES, path.name)]
        self.assertEqual(found, [])

    def test_14e_the_agy_modules_reach_no_feature_writer_and_no_config(self):
        files = agy_files(AGY_PATTERNS)
        self.assertTrue(files)
        found = [line for path in files for line in agy_feature_uses(path.read_text(encoding="utf-8"), path.name)]
        self.assertEqual(found, [])

    def test_14e_the_scans_fire_on_small_made_up_sources(self):
        for why, source in {
            "imports the env": "from .runtime import agy_chat_env\n",
            "imports the session": "from vbear.runtime.agy_chat_session import AgyChatProcess\n",
            "imports the protocol": "import vbear.runtime.agy_chat_protocol as p\n",
            "imports the check": "from . import agy_chat_check\n",
            "imports the verifier": "from .agy_verify import AgyChatVerifier\n",
        }.items():
            self.assertTrue(imports_of(source, AGY_CHAT_MODULES), why)
        for why, source in {
            "switches memory": "from . import memory\nmemory.set_card({}, [])\n",
            "switches the shared folder": "from . import shared_folder\nshared_folder.set_card({}, [])\n",
            "saves a card": "def f(ap):\n    ap.save_profile(None, {})\n",
            "saves the config": "from . import config as cfg\ncfg.save({})\n",
            "imports the groups": "from . import groups\n",
            "imports the templates": "from .templates_apply import begin_apply\n",
        }.items():
            self.assertTrue(agy_feature_uses(source), why)
        self.assertEqual(agy_feature_uses("import json\nfrom . import admin_policy\n"), [])

    # 14f: memory and the shared folder are off for an AGY employee, and open only on the person's yes to Google
    def setUp(self):
        import tempfile
        tmp = tempfile.TemporaryDirectory(prefix="vg14-")
        self.addCleanup(tmp.cleanup)
        self.root = Path(os.path.realpath(tmp.name))
        home = self.root / "h"
        (home / ".vbear").mkdir(parents=True, mode=0o700)
        patch = mock.patch.dict(os.environ, {"HOME": str(home), "VBEAR_HOME": str(home / ".vbear"), "VBEAR_RUNTIME_AUTOSTART": "0"})
        patch.start()
        self.addCleanup(patch.stop)
        self.state = home / ".vbear"
        self.cards = [{"id": "agy-one", "name": "虛構AGY員工", "tool": "agy", "engine": "agy-chat", "can_chat": True},
                      {"id": "agy-two", "name": "虛構AGY員工二", "tool": "agy", "engine": "agy-chat", "can_chat": True}]

    def tree(self):
        return {str(p.relative_to(self.state)): p.read_bytes() for p in sorted(self.state.rglob("*")) if p.is_file()}

    def test_14f_memory_is_off_for_agy_by_default_and_needs_the_yes_to_google(self):
        from vbear import memory
        from vbear.api_error import ApiError
        self.assertIs(memory.DEFAULT_ON["agy-chat"], False)
        self.assertEqual(memory.COMPANY["agy-chat"], "Google")
        before = self.tree()
        for body in ({"profile_id": "agy-one", "on": True}, {"profile_id": "agy-one", "on": True, "confirm_company": False}):
            with self.assertRaises(ApiError) as got:
                memory.set_card(body, self.cards)
            self.assertEqual((got.exception.status, got.exception.code, got.exception.extra["warn"]), (409, "memory_confirm", ["send_to_google"]))
        with self.assertRaises(ApiError) as got:
            memory.set_card({"profile_id": "agy-one", "on": True, "confirm_company": "yes"}, self.cards)
        self.assertEqual(got.exception.status, 400)
        self.assertEqual(self.tree(), before, "a refusal writes nothing")
        self.assertEqual(memory.set_card({"profile_id": "agy-one", "on": True, "confirm_company": True}, self.cards)["on"], True)

    def test_14f_the_shared_folder_is_not_open_to_agy_in_v0200_by_any_way_in(self):
        """v0.20.0 does not open the shared folder to an AGY employee (ADR 0012): every way in is refused, and nothing is written."""
        from vbear import shared_folder as sf
        from vbear.api_error import ApiError
        self.assertNotIn("agy-chat", sf.SUPPORTED_ENGINES)
        before = self.tree()
        for call in (lambda: sf.set_card({"profile_id": "agy-one", "on": True, "confirm_company": True}, self.cards),
                     lambda: sf.plan_cards(["agy-one", "agy-two"], self.cards, True),
                     lambda: sf.plan_cards([], self.cards, True, new_engines=["agy-chat"])):
            with self.assertRaises(ApiError) as got:
                call()
            self.assertEqual((got.exception.status, got.exception.code, str(got.exception)),
                             (400, "card_tool_unsupported", "AGY 員工這版不能用共用資料夾，之後 AGY 新版再檢查。"))
        opened, error = sf.open_cards(["agy-one", "agy-two"], self.cards, "group", True)
        self.assertEqual((opened, error.code), ([], "card_tool_unsupported"))
        self.assertEqual(self.tree(), before, "none of them wrote a byte")
        self.assertFalse(sf.for_card("agy-one", "agy-chat"))

    def test_14f_the_part_for_agy_kept_in_the_code_still_needs_the_yes_to_google(self):
        """If a newer AGY is checked and ``agy-chat`` is put back into ``SUPPORTED_ENGINES``, the rule 14f is still there."""
        from unittest import mock
        from vbear import shared_folder as sf
        from vbear.api_error import ApiError
        self.assertEqual(sf.COMPANY["agy-chat"], "Google")
        with mock.patch.object(sf, "SUPPORTED_ENGINES", ("claude-chat", "codex-chat", "agy-chat")):
            before = self.tree()
            with self.assertRaises(ApiError) as got:
                sf.set_card({"profile_id": "agy-one", "on": True}, self.cards)
            self.assertEqual((got.exception.status, got.exception.code, got.exception.extra["warn"]), (409, "shared_confirm", ["send_to_google"]))
            with self.assertRaises(ApiError) as got:
                sf.plan_cards(["agy-one", "agy-two"], self.cards)
            self.assertEqual((got.exception.status, got.exception.code), (409, "shared_confirm"))
            with self.assertRaises(ApiError) as got:
                sf.plan_cards([], self.cards, False, new_engines=["agy-chat"])
            self.assertEqual(got.exception.code, "shared_confirm")
            opened, error = sf.open_cards(["agy-one", "agy-two"], self.cards, "group")
            self.assertEqual((opened, error.code), ([], "shared_confirm"))
            self.assertEqual(self.tree(), before, "none of them wrote a byte")
            self.assertFalse(sf.for_card("agy-one", "agy-chat"))

    def test_14f_a_dispatch_that_was_not_ticked_opens_nothing_for_the_employee_it_made(self):
        from unittest import mock
        from vbear import shared_folder as sf
        before = self.tree()
        self.assertFalse(sf.open_for_dispatch("d-" + "0" * 12, "agy-one", self.cards))
        self.assertEqual(self.tree(), before)
        sf.mark_dispatch("d-" + "1" * 12, True, False)              # ticked, but the yes to Google was not given
        marked = self.tree()
        from vbear.api_error import ApiError
        with self.assertRaises(ApiError) as got:
            sf.open_for_dispatch("d-" + "1" * 12, "agy-one", self.cards)
        self.assertEqual(got.exception.code, "card_tool_unsupported", "this version: AGY has no shared folder at all")
        self.assertEqual(self.tree(), marked)
        with mock.patch.object(sf, "SUPPORTED_ENGINES", ("claude-chat", "codex-chat", "agy-chat")):
            with self.assertRaises(ApiError) as got:
                sf.open_for_dispatch("d-" + "1" * 12, "agy-one", self.cards)
            self.assertEqual(got.exception.code, "shared_confirm")
            self.assertEqual(self.tree(), marked)

    def test_14f_the_templates_and_the_dispatch_name_neither_memory_nor_the_shared_folder_in_a_card(self):
        from vbear import dispatch, templates
        card = {"key": "x", "name": "名", "position": "pm", "instructions": "寫", "claude_model": None}
        for body in (templates.card_body(card, "agy"),
                     dispatch.card_body({"ref": "N1", "name": "名", "position": "pm", "tool": "agy", "model_alias": ""})):
            text = json.dumps(body, ensure_ascii=False)
            for word in ("memory", "shared", "confirm_company", "send_to_google"):
                self.assertNotIn(word, text)
            self.assertEqual(body["model"], {"tool": "agy", "model_id": ""})


# ===================================================================================================================================
# 15a, 15b (P47-1, ADR 0013): the plain navigation changes only what the screen shows. 15c, 15d and 15e are in the front-end tests named in
# the module's description above; P47-6's documentation test checks that those files carry their rule.
# ===================================================================================================================================

ADVANCED_MODE = "advanced_mode"


def _advanced_mode_nodes(tree):
    """Every place of a syntax tree that names the advanced mode as a string (a key, a name in a set, a call's text) or as a name."""
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and node.value == ADVANCED_MODE:
            yield node
        elif isinstance(node, ast.Name) and node.id == ADVANCED_MODE:
            yield node
        elif isinstance(node, ast.Attribute) and node.attr == ADVANCED_MODE:
            yield node
        elif isinstance(node, ast.keyword) and node.arg == ADVANCED_MODE:
            yield node


def advanced_mode_uses(source: str, label: str = "<source>", allow: str = "") -> list[str]:
    """The places of a Python source that name the advanced mode, except the ones ``allow`` names: "default" (a key of the default config),
    "server" (the set of keys the console may write, and the line that turns the value into a boolean and nothing else)."""
    tree = ast.parse(source)
    parents = {}
    for parent in ast.walk(tree):
        for child in ast.iter_child_nodes(parent):
            parents[child] = parent
    found = []
    for node in _advanced_mode_nodes(tree):
        parent = parents.get(node)
        ok = False
        if allow == "default":
            ok = isinstance(parent, ast.Dict) and node in parent.keys
        elif allow == "server":
            if isinstance(parent, ast.Set):
                ok = True
            elif isinstance(parent, ast.Tuple) and isinstance(parents.get(parent), ast.Compare):
                branch = parents.get(parents[parent])
                ok = (isinstance(branch, ast.If) and len(branch.body) == 1 and isinstance(branch.body[0], ast.Assign)
                      and ast.dump(branch.body[0].value) == ast.dump(ast.parse("bool(value)").body[0].value))
        if not ok:
            found.append(f"{label}:{getattr(node, 'lineno', '?')} names the advanced mode")
    return found


# the lines of web/app.js that may name the advanced mode: reading it from the console's config, and the key of the settings switch's save
APP_ADVANCED_READ = re.compile(r"\b(?:conf|config)\.advanced_mode\b")
APP_ADVANCED_SAVE = re.compile(r"""(?:saveConf\(|api\.post\("/api/config",\s*)\{\s*advanced_mode:""")
APP_SENDS = re.compile(r"""api\.(?:post|patch|send|del)\(|fetch\(|localStorage|store\.set""")


def app_advanced_uses(source: str, label: str = "<app.js>") -> list[str]:
    """The lines of the page's code that name the advanced mode in any other way than the two allowed: read from a config, or sent as the
    key of the save of the settings switch (to /api/config). A line that sends something else with it (any other path, the browser's storage)
    is a use."""
    found = []
    for number, line in enumerate(source.splitlines(), 1):
        if ADVANCED_MODE not in line or line.lstrip().startswith("//"):
            continue
        rest = APP_ADVANCED_READ.sub("", line)
        rest = APP_ADVANCED_SAVE.sub("", rest)
        if ADVANCED_MODE in rest:
            found.append(f"{label}:{number}: {line.strip()[:90]}")
        elif APP_SENDS.search(line) and not APP_ADVANCED_SAVE.search(line):
            found.append(f"{label}:{number}: sends it: {line.strip()[:90]}")
    return found


class AdvancedModeIsADisplay(unittest.TestCase):
    """15a"""

    def test_15a_only_config_and_server_name_the_advanced_mode(self):
        named = {}
        for path in sorted(PACKAGE.rglob("*.py")):
            relative = path.relative_to(PACKAGE).as_posix()
            if ADVANCED_MODE in path.read_text(encoding="utf-8"):
                named[relative] = path
        self.assertEqual(sorted(named), ["config.py", "server.py"], "no other Python file reads the advanced mode to decide anything")

    def test_15a_config_has_it_only_as_its_default_and_server_only_as_a_writable_key_turned_into_a_boolean(self):
        self.assertEqual(advanced_mode_uses((PACKAGE / "config.py").read_text(encoding="utf-8"), "config.py", "default"), [])
        self.assertEqual(advanced_mode_uses((PACKAGE / "server.py").read_text(encoding="utf-8"), "server.py", "server"), [])
        self.assertEqual(cfg_default()["advanced_mode"], False, "off unless the person turns it on")

    def test_15a_the_scan_fires_on_small_made_up_sources(self):
        read = "def mode(conf):\n    if conf.get('advanced_mode'):\n        return 'full'\n    return 'safe'\n"
        self.assertEqual(len(advanced_mode_uses(read, "x.py")), 1)
        attr = "def f(c):\n    return c.advanced_mode\n"
        self.assertEqual(len(advanced_mode_uses(attr, "x.py")), 1)
        kw = "launch(advanced_mode=True)\n"
        self.assertEqual(len(advanced_mode_uses(kw, "x.py")), 1)
        self.assertEqual(len(advanced_mode_uses("DEFAULT = {'advanced_mode': False}\n", "x.py", "server")), 1, "a default belongs to config.py, not the server")
        self.assertEqual(advanced_mode_uses("DEFAULT = {'advanced_mode': False}\n", "x.py", "default"), [])
        self.assertEqual(advanced_mode_uses("W = {'a', 'advanced_mode'}\n", "x.py", "server"), [])
        ok = "for key in body:\n    if key in ('advanced_mode', 'usage_enabled'):\n        value = bool(value)\n"
        self.assertEqual(advanced_mode_uses(ok, "x.py", "server"), [])
        bad = "for key in body:\n    if key in ('advanced_mode', 'usage_enabled'):\n        value = bool(value)\n        grant(value)\n"
        self.assertEqual(len(advanced_mode_uses(bad, "x.py", "server")), 1, "the line may do nothing but make a boolean")
        other = "for key in body:\n    if key in ('advanced_mode',):\n        full_mode = True\n"
        self.assertEqual(len(advanced_mode_uses(other, "x.py", "server")), 1)

    def test_15a_the_page_names_it_only_to_read_it_and_to_save_the_switch(self):
        source = (Path(__file__).resolve().parents[1] / "web" / "app.js").read_text(encoding="utf-8")
        self.assertEqual(app_advanced_uses(source), [])
        self.assertGreaterEqual(len([line for line in source.splitlines() if ADVANCED_MODE in line]), 2, "and it does name it (the scan is looking at something)")

    def test_15a_the_page_scan_fires_on_small_made_up_sources(self):
        reads = ["const advanced = !!conf.advanced_mode;", "const on = !!(conf && conf.advanced_mode);", "if (config.advanced_mode) show();"]
        for line in reads:
            self.assertEqual(app_advanced_uses(line), [], line)
        saves = ["on: { change: (e) => saveConf({ advanced_mode: e.target.checked }) }", 'await api.post("/api/config", { advanced_mode: true });']
        for line in saves:
            self.assertEqual(app_advanced_uses(line), [], line)
        for line in ['await api.post("/api/dispatch", { advanced_mode: conf.advanced_mode });',
                     'await api.post("/api/chats", { profile_id: p, mode: conf.advanced_mode ? "full" : "safe" });',
                     'store.set("mode", conf.advanced_mode);',
                     'const mode = advanced_mode ? "full" : "safe";',
                     'fetch("/x?m=" + conf.advanced_mode);',
                     'api.post("/api/settings/autonomy", { advanced_mode: true });']:
            self.assertEqual(len(app_advanced_uses(line)), 1, line)
        self.assertEqual(app_advanced_uses("// the advanced_mode switch\n"), [], "a comment is not a use")


class AdvancedModeChangesNothingElse(unittest.TestCase):
    """15a, the behaviour: a console with the advanced mode turned on and off answers everything else the same."""

    def setUp(self):
        import tempfile
        import threading
        import urllib.error
        import urllib.request
        from http.server import ThreadingHTTPServer
        from vbear import config as cfg, server
        from vbear.index import Store
        self.tmp = tempfile.TemporaryDirectory(prefix="vbear-p47-adv-")
        self.addCleanup(self.tmp.cleanup)
        home = Path(self.tmp.name) / "h"
        home.mkdir()
        patch = mock.patch.dict(os.environ, {"HOME": str(home), "VBEAR_HOME": str(home / ".vbear"), "VBEAR_RUNTIME_AUTOSTART": "0"})
        patch.start()
        self.addCleanup(patch.stop)
        self.token = "synthetic-test-token"
        self.console = c = server.Console.__new__(server.Console)
        c.lock = threading.Lock()
        c.auth_token = self.token
        c.store = Store()
        c.store._static = {"skills": [], "roles": []}
        c.store.set_conf(cfg.load())
        c.runtime = mock.Mock(binary=lambda: "unused")
        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), None)
        c.port = self.httpd.server_address[1]
        self.httpd.RequestHandlerClass = server.make_handler(c)
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()
        self.addCleanup(self.httpd.server_close)
        self.addCleanup(self.httpd.shutdown)
        self._urllib = urllib

    def call(self, path, method="GET", body=None):
        headers = {"Authorization": f"Bearer {self.token}", "X-VBear": "1", "Origin": f"http://127.0.0.1:{self.console.port}",
                   "Content-Type": "application/json"}
        data = json.dumps(body).encode() if body is not None else None
        req = self._urllib.request.Request(f"http://127.0.0.1:{self.console.port}" + path, data=data, method=method, headers=headers)
        try:
            with self._urllib.request.urlopen(req, timeout=15) as response:
                return response.status, json.loads(response.read())
        except self._urllib.error.HTTPError as exc:
            with exc:
                return exc.code, json.loads(exc.read() or b"{}")

    def snapshot(self):
        autonomy = self.call("/api/settings/autonomy")
        config = self.call("/api/config")
        profiles = self.call("/api/agent-profiles")
        self.assertEqual((autonomy[0], config[0], profiles[0]), (200, 200, 200), (autonomy, config, profiles))
        conf = dict(config[1]["config"])
        conf.pop(ADVANCED_MODE, None)
        return {"autonomy": autonomy[1], "config": conf,
                "launch_modes": sorted((p["id"], p.get("launch_mode")) for p in profiles[1]["profiles"])}

    def test_15a_switching_it_changes_no_autonomy_setting_no_limit_and_no_launch_mode(self):
        from vbear import agent_profiles as ap
        card = ap.save_profile(None, {"name": "虛構員工", "position": "pm", "model": {"tool": "claude"}})["id"]
        self.assertEqual(self.call("/api/config", "POST", {"meeting_limits": {"daily_usd": 7}})[0], 200)
        self.assertEqual(self.call("/api/config", "POST", {"chat_limits": {"per_turn_usd": 0.5}})[0], 200)
        self.assertEqual(self.call("/api/settings/autonomy", "POST", {"create_cards": False, "dispatch": False, "routines": True, "auto_continue": False})[0], 200)
        before = self.snapshot()
        self.assertIn(card, [p[0] for p in before["launch_modes"]])
        self.assertEqual(before["config"]["meeting_limits"]["daily_usd"], 7)
        self.assertEqual(before["config"]["chat_limits"]["per_turn_usd"], 0.5)
        for value in (True, False, True):
            status, out = self.call("/api/config", "POST", {ADVANCED_MODE: value})
            self.assertEqual(status, 200, out)
            self.assertIs(self.call("/api/config")[1]["config"][ADVANCED_MODE], value)
            self.assertEqual(self.snapshot(), before, f"advanced mode {value} changed nothing else")
        self.assertEqual(self.call("/api/config", "POST", {ADVANCED_MODE: "yes"})[0], 200)
        self.assertIs(self.call("/api/config")[1]["config"][ADVANCED_MODE], True, "a value that is not a boolean is made one")
        self.assertEqual(self.snapshot(), before)

def cfg_default():
    from vbear import config as cfg
    return cfg.DEFAULT_CONFIG


# --- 15b ---------------------------------------------------------------------------------------------------------------------------
# What v0.20.0 (f920402) had. A later version may use fewer of these; it may not use one that is not here.
V0200_APP_API_PREFIXES = frozenset({
    "/api/actions", "/api/agent-builder/catalog", "/api/agent-builder/intent-check?", "/api/agent-profiles",
    "/api/agent-profiles/", "/api/annotations", "/api/armory", "/api/auth", "/api/chat-support/verify", "/api/chats",
    "/api/chats/", "/api/chief", "/api/chief/", "/api/chief/preview?chat_id=", "/api/config", "/api/dispatch",
    "/api/dispatch/", "/api/first-ceo", "/api/first-ceo?tool=", "/api/flows", "/api/flows/", "/api/flows/storage", "/api/folders/inspect?path=",
    "/api/governance", "/api/groups", "/api/groups/", "/api/live", "/api/meetings", "/api/meetings/", "/api/meetings/ledger",
    "/api/meetings/preview", "/api/meetings/verify", "/api/memory", "/api/memory/", "/api/memory/cards", "/api/memory/clear",
    "/api/memory/export", "/api/memory/suggest", "/api/memory/suggest/", "/api/memory/suggest/preview", "/api/my-skills",
    "/api/my-skills/", "/api/my-skills/suggest", "/api/my-skills/suggest/", "/api/my-skills/suggest/preview",
    "/api/native/agent-launches", "/api/native/agent-previews", "/api/native/claude-verification", "/api/native/sessions/",
    "/api/native/terminals", "/api/overview", "/api/rescan", "/api/role-translations", "/api/role-translations/batch",
    "/api/role-translations/batch/cancel", "/api/roles", "/api/routines", "/api/routines/", "/api/routines/missed/",
    "/api/routines/settings", "/api/routines/waiting/", "/api/settings/autonomy", "/api/setup/daily-limit",
    "/api/setup/settle", "/api/setup/terminals", "/api/setup/tools", "/api/setup/tools/", "/api/setup/tools?force=1",
    "/api/shared", "/api/shared/cards", "/api/shared/reveal", "/api/skills", "/api/skills/", "/api/staffing", "/api/staffing/",
    "/api/staffing/preview", "/api/staffing/suggest?task_id=", "/api/staffing?task_id=", "/api/task-templates", "/api/tasks",
    "/api/tasks/", "/api/templates", "/api/templates/applies/", "/api/templates/apply", "/api/templates/mine",
    "/api/templates/mine/", "/api/templates/preview", "/api/term/", "/api/translations", "/api/translations/batch",
    "/api/translations/batch/cancel", "/api/translations/orphans", "/api/translations/verify", "/api/waiting",
})

V0200_SERVER_ROUTES = frozenset({
    "/api/", "/api/actions", "/api/agent-builder/catalog", "/api/agent-builder/intent-check", "/api/agent-profiles",
    "/api/agent-profiles/", "/api/annotations", "/api/armory", "/api/auth", "/api/chat-support", "/api/chat-support/verify",
    "/api/chats", "/api/chats/", "/api/chief", "/api/chief/", "/api/chief/preview", "/api/config", "/api/dispatch",
    "/api/dispatch/", "/api/first-ceo", "/api/flows", "/api/flows/", "/api/flows/storage", "/api/folders/inspect",
    "/api/governance", "/api/groups", "/api/groups/", "/api/live", "/api/meetings", "/api/meetings/", "/api/meetings/ledger",
    "/api/meetings/preview", "/api/meetings/verify", "/api/memory", "/api/memory/", "/api/memory/cards", "/api/memory/clear",
    "/api/memory/export", "/api/memory/suggest", "/api/memory/suggest/", "/api/memory/suggest/preview", "/api/my-skills",
    "/api/my-skills/", "/api/my-skills/suggest", "/api/my-skills/suggest/", "/api/my-skills/suggest/preview",
    "/api/native/agent-launches", "/api/native/agent-previews", "/api/native/claude-verification", "/api/native/sessions",
    "/api/native/sessions/", "/api/native/terminals", "/api/overview", "/api/rescan", "/api/role-translations",
    "/api/role-translations/batch", "/api/role-translations/batch/cancel", "/api/roles", "/api/routines", "/api/routines/",
    "/api/routines/settings", "/api/settings/autonomy", "/api/setup/daily-limit", "/api/setup/settle", "/api/setup/terminals",
    "/api/setup/tools", "/api/setup/tools/", "/api/shared", "/api/shared/cards", "/api/shared/reveal", "/api/skills",
    "/api/skills/", "/api/staffing", "/api/staffing/", "/api/staffing/preview", "/api/staffing/suggest", "/api/task-templates",
    "/api/tasks", "/api/tasks/", "/api/templates", "/api/templates/", "/api/templates/apply", "/api/templates/mine",
    "/api/templates/preview", "/api/term/", "/api/translations", "/api/translations/batch", "/api/translations/batch/cancel",
    "/api/translations/orphans", "/api/translations/verify", "/api/waiting",
})

CHAT_KINDS_V0200 = {
    "chat_created": ("profile_id",),
    "user_message": ("text", "turn"),
    "turn_started": ("cap_usd", "turn"),
    "process_started": ("budget_usd", "instructions", "mode"),
    "session_ready": ("model", "permission_mode"),
    "reply": ("text", "truncated", "turn"),
    "tool_call": ("summary", "tool", "tool_use_id", "turn"),
    "tool_result": ("is_error", "source", "text", "tool", "tool_use_id", "truncated", "turn"),
    "card": ("card_id", "editable", "input", "reason", "state", "tool", "turn"),
    "card_decision": ("card_id", "decision", "turn", "value"),
    "auto_allowed": ("reason", "summary", "tool", "tool_use_id", "turn"),
    "denied": ("by", "reason", "summary", "tool", "tool_use_id", "turn"),
    "turn_ended": ("cost_usd", "is_error", "reason", "reported", "subtype", "total_usd", "turn"),
    "process_ended": ("reason", "returncode"),
    "anomaly": ("event_type", "fields"),
    "error": ("message", "turn"),
    "session_bound": ("thread_id",),
    "usage": ("delta_tokens", "total_tokens", "turn"),
    "plan_usage": ("primary_pct", "primary_resets_at", "primary_window_min", "reached", "secondary_pct", "secondary_resets_at", "secondary_window_min", "turn"),
    "card_edit_sent": ("card_id", "text"),
}
CHAT_OPTIONAL_V0200 = {"turn_ended": ("estimate", "tokens"), "user_message": ("origin",)}
CHAT_ALTERNATIVES_V0200 = {"session_ready": ("claude_code_version", "cli_version")}
API_PREFIX = re.compile(r"""["'`](/api/[^"'`$\s]*)""")


def app_api_prefixes(source: str) -> set[str]:
    """The /api/ paths the page uses, each cut at the first ``${``, quote or space: ``/api/chats/${id}`` is ``/api/chats/``."""
    return set(API_PREFIX.findall(source))


def server_routes(source: str) -> set[str]:
    """Every string of the console that is a path under /api/ (the routes it answers)."""
    return {n.value for n in ast.walk(ast.parse(source)) if isinstance(n, ast.Constant) and isinstance(n.value, str) and n.value.startswith("/api/")}


def chat_record_shape(kinds, optional, alternatives) -> dict:
    """The kinds of a chat's record and the names of their fields (not the checks of their values)."""
    return {"kinds": {k: tuple(sorted(v)) for k, v in kinds.items()},
            "optional": {k: tuple(sorted(v)) for k, v in optional.items()},
            "alternatives": {k: tuple(sorted(v)) for k, v in alternatives.items()}}


class NothingNewIsAsked(unittest.TestCase):
    """15b"""

    def test_15b_the_page_uses_no_path_that_v0200_did_not(self):
        source = (Path(__file__).resolve().parents[1] / "web" / "app.js").read_text(encoding="utf-8")
        used = app_api_prefixes(source)
        self.assertGreater(len(used), 60, "the scan is looking at something")
        self.assertEqual(sorted(used - V0200_APP_API_PREFIXES), [], "a path v0.20.0 did not use")

    def test_15b_the_console_answers_the_routes_of_v0200_and_no_other(self):
        used = server_routes((PACKAGE / "server.py").read_text(encoding="utf-8"))
        self.assertEqual(sorted(used - V0200_SERVER_ROUTES), [], "a new route")
        self.assertEqual(sorted(V0200_SERVER_ROUTES - used), [], "a route of v0.20.0 that is gone")

    def test_15b_the_record_of_a_chat_has_the_kinds_and_fields_of_v0200(self):
        from vbear.runtime import chat_store
        shape = chat_record_shape(chat_store.KINDS, chat_store._OPTIONAL, chat_store._ALTERNATIVES)
        self.assertEqual(shape["kinds"], {k: tuple(sorted(v)) for k, v in CHAT_KINDS_V0200.items()})
        self.assertEqual(shape["optional"], {k: tuple(sorted(v)) for k, v in CHAT_OPTIONAL_V0200.items()})
        self.assertEqual(shape["alternatives"], {k: tuple(sorted(v)) for k, v in CHAT_ALTERNATIVES_V0200.items()})

    def test_15b_the_scans_fire_on_small_made_up_sources(self):
        new_path = 'api.get("/api/spending");\nconst x = `/api/chats/${id}/summary`;\n'
        self.assertEqual(app_api_prefixes(new_path) - V0200_APP_API_PREFIXES, {"/api/spending"}, "a new path is caught; a longer one under a known prefix is the same prefix")
        self.assertEqual(app_api_prefixes('api.get("/api/chats/" + id)') - V0200_APP_API_PREFIXES, set())
        # P48-3: the one query on a known path that ADR 0014 approves is listed; any other new query, or a new path, is still caught
        self.assertEqual(app_api_prefixes("api.get(`/api/first-ceo?tool=${pick}`)") - V0200_APP_API_PREFIXES, set())
        self.assertEqual(app_api_prefixes("api.get(`/api/first-ceo?name=${x}`)") - V0200_APP_API_PREFIXES, {"/api/first-ceo?name="})
        self.assertEqual(app_api_prefixes('api.get("/api/first-ceo-other")') - V0200_APP_API_PREFIXES, {"/api/first-ceo-other"})
        route = 'if path == "/api/spending":\n    return 1\nif path.startswith("/api/chats/"):\n    return 2\n'
        self.assertEqual(server_routes(route) - V0200_SERVER_ROUTES, {"/api/spending"})
        kinds = dict(CHAT_KINDS_V0200)
        base = chat_record_shape({k: dict.fromkeys(v) for k, v in kinds.items()}, {k: dict.fromkeys(v) for k, v in CHAT_OPTIONAL_V0200.items()},
                                 {k: dict.fromkeys(v) for k, v in CHAT_ALTERNATIVES_V0200.items()})
        self.assertEqual(base["kinds"], {k: tuple(sorted(v)) for k, v in CHAT_KINDS_V0200.items()}, "the helper reads a table the way the test does")
        more = chat_record_shape({**{k: dict.fromkeys(v) for k, v in kinds.items()}, "spending": {"usd": None}}, {}, {})
        self.assertNotEqual(more["kinds"], base["kinds"], "a new kind is caught")
        fewer = {k: dict.fromkeys(v) for k, v in kinds.items()}
        fewer["reply"] = {"text": None, "turn": None, "truncated": None, "extra": None}
        self.assertNotEqual(chat_record_shape(fewer, {}, {})["kinds"], base["kinds"], "a new field of a kind is caught")



class DeletingNeverLowersTheDay(unittest.TestCase):
    """16f: deletion cannot erase the day's bill, including future spend kinds."""

    def test_16f_each_deletable_kind_keeps_its_cost(self):
        from tests import test_p48_spend_keep as fixtures
        case = fixtures.SpendKeepTests()
        case.setUp()
        self.addCleanup(case.doCleanups)
        for mod, store in fixtures.CASES:
            with self.subTest(kind=mod.__name__):
                case.assert_kept(mod, store)
        from vbear.runtime import chat_store as cs
        chat = cs.create(case.base, 'fictional', now=case.now)
        log = cs.ChatLog(case.base, chat['id'])
        try:
            log.append('turn_started', {'turn': 1, 'cap_usd': '0.1'}, now=case.now)
            log.append('turn_ended', {'turn': 1, 'cost_usd': '0.02', 'reported': True, 'total_usd': None,
                                    'reason': 'result', 'subtype': None, 'is_error': False}, now=case.now)
        finally:
            log.close()
        before = case.runner._day()
        cs.delete(case.base, chat['id'], now=case.now)
        self.assertGreaterEqual(case.runner._day(), before)

    def test_16f_bad_evidence_and_running_records_fail_closed(self):
        from tests import test_p48_spend_keep as fixtures
        for method in ('test_bad_tombstone_makes_day_unknown_and_blocks_spending',
                       'test_queued_and_running_cannot_be_deleted'):
            case = fixtures.SpendKeepTests()
            case.setUp()
            try:
                getattr(case, method)()
            finally:
                case.doCleanups()

    def test_16f_table_covers_every_spend_kind_with_delete(self):
        import inspect
        import sys
        from tests import test_p48_spend_keep as fixtures
        from vbear.meeting_runner import MeetingRunner
        seen = set()

        def modules(fn):
            if inspect.ismodule(fn):
                return {fn.__name__}
            if inspect.ismethod(fn):
                fn = fn.__func__
            if not inspect.isfunction(fn) or id(fn) in seen:
                return set()
            seen.add(id(fn))
            result = {fn.__module__}
            for name in fn.__code__.co_names:
                value = fn.__globals__.get(name)
                if inspect.ismodule(value):
                    result |= modules(value)
            for cell in fn.__closure__ or ():
                result |= modules(cell.cell_contents)
            return result

        def deletable(kinds):
            return {name for kind in kinds for fn in kind for name in modules(fn)
                    if hasattr(sys.modules.get(name), 'delete')}

        from vbear.runtime import chat_store
        expected = {mod.__name__ for mod, _ in fixtures.CASES} | {chat_store.__name__}
        self.assertEqual(deletable(MeetingRunner().spend_kinds()), expected)
        # A new paid kind with a delete must extend the behavioural table too.
        import types
        from unittest import mock
        fake = types.ModuleType('fictional_paid_kind')
        exec('def ids(): return []\ndef load(rid): return {}\ndef limit(rec, turn): return 0\ndef delete(rid): pass', fake.__dict__)
        with mock.patch.dict(sys.modules, {fake.__name__: fake}):
            seen.clear()
            self.assertNotEqual(deletable(MeetingRunner().spend_kinds() + [(fake.ids, fake.load, fake.limit)]), expected)

    def test_16f_catches_a_delete_that_forgets_the_cost(self):
        from tests import test_p48_spend_keep as fixtures
        from unittest import mock
        case = fixtures.SpendKeepTests()
        case.setUp()
        self.addCleanup(case.doCleanups)
        mod, store = fixtures.CASES[0]
        # Replace only the retention step with the old broken implementation.
        with mock.patch('vbear.spend_keep.keep', return_value=None):
            with self.assertRaises(AssertionError):
                case.assert_kept(mod, store)

class Guard16FilesAreThere(unittest.TestCase):
    """16: the seven rules of v0.22.0 are kept where the description above says, and each file carries the number of its rule (16f is in this file)."""

    ROOT = Path(__file__).resolve().parents[1]

    def read(self, *parts):
        return self.ROOT.joinpath(*parts).read_text(encoding="utf-8")

    def test_16_the_description_names_all_seven_rules_and_their_files(self):
        text = self.read("tests", "test_autonomy_guard.py")
        for rule in "abcdefg":
            self.assertIn(f"     16{rule}  ", text, rule)
        for name in ("p48_setup.cjs", "p48_home.cjs", "p48_notify.cjs", "p48_chat.cjs", "test_waiting_bridge.sh", "test_p48_notify_static.py", "test_p48_spend_keep.py"):
            self.assertIn(name, text, name)

    def test_16_each_file_exists_and_carries_the_number_of_its_rule(self):
        for rule, parts in (("16a", ("tests", "frontend", "p48_setup.cjs")), ("16b", ("tests", "frontend", "p48_setup.cjs")),
                            ("16c", ("tests", "frontend", "p48_home.cjs")), ("16d", ("tests", "frontend", "p48_home.cjs")),
                            ("16e", ("tests", "frontend", "p48_notify.cjs")), ("16e", ("tests", "test_p48_notify_static.py")),
                            ("16g", ("tests", "frontend", "p48_chat.cjs")), ("16f", ("tests", "test_p48_spend_keep.py"))):
            self.assertIn(rule, self.read(*parts), "/".join(parts))
        self.assertTrue((self.ROOT / "macos" / "test_waiting_bridge.sh").is_file())
        self.assertRegex(self.read("tests", "test_autonomy_guard.py"), r"class DeletingNeverLowersTheDay")
        self.assertRegex(self.read("tests", "test_autonomy_guard.py"), r"def test_16f_")

    def test_16e_the_bridge_test_is_in_the_release_and_the_app_source_it_checks_is_there(self):
        self.assertTrue((self.ROOT / "macos" / "VBear" / "main.swift").is_file())
        script = self.read("macos", "test_waiting_bridge.sh")
        self.assertIn("main.swift", script)


# ---- 17: the chat-first home (v0.23.0, ADR 0015) ---------------------------------------------------------------------------------------------------
# These scan the JavaScript of web/app.js as text: the function bodies are cut out by their braces, the comments are dropped, and a rule fires when a body does something it
# must not. Each ``*_problems`` function is run on the real page (must be empty) and on a made-up bad source (must not be).

def js_without_comments(text: str) -> str:
    """The text without ``//`` comments (a ``//`` that follows whitespace or starts a line; a URL's ``://`` is kept)."""
    return "\n".join(re.sub(r"(^|\s)//.*$", r"\1", line) for line in text.splitlines())


def js_function_body(source: str, name: str) -> str | None:
    """The text between the braces of ``function name(...) {...}`` (or ``async function``), comments dropped, or None when there is no such function."""
    m = re.search(r"(?:^|\n)(?:async )?function " + re.escape(name) + r"\(", source)
    if not m:
        return None
    start = source.index("{", source.index(")", m.end()))
    depth = 0
    for i in range(start, len(source)):
        if source[i] == "{":
            depth += 1
        elif source[i] == "}":
            depth -= 1
            if depth == 0:
                return js_without_comments(source[start + 1:i])
    return None


# anything that makes a request, sends, stores or leaves the page
JS_REACHES_OUT = re.compile(r"\bapi\.|\bfetch\(|XMLHttpRequest|sendBeacon|openChatWith|\bsend\b|\bsubmit\b|\blocation\b|localStorage|sessionStorage|\.post\b|postMessage|\bpost\(|window\.open|\.click\(")
EXAMPLE_FILL_STATEMENTS = ("input.value = sentence", "homeAskGrow(input)", "input.focus()")
EXAMPLE_CLICK = re.compile(r'"data-home": "ask-example", on: \{ click: \(\) => ([^}]*?) \}')


def example_problems(source: str, label: str = "<app.js>") -> list[str]:
    """17a: the function that handles an example sentence only writes ``input.value``, grows the box and focuses it; the button calls nothing but that function."""
    found = []
    body = js_function_body(source, "homeExampleFill")
    if body is None:
        return [f"{label}: homeExampleFill is not there"]
    for hit in JS_REACHES_OUT.finditer(body):
        found.append(f"{label}: homeExampleFill reaches out: {hit.group(0)}")
    for statement in [x.strip() for x in body.replace("\n", " ").split(";") if x.strip()]:
        if statement not in EXAMPLE_FILL_STATEMENTS:
            found.append(f"{label}: homeExampleFill does more than fill and focus: {statement[:60]}")
    clicks = EXAMPLE_CLICK.findall(js_without_comments(source))
    if not clicks:
        found.append(f"{label}: no example button wired to homeExampleFill")
    for call in clicks:
        if call != "homeExampleFill(input, sentence)":
            found.append(f"{label}: an example button does more than call homeExampleFill: {call[:60]}")
    if js_without_comments(source).count('"ask-example"') != len(clicks):
        found.append(f"{label}: an example button is not wired the way the rule reads")
    return found


NAV_RECENT_START = "// ---------- the side bar's 最近"
NAV_RECENT_END = "// ---------- end of the side bar's 最近"
NAV_RECENT_FORBIDDEN = re.compile(r"\bapi\b|/api/|\bfetch\b|XMLHttpRequest|sendBeacon|setInterval|setTimeout|requestAnimationFrame|waitingModel|WebSocket|EventSource")


def nav_recent_problems(source: str, label: str = "<app.js>") -> list[str]:
    """17b: the part of the page between the two markers (the side bar's 最近) never calls ``api``, never names a path under /api/ or the chat list, and sets no timer."""
    if NAV_RECENT_START not in source or NAV_RECENT_END not in source or source.index(NAV_RECENT_END) < source.index(NAV_RECENT_START):
        return [f"{label}: the markers of the side bar's 最近 are not there"]
    part = js_without_comments(source[source.index(NAV_RECENT_START):source.index(NAV_RECENT_END)])
    found = [f"{label}: the side bar's 最近 reaches out or sets a timer: {hit.group(0)}" for hit in NAV_RECENT_FORBIDDEN.finditer(part)]
    if "navRecentRows" not in part or "drawNavRecent" not in part:
        found.append(f"{label}: navRecentRows / drawNavRecent are not between the markers")
    return found


KEYDOWN_BODY = re.compile(r'^if \(e\.key === "Enter" && \(e\.metaKey \|\| e\.ctrlKey\)( && !e\.isComposing)?\) \{ e\.preventDefault\(\); send\(\); \}$')
HOME_SEND_USES = ("homeAskKeydown(e, send)", "async function send()", "click: () => send()")


def home_keydown_problems(source: str, label: str = "<app.js>") -> list[str]:
    """17c: the keydown handler of the home box calls ``send`` only for Enter together with Cmd or Ctrl; the box has no other key, form or submit path to ``send``."""
    found = []
    key = js_function_body(source, "homeAskKeydown")
    if key is None:
        return [f"{label}: homeAskKeydown is not there"]
    if not KEYDOWN_BODY.match(" ".join(key.split())):
        found.append(f"{label}: homeAskKeydown is not 'Enter with Cmd or Ctrl sends, nothing else': {' '.join(key.split())[:90]}")
    ask = js_function_body(source, "homeAsk")
    if ask is None:
        return found + [f"{label}: homeAsk is not there"]
    rest = ask
    for use in HOME_SEND_USES:
        rest = rest.replace(use, "")
    for hit in re.finditer(r"(?<![\w-])send(?![\w-])", rest):      # (the word ``send`` as a name, not the ``send`` inside ``home-send`` or ``ask-send``)
        found.append(f"{label}: homeAsk reaches send another way (near: {rest[max(0, hit.start() - 30):hit.end() + 10].strip()!r})")
    for hit in re.finditer(r"keypress|keyup|onkeydown|onkeypress|onkeyup|[\"\']submit[\"\']|addEventListener|<form|el\(\"form\"", ask):
        found.append(f"{label}: homeAsk has another input path: {hit.group(0)}")
    if len(re.findall(r"keydown:", ask)) != 1 or "keydown: (e) => homeAskKeydown(e, send)" not in ask:
        found.append(f"{label}: the box does not have exactly one keydown, the one that calls homeAskKeydown")
    return found


class ChatFirstHomeRules(unittest.TestCase):
    """17a, 17b, 17c"""

    SOURCE = (Path(__file__).resolve().parents[1] / "web" / "app.js").read_text(encoding="utf-8")

    GOOD_FILL = """
function homeAskGrow(input) { input.style.height = "1px"; }
function homeExampleFill(input, sentence) {
  input.value = sentence;   // only the words
  homeAskGrow(input);
  input.focus();
}
function x() { return el("button", { type: "button", "data-home": "ask-example", on: { click: () => homeExampleFill(input, sentence) } }, sentence); }
"""

    def test_17a_the_page_only_fills_and_focuses(self):
        self.assertEqual(example_problems(self.SOURCE), [])

    def test_17a_the_scan_fires_on_a_handler_that_sends_asks_or_stores(self):
        self.assertEqual(example_problems(self.GOOD_FILL), [])
        for bad in ("  openChatWith(ceo.id, { text: sentence });", "  api.post(\"/api/chats\", { text: sentence });", "  send();", "  fetch(\"/x\");",
                    "  location.hash = \"#/chat\";", "  localStorage.setItem(\"k\", sentence);", "  button.click();", "  navigator.sendBeacon(\"/x\");", "  console.log(sentence);"):
            worse = self.GOOD_FILL.replace("  input.focus();", "  input.focus();\n" + bad)
            self.assertNotEqual(example_problems(worse), [], bad)

    def test_17a_the_scan_fires_on_a_button_that_does_more_than_call_the_function(self):
        for call in ("send()", "homeExampleFill(input, sentence); send()", "(homeExampleFill(input, sentence), openChatWith(ceo.id, { text: sentence }))"):
            worse = self.GOOD_FILL.replace("click: () => homeExampleFill(input, sentence)", "click: () => " + call)
            self.assertNotEqual(example_problems(worse), [], call)
        self.assertNotEqual(example_problems("function homeExampleFill(input, sentence) { input.value = sentence; }\n"), [], "no button at all")
        self.assertNotEqual(example_problems(self.GOOD_FILL + 'x = { "data-home": "ask-example", onclick: send };'), [], "a second example button wired another way")
        self.assertNotEqual(example_problems("function other() {}"), [], "no function")

    def test_17b_the_side_bar_recent_asks_for_nothing_and_has_no_timer(self):
        self.assertEqual(nav_recent_problems(self.SOURCE), [])

    def test_17b_the_scan_fires_on_a_read_or_a_timer(self):
        good = NAV_RECENT_START + "\nfunction navRecentRows(x) { return []; }\nfunction drawNavRecent() { setKids(a, []); }\n" + NAV_RECENT_END + "\n"
        self.assertEqual(nav_recent_problems(good), [])
        for bad in ("api.get(\"/api/chats\")", "await api.get(`/api/chats`)", "fetch(\"/api/chats\")", "setInterval(drawNavRecent, 1000)", "setTimeout(drawNavRecent, 10)",
                    "requestAnimationFrame(drawNavRecent)", "waitingModel.refresh()", "new EventSource(\"/x\")"):
            worse = good.replace("setKids(a, []);", "setKids(a, []); " + bad + ";")
            self.assertNotEqual(nav_recent_problems(worse), [], bad)
        self.assertEqual(nav_recent_problems(good.replace("setKids(a, []);", "setKids(a, []); // api.get(\"/api/chats\") is not called here")), [], "a comment is not a call")
        self.assertNotEqual(nav_recent_problems("function navRecentRows() {}"), [], "no markers")

    GOOD_ASK = """
function homeAskKeydown(e, send) {
  if (e.key === "Enter" && (e.metaKey || e.ctrlKey) && !e.isComposing) { e.preventDefault(); send(); }
}
function homeAsk(state) {
  const input = el("textarea", { on: { keydown: (e) => homeAskKeydown(e, send), input: () => homeAskGrow(input) } });
  const button = el("button", { on: { click: () => send() } }, "送出");
  async function send() { await openChatWith(1, {}); }
  return block(el("div", null, input, button));
}
"""

    def test_17c_the_box_sends_only_on_cmd_or_ctrl_enter(self):
        self.assertEqual(home_keydown_problems(self.SOURCE), [])

    def test_17c_the_scan_fires_on_a_plain_enter_or_another_path_to_send(self):
        self.assertEqual(home_keydown_problems(self.GOOD_ASK), [])
        worse_keys = ("if (e.key === \"Enter\") { e.preventDefault(); send(); }", "if (e.key === \"Enter\" && !e.shiftKey) { e.preventDefault(); send(); }",
                      "if (e.key === \"Enter\" && (e.metaKey || e.ctrlKey)) { send(); } else if (e.key === \"Enter\") { send(); }",
                      "if (e.key === \"Enter\" || (e.metaKey || e.ctrlKey)) { e.preventDefault(); send(); }", "send();")
        for worse in worse_keys:
            source = self.GOOD_ASK.replace("if (e.key === \"Enter\" && (e.metaKey || e.ctrlKey) && !e.isComposing) { e.preventDefault(); send(); }", worse)
            self.assertNotEqual(home_keydown_problems(source), [], worse)
        for extra in ("input.addEventListener(\"keypress\", (e) => { if (e.key === \"Enter\") send(); });", "const f = el(\"form\", { on: { submit: send } });",
                      "input.onkeyup = (e) => send();", "setTimeout(send, 10);"):
            source = self.GOOD_ASK.replace("  return block(", "  " + extra + "\n  return block(")
            self.assertNotEqual(home_keydown_problems(source), [], extra)
        two = self.GOOD_ASK.replace("input: () => homeAskGrow(input) }", "input: () => homeAskGrow(input), keydown: (e) => send() }")
        self.assertNotEqual(home_keydown_problems(two), [], "a second keydown")


class Guard17FilesAreThere(unittest.TestCase):
    """17: the three rules of v0.23.0 are kept where the description above says, and each file carries the number of its rule."""

    ROOT = Path(__file__).resolve().parents[1]

    def read(self, *parts):
        return self.ROOT.joinpath(*parts).read_text(encoding="utf-8")

    def test_17_the_description_names_all_three_rules_and_their_files(self):
        text = self.read("tests", "test_autonomy_guard.py")
        for rule in "abc":
            self.assertIn(f"     17{rule}  ", text, rule)
        for name in ("p50_home.cjs", "p50_nav.cjs", "ChatFirstHomeRules"):
            self.assertIn(name, text, name)

    def test_17_each_file_exists_and_carries_the_number_of_its_rule(self):
        for rule, parts in (("17a", ("tests", "frontend", "p50_home.cjs")), ("17c", ("tests", "frontend", "p50_home.cjs")), ("17b", ("tests", "frontend", "p50_nav.cjs"))):
            self.assertIn(rule, self.read(*parts), "/".join(parts))
        self.assertRegex(self.read("tests", "test_autonomy_guard.py"), r"class ChatFirstHomeRules")
        for rule in ("test_17a_", "test_17b_", "test_17c_"):
            self.assertIn(rule, self.read("tests", "test_autonomy_guard.py"), rule)


# ---- 18: the chat reads like text (v0.24.0, ADR 0016) ---------------------------------------------------------------------------------------------------
# Same method as 17: the JavaScript of web/app.js as text, function bodies cut out by their braces, comments dropped; each ``*_problems`` function is run on the real page (must be empty)
# and on a made-up bad source (must not be).

QUIET_DATA_CHAT = ("process", "tool", "result", "auto", "cost", "process-end")                     # the data-chat of the lines a fold may hold
QUIET_RECORDS = {"tool_call", "tool_result", "auto_allowed", "process_started", "turn_ended", "process_ended"}
NEVER_FOLDED = ("card", "card_decision", "denied", "error", "anomaly", "user_message", "reply")


def chat_line_data_chats(source: str) -> dict[str, str]:
    """{record kind: data-chat of its line} read from the cases of ``chatLine``."""
    body = js_function_body(source, "chatLine") or ""
    parts = re.split(r'\n\s*case "(\w+)":', body)
    out = {}
    for kind, chunk in zip(parts[1::2], parts[2::2]):
        m = re.search(r'"data-chat": "([\w-]+)"', chunk)
        if m:
            out[kind] = m.group(1)
    return out


def quiet_group_problems(source: str, label: str = "<app.js>") -> list[str]:
    """18a: what may be put in a fold is a closed list; ``chatIsQuiet`` says yes to those record kinds only (the same ones whose line has one of the six quiet data-chat values),
    never to the kinds that must stay in the open, and ``chatQuietLog.add`` puts every other line straight into the list and every line somewhere (nothing is dropped)."""
    found = []
    kinds_const = re.search(r"const CHAT_QUIET_KINDS = \[([^\]]*)\]", source)
    if not kinds_const or tuple(re.findall(r'"([\w-]+)"', kinds_const.group(1))) != QUIET_DATA_CHAT:
        found.append(f"{label}: CHAT_QUIET_KINDS is not exactly {QUIET_DATA_CHAT}")
    quiet = js_function_body(source, "chatIsQuiet")
    if quiet is None:
        return found + [f"{label}: chatIsQuiet is not there"]
    said = set(re.findall(r'case "(\w+)":', quiet))
    if said != QUIET_RECORDS:
        found.append(f"{label}: chatIsQuiet names {sorted(said)}, not {sorted(QUIET_RECORDS)}")
    for kind in NEVER_FOLDED:
        if re.search(r'["\']' + kind + r'["\']', quiet):
            found.append(f"{label}: chatIsQuiet names {kind}, which must never be folded")
    if not re.search(r"default:\s*return false;", quiet):
        found.append(f"{label}: chatIsQuiet does not say no to every other kind")
    if "rec.kind" not in quiet or not re.search(r'if \(!rec \|\| typeof rec !== "object"\) return false;', quiet):
        found.append(f"{label}: chatIsQuiet does not say no to a record it cannot read")
    lines = chat_line_data_chats(source)
    if not lines:
        found.append(f"{label}: could not read the lines of chatLine")
    quiet_lines = {kind for kind, dc in lines.items() if dc in QUIET_DATA_CHAT}
    if quiet_lines != QUIET_RECORDS:
        found.append(f"{label}: the records whose line is a quiet one are {sorted(quiet_lines)}, not {sorted(QUIET_RECORDS)}")
    for kind in NEVER_FOLDED:
        if lines.get(kind) in QUIET_DATA_CHAT:
            found.append(f"{label}: the line of {kind} has a quiet data-chat ({lines[kind]})")
    log = js_function_body(source, "chatQuietLog")
    if log is None:
        return found + [f"{label}: chatQuietLog is not there"]
    flat_log = " ".join(log.split())
    if "if (!chatIsQuiet(rec)) { group = null; log.append(line); return; }" not in flat_log:
        found.append(f"{label}: chatQuietLog does not put a line that may not be folded straight into the list")
    if len(re.findall(r"group\.list\.append\(line\)", flat_log)) != 1:
        found.append(f"{label}: chatQuietLog does not put every folded line into its fold exactly once")
    for hit in re.finditer(r"\.remove\(|\.replaceChildren\(|setKids\(group\.list|\.splice\(|\.shift\(|\.pop\(", flat_log):
        found.append(f"{label}: chatQuietLog takes a line out: {hit.group(0)}")
    return found


WHO_REACHES_OUT = re.compile(r"\bapi\b|\bfetch\b|XMLHttpRequest|sendBeacon|openChatWith|(?<![\w-])send(?![\w-])|\bsubmit\b|\.post\b|\.put\b|\.del\b|\bPOST\b|\bPUT\b|\bDELETE\b|/api/|postMessage|window\.open|\.click\(|setInterval|setTimeout|localStorage|sessionStorage")
WHO_PICK_WIRING = "onPick: (c) => chatWhoGo(c.id, input.value, info), onLater: (c) => chatWhoLater(c.id, input.value) });"


def who_pick_problems(source: str, label: str = "<app.js>") -> list[str]:
    """18b: the handlers of a pick on the chat page and on the home page, and the pick list itself, call no send or request function and do not read ``/api/chats``; on the chat page
    the pick goes to a page (``location``) and the unsent words wait in ``ceoDrafts``; the picker is wired to exactly those two functions."""
    found = []
    for name in ("chatWhoGo", "chatWhoLater", "whoPicker"):
        body = js_function_body(source, name)
        if body is None:
            found.append(f"{label}: {name} is not there")
            continue
        for hit in WHO_REACHES_OUT.finditer(body):
            found.append(f"{label}: {name} reaches out: {hit.group(0)}")
    ask = js_function_body(source, "homeAsk") or ""
    at = ask.find("onPick: (c) => {")
    end = ask.find("onLater:", at)
    if at < 0 or end < 0:
        found.append(f"{label}: the home page's pick handler is not there")
    else:
        for hit in WHO_REACHES_OUT.finditer(ask[at:end]):
            found.append(f"{label}: the home page's pick handler reaches out: {hit.group(0)}")
    detail = js_function_body(source, "viewChatDetail") or ""
    flat_detail = " ".join(detail.split())
    if WHO_PICK_WIRING not in flat_detail:
        found.append(f"{label}: the chat page's picker is not wired to chatWhoGo and chatWhoLater only")
    if flat_detail.count("whoPicker(") != 1:
        found.append(f"{label}: the chat page does not have exactly one picker")
    return found


CHAT_KEYDOWN = re.compile(r'on: \{ keydown: \(e\) => \{ if \(e\.key === "Enter" && \(e\.metaKey \|\| e\.ctrlKey\)( && !e\.isComposing)?\) \{ e\.preventDefault\(\); send\(\); \} \}, input: \(\) => homeAskGrow\(input\) \}')
CHAT_SEND_USES = ("async function send()", "click: () => send() } }, \"送出\"", "e.preventDefault(); send(); }")


def chat_keydown_problems(source: str, label: str = "<app.js>") -> list[str]:
    """18c: in the chat page, the box's one keydown calls ``send`` only for Enter together with Cmd or Ctrl; no other key, form or submit path reaches ``send``."""
    detail = js_function_body(source, "viewChatDetail")
    if detail is None:
        return [f"{label}: viewChatDetail is not there"]
    flat = " ".join(detail.split())
    found = []
    box = re.search(r'const input = el\("textarea", \{.*?\}\);', flat)
    if not box:
        return [f"{label}: the chat page's box is not there"]
    if not CHAT_KEYDOWN.search(box.group(0)):
        found.append(f"{label}: the chat box's keydown is not 'Enter with Cmd or Ctrl sends, nothing else': {box.group(0)[:160]}")
    if len(re.findall(r"keydown:", box.group(0))) != 1:
        found.append(f"{label}: the chat box does not have exactly one keydown")
    rest = flat
    for use in CHAT_SEND_USES:
        rest = rest.replace(use, "")
    for hit in re.finditer(r"(?<![\w.\"'-])send(?![\w\"'-])", rest):      # (the word ``send`` as a name, called or handed on; not a string such as "send")
        found.append(f"{label}: the chat page reaches send another way (near: {rest[max(0, hit.start() - 30):hit.end() + 10].strip()!r})")
    for hit in re.finditer(r"keypress|keyup|onkeydown|onkeypress|onkeyup|[\"\']submit[\"\']|<form|el\(\"form\"", flat):
        found.append(f"{label}: the chat page has another input path: {hit.group(0)}")
    return found


MONEY_IN_SUMMARY = re.compile(r"chatMoney|chatTurnCost|usd|US\$|budget|total|spent|\.cost|\.reported|\.estimate|toFixed|toLocale")


def quiet_summary_problems(source: str, label: str = "<app.js>") -> list[str]:
    """18d: the line over a fold is made by ``chatQuietSummary`` from counts only, and it is the only thing that writes into the line; no amount, no money word, no record field."""
    found = []
    body = js_function_body(source, "chatQuietSummary")
    if body is None:
        return [f"{label}: chatQuietSummary is not there"]
    for hit in MONEY_IN_SUMMARY.finditer(body):
        found.append(f"{label}: chatQuietSummary mentions money or a record field: {hit.group(0)}")
    log = js_function_body(source, "chatQuietLog") or ""
    writes = re.findall(r"setKids\(group\.summary, ([^;]*)\);", log)
    if writes != ["chatQuietSummary(group.counts)"]:
        found.append(f"{label}: something other than chatQuietSummary(group.counts) writes into the line over a fold: {writes}")
    for hit in MONEY_IN_SUMMARY.finditer(log):
        found.append(f"{label}: chatQuietLog mentions money or a record field: {hit.group(0)}")
    if re.search(r"\bsummary\b[^;]*(textContent|innerText)", log):
        found.append(f"{label}: the line over a fold is written another way")
    return found


class ChatReadsLikeTextRules(unittest.TestCase):
    """18a, 18b, 18c, 18d"""

    SOURCE = (Path(__file__).resolve().parents[1] / "web" / "app.js").read_text(encoding="utf-8")

    def test_the_scans_find_their_functions_in_the_real_page(self):
        for name in ("chatIsQuiet", "chatQuietSummary", "chatQuietLog", "chatWhoGo", "chatWhoLater", "whoPicker", "chatLine", "viewChatDetail", "homeAsk"):
            self.assertIsNotNone(js_function_body(self.SOURCE, name), name)
        self.assertEqual(set(chat_line_data_chats(self.SOURCE)), {"user_message", "reply", "tool_call", "tool_result", "auto_allowed", "denied", "card", "card_decision", "turn_ended",
                                                                   "process_started", "process_ended", "anomaly", "error"})

    # ---- 18a ----

    GOOD_QUIET = """
const CHAT_QUIET_KINDS = ["process", "tool", "result", "auto", "cost", "process-end"];
function chatIsQuiet(rec) {
  if (!rec || typeof rec !== "object") return false;
  switch (rec.kind) {
    case "tool_call": case "tool_result": case "auto_allowed": case "process_started": return true;
    case "turn_ended": return rec.reason === "result";
    case "process_ended": return true;
    default: return false;
  }
}
function chatQuietLog(log) {
  let group = null;
  return { add(line, rec) {
    if (!chatIsQuiet(rec)) { group = null; log.append(line); return; }
    if (!group) group = start();
    group.list.append(line);
  } };
}
function chatLine(rec) {
  switch (rec.kind) {
    case "user_message": {
      return el("li", { "data-chat": "user" });
    }
    case "reply":
      return el("li", { "data-chat": "reply" });
    case "tool_call":
      return el("li", { "data-chat": "tool" });
    case "tool_result":
      return el("li", { "data-chat": "result" });
    case "auto_allowed":
      return el("li", { "data-chat": "auto" });
    case "denied":
      return el("li", { "data-chat": "denied" });
    case "card":
      return el("li", { "data-chat": "card" });
    case "card_decision":
      return el("li", { "data-chat": "decision" });
    case "turn_ended": {
      return el("li", { "data-chat": "cost" });
    }
    case "process_started":
      return el("li", { "data-chat": "process" });
    case "process_ended":
      return el("li", { "data-chat": "process-end" });
    case "anomaly":
      return el("li", { "data-chat": "anomaly" });
    case "error":
      return el("li", { "data-chat": "error" });
    default:
      return null;
  }
}
"""

    def test_18a_the_page_folds_only_the_quiet_kinds(self):
        self.assertEqual(quiet_group_problems(self.SOURCE), [])

    def test_18a_the_scan_fires_on_a_fold_that_could_hold_a_card_an_error_or_the_words_said(self):
        self.assertEqual(quiet_group_problems(self.GOOD_QUIET), [])
        for kind in ("card", "card_decision", "denied", "error", "anomaly", "user_message", "reply"):
            worse = self.GOOD_QUIET.replace('case "process_ended": return true;', f'case "process_ended": return true;\n    case "{kind}": return true;')
            self.assertNotEqual(quiet_group_problems(worse), [], kind)
        self.assertNotEqual(quiet_group_problems(self.GOOD_QUIET.replace("default: return false;", "default: return true;")), [], "yes to every other kind")
        self.assertNotEqual(quiet_group_problems(self.GOOD_QUIET.replace('if (!rec || typeof rec !== "object") return false;', "")), [], "a record it cannot read")
        self.assertNotEqual(quiet_group_problems(self.GOOD_QUIET.replace('"data-chat": "error"', '"data-chat": "tool"')), [], "the line of an error has a quiet data-chat")
        self.assertNotEqual(quiet_group_problems(self.GOOD_QUIET.replace('"data-chat": "decision"', '"data-chat": "auto"')), [], "the line of a decision has a quiet data-chat")
        self.assertNotEqual(quiet_group_problems(self.GOOD_QUIET.replace('const CHAT_QUIET_KINDS = ["process", "tool", "result", "auto", "cost", "process-end"];', 'const CHAT_QUIET_KINDS = ["process", "tool", "result", "auto", "cost", "process-end", "card"];')), [], "a seventh kind")
        self.assertNotEqual(quiet_group_problems(self.GOOD_QUIET.replace('case "tool_call": case "tool_result":', 'case "tool_call":')), [], "a kind left out of the fold list but still a quiet line")

    def test_18a_the_scan_fires_on_a_log_that_drops_a_line(self):
        self.assertNotEqual(quiet_group_problems(self.GOOD_QUIET.replace("if (!chatIsQuiet(rec)) { group = null; log.append(line); return; }", "if (!chatIsQuiet(rec)) { group = null; return; }")), [], "a line is dropped")
        self.assertNotEqual(quiet_group_problems(self.GOOD_QUIET.replace("group.list.append(line);", "")), [], "a folded line is dropped")
        self.assertNotEqual(quiet_group_problems(self.GOOD_QUIET.replace("group.list.append(line);", "group.list.append(line); group.list.children[0].remove();")), [], "a line is taken out")
        self.assertNotEqual(quiet_group_problems(self.GOOD_QUIET.replace("group.list.append(line);", "setKids(group.list, line);")), [], "the fold is redrawn with one line")

    # ---- 18b ----

    GOOD_WHO = """
function whoPicker(opts) {
  const x = el("button", { on: { click: () => choose(c) } });
  function choose(c) { close(false); if (typeof opts.onPick === "function") opts.onPick(c); }
  return { node: x };
}
function chatWhoGo(profileId, words, chatsRes) {
  const chat = homeChatsOf(chatsRes, null, profileId)[0] || null;
  if (chat) { ceoDrafts.set(chat.id, words); location.hash = `#/chat/${chat.id}`; return; }
  location.hash = `#/chat?profile=${profileId}`;
}
function chatWhoLater(profileId, words) { ceoDrafts.set(profileId, words); }
function homeAsk(state) {
  const picker = whoPicker({ cards: state.chats && state.chats.cards, data: state.chats, current: ceo.id, dir: "down",
    onPick: (c) => {
      target = { id: c.id };
      picker.setCurrent(c.id);
      input.focus();
    },
    onLater: (c) => chatWhoLater(c.id, input.value) });
}
async function viewChatDetail(token, id) {
  const picker = whoPicker({ cards: info && info.cards, data: info, current: ownerId, currentName: all.card && all.card.name, dir: "up",
      onPick: (c) => chatWhoGo(c.id, input.value, info), onLater: (c) => chatWhoLater(c.id, input.value) });
}
"""

    def test_18b_a_pick_only_goes_to_a_page_or_changes_whom_the_box_is_for(self):
        self.assertEqual(who_pick_problems(self.SOURCE), [])

    def test_18b_the_scan_fires_on_a_pick_that_sends_writes_or_reads_the_chat_list(self):
        self.assertEqual(who_pick_problems(self.GOOD_WHO), [])
        for bad in ("api.post(\"/api/chats\", { profile_id: c.id });", "await api.get(\"/api/chats\");", "openChatWith(c.id, { text: input.value });", "send();", "fetch(\"/x\");",
                    "localStorage.setItem(\"k\", c.id);", "api.del(\"/api/chats/x\");", "setTimeout(() => {}, 10);", "button.click();"):
            for where in ("function chatWhoGo(profileId, words, chatsRes) {", "function chatWhoLater(profileId, words) {", "function whoPicker(opts) {", "    onPick: (c) => {"):
                worse = self.GOOD_WHO.replace(where, where + "\n  " + bad)
                self.assertNotEqual(who_pick_problems(worse), [], f"{bad} in {where}")
        for wired in ("onPick: (c) => { send(); chatWhoGo(c.id, input.value, info) }, onLater: (c) => chatWhoLater(c.id, input.value) });",
                      "onPick: (c) => chatWhoGo(c.id, input.value, info), onLater: (c) => openChatWith(c.id) });"):
            worse = self.GOOD_WHO.replace(WHO_PICK_WIRING, wired)
            self.assertNotEqual(who_pick_problems(worse), [], wired)
        self.assertNotEqual(who_pick_problems(self.GOOD_WHO.replace("function chatWhoGo(", "function chatWhoElsewhere(")), [], "no handler")
        two = self.GOOD_WHO.replace("      onPick: (c) => chatWhoGo(c.id, input.value, info), onLater:", "      onPick: (c) => chatWhoGo(c.id, input.value, info), onLater:").replace(
            "async function viewChatDetail(token, id) {", "async function viewChatDetail(token, id) {\n  const other = whoPicker({ onPick: (c) => doIt(c) });")
        self.assertNotEqual(who_pick_problems(two), [], "a second picker on the chat page, with a handler of its own")

    # ---- 18c ----

    GOOD_CHAT_BOX = """
async function viewChatDetail(token, id) {
  const input = el("textarea", { rows: "2", "data-chat": "input", "aria-label": "要對員工說的話", maxlength: "20000", placeholder: "要對員工說什麼？（Cmd/Ctrl + Enter 送出）",
    on: { keydown: (e) => { if (e.key === "Enter" && (e.metaKey || e.ctrlKey) && !e.isComposing) { e.preventDefault(); send(); } }, input: () => homeAskGrow(input) } });
  const sendBtn = el("button", { type: "button", class: "btn primary home-send", "data-chat": "send", on: { click: () => send() } }, "送出");
  async function send() { await api.post("/x", {}); }
  return 1;
}
"""

    def test_18c_the_chat_box_sends_only_on_cmd_or_ctrl_enter(self):
        self.assertEqual(chat_keydown_problems(self.SOURCE), [])

    def test_18c_the_scan_fires_on_a_plain_enter_or_another_path_to_send(self):
        self.assertEqual(chat_keydown_problems(self.GOOD_CHAT_BOX), [])
        for worse in ('if (e.key === "Enter") { e.preventDefault(); send(); }', 'if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); send(); }',
                      'if (e.key === "Enter" || (e.metaKey || e.ctrlKey)) { e.preventDefault(); send(); }', "send();"):
            source = self.GOOD_CHAT_BOX.replace('if (e.key === "Enter" && (e.metaKey || e.ctrlKey) && !e.isComposing) { e.preventDefault(); send(); }', worse)
            self.assertNotEqual(chat_keydown_problems(source), [], worse)
        for extra in ('input.addEventListener("keypress", (e) => { if (e.key === "Enter") send(); });', 'const f = el("form", { on: { submit: send } });', "input.onkeyup = (e) => send();",
                      "setTimeout(send, 10);", "picker.onpick = () => send();", "who.button.click(); send();"):
            source = self.GOOD_CHAT_BOX.replace("  return 1;", "  " + extra + "\n  return 1;")
            self.assertNotEqual(chat_keydown_problems(source), [], extra)
        two = self.GOOD_CHAT_BOX.replace("input: () => homeAskGrow(input) }", "input: () => homeAskGrow(input), keydown: (e) => send() }")
        self.assertNotEqual(chat_keydown_problems(two), [], "a second keydown")

    # ---- 18d ----

    GOOD_SUMMARY = """
function chatQuietSummary(counts) {
  const c = counts && typeof counts === "object" ? counts : {};
  const n = (k) => (Number.isInteger(c[k]) && c[k] > 0 ? c[k] : 0);
  const said = [];
  if (n("tool")) said.push(`用了 ${n("tool")} 次工具`);
  if (n("cost")) said.push(`${n("cost")} 回合結算`);
  return [...said, "細節"].join("・");
}
function chatQuietLog(log) {
  return { add(line, rec) {
    group.counts[kind] = (group.counts[kind] || 0) + 1;
    setKids(group.summary, chatQuietSummary(group.counts));
  } };
}
"""

    def test_18d_the_line_over_a_fold_has_no_money(self):
        self.assertEqual(quiet_summary_problems(self.SOURCE), [])

    def test_18d_the_scan_fires_on_an_amount_or_another_writer(self):
        self.assertEqual(quiet_summary_problems(self.GOOD_SUMMARY), [])
        for bad in ("said.push(`花了 ${chatMoney(c.usd)}`);", "said.push(`US$${c.total}`);", "said.push(chatTurnCost(rec));", "said.push(String(c.cost_usd.toFixed(2)));", "said.push(`${c.spent}`);"):
            worse = self.GOOD_SUMMARY.replace('  return [...said, "細節"]', "  " + bad + '\n  return [...said, "細節"]')
            self.assertNotEqual(quiet_summary_problems(worse), [], bad)
        self.assertNotEqual(quiet_summary_problems(self.GOOD_SUMMARY.replace("setKids(group.summary, chatQuietSummary(group.counts));", "setKids(group.summary, chatQuietSummary(group.counts) + chatMoney(rec.cost_usd));")), [], "money added where it is written")
        self.assertNotEqual(quiet_summary_problems(self.GOOD_SUMMARY.replace("setKids(group.summary, chatQuietSummary(group.counts));", "setKids(group.summary, chatQuietSummary(group.counts)); setKids(group.summary, `${rec.cost_usd}`);")), [], "a second writer")
        self.assertNotEqual(quiet_summary_problems("function other() {}"), [], "no function")


class Guard18FilesAreThere(unittest.TestCase):
    """18: the four rules of v0.24.0 are kept where the description above says, and each file carries the number of its rule."""

    ROOT = Path(__file__).resolve().parents[1]

    def read(self, *parts):
        return self.ROOT.joinpath(*parts).read_text(encoding="utf-8")

    def test_18_the_description_names_all_four_rules_and_their_files(self):
        text = self.read("tests", "test_autonomy_guard.py")
        for rule in "abcd":
            self.assertIn(f"     18{rule}  ", text, rule)
        for name in ("p51_chat.cjs", "p51_who.cjs", "ChatReadsLikeTextRules"):
            self.assertIn(name, text, name)

    def test_18_each_file_exists_and_carries_the_number_of_its_rule(self):
        for rule, parts in (("18a", ("tests", "frontend", "p51_chat.cjs")), ("18d", ("tests", "frontend", "p51_chat.cjs")), ("18b", ("tests", "frontend", "p51_who.cjs"))):
            self.assertIn(rule, self.read(*parts), "/".join(parts))
        self.assertIn("p51_who.cjs", self.read("tests", "test_autonomy_guard.py"))
        self.assertRegex(self.read("tests", "test_autonomy_guard.py"), r"class ChatReadsLikeTextRules")
        for rule in ("test_18a_", "test_18b_", "test_18c_", "test_18d_"):
            self.assertIn(rule, self.read("tests", "test_autonomy_guard.py"), rule)


if __name__ == "__main__":
    unittest.main()
