"""No test listens on a port it chose itself: two copies of the suite (or the suite and anything else on the Mac)
must not be able to collide. A test that needs a listener binds port 0 and reads the real port back from the
listening socket (``httpd.server_address[1]``), then builds what needs the number.

What is judged, and how:

* Python files (``tests/**/*.py``) are parsed, and only the *arguments of listener calls* are looked at, so a
  docstring, a comment or a JSON string that happens to contain a port is never a finding. A finding is: a
  ``(host, N)`` tuple, a ``port=N`` keyword or a first positional integer ``N`` in a call of ``bind``, ``listen``,
  ``HTTPServer``, ``ThreadingHTTPServer``, ``TCPServer``, ``ThreadingTCPServer``, ``UDPServer``,
  ``create_server``, ``start_server``, ``serve`` or ``Console``; a literal ``--port`` followed by a number in a
  list or tuple handed to any call; and a ``port``-named variable or attribute assigned a non-zero integer.
  The host does not matter (IPv4, IPv6 ``::1`` and ``::``, or ``""``), and ``N == 0`` is the allowed form.
* JavaScript tests (``tests/frontend/*.cjs``) have no parser here, so they are judged by line patterns for the
  two shapes: ``.listen(N`` and ``port: N`` / ``port = N``; comment lines are skipped. A string that merely
  looks like one of those shapes can be a false finding.

Limits: a port built at run time (``base + 1``, read from a file) is not seen, and a listener created through a
helper with another name is only found when it passes a literal to one of the names above.
"""

import ast
import re
import unittest
from pathlib import Path

TESTS = Path(__file__).resolve().parent
LISTENER_CALLS = frozenset({"bind", "listen", "HTTPServer", "ThreadingHTTPServer", "TCPServer", "ThreadingTCPServer",
                            "UDPServer", "create_server", "start_server", "serve", "Console"})
_FIRST_POSITIONAL_IS_PORT = frozenset({"Console", "serve"})
_JS_PATTERNS = (
    re.compile(r"""\.listen\(\s*[1-9][0-9]*\b"""),
    re.compile(r"""\bport\s*[:=]\s*[1-9][0-9]{2,5}\b"""),
)


def _nonzero_int(node) -> bool:
    return (isinstance(node, ast.Constant) and isinstance(node.value, int) and not isinstance(node.value, bool)
            and node.value != 0)


def _call_name(call: ast.Call) -> str:
    f = call.func
    return f.attr if isinstance(f, ast.Attribute) else (f.id if isinstance(f, ast.Name) else "")


def _port_name(target) -> bool:
    name = target.attr if isinstance(target, ast.Attribute) else (target.id if isinstance(target, ast.Name) else "")
    return name.lower() == "port" or name.lower().endswith("_port")


def python_findings(source: str, filename: str = "<test>") -> list[str]:
    """(line: what) for each fixed port in the arguments of a listener call, a ``--port N`` argument list or a
    port-named assignment. Docstrings, comments and plain strings are never looked at."""
    found = []
    tree = ast.parse(source, filename)
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            name = _call_name(node)
            if name in LISTENER_CALLS:
                for n, arg in enumerate(node.args):
                    if isinstance(arg, ast.Tuple) and len(arg.elts) >= 2 and _nonzero_int(arg.elts[1]):
                        found.append(f"{arg.lineno}: {name}(..., (host, {arg.elts[1].value}))")
                    elif n == 0 and name in _FIRST_POSITIONAL_IS_PORT and _nonzero_int(arg):
                        found.append(f"{arg.lineno}: {name}({arg.value})")
                for kw in node.keywords:
                    if kw.arg == "port" and _nonzero_int(kw.value):
                        found.append(f"{kw.value.lineno}: {name}(port={kw.value.value})")
            for arg in list(node.args) + [kw.value for kw in node.keywords]:
                if isinstance(arg, (ast.List, ast.Tuple)):
                    elts = arg.elts
                    for i, e in enumerate(elts[:-1]):
                        nxt = elts[i + 1]
                        if (isinstance(e, ast.Constant) and e.value == "--port" and isinstance(nxt, ast.Constant)
                                and str(nxt.value) not in ("0", "")):
                            found.append(f"{nxt.lineno}: --port {nxt.value}")
        elif isinstance(node, (ast.Assign, ast.AnnAssign, ast.AugAssign)):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            value = node.value
            if value is not None and _nonzero_int(value) and any(_port_name(t) for t in targets):
                found.append(f"{node.lineno}: a port-named variable is {value.value}")
    return found


def js_findings(source: str) -> list[str]:
    found = []
    for n, line in enumerate(source.splitlines(), 1):
        if line.lstrip().startswith(("//", "*", "/*")):
            continue
        if any(p.search(line) for p in _JS_PATTERNS):
            found.append(f"{n}: {line.strip()[:100]}")
    return found


class FixedPortTests(unittest.TestCase):
    def test_no_test_file_names_a_port(self):
        found = []
        for path in sorted(TESTS.rglob("*.py")):
            if path.resolve() == Path(__file__).resolve():
                continue
            found += [f"{path.relative_to(TESTS)}:{x}" for x in python_findings(path.read_text(encoding="utf-8"), str(path))]
        for path in sorted(TESTS.rglob("*.cjs")):
            found += [f"{path.relative_to(TESTS)}:{x}" for x in js_findings(path.read_text(encoding="utf-8"))]
        self.assertEqual(found, [], "a fixed port: bind port 0 and read the real one back")

    def test_the_checker_finds_what_it_is_for_and_only_that(self):
        bad = [
            'cls.port = 18891',
            'ThreadingHTTPServer(("127.0.0.1", 18889), h)',
            'http.server.HTTPServer(("::1", 18800), h)',                       # IPv6 loopback
            'srv = ThreadingHTTPServer(("::", 18800), h)',                     # IPv6 any
            'ThreadingHTTPServer(("", 8080), h)',
            's.bind(("0.0.0.0", 7788))',
            'Console(7788)',
            'server.Console(port=7788)',
            'asyncio.start_server(cb, host="x", port=9000)',
            'subprocess.Popen([sys.executable, "-m", "vbear", "serve", "--port", "18800"])',
            'self.server_port = 4000',
        ]
        for src in bad:
            with self.subTest(src=src):
                self.assertTrue(python_findings(src), src)
        good = [
            'ThreadingHTTPServer(("127.0.0.1", 0), None)',
            'ThreadingHTTPServer(("::1", 0), None)',
            'cls.port = cls.httpd.server_address[1]',
            'self.port = 0',
            'Console(self.port)',
            'subprocess.Popen([sys.executable, "-m", "vbear", "serve", "--port", str(port)])',
            '"""a docstring that says ThreadingHTTPServer(("127.0.0.1", 18889)) and cls.port = 18891"""',
            '# s.bind(("127.0.0.1", 18889))',
            'x = {"port": 7788}',
            'open(p).write(\'{"port": 7788}\')',
            'self.assertEqual(data["config"]["port"], cfg.DEFAULT_PORT)',
            'urllib.request.urlopen("http://127.0.0.1:18889/x")',                  # a client, not a listener
        ]
        for src in good:
            with self.subTest(src=src):
                self.assertEqual(python_findings(src), [], src)
        self.assertTrue(js_findings("server.listen(18800)"))
        self.assertTrue(js_findings("const c = { port: 18800 };"))
        self.assertEqual(js_findings("server.listen(0, () => {});\n// server.listen(18800)\n"), [])


if __name__ == "__main__":
    unittest.main()
