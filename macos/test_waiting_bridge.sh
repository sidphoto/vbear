#!/bin/bash
# The waiting-count bridge (v0.22, P48-4): every decision the app makes about the page's number, run without a window, a NSApplication or the
# system's notification center. Same method as test_browser_mode.sh: main.swift minus its start-up code, compiled with a small harness.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
mkdir -p "$ROOT/_sandbox"
TEST_DIR="$(mktemp -d "$ROOT/_sandbox/waiting-unit.XXXXXX")"
sed '/^let app = NSApplication.shared/,$d' "$ROOT/macos/VBear/main.swift" > "$TEST_DIR/main.swift"
cat >> "$TEST_DIR/main.swift" <<'SWIFT'
func check(_ condition: @autoclosure () -> Bool, _ label: String) {
    guard condition() else { fatalError(label) }
    print("PASS  \(label)")
}
func ask(_ body: Any, main: Bool = true, scheme: String = "http", host: String = "127.0.0.1", port: Int = 7799) -> WaitingRequest {
    waitingRequest(frameIsMain: main, scheme: scheme, host: host, port: port, serverPort: 7799, body: body)
}
let good: [String: Any] = ["count": 3, "notify": true]

// ---- what the page may say -------------------------------------------------------------------------------------------
check(ask(good) == .count(3, notify: true), "a count and a notify flag from the app's own page is taken")
check(ask(["count": 0, "notify": false]) == .count(0, notify: false), "zero is a number")
check(ask(["count": 999, "notify": false]) == .count(999, notify: false), "999 is the largest")
check(ask(["ask": true]) == .ask, "the ask message asks for the allowance")
check(waitingMessage == "vbearWaiting", "the message name the page uses")

check(ask(good, main: false) == .ignore, "a message from a subframe is ignored")
check(ask(good, port: 7800) == .ignore, "a message from another port is ignored")
check(ask(good, host: "localhost") == .ignore, "a message from another name of the machine is ignored")
check(ask(good, host: "evil.example") == .ignore, "a message from another host is ignored")
check(ask(good, scheme: "https") == .ignore, "a message from another scheme is ignored")
check(ask(["ask": true], main: false) == .ignore && ask(["ask": true], port: 7800) == .ignore && ask(["ask": true], host: "localhost") == .ignore,
      "the ask message has the same origin rules")

check(ask(["count": 3, "notify": true, "text": "hello"]) == .ignore, "an extra key is ignored")
check(ask(["count": 3, "notify": true, "ask": true]) == .ignore, "count, notify and ask together are ignored")
check(ask(["count": 3]) == .ignore && ask(["notify": true]) == .ignore, "a missing key is ignored")
check(ask([String: Any]()) == .ignore, "an empty body is ignored")
check(ask(["ask": true, "count": 1]) == .ignore, "ask with another key is ignored")
check(ask(["ask": false]) == .ignore, "ask that is not true is ignored")
check(ask(["ask": 1]) == .ignore && ask(["ask": "true"]) == .ignore, "ask of another type is ignored")
check(ask(["count": -1, "notify": true]) == .ignore, "a negative count is ignored")
check(ask(["count": 1000, "notify": true]) == .ignore, "a count over 999 is ignored")
check(ask(["count": 3.5, "notify": true]) == .ignore, "a fraction is ignored")
check(ask(["count": "3", "notify": true]) == .ignore, "a string count is ignored")
check(ask(["count": true, "notify": true]) == .ignore, "a true count is not the number 1")
check(ask(["count": NSNumber(value: true), "notify": true]) == .ignore, "a boolean that came across the bridge is not a number")
check(ask(["count": NSNumber(value: 3), "notify": NSNumber(value: false)]) == .count(3, notify: false), "numbers and booleans that came across the bridge are taken")
check(ask(["count": 3, "notify": 1]) == .ignore && ask(["count": 3, "notify": "yes"]) == .ignore, "a notify flag that is not a boolean is ignored")
check(ask(["count": NSNull(), "notify": true]) == .ignore, "null is ignored")
check(ask("3") == .ignore && ask([3]) == .ignore && ask(3) == .ignore, "a body of another shape is ignored")

// ---- the words are the app's own, made from the number -----------------------------------------------------------------
check(waitingTitle(count: 0) == "VBear", "no number in the title for zero")
check(waitingTitle(count: 1) == "(1) VBear" && waitingTitle(count: 12) == "(12) VBear", "the title carries the number")
check(waitingTitle(count: 5000) == "(999) VBear" && waitingTitle(count: -4) == "VBear", "the title clamps")
check(waitingBadge(count: 0) == nil && waitingBadge(count: 7) == "7" && waitingBadge(count: 5000) == "999", "the Dock shows a number only when something waits")
let note = waitingNote(count: 3)
check(note.title == "VBear" && note.body == "有 3 件事等你決定", "the notification has a fixed form")
check(waitingNote(count: 5000).body == "有 999 件事等你決定" && waitingNote(count: -2).body == "有 0 件事等你決定", "the notification clamps")
for n in [1, 2, 9, 10, 99, 100, 999] {
    let b = waitingNote(count: n).body
    check(b.hasPrefix("有 ") && b.hasSuffix(" 件事等你決定") && Int(b.dropFirst(2).dropLast(7)) == n, "the notification for \(n) is the form and the number only")
}

// ---- when to tell the person ------------------------------------------------------------------------------------------
check(!waitingShouldNotify(previous: nil, count: 2, appIsActive: false), "the first number is only remembered")
check(waitingShouldNotify(previous: 1, count: 2, appIsActive: false), "more than before, and VBear is not in front: tell")
check(!waitingShouldNotify(previous: 1, count: 2, appIsActive: true), "VBear in front: do not tell")
check(!waitingShouldNotify(previous: 2, count: 2, appIsActive: false), "the same number does not tell again")
check(!waitingShouldNotify(previous: 3, count: 2, appIsActive: false), "fewer does not tell")
check(!waitingShouldNotify(previous: 0, count: 0, appIsActive: false), "nothing waiting does not tell")
var record = WaitingRecord()
check(!record.see(count: 2, notify: true, appIsActive: false) && record.last == 2, "the first number sets the record without telling")
check(record.see(count: 3, notify: true, appIsActive: false) && record.last == 3, "one more tells and is remembered")
check(!record.see(count: 3, notify: true, appIsActive: false), "the same number is not told twice")
check(!record.see(count: 4, notify: true, appIsActive: true) && record.last == 4, "one more seen in front is remembered and not told")
check(!record.see(count: 4, notify: true, appIsActive: false), "so it is not told when VBear goes behind")
check(!record.see(count: 1, notify: true, appIsActive: false) && record.last == 1, "fewer only moves the record")
check(record.see(count: 2, notify: true, appIsActive: false), "a new one after fewer tells")
check(!record.see(count: 9, notify: false, appIsActive: false) && record.last == 2, "with the switch off nothing is told or recorded")
var fresh = WaitingRecord()
check(!fresh.see(count: 5, notify: false, appIsActive: false) && fresh.last == nil, "off from the start leaves no record")
check(!fresh.see(count: 6, notify: true, appIsActive: true) && fresh.last == 6, "turning it on in front records without telling")

// ---- the answer back to the page: three fixed words ----------------------------------------------------------------------
check(waitingAnswerScript("granted") == "window.vbearNotifyAnswer && window.vbearNotifyAnswer(\"granted\")", "granted")
check(waitingAnswerScript("denied") == "window.vbearNotifyAnswer && window.vbearNotifyAnswer(\"denied\")", "denied")
check(waitingAnswerScript("unavailable") == "window.vbearNotifyAnswer && window.vbearNotifyAnswer(\"unavailable\")", "unavailable")
for bad in ["", "Granted", "ok", "granted\")", "granted; alert(1)", "\"granted\""] {
    check(waitingAnswerScript(bad) == nil, "no other word is sent: \(bad.debugDescription)")
}
check(waitingAnswer(granted: true, failed: false) == "granted" && waitingAnswer(granted: false, failed: false) == "denied"
      && waitingAnswer(granted: true, failed: true) == "unavailable" && waitingAnswer(granted: false, failed: true) == "unavailable",
      "the system's answer becomes one of the three words")
check(waitingOpenScript == "location.hash = \"#/\"", "a press on the notification goes home with a fixed line")
SWIFT
swiftc -framework Cocoa -framework WebKit -o "$TEST_DIR/waiting-tests" "$TEST_DIR/main.swift"
"$TEST_DIR/waiting-tests"
