// VBear for macOS: a window around the local VBear console.
//
// On launch it reuses a running VBear that accepts the token in its state
// directory, or starts the bundled Python on a free local port with a fresh
// token handed over through the environment (the server removes it from its
// own environment at once). The window signs in through the URL fragment,
// never a command line. Quitting stops only a server this app started; the
// runtime daemon and its terminals keep running.

import Cocoa
import WebKit
import UserNotifications

// Scripted acceptance can select a port without ever probing the user's console.
let testPort = ProcessInfo.processInfo.environment["VBEAR_APP_PORT"].flatMap(Int.init)
let defaultPort = testPort ?? 7788
let browserPreference = "BrowserOnLaunch"

func shouldLaunchBrowser(_ preferred: Bool, modifiers: NSEvent.ModifierFlags) -> Bool {
    preferred && !modifiers.contains(.option)
}

func browserLaunchProblem(_ process: Process, timeout: TimeInterval = 15) throws -> String? {
    try process.run()
    let deadline = Date().addingTimeInterval(timeout)
    while process.isRunning && Date() < deadline { Thread.sleep(forTimeInterval: 0.05) }
    if process.isRunning {
        process.terminate()
        return "瀏覽器啟動超過 15 秒，已改用視窗模式。"
    }
    if process.terminationStatus != 0 {
        return "瀏覽器啟動失敗（代碼 \(process.terminationStatus)），已改用視窗模式。"
    }
    return nil
}

// ---- the folder chooser the page can ask for (design card-play 4, R9) --------------------------------------------
// The page posts {requestId} to the script message handler `vbearPickFolder` and hears back through
// window.__vbearFolderPicked(JSON). What it gets is only a path as text: it still asks the server (inspect) about
// it, and the chooser gives the page no file access. The decisions live in these plain functions so a test can run
// them without a window.

let folderPickerMessage = "vbearPickFolder"

/// ^[a-z0-9-]{1,32}$
func isValidPickerRequestId(_ id: String) -> Bool {
    guard (1...32).contains(id.utf8.count) else { return false }
    return id.utf8.allSatisfy { ($0 >= 97 && $0 <= 122) || ($0 >= 48 && $0 <= 57) || $0 == 45 }
}

/// Only the app's own server: http, 127.0.0.1, and the port this app started (or found) it on.
func isConsoleOrigin(scheme: String, host: String, port: Int, serverPort: Int) -> Bool {
    scheme == "http" && host == "127.0.0.1" && port == serverPort
}

/// One chooser panel at a time.
final class FolderPickerGate {
    private(set) var isOpen = false
    func begin() -> Bool {
        if isOpen { return false }
        isOpen = true
        return true
    }
    func end() { isOpen = false }
}

enum PickerRequest: Equatable {
    case ignore               // not ours to answer: no reply at all
    case busy(String)         // a panel is already open
    case open(String)         // show the panel; the gate is now taken
}

func pickerRequest(frameIsMain: Bool, scheme: String, host: String, port: Int, serverPort: Int,
                   body: Any, gate: FolderPickerGate) -> PickerRequest {
    guard frameIsMain, isConsoleOrigin(scheme: scheme, host: host, port: port, serverPort: serverPort),
          let dict = body as? [String: Any], dict.count == 1,
          let id = dict["requestId"] as? String, isValidPickerRequestId(id) else { return .ignore }
    return gate.begin() ? .open(id) : .busy(id)
}

/// The JavaScript that hands the answer to the page; the JSON comes from JSONSerialization, never from string pasting.
func pickerReplyScript(requestId: String, status: String, path: String?) -> String? {
    guard ["ok", "cancel", "busy"].contains(status), isValidPickerRequestId(requestId) else { return nil }
    var object: [String: Any] = ["requestId": requestId, "status": status]
    if status == "ok" {
        guard let path = path else { return nil }
        object["path"] = path
    }
    guard JSONSerialization.isValidJSONObject(object),
          let data = try? JSONSerialization.data(withJSONObject: object),
          let json = String(data: data, encoding: .utf8) else { return nil }
    return "window.__vbearFolderPicked(\(json))"
}

// ---- the number of things that wait, the Dock, the window title and the Mac notification (v0.22, P48-4) ---------------
// The page posts {count, notify} to the script message handler `vbearWaiting` (count: a whole number 0 to 999; notify: whether the person turned the
// notification on in the page's settings), and {ask: true} when the person presses that switch. Nothing else is taken: the words of the window title,
// the Dock and the notification are made here from the number, never copied from the page. This section opens no connection (no network call and no
// subprocess) and keeps nothing on disk. The decisions are plain functions so a test can run them without a window or the notification center.

let waitingMessage = "vbearWaiting"

enum WaitingRequest: Equatable {
    case ignore                         // not ours to answer
    case count(Int, notify: Bool)       // the number, and whether to tell the person when it grows
    case ask                            // the person pressed the switch: ask the system for the allowance (the only time it is asked)
}

/// A whole number that is not a boolean in disguise (a boolean that crosses the bridge is an NSNumber too).
func waitingInteger(_ value: Any) -> Int? {
    if let n = value as? NSNumber {
        if CFGetTypeID(n) == CFBooleanGetTypeID() { return nil }
        let d = n.doubleValue
        guard d == d.rounded(), abs(d) < 1_000_000 else { return nil }
        return Int(d)
    }
    return nil
}

func waitingBoolean(_ value: Any) -> Bool? {
    guard let n = value as? NSNumber, CFGetTypeID(n) == CFBooleanGetTypeID() else { return nil }
    return n.boolValue
}

func waitingRequest(frameIsMain: Bool, scheme: String, host: String, port: Int, serverPort: Int, body: Any) -> WaitingRequest {
    guard frameIsMain, isConsoleOrigin(scheme: scheme, host: host, port: port, serverPort: serverPort),
          let dict = body as? [String: Any] else { return .ignore }
    if dict.count == 1, let ask = dict["ask"], waitingBoolean(ask) == true { return .ask }
    guard dict.count == 2, let rawCount = dict["count"], let rawNotify = dict["notify"],
          let count = waitingInteger(rawCount), (0...999).contains(count), let notify = waitingBoolean(rawNotify) else { return .ignore }
    return .count(count, notify: notify)
}

func waitingClamped(_ count: Int) -> Int { min(max(count, 0), 999) }

/// `VBear`, or `(N) VBear`: the number and nothing else.
func waitingTitle(count: Int) -> String {
    let n = waitingClamped(count)
    return n > 0 ? "(\(n)) VBear" : "VBear"
}

/// The Dock icon's number; none when nothing waits.
func waitingBadge(count: Int) -> String? {
    let n = waitingClamped(count)
    return n > 0 ? String(n) : nil
}

/// The notification: a fixed form with the number in it.
func waitingNote(count: Int) -> (title: String, body: String) {
    ("VBear", "有 \(waitingClamped(count)) 件事等你決定")
}

/// Tell the person only when more things wait than the last number seen, and VBear is not the window in front.
func waitingShouldNotify(previous: Int?, count: Int, appIsActive: Bool) -> Bool {
    guard let previous = previous else { return false }
    return count > previous && !appIsActive
}

/// What was last seen while the notification was on. A number seen with the switch off (or a read that was not whole: the page says notify false then)
/// is not recorded, so turning the switch on, or a read that comes back whole, does not read as "something new".
struct WaitingRecord {
    private(set) var last: Int?
    mutating func see(count: Int, notify: Bool, appIsActive: Bool) -> Bool {
        guard notify else { return false }
        let before = last
        last = count
        return waitingShouldNotify(previous: before, count: count, appIsActive: appIsActive)
    }
}

/// The system's answer as one of the three words the page knows.
func waitingAnswer(granted: Bool, failed: Bool) -> String {
    failed ? "unavailable" : (granted ? "granted" : "denied")
}

func waitingAnswerScript(_ answer: String) -> String? {
    guard ["granted", "denied", "unavailable"].contains(answer) else { return nil }
    return "window.vbearNotifyAnswer && window.vbearNotifyAnswer(\"\(answer)\")"
}

/// A press on the notification brings the app forward and shows the home page; the line is fixed.
let waitingOpenScript = "location.hash = \"#/\""

/// The side effects. It is made only when the window is (never in the tests).
final class WaitingBridge: NSObject, UNUserNotificationCenterDelegate {
    private var record = WaitingRecord()
    var show: (String?, String?) -> Void = { _, _ in }        // (window title, Dock badge)
    var answer: (String) -> Void = { _ in }                    // to the page
    var goHome: () -> Void = {}

    func attach() { UNUserNotificationCenter.current().delegate = self }

    func receive(count: Int, notify: Bool) {
        show(waitingTitle(count: count), waitingBadge(count: count))
        if record.see(count: count, notify: notify, appIsActive: NSApp.isActive) { post(count: count) }
    }

    /// The only place the system is asked for the allowance: after the person pressed the switch in the page.
    func askForAllowance() {
        UNUserNotificationCenter.current().requestAuthorization(options: [.alert]) { granted, error in
            DispatchQueue.main.async { self.answer(waitingAnswer(granted: granted, failed: error != nil)) }
        }
    }

    func clear() { show("VBear", nil) }

    private func post(count: Int) {
        let center = UNUserNotificationCenter.current()
        center.getNotificationSettings { settings in
            guard settings.authorizationStatus == .authorized || settings.authorizationStatus == .provisional else { return }
            let words = waitingNote(count: count)
            let content = UNMutableNotificationContent()
            content.title = words.title
            content.body = words.body
            center.add(UNNotificationRequest(identifier: "vbear-waiting", content: content, trigger: nil))
        }
    }

    func userNotificationCenter(_ center: UNUserNotificationCenter, didReceive response: UNNotificationResponse,
                                withCompletionHandler completionHandler: @escaping () -> Void) {
        DispatchQueue.main.async { self.goHome() }
        completionHandler()
    }
}
// ---- end of the waiting bridge ---------------------------------------------------------------------------------------

func randomToken() -> String {
    var bytes = [UInt8](repeating: 0, count: 32)
    _ = SecRandomCopyBytes(kSecRandomDefault, bytes.count, &bytes)
    return Data(bytes).base64EncodedString()
        .replacingOccurrences(of: "+", with: "-")
        .replacingOccurrences(of: "/", with: "_")
        .replacingOccurrences(of: "=", with: "")
}

/// The state directory the Python side uses (VBEAR_HOME is not set for apps
/// started from Finder; the legacy directory is used until it is migrated).
func stateDirectory() -> URL {
    if let override = ProcessInfo.processInfo.environment["VBEAR_HOME"], !override.isEmpty {
        return URL(fileURLWithPath: (override as NSString).expandingTildeInPath)  // tests, scripted runs
    }
    let home = FileManager.default.homeDirectoryForCurrentUser
    let current = home.appendingPathComponent(".vbear")
    let legacy = home.appendingPathComponent(".sid-console")
    var isDir: ObjCBool = false
    if !FileManager.default.fileExists(atPath: current.path),
       FileManager.default.fileExists(atPath: legacy.path, isDirectory: &isDir), isDir.boolValue {
        return legacy
    }
    return current
}

/// Port and token of a VBear started earlier (by this app or `vbear launch`).
func recordedAccess() -> (port: Int, token: String)? {
    let file = stateDirectory().appendingPathComponent("server.token")
    guard let data = try? Data(contentsOf: file),
          let obj = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
          let port = obj["port"] as? Int, let token = obj["token"] as? String else { return nil }
    return (port, token)
}

/// A VBear that lets us in: 200 from /api/config with this token, its Server
/// header, and the shape of its config reply.
func accepts(port: Int, token: String) -> Bool {
    guard let url = URL(string: "http://127.0.0.1:\(port)/api/config") else { return false }
    var req = URLRequest(url: url, timeoutInterval: 1.5)
    req.setValue("Bearer \(token)", forHTTPHeaderField: "Authorization")
    let done = DispatchSemaphore(value: 0)
    var ok = false
    URLSession.shared.dataTask(with: req) { data, resp, _ in
        defer { done.signal() }
        guard let http = resp as? HTTPURLResponse, http.statusCode == 200,
              (http.value(forHTTPHeaderField: "Server") ?? "").hasPrefix("VBear/"),
              let data = data,
              let obj = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
              obj["config"] is [String: Any], obj["state_dir"] is String else { return }
        ok = true
    }.resume()
    _ = done.wait(timeout: .now() + 2)
    return ok
}

func portIsFree(_ port: Int) -> Bool {
    let fd = socket(AF_INET, SOCK_STREAM, 0)
    guard fd >= 0 else { return false }
    defer { close(fd) }
    var addr = sockaddr_in()
    addr.sin_family = sa_family_t(AF_INET)
    addr.sin_port = in_port_t(UInt16(port).bigEndian)
    addr.sin_addr.s_addr = inet_addr("127.0.0.1")
    return withUnsafePointer(to: &addr) {
        $0.withMemoryRebound(to: sockaddr.self, capacity: 1) {
            bind(fd, $0, socklen_t(MemoryLayout<sockaddr_in>.size)) == 0
        }
    }
}

func freePort() -> Int {
    if !(1...65535).contains(defaultPort) { return 0 }
    if portIsFree(defaultPort) { return defaultPort }
    if testPort != nil { return 0 }
    for p in 7789...7899 where portIsFree(p) { return p }
    return 0
}

final class AppDelegate: NSObject, NSApplicationDelegate, WKNavigationDelegate, WKUIDelegate, WKScriptMessageHandler, NSMenuItemValidation {
    var window: NSWindow!
    let folderGate = FolderPickerGate()
    var waiting: WaitingBridge?
    var webView: WKWebView!
    var server: Process?
    var port = defaultPort
    var token = ""
    var browserItem: NSMenuItem!
    var browserReady = false

    func applicationDidFinishLaunching(_ note: Notification) {
        buildMenu()
        if shouldLaunchBrowser(UserDefaults.standard.bool(forKey: browserPreference),
                               modifiers: NSEvent.modifierFlags) {
            launchBrowser()
        } else {
            startWindow()
        }
    }

    func startWindow() {
        let config = WKWebViewConfiguration()
        if testPort != nil { config.websiteDataStore = .nonPersistent() }
        config.preferences.javaScriptCanOpenWindowsAutomatically = false
        config.userContentController.add(self, name: folderPickerMessage)
        config.userContentController.add(self, name: waitingMessage)
        webView = WKWebView(frame: .zero, configuration: config)
        webView.navigationDelegate = self
        webView.uiDelegate = self
        window = NSWindow(contentRect: NSRect(x: 0, y: 0, width: 1280, height: 820),
                          styleMask: [.titled, .closable, .miniaturizable, .resizable],
                          backing: .buffered, defer: false)
        window.title = "VBear"
        window.minSize = NSSize(width: 760, height: 520)
        window.contentView = webView
        window.center()
        if testPort == nil { window.setFrameAutosaveName("VBearMain") }
        window.makeKeyAndOrderFront(nil)
        startWaiting()
        showMessage("VBear 正在啟動…", detail: "第一次開啟會先整理你的技能與工作紀錄，可能需要一點時間。")
        DispatchQueue.global(qos: .userInitiated).async { self.connect() }
    }

    func answerFolderPicker(_ requestId: String, _ status: String, _ path: String? = nil) {
        guard let script = pickerReplyScript(requestId: requestId, status: status, path: path) else { return }
        webView.evaluateJavaScript(script, completionHandler: nil)
    }

    func userContentController(_ controller: WKUserContentController, didReceive message: WKScriptMessage) {
        if message.name == waitingMessage { receiveWaiting(message); return }
        guard message.name == folderPickerMessage else { return }
        let origin = message.frameInfo.securityOrigin
        switch pickerRequest(frameIsMain: message.frameInfo.isMainFrame, scheme: origin.protocol, host: origin.host,
                             port: origin.port, serverPort: port, body: message.body, gate: folderGate) {
        case .ignore:
            return
        case .busy(let id):
            answerFolderPicker(id, "busy")
        case .open(let id):
            let panel = NSOpenPanel()
            panel.canChooseDirectories = true
            panel.canChooseFiles = false
            panel.allowsMultipleSelection = false
            panel.canCreateDirectories = false
            panel.message = "選一個專案資料夾"
            panel.prompt = "選擇"
            panel.beginSheetModal(for: window) { response in
                self.folderGate.end()
                if response == .OK, let url = panel.url {
                    self.answerFolderPicker(id, "ok", url.path)
                } else {
                    self.answerFolderPicker(id, "cancel")
                }
            }
        }
    }

    func startWaiting() {
        let bridge = WaitingBridge()
        bridge.show = { [weak self] title, badge in
            self?.window.title = title ?? "VBear"
            NSApp.dockTile.badgeLabel = badge
        }
        bridge.answer = { [weak self] word in
            if let script = waitingAnswerScript(word) { self?.webView.evaluateJavaScript(script, completionHandler: nil) }
        }
        bridge.goHome = { [weak self] in
            NSApp.activate(ignoringOtherApps: true)
            self?.window.makeKeyAndOrderFront(nil)
            self?.webView.evaluateJavaScript(waitingOpenScript, completionHandler: nil)
        }
        bridge.attach()
        waiting = bridge
    }

    func receiveWaiting(_ message: WKScriptMessage) {
        let origin = message.frameInfo.securityOrigin
        switch waitingRequest(frameIsMain: message.frameInfo.isMainFrame, scheme: origin.protocol, host: origin.host,
                              port: origin.port, serverPort: port, body: message.body) {
        case .ignore: return
        case .count(let n, let notify): waiting?.receive(count: n, notify: notify)
        case .ask: waiting?.askForAllowance()
        }
    }

    // A page that is replaced has no number any more: until the new one tells, the title and the Dock show none.
    func webView(_ webView: WKWebView, didCommit navigation: WKNavigation!) { waiting?.clear() }

    // Launch has its own detached server lifecycle. Never assign it to `server`.
    func launchBrowser() {
        DispatchQueue.global(qos: .userInitiated).async {
            var problem: String?
            let p = Process()
            do {
                guard let res = Bundle.main.resourceURL else { throw CocoaError(.fileNoSuchFile) }
                let appDir = res.appendingPathComponent("app")
                p.executableURL = res.appendingPathComponent("python/bin/python3")
                p.currentDirectoryURL = appDir
                p.arguments = ["-B", "-m", "vbear", "launch"]
                if let port = testPort { p.arguments! += ["--port", String(port)] }
                p.environment = self.pythonEnvironment(appDir)
                p.standardInput = FileHandle.nullDevice
                p.standardOutput = FileHandle.nullDevice
                p.standardError = FileHandle.nullDevice
                problem = try browserLaunchProblem(p)
            } catch {
                problem = "無法啟動瀏覽器模式：\(error.localizedDescription)"
            }
            DispatchQueue.main.async {
                if let problem = problem {
                    self.startWindow()
                    self.showBrowserError(problem)
                } else {
                    NSApp.terminate(nil)
                }
            }
        }
    }

    func pythonEnvironment(_ appDir: URL) -> [String: String] {
        let env = ProcessInfo.processInfo.environment
        var child: [String: String] = [:]
        for key in ["HOME", "USER", "LOGNAME", "TMPDIR", "VBEAR_HOME", "VBEAR_RUNTIME_AUTOSTART", "BROWSER"] {
            if let v = env[key] { child[key] = v }
        }
        child["LANG"] = env["LANG"] ?? "zh_TW.UTF-8"
        // Same list as vbear/runtime/daemon.py extra_path: the home directory's .local/bin
        // (where Claude Code and Codex install themselves) and the folders Grok and MiniMax Code
        // install into come last.
        var path = "/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin"
        if let home = child["HOME"], home.hasPrefix("/"), !home.contains(":") {
            path += ":" + home + "/.local/bin"
            path += ":" + home + "/.grok/bin"
            path += ":" + home + "/.minimax-code/bin"
        }
        child["PATH"] = path
        child["PYTHONPATH"] = appDir.path
        child["PYTHONDONTWRITEBYTECODE"] = "1"
        return child
    }

    func showBrowserError(_ message: String) {
        let alert = NSAlert()
        alert.messageText = "無法在瀏覽器中開啟"
        alert.informativeText = message + " 啟動時按住 Option 可使用視窗模式；你也可以在「顯示方式」取消瀏覽器啟動偏好。"
        alert.addButton(withTitle: "好")
        alert.beginSheetModal(for: window)
    }

    @objc func toggleBrowser(_ sender: NSMenuItem) {
        let enabled = !UserDefaults.standard.bool(forKey: browserPreference)
        UserDefaults.standard.set(enabled, forKey: browserPreference)
        sender.state = enabled ? .on : .off
    }

    @objc func openBrowser(_ sender: Any?) {
        // The server already wrote this private handoff; do not create another
        // token-bearing file or put the token in a subprocess argument.
        let opener = stateDirectory().appendingPathComponent("open.html")
        let expected = "<!doctype html><meta charset=utf-8><title>VBear</title>"
            + "<script>location.replace(\"http://127.0.0.1:\(port)/#auth=\(token)\")</script>"
            + "<p>正在開啟 VBear…</p>\n"
        guard browserReady, let contents = try? String(contentsOf: opener, encoding: .utf8),
              contents == expected, NSWorkspace.shared.open(opener) else {
            showBrowserError("主控台尚未就緒，或瀏覽器交接檔無法開啟。請稍後重試。")
            return
        }
    }

    func connect() {
        if let rec = recordedAccess(), (testPort == nil || rec.port == testPort), accepts(port: rec.port, token: rec.token) {
            port = rec.port
            token = rec.token
            return DispatchQueue.main.async { self.openConsole() }
        }
        port = freePort()
        guard port != 0 else {
            return fail("找不到可用的本機連接埠（7788–7899 都被佔用）。")
        }
        token = randomToken()
        do {
            try startServer()
        } catch {
            return fail("無法啟動 VBear：\(error.localizedDescription)")
        }
        let deadline = Date().addingTimeInterval(180)
        while Date() < deadline {
            if accepts(port: port, token: token) {
                return DispatchQueue.main.async { self.openConsole() }
            }
            if let s = server, !s.isRunning {
                return fail("VBear 啟動後結束了（代碼 \(s.terminationStatus)）。")
            }
            Thread.sleep(forTimeInterval: 0.3)
        }
        server?.terminate()  // do not leave a hung server behind
        fail("VBear 在 3 分鐘內沒有完成啟動。")
    }

    func startServer() throws {
        guard let res = Bundle.main.resourceURL else { throw CocoaError(.fileNoSuchFile) }
        let python = res.appendingPathComponent("python/bin/python3")
        let appDir = res.appendingPathComponent("app")
        let p = Process()
        p.executableURL = python
        p.arguments = ["-B", "-m", "vbear", "serve", "--port", String(port)]
        p.currentDirectoryURL = appDir
        var child = pythonEnvironment(appDir)
        child["VBEAR_ACCESS_TOKEN"] = token
        p.environment = child
        let logDir = stateDirectory()
        try? FileManager.default.createDirectory(at: logDir, withIntermediateDirectories: true,
                                                 attributes: [.posixPermissions: 0o700])
        let logURL = logDir.appendingPathComponent("app-server.log")
        if !FileManager.default.fileExists(atPath: logURL.path) {
            FileManager.default.createFile(atPath: logURL.path, contents: nil,
                                           attributes: [.posixPermissions: 0o600])
        }
        if let log = try? FileHandle(forWritingTo: logURL) {
            log.seekToEndOfFile()
            p.standardOutput = log
            p.standardError = log
        }
        p.standardInput = FileHandle.nullDevice
        try p.run()
        server = p
    }

    func openConsole() {
        guard let url = URL(string: "http://127.0.0.1:\(port)/#auth=\(token)") else { return }
        browserReady = true
        webView.load(URLRequest(url: url))
    }

    func fail(_ message: String) {
        DispatchQueue.main.async {
            let log = stateDirectory().appendingPathComponent("app-server.log").path
            self.showMessage(message, detail: "詳細紀錄：\(log)")
        }
    }

    func showMessage(_ title: String, detail: String) {
        func esc(_ s: String) -> String {
            s.replacingOccurrences(of: "&", with: "&amp;").replacingOccurrences(of: "<", with: "&lt;")
        }
        let html = """
        <!doctype html><meta charset="utf-8"><style>
        body{font:15px -apple-system,sans-serif;display:grid;place-items:center;height:95vh;margin:0;
        background:#1d1d1b;color:#f3efe4}div{max-width:520px;text-align:center}p{color:#b9b3a6}</style>
        <div><h2>\(esc(title))</h2><p>\(esc(detail))</p></div>
        """
        webView.loadHTMLString(html, baseURL: nil)
    }

    // Keep the window on the local console; everything else opens in the browser.
    func webView(_ webView: WKWebView, decidePolicyFor action: WKNavigationAction,
                 decisionHandler: @escaping (WKNavigationActionPolicy) -> Void) {
        guard let url = action.request.url else { return decisionHandler(.cancel) }
        if url.scheme == "about" || (url.host == "127.0.0.1" && url.port == port) {
            return decisionHandler(.allow)
        }
        if ["http", "https", "mailto"].contains(url.scheme ?? "") {
            NSWorkspace.shared.open(url)
        }
        decisionHandler(.cancel)
    }

    func webView(_ webView: WKWebView, createWebViewWith configuration: WKWebViewConfiguration,
                 for action: WKNavigationAction, windowFeatures: WKWindowFeatures) -> WKWebView? {
        if let url = action.request.url, ["http", "https", "mailto"].contains(url.scheme ?? "") {
            NSWorkspace.shared.open(url)
        }
        return nil
    }

    func applicationShouldTerminateAfterLastWindowClosed(_ sender: NSApplication) -> Bool { true }

    func applicationWillTerminate(_ note: Notification) {
        guard let p = server, p.isRunning else { return }
        p.terminate()  // SIGTERM: the server removes its token files; terminals keep running
        let deadline = Date().addingTimeInterval(3)
        while p.isRunning && Date() < deadline { Thread.sleep(forTimeInterval: 0.05) }
    }

    @objc func reload(_ sender: Any?) { webView?.reload() }

    func validateMenuItem(_ menuItem: NSMenuItem) -> Bool {
        if menuItem.action == #selector(openBrowser(_:)) { return browserReady }
        if menuItem.action == #selector(reload(_:)) { return webView != nil }
        return true
    }

    func buildMenu() {
        let main = NSMenu()
        func item(_ title: String, _ action: Selector?, _ key: String, _ mods: NSEvent.ModifierFlags = .command) -> NSMenuItem {
            let i = NSMenuItem(title: title, action: action, keyEquivalent: key)
            i.keyEquivalentModifierMask = mods
            return i
        }
        let app = NSMenu()
        app.addItem(item("關於 VBear", #selector(NSApplication.orderFrontStandardAboutPanel(_:)), ""))
        app.addItem(.separator())
        app.addItem(item("隱藏 VBear", #selector(NSApplication.hide(_:)), "h"))
        app.addItem(item("結束 VBear", #selector(NSApplication.terminate(_:)), "q"))
        let edit = NSMenu(title: "編輯")
        edit.addItem(item("還原", Selector(("undo:")), "z"))
        edit.addItem(item("重做", Selector(("redo:")), "z", [.command, .shift]))
        edit.addItem(.separator())
        edit.addItem(item("剪下", #selector(NSText.cut(_:)), "x"))
        edit.addItem(item("拷貝", #selector(NSText.copy(_:)), "c"))
        edit.addItem(item("貼上", #selector(NSText.paste(_:)), "v"))
        edit.addItem(item("全選", #selector(NSText.selectAll(_:)), "a"))
        let view = NSMenu(title: "顯示方式")
        view.addItem(item("重新載入", #selector(reload(_:)), "r"))
        view.addItem(item("在瀏覽器中開啟", #selector(openBrowser(_:)), ""))
        view.addItem(.separator())
        browserItem = item("啟動時用瀏覽器開啟（按住 Option 使用視窗）", #selector(toggleBrowser(_:)), "")
        browserItem.state = UserDefaults.standard.bool(forKey: browserPreference) ? .on : .off
        view.addItem(browserItem)
        let win = NSMenu(title: "視窗")
        win.addItem(item("縮到最小", #selector(NSWindow.miniaturize(_:)), "m"))
        win.addItem(item("關閉", #selector(NSWindow.performClose(_:)), "w"))
        for (title, menu) in [("VBear", app), ("編輯", edit), ("顯示方式", view), ("視窗", win)] {
            let top = NSMenuItem(title: title, action: nil, keyEquivalent: "")
            top.submenu = menu
            main.addItem(top)
        }
        NSApp.mainMenu = main
        NSApp.windowsMenu = win
    }
}

let app = NSApplication.shared
let delegate = AppDelegate()
app.delegate = delegate
app.setActivationPolicy(.regular)
app.activate(ignoringOtherApps: true)
app.run()
