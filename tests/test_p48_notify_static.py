"""P48-4 / guard 16e, the sources: the notification and the bridge to the app open no connection, ask the system for the allowance in one place
(after the person pressed the switch) and carry only a number. Reads sources only: no window, no notification center, no browser, no AI tool.
The behaviour is run by tests/frontend/p48_notify.cjs (the page) and macos/test_waiting_bridge.sh (the Swift decisions)."""
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SWIFT = (ROOT / "macos" / "VBear" / "main.swift").read_text(encoding="utf-8")
APP_JS = (ROOT / "web" / "app.js").read_text(encoding="utf-8")

SWIFT_FROM = "// ---- the number of things that wait, the Dock, the window title and the Mac notification (v0.22, P48-4)"
SWIFT_TO = "// ---- end of the waiting bridge"
HOOKS_FROM = "    func startWaiting() {"
HOOKS_TO = "    // Launch has its own detached server lifecycle."
JS_FROM = "// ---------- notifications (v0.22, P48-4)"
JS_TO = "// ---------- end of notifications"

NO_NETWORK = ("URLSession", "URLRequest", "NSURLConnection", "Process(", "NSWorkspace", "URL(string", "WKWebView(", "evaluateJavaScript(\"")


def between(text: str, start: str, end: str) -> str:
    i = text.index(start)
    j = text.index(end, i)
    return text[i:j]


def swift_violations(section: str, label: str = "swift") -> list[str]:
    """What a bridge section must not hold: a network call, a subprocess, a way to open a page of its own, a notification made of anything but the
    fixed form, the allowance asked in more than one place."""
    found = [f"{label}: {word}" for word in NO_NETWORK if word in section]
    for match in re.finditer(r"content\.(title|body)\s*=\s*([^\n]+)", section):
        if match.group(2).strip() != f"words.{match.group(1)}":
            found.append(f"{label}: the notification's {match.group(1)} is not made from the fixed form: {match.group(2).strip()[:60]}")
    if section.count("requestAuthorization(") > 1:
        found.append(f"{label}: the allowance is asked in more than one place")
    if "\\(" in re.sub(r'"有 \\\(waitingClamped\(count\)\) 件事等你決定"|"\(\\\(n\)\) VBear"|"window\.vbearNotifyAnswer && window\.vbearNotifyAnswer\(\\"\\\(answer\)\\"\)"', "", section):
        found.append(f"{label}: a string interpolation other than the number or the three fixed words")
    return found


def js_violations(app: str, label: str = "app.js") -> list[str]:
    found = []
    for word in ("PushManager", "pushManager", "serviceWorker", "ServiceWorker", "sw.js"):
        if word in app:
            found.append(f"{label}: {word}")
    if app.count("requestPermission") != 1:
        found.append(f"{label}: the allowance is asked in {app.count('requestPermission')} places")
    if app.count("new Notification(") != 1 or 'new Notification("VBear", ' not in app:
        found.append(f"{label}: a notification that is not titled VBear, or more than one place makes one")
    return found


class NotificationSources(unittest.TestCase):
    def test_16e_the_swift_bridge_opens_no_connection_and_asks_the_system_in_one_place(self):
        section = between(SWIFT, SWIFT_FROM, SWIFT_TO)
        hooks = between(SWIFT, HOOKS_FROM, HOOKS_TO)
        self.assertEqual(swift_violations(section, "bridge"), [])
        # the two methods of AppDelegate that carry it: they only hand the number on, they open nothing
        self.assertEqual([w for w in NO_NETWORK[:5] if w in hooks], [])
        self.assertEqual(SWIFT.count("requestAuthorization("), 1, "the allowance is asked in one place")
        self.assertEqual(SWIFT.count(".askForAllowance()"), 1, "and one thing calls it: the message that says ask")
        self.assertIn("case .ask: waiting?.askForAllowance()", hooks)
        for name in ("requestAuthorization", "getNotificationSettings", "center.add("):
            self.assertIn(name, section, name)
            self.assertEqual(SWIFT.count(name), 1, name)

    def test_16e_the_swift_bridge_takes_the_number_from_the_pure_function_and_nothing_from_the_page(self):
        hooks = between(SWIFT, HOOKS_FROM, HOOKS_TO)
        self.assertIn("switch waitingRequest(frameIsMain: message.frameInfo.isMainFrame", hooks)
        self.assertIn("message.frameInfo.securityOrigin", hooks)
        self.assertIn("waiting?.receive(count: n, notify: notify)", hooks)
        self.assertNotIn("message.body", hooks.replace("body: message.body)", ""), "the body is only given to the pure function")
        # the window title, the Dock and the notification are made from the number by the pure functions
        self.assertIn("window.title = title", hooks)
        self.assertIn("show(waitingTitle(count: count), waitingBadge(count: count))", SWIFT)
        self.assertIn("waitingNote(count: count)", SWIFT)
        # the notification text and the identifier are fixed
        self.assertIn('("VBear", "有 \\(waitingClamped(count)) 件事等你決定")', SWIFT)
        self.assertIn('identifier: "vbear-waiting"', SWIFT)
        # the system is asked only for the alert (no sound, no badge asked of the system: the Dock number is the app's own)
        self.assertIn("requestAuthorization(options: [.alert])", SWIFT)

    def test_16e_swift_check_fires_on_small_made_up_sources(self):
        good = 'let words = waitingNote(count: count)\ncontent.title = words.title\ncontent.body = words.body\ncenter.requestAuthorization(options: [.alert]) { _, _ in }\n'
        self.assertEqual(swift_violations(good), [])
        for bad, why in (("URLSession.shared.dataTask(with: u)", "URLSession"), ("let r = URLRequest(url: u)", "URLRequest"), ("NSURLConnection.send()", "NSURLConnection"),
                         ("let p = Process()", "Process("), ("NSWorkspace.shared.open(u)", "NSWorkspace"), ("let u = URL(string: page)", "URL(string")):
            self.assertTrue(swift_violations(good + bad + "\n"), why)
        self.assertTrue(swift_violations(good + 'content.body = pageText\n'), "a body that is not from the fixed form")
        self.assertTrue(swift_violations(good + 'content.title = "\\(page)"\n'), "a title that is not from the fixed form")
        self.assertTrue(swift_violations(good + 'center.requestAuthorization(options: [.alert]) { _, _ in }\n'), "a second place that asks")
        self.assertTrue(swift_violations(good + 'let line = "hello \\(page)"\n'), "an interpolation of the page's words")

    def test_16e_the_page_has_no_push_no_service_worker_and_one_place_that_asks_and_makes_a_notification(self):
        self.assertEqual(js_violations(APP_JS), [])
        section = between(APP_JS, JS_FROM, JS_TO)
        self.assertIn("requestPermission", section)
        self.assertIn('new Notification("VBear", { body: `有 ${Math.min(count, 999)} 件事等你決定`, tag: "vbear-waiting" })', section)
        # the question is in notifyAsk, and notifyAsk is called from the switch's handler and nowhere else
        ask = re.search(r"function notifyAsk\(\) \{.*?\n\}\n", section, re.S).group(0)
        self.assertIn("requestPermission", ask)
        self.assertEqual(len(re.findall(r"\bnotifyAsk\(\)", APP_JS)), 2, "its definition and one call")
        handler = re.search(r'input\.addEventListener\("change", async \(\) => \{.*?\n  \}\);', section, re.S).group(0)
        self.assertIn("await notifyAsk()", handler)
        for name in ("web/index.html", "web/style.css"):
            self.assertNotIn("requestPermission", (ROOT / name).read_text(encoding="utf-8"), name)
        self.assertFalse(list((ROOT / "web").glob("sw*.js")) or list((ROOT / "web").glob("*worker*")), "no service worker file")

    def test_16e_the_only_new_browser_storage_key_is_vbear_notify_and_only_the_switch_writes_it(self):
        section = between(APP_JS, JS_FROM, JS_TO)
        self.assertIn('const NOTIFY_KEY = "vbear-notify";', section)
        self.assertEqual(len(re.findall(r"localStorage\.(?:setItem|removeItem)\(NOTIFY_KEY", APP_JS)), 2, "set and remove, both in notifyWrite")
        self.assertEqual(len(re.findall(r"\bnotifyWrite\(", APP_JS)), 3, "its definition and the switch's handler (off, on)")
        self.assertNotIn("innerHTML", section)
        self.assertNotIn("api.post", section)
        self.assertNotIn("fetch(", section)

    def test_16e_the_page_check_fires_on_small_made_up_sources(self):
        good = 'function a() { Notification.requestPermission(f); }\nconst n = new Notification("VBear", { body: x });\n'
        self.assertEqual(js_violations(good), [])
        self.assertTrue(js_violations(good + "navigator.serviceWorker.register('/sw.js');"), "a service worker")
        self.assertTrue(js_violations(good + "new PushManager();"), "push")
        self.assertTrue(js_violations(good + "Notification.requestPermission(g);"), "a second place that asks")
        self.assertTrue(js_violations(good.replace('"VBear"', "name")), "a notification titled with something else")
        self.assertTrue(js_violations(good + 'new Notification("VBear", {});'), "a second place that makes one")


if __name__ == "__main__":
    unittest.main()
