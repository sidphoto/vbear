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

The scan reads the syntax tree (imports and calls) of every ``vbear/chief*.py``, ``vbear/dispatch*.py``, ``vbear/group*.py``,
``vbear/memory*.py``, ``vbear/runtime/memory*.py``, ``vbear/shared*.py``, ``vbear/runtime/shared*.py``, ``vbear/skillbook*.py`` and ``vbear/autonomy.py`` that exists, so the later modules of the chief of
staff, of dispatch, of groups and of memory (the suggestions, P42-4) are held to it the day they are added. The rules are below, as a table; the tests at the bottom run the scan on small made-up sources to show each rule fires,
so the scan cannot go quiet.
"""

from __future__ import annotations

import ast
import re
import unittest
from pathlib import Path

PACKAGE = Path(__file__).resolve().parents[1] / "vbear"
PATTERNS = ("chief*.py", "dispatch*.py", "group*.py", "autonomy.py", "memory*.py", "runtime/memory*.py", "shared*.py", "runtime/shared*.py",
            "skillbook*.py", "routine*.py")

PATTERNS = PATTERNS + ("auto_continue.py",)    # (P44-4) item 5's module is held to every rule below

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
BANNED_STRINGS = ("/api/native/", "/api/settings/autonomy", "/api/config", "/api/setup/daily-limit", "acceptForSession", "/answer")
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


if __name__ == "__main__":
    unittest.main()
