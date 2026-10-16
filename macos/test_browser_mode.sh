#!/bin/bash
# Exercise the actual Swift decision and subprocess code without opening a UI.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
mkdir -p "$ROOT/_sandbox"
TEST_DIR="$(mktemp -d "$ROOT/_sandbox/browser-unit.XXXXXX")"
# Keep the generated harness and binary as reproducible local evidence.
sed '/^let app = NSApplication.shared/,$d' "$ROOT/macos/VBear/main.swift" > "$TEST_DIR/main.swift"
cat >> "$TEST_DIR/main.swift" <<'SWIFT'
func check(_ condition: @autoclosure () -> Bool, _ label: String) {
    guard condition() else { fatalError(label) }
    print("PASS  \(label)")
}
check(!shouldLaunchBrowser(false, modifiers: []), "window mode is the default")
check(shouldLaunchBrowser(true, modifiers: []), "enabled preference selects browser mode")
check(!shouldLaunchBrowser(true, modifiers: .option), "Option overrides browser preference")
check(!shouldLaunchBrowser(true, modifiers: [.option, .shift]), "Option with other keys still overrides")
let child = AppDelegate().pythonEnvironment(URL(fileURLWithPath: "/synthetic/app"))
check(child["BROWSER"] == ProcessInfo.processInfo.environment["BROWSER"],
      "BROWSER is passed through unchanged without a default")
func process(_ path: String, _ arguments: [String] = []) -> Process {
    let p = Process()
    p.executableURL = URL(fileURLWithPath: path)
    p.arguments = arguments
    p.standardInput = FileHandle.nullDevice
    p.standardOutput = FileHandle.nullDevice
    p.standardError = FileHandle.nullDevice
    return p
}
let success = try browserLaunchProblem(process("/usr/bin/true"))
check(success == nil, "successful launch has no fallback error")
let failure = try browserLaunchProblem(process("/usr/bin/false"))
check(failure?.contains("代碼 1") == true, "nonzero exit explains fallback")
let slow = process("/bin/sleep", ["30"])
let start = Date()
let timeout = try browserLaunchProblem(slow, timeout: 0.1)
check(timeout?.contains("15 秒") == true && Date().timeIntervalSince(start) < 2,
      "deadline returns a fallback error promptly")
slow.waitUntilExit()
check(!slow.isRunning, "timed-out launcher is terminated")
do {
    _ = try browserLaunchProblem(process("/no-such-vbear-python"))
    fatalError("missing executable must fail")
} catch {
    print("PASS  missing bundled executable throws for fallback")
}
// The folder chooser bridge: every decision, without a window or a panel.
check(isValidPickerRequestId("pick-k3x9a-1"), "a lowercase token is a request id")
check(isValidPickerRequestId("a") && isValidPickerRequestId(String(repeating: "a", count: 32)), "1 and 32 characters are allowed")
for bad in ["", String(repeating: "a", count: 33), "Pick-1", "pick_1", "pick 1", "pick/1", "pick-1\n", "選擇", "a;b", "\"x\""] {
    check(!isValidPickerRequestId(bad), "request id refused: \(bad.debugDescription)")
}
check(isConsoleOrigin(scheme: "http", host: "127.0.0.1", port: 7799, serverPort: 7799), "the app's own server is allowed")
check(!isConsoleOrigin(scheme: "https", host: "127.0.0.1", port: 7799, serverPort: 7799), "https is not the app's server")
check(!isConsoleOrigin(scheme: "http", host: "localhost", port: 7799, serverPort: 7799), "another name for the machine is not")
check(!isConsoleOrigin(scheme: "http", host: "127.0.0.1", port: 7800, serverPort: 7799), "another port is not")
check(!isConsoleOrigin(scheme: "http", host: "evil.example", port: 7799, serverPort: 7799), "another host is not")
let gate = FolderPickerGate()
let okBody: [String: Any] = ["requestId": "pick-1"]
func ask(_ body: Any, main: Bool = true, scheme: String = "http", host: String = "127.0.0.1", port: Int = 7799) -> PickerRequest {
    pickerRequest(frameIsMain: main, scheme: scheme, host: host, port: port, serverPort: 7799, body: body, gate: gate)
}
check(ask(okBody, main: false) == .ignore, "a message from a subframe is ignored")
check(ask(okBody, port: 7800) == .ignore, "a message from another port is ignored")
check(ask(okBody, host: "localhost") == .ignore, "a message from another host is ignored")
check(ask(okBody, scheme: "https") == .ignore, "a message from another scheme is ignored")
check(ask("pick-1") == .ignore && ask(["requestId": 5]) == .ignore && ask([String: Any]()) == .ignore, "a body of the wrong shape is ignored")
check(ask(["requestId": "pick-1", "path": "/etc"]) == .ignore, "extra keys are ignored")
check(ask(["requestId": "BAD ID"]) == .ignore, "a bad request id is ignored")
check(!gate.isOpen, "ignored messages never take the panel")
check(ask(okBody) == .open("pick-1"), "a valid request opens the panel")
check(gate.isOpen, "and takes the gate")
check(ask(["requestId": "pick-2"]) == .busy("pick-2"), "while the panel is open a new request is busy")
check(ask(okBody, main: false) == .ignore, "busy does not answer a message that was ignored anyway")
gate.end()
check(ask(["requestId": "pick-3"]) == .open("pick-3"), "after the panel closed a request opens it again")
gate.end()
func decode(_ script: String?) -> [String: Any]? {
    guard let script = script, script.hasPrefix("window.__vbearFolderPicked("), script.hasSuffix(")") else { return nil }
    let json = String(script.dropFirst("window.__vbearFolderPicked(".count).dropLast())
    return try? JSONSerialization.jsonObject(with: Data(json.utf8)) as? [String: Any]
}
let okReply = decode(pickerReplyScript(requestId: "pick-1", status: "ok", path: "/Users/x/My \"Projects\"/\u{4E2D}\u{6587}"))
check(okReply?["status"] as? String == "ok" && okReply?["requestId"] as? String == "pick-1"
      && okReply?["path"] as? String == "/Users/x/My \"Projects\"/\u{4E2D}\u{6587}", "the path survives quotes and Chinese in the JSON")
let hostile = "/x\"); alert(1); (\""
let hostileScript = pickerReplyScript(requestId: "pick-1", status: "ok", path: hostile)
check(decode(hostileScript)?["path"] as? String == hostile, "a hostile path stays data inside the JSON")
check(decode(pickerReplyScript(requestId: "pick-1", status: "cancel", path: "/ignored"))?["path"] == nil, "cancel carries no path")
check(decode(pickerReplyScript(requestId: "pick-1", status: "busy", path: nil))?["status"] as? String == "busy", "busy reply")
check(pickerReplyScript(requestId: "pick-1", status: "ok", path: nil) == nil, "ok without a path is not sent")
check(pickerReplyScript(requestId: "pick-1", status: "approved", path: "/x") == nil, "an unknown status is not sent")
check(pickerReplyScript(requestId: "BAD", status: "cancel", path: nil) == nil, "a bad id is not echoed back")
check(folderPickerMessage == "vbearPickFolder", "the message name the page uses")
SWIFT
swiftc -framework Cocoa -framework WebKit -o "$TEST_DIR/browser-tests" "$TEST_DIR/main.swift"
BROWSER="$TEST_DIR/fake-browser" "$TEST_DIR/browser-tests"
env -u BROWSER "$TEST_DIR/browser-tests"
