"""No test listens on a port it chose itself: two copies of the suite (or the suite and anything else on the Mac)
must not be able to collide. A test that needs a listener binds port 0 and reads the real port back from the
listening socket (``httpd.server_address[1]``), then builds what needs the number."""

import re
import unittest
from pathlib import Path

TESTS = Path(__file__).resolve().parent
# a literal port in a bind/serve address, a port attribute set to a literal, a console built on a literal
_PATTERNS = (
    re.compile(r"""\(\s*["'](?:127\.0\.0\.1|localhost|0\.0\.0\.0|)["']\s*,\s*[1-9][0-9]*\s*\)"""),
    re.compile(r"""\bport\s*=\s*[1-9][0-9]{3,5}\b"""),
    re.compile(r"""\bConsole\(\s*[1-9][0-9]*\s*\)"""),
)


class FixedPortTests(unittest.TestCase):
    def test_no_test_file_names_a_port(self):
        found = []
        for path in sorted(TESTS.rglob("*.py")):
            if path.resolve() == Path(__file__).resolve():
                continue
            for n, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
                if line.lstrip().startswith("#"):
                    continue
                if any(p.search(line) for p in _PATTERNS):
                    found.append(f"{path.relative_to(TESTS)}:{n}: {line.strip()[:100]}")
        self.assertEqual(found, [], "a fixed port: bind port 0 and read the real one back")


if __name__ == "__main__":
    unittest.main()
