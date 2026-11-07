"""P43-1 (ADR 0009): what the shared folder's own code never does, kept by reading its syntax tree. VBear does not open a file of the shared
folder (names, sizes and times only), has no way to delete one, never starts a program itself (Finder is opened by a function the console
hands in), never writes a name to a log, and does not write the console's config. The scan is over ``vbear/shared_folder.py`` and
``vbear/runtime/shared_rules.py`` and over the shared folder's part of the daemon, the launch code and the judgement."""

from __future__ import annotations

import ast
import unittest
from pathlib import Path

PACKAGE = Path(__file__).resolve().parents[1] / "vbear"
SHARED_MODULES = ("shared_folder.py", "runtime/shared_rules.py")
READS = {"open", "read_text", "read_bytes", "fdopen", "readlines", "readline", "read"}
DELETES = {"remove", "unlink", "rmdir", "rmtree", "removedirs", "truncate", "ftruncate", "move", "rename"}
PROGRAMS = {"run", "Popen", "system", "call", "check_call", "check_output", "execv", "execvp", "spawn"}


def tree_of(rel: str) -> ast.AST:
    return ast.parse((PACKAGE / rel).read_text(encoding="utf-8"), filename=rel)


def calls(tree: ast.AST):
    """(function it is in, the name called) of every call; ``os.open`` is "os.open"."""
    out = []

    def walk(node, fn):
        for child in ast.iter_child_nodes(node):
            inner = child.name if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)) else fn
            if isinstance(child, ast.Call):
                f = child.func
                if isinstance(f, ast.Name):
                    out.append((fn, f.id))
                elif isinstance(f, ast.Attribute):
                    base = f.value.id if isinstance(f.value, ast.Name) else ""
                    out.append((fn, f"{base}.{f.attr}" if base else f.attr))
            walk(child, inner)
    walk(tree, "<module>")
    return out


class ShapeTests(unittest.TestCase):
    def test_no_file_of_the_shared_folder_is_opened_or_read(self):
        for rel in SHARED_MODULES:
            for fn, name in calls(tree_of(rel)):
                short = name.split(".")[-1]
                if short in READS and not (rel == "shared_folder.py" and fn == "_log" and name == "os.open"):
                    self.fail(f"{rel}: {fn} calls {name}")
        # the one open is the append-only log of shared-meta, and it is opened without following a link
        source = (PACKAGE / "shared_folder.py").read_text(encoding="utf-8")
        self.assertIn("os.O_NOFOLLOW", source)

    def test_nothing_in_the_shared_folder_can_be_deleted_or_moved_by_vbear(self):
        for rel in SHARED_MODULES:
            for fn, name in calls(tree_of(rel)):
                short = name.split(".")[-1]
                if short in DELETES:
                    self.fail(f"{rel}: {fn} calls {name}")
        for fn, name in calls(tree_of("shared_folder.py")):
            if name == "os.replace":
                self.assertEqual(fn, "_log", "the only move is the log of shared-meta turning over at 1 MiB")

    def test_no_program_is_started_by_these_modules(self):
        for rel in SHARED_MODULES:
            for fn, name in calls(tree_of(rel)):
                self.assertNotIn(name.split(".")[-1], PROGRAMS, f"{rel}: {fn} calls {name}")
            imported = {a.name.split(".")[0] for n in ast.walk(tree_of(rel)) if isinstance(n, ast.Import) for a in n.names}
            imported |= {(n.module or "").split(".")[0] for n in ast.walk(tree_of(rel)) if isinstance(n, ast.ImportFrom)}
            self.assertFalse(imported & {"subprocess", "pty", "multiprocessing", "ctypes"}, rel)

    def test_a_log_line_carries_only_who_and_how(self):
        tree = tree_of("shared_folder.py")
        found = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "_log":
                found.append(sorted(k.arg for k in node.keywords))
                self.assertTrue(isinstance(node.args[0], ast.Constant) and node.args[0].value in ("card_on", "card_off", "revealed")
                                or isinstance(node.args[0], ast.IfExp), "what is a fixed word")
        self.assertTrue(found)
        for keys in found:
            self.assertTrue(set(keys) <= {"profile_id", "how"}, keys)

    def test_the_shared_modules_do_not_touch_the_config(self):
        for rel in SHARED_MODULES:
            tree = tree_of(rel)
            docs = {id(n.body[0].value) for n in ast.walk(tree) if isinstance(n, (ast.Module, ast.FunctionDef, ast.ClassDef)) and n.body
                    and isinstance(n.body[0], ast.Expr) and isinstance(n.body[0].value, ast.Constant)}
            for node in ast.walk(tree):
                if isinstance(node, ast.Constant) and isinstance(node.value, str) and id(node) not in docs:
                    self.assertNotIn("config.json", node.value, rel)
                if isinstance(node, ast.Name):
                    self.assertNotIn(node.id, ("config_path", "set_conf", "write_private"), rel)
                if isinstance(node, ast.Attribute):
                    self.assertNotIn(node.attr, ("config_path", "set_conf", "write_private"), rel)
                    if node.attr in ("save", "load") and isinstance(node.value, ast.Name):
                        self.assertNotIn(node.value.id, ("cfg", "config"), f"{rel} {node.value.id}.{node.attr}" if node.attr == "save" else "")

    def test_a_file_name_never_reaches_a_log_an_error_or_an_exception_of_the_daemons_shared_code(self):
        source = (PACKAGE / "runtime" / "daemon_chat.py").read_text(encoding="utf-8")
        start = source.index("def _chat_shared")
        end = source.index("# ---- a Claude Code chat")
        piece = source[start:end]
        self.assertNotIn("_log(", piece)
        self.assertNotIn("listdir", piece + source[source.index("shared_rules.usage"):source.index("shared_rules.usage") + 200])
        for fn, name in calls(tree_of("runtime/shared_rules.py")):
            self.assertNotIn(name, ("print", "logging.info", "logging.warning"), fn)


if __name__ == "__main__":
    unittest.main()
