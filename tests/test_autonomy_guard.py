"""P40-2, P41-1, P42-2: the things the chief of staff, the dispatch code, the group code and the memory code never do, kept by the
structure of the code (ADR 0003, 0006, 0007, 0008).

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

The scan reads the syntax tree (imports and calls) of every ``vbear/chief*.py``, ``vbear/dispatch*.py``, ``vbear/group*.py``,
``vbear/memory*.py``, ``vbear/runtime/memory*.py`` and ``vbear/autonomy.py`` that exists, so the later modules of the chief of
staff, of dispatch, of groups and of memory (the suggestions, P42-4) are held to it the day they are added. The rules are below, as a table; the tests at the bottom run the scan on small made-up sources to show each rule fires,
so the scan cannot go quiet.
"""

from __future__ import annotations

import ast
import re
import unittest
from pathlib import Path

PACKAGE = Path(__file__).resolve().parents[1] / "vbear"
PATTERNS = ("chief*.py", "dispatch*.py", "group*.py", "autonomy.py", "memory*.py", "runtime/memory*.py")

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


def memory_writer_uses(source: str, label: str = "<source>") -> list[str]:
    """Every place this source reaches a writer of vbear/memory.py: ``<the memory module>.add(...)`` however the module is named
    (``from . import memory as m``, ``import vbear.memory``, ``vbear.memory.add``), ``from .memory import add``, a ``getattr`` of
    one, and a star import of the module."""
    tree = ast.parse(source, filename=label)
    found: list[str] = []
    aliases: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            mod = node.module or ""
            if mod in ("", "vbear") or (node.level and mod == ""):
                aliases |= {a.asname or a.name for a in node.names if a.name == MEMORY_MODULE}
            if mod.split(".")[-1] == MEMORY_MODULE:
                for a in node.names:
                    if a.name == "*" or a.name in MEMORY_WRITERS:
                        found.append(f"{label}:{node.lineno}: imports memory.{a.name}")
        elif isinstance(node, ast.Import):
            aliases |= {a.asname for a in node.names if a.name in ("vbear.memory",) and a.asname}
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute) and node.attr in MEMORY_WRITERS:
            base = node.value
            chain = (isinstance(base, ast.Attribute) and base.attr == MEMORY_MODULE and isinstance(base.value, ast.Name)
                     and base.value.id == "vbear")
            if (isinstance(base, ast.Name) and base.id in aliases) or chain:
                found.append(f"{label}:{node.lineno}: reaches memory.{node.attr}")
        elif (isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "getattr"
              and len(node.args) >= 2 and isinstance(node.args[0], ast.Name) and node.args[0].id in aliases
              and not (isinstance(node.args[1], ast.Constant) and node.args[1].value not in MEMORY_WRITERS)):
            found.append(f"{label}:{node.lineno}: getattr of the memory module")
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
            if path.suffix == ".py" and path.name.startswith(("chief", "dispatch", "group")):
                self.assertIn(path.name, names, "a chief, dispatch or group module the scan does not cover")

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

    def test_the_console_does_call_every_writer_so_the_rule_is_not_empty(self):
        calls = {m.group(1) for m in re.finditer(r"memory_mod\.(\w+)", (PACKAGE / "server.py").read_text(encoding="utf-8"))}
        self.assertEqual(calls & (MEMORY_WRITERS - {"store"}), MEMORY_WRITERS - {"store"})
        self.assertEqual(memory_writer_uses((PACKAGE / "server.py").read_text(encoding="utf-8"), "server.py") != [], True)

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

    def test_the_memory_modules_obey_the_rules_of_the_others(self):
        self.assertCaught("from . import config as cfg\ncfg.save({})\n", "config.save")      # the same table, now over memory*.py
        self.assertCaught("from .runtime import daemon\n", "runtime.daemon")

    def assertWrites(self, source: str, *needles: str):
        found = " | ".join(memory_writer_uses(source))
        self.assertTrue(found, f"nothing found in:\n{source}")
        for needle in needles:
            self.assertIn(needle, found)

    def test_what_is_allowed_is_clean(self):
        clean = (
            "from . import agent_profiles as ap, autonomy, config as cfg, meetings\n"
            "from .runtime import chat_store\n"
            "from .chat_service import ChatService\n"
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


if __name__ == "__main__":
    unittest.main()
