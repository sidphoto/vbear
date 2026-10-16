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
SWIFT
swiftc -framework Cocoa -framework WebKit -o "$TEST_DIR/browser-tests" "$TEST_DIR/main.swift"
BROWSER="$TEST_DIR/fake-browser" "$TEST_DIR/browser-tests"
env -u BROWSER "$TEST_DIR/browser-tests"
