"""P59-1 (#22): every vbear module must import on its own, in a clean interpreter.

``vbear.translations`` used to fail with a circular import when it was the first vbear module imported
(translations -> runtime.daemon -> daemon_chat -> meetings -> translations). Normal start-up always imported something else first,
so nothing noticed. This test imports each module alone in a fresh ``python -I`` so any future cycle shows up here.
Nothing here starts a program other than the test's own Python; HOME and VBEAR_HOME are a temporary folder.
"""
from __future__ import annotations

import concurrent.futures
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PACKAGE = ROOT / "vbear"

# Modules that cannot be imported on their own for a reason other than a cycle. Keep this empty if at all possible.
EXCEPTIONS: dict[str, str] = {}

SNIPPET = "import importlib, sys; sys.path.insert(0, sys.argv[1]); importlib.import_module(sys.argv[2])"


def module_names(package_dir: Path = PACKAGE) -> list[str]:
    """Dotted names of the package, its sub-packages and every .py file under it (read from disk, nothing imported)."""
    names = []
    for path in sorted(package_dir.rglob("*.py")):
        if "__pycache__" in path.parts:
            continue
        rel = path.relative_to(package_dir.parent).with_suffix("")
        parts = list(rel.parts)
        if parts[-1] == "__init__":
            parts.pop()
        names.append(".".join(parts))
    return names


def import_alone(name: str, root: Path, home: Path) -> subprocess.CompletedProcess:
    env = {"HOME": str(home), "VBEAR_HOME": str(home / ".vbear"), "VBEAR_RUNTIME_AUTOSTART": "0",
           "PATH": "/usr/bin:/bin"}
    return subprocess.run([sys.executable, "-I", "-B", "-c", SNIPPET, str(root), name],
                          env=env, cwd=str(home), capture_output=True, text=True, timeout=120)


class EveryModuleImportsAlone(unittest.TestCase):
    def test_module_list_is_not_empty_and_has_the_known_cycle_members(self):
        names = module_names()
        for expected in ("vbear", "vbear.translations", "vbear.meetings", "vbear.runtime.daemon", "vbear.scan.walk"):
            self.assertIn(expected, names)

    def test_each_module_imports_in_a_clean_interpreter(self):
        names = [n for n in module_names() if n not in EXCEPTIONS]
        with tempfile.TemporaryDirectory(prefix="v59i.") as tmp:
            home = Path(tmp)
            (home / ".vbear").mkdir()
            with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
                results = list(pool.map(lambda n: (n, import_alone(n, ROOT, home)), names))
        failures = [f"{n}: {r.stderr.strip().splitlines()[-1] if r.stderr.strip() else r.returncode}"
                    for n, r in results if r.returncode != 0]
        self.assertEqual(failures, [], "modules that fail to import on their own:\n" + "\n".join(failures))

    def test_the_helper_catches_a_circular_import(self):
        """A small package with a cycle must be reported, so the check above is not vacuous."""
        with tempfile.TemporaryDirectory(prefix="v59c.") as tmp:
            base = Path(tmp)
            pkg = base / "cyc"
            pkg.mkdir()
            (pkg / "__init__.py").write_text("")
            (pkg / "a.py").write_text("from .b import OTHER\nVALUE = 1\n")
            (pkg / "b.py").write_text("from .a import VALUE\nOTHER = 2\n")
            home = base / "home"
            home.mkdir()
            self.assertEqual(import_alone("cyc.b", base, home).returncode, 1)
            self.assertIn("circular import", import_alone("cyc.b", base, home).stderr)
            self.assertEqual(module_names(pkg), ["cyc", "cyc.a", "cyc.b"])

    def test_exceptions_are_explained(self):
        for name, why in EXCEPTIONS.items():
            self.assertIn(name, module_names())
            self.assertTrue(why.strip())


if __name__ == "__main__":
    unittest.main()
