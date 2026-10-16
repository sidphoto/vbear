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

final class AppDelegate: NSObject, NSApplicationDelegate, WKNavigationDelegate, WKUIDelegate, NSMenuItemValidation {
    var window: NSWindow!
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
        showMessage("VBear 正在啟動…", detail: "第一次開啟會先整理你的技能與工作紀錄，可能需要一點時間。")
        DispatchQueue.global(qos: .userInitiated).async { self.connect() }
    }

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
        child["PATH"] = "/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin"
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
