"""Product code in web/ must not call the browser's own confirm(), alert() or prompt().

The VBear app window is a WKWebView whose UI delegate shows none of them: confirm() quietly answers
"no" and the button does nothing. The page has its own dialogs (confirmInPage, toast). Comments and
string contents are not product code, so they are blanked out before the search.
"""
import re
import unittest
from pathlib import Path

WEB = Path(__file__).resolve().parent.parent / "web"
NATIVE_CALL = re.compile(r"(?<![\w$.])(?:window\s*\.\s*)?(?:confirm|alert|prompt)\s*\(")


def blank_comments_and_strings(src):
    """Return src with comments, string literals and regex literals blanked (newlines kept).

    Template literal ${...} parts are code and are kept, so a call inside one is still found."""
    out = []
    i, n = 0, len(src)
    prev_sig = ""  # last significant (non-space) character emitted, to tell "/" division from a regex
    while i < n:
        c = src[i]
        two = src[i:i + 2]
        if two == "//":
            j = src.find("\n", i)
            j = n if j < 0 else j
            out.append(" " * (j - i)); i = j; continue
        if two == "/*":
            j = src.find("*/", i + 2)
            j = n if j < 0 else j + 2
            out.append(re.sub(r"[^\n]", " ", src[i:j])); i = j; continue
        if c in "\"'":
            j = i + 1
            while j < n and src[j] != c and src[j] != "\n":
                j += 2 if src[j] == "\\" else 1
            out.append(" " * (min(j + 1, n) - i)); i = j + 1; prev_sig = '"'; continue
        if c == "`":
            i, prev_sig = _template(src, i + 1, out), '"'
            if i < 0:
                raise AssertionError("unterminated template literal")
            continue
        if c == "/" and prev_sig in ("", "(", ",", "=", ":", "[", "!", "&", "|", "?", "{", "}", ";", "+", "-", "*", "%", "<", ">", "~", "^"):
            j = i + 1
            in_class = False
            while j < n and src[j] != "\n":
                if src[j] == "\\": j += 2; continue
                if src[j] == "[": in_class = True
                elif src[j] == "]": in_class = False
                elif src[j] == "/" and not in_class: break
                j += 1
            out.append(" " * (min(j + 1, n) - i)); i = j + 1; prev_sig = '"'; continue
        out.append(c)
        if not c.isspace(): prev_sig = c
        i += 1
    return "".join(out)


def _template(src, i, out):
    """Blank a template literal's text; recurse into ${ ... } as code. Return the index after it."""
    n = len(src)
    out.append(" ")  # the opening backtick
    while i < n:
        c = src[i]
        if c == "\\":
            out.append("  "); i += 2; continue
        if c == "`":
            out.append(" "); return i + 1
        if src[i:i + 2] == "${":
            out.append("  "); i += 2
            level = 1
            start = i
            while i < n and level:
                d = src[i]
                if d in "\"'":
                    j = i + 1
                    while j < n and src[j] != d: j += 2 if src[j] == "\\" else 1
                    i = j + 1; continue
                if d == "`":
                    sub = []
                    i = _template(src, i + 1, sub)
                    continue
                if d == "{": level += 1
                elif d == "}": level -= 1
                i += 1
            out.append(blank_comments_and_strings(src[start:i - 1]) + " ")
            continue
        out.append("\n" if c == "\n" else " "); i += 1
    return -1


class NoNativeDialogsTest(unittest.TestCase):
    def test_scanner_sees_calls_but_not_comments_or_strings(self):
        code = (
            "// confirm('x') in a comment\n"
            "/* alert('y')\n   prompt('z') */\n"
            "const a = \"confirm('in a string')\";\n"
            "const b = `alert('in a template') ${ok ? 'x' : 'y'}`;\n"
            "const r = /confirm\\(/.test(s);\n"
            "await confirmInPage('t', 'm', 'ok');\n"
            "obj.confirm(1);\n"
        )
        self.assertEqual(NATIVE_CALL.findall(blank_comments_and_strings(code)), [])
        for call in ("if (!confirm('x')) return;", "window.alert('x');", "const v = prompt('x');",
                     "x = `${confirm('x')}`;", "go(() => alert(1));"):
            with self.subTest(call=call):
                self.assertTrue(NATIVE_CALL.search(blank_comments_and_strings(call)), call)

    def test_product_code_never_calls_native_dialogs(self):
        # web/vendor holds third-party libraries (xterm), which are not product code.
        files = [f for f in sorted(WEB.rglob("*.js")) + sorted(WEB.rglob("*.html")) if "vendor" not in f.relative_to(WEB).parts]
        self.assertTrue(any(f.name == "app.js" for f in files), "web/app.js not found")
        found = []
        for f in files:
            text = f.read_text(encoding="utf-8")
            if f.suffix == ".html":
                text = "\n".join(m.group(1) for m in re.finditer(r"<script\b[^>]*>(.*?)</script>", text, re.S))
            clean = blank_comments_and_strings(text)
            for m in NATIVE_CALL.finditer(clean):
                line = clean.count("\n", 0, m.start()) + 1
                found.append(f"{f.relative_to(WEB.parent)}:{line}: {m.group(0)}")
        self.assertEqual(found, [], "native dialogs do not show in the app window; use confirmInPage or toast")


if __name__ == "__main__":
    unittest.main()
