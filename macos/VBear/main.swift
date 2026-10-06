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

let defaultPort = 7788

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

/// 200 from /api/config with this token means a VBear that will let us in.
func accepts(port: Int, token: String) -> Bool {
    guard let url = URL(string: "http://127.0.0.1:\(port)/api/config") else { return false }
    var req = URLRequest(url: url, timeoutInterval: 1.5)
    req.setValue("Bearer \(token)", forHTTPHeaderField: "Authorization")
    let done = DispatchSemaphore(value: 0)
    var ok = false
    URLSession.shared.dataTask(with: req) { _, resp, _ in
        ok = (resp as? HTTPURLResponse)?.statusCode == 200
        done.signal()
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
    if portIsFree(defaultPort) { return defaultPort }
    for p in 7789...7899 where portIsFree(p) { return p }
    return 0
}

final class AppDelegate: NSObject, NSApplicationDelegate, WKNavigationDelegate, WKUIDelegate {
    var window: NSWindow!
    var webView: WKWebView!
    var server: Process?
    var port = defaultPort
    var token = ""

    func applicationDidFinishLaunching(_ note: Notification) {
        buildMenu()
        let config = WKWebViewConfiguration()
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
        window.setFrameAutosaveName("VBearMain")
        window.makeKeyAndOrderFront(nil)
        showMessage("VBear 正在啟動…", detail: "第一次開啟會先整理你的技能與工作紀錄，可能需要一點時間。")
        DispatchQueue.global(qos: .userInitiated).async { self.connect() }
    }

    func connect() {
        if let rec = recordedAccess(), accepts(port: rec.port, token: rec.token) {
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
        let env = ProcessInfo.processInfo.environment
        var child: [String: String] = [:]
        for key in ["HOME", "USER", "LOGNAME", "TMPDIR", "VBEAR_HOME"] { if let v = env[key] { child[key] = v } }
        child["LANG"] = env["LANG"] ?? "zh_TW.UTF-8"
        child["PATH"] = "/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin"
        child["PYTHONPATH"] = appDir.path
        child["PYTHONDONTWRITEBYTECODE"] = "1"
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
        if let url = action.request.url { NSWorkspace.shared.open(url) }
        return nil
    }

    func applicationShouldTerminateAfterLastWindowClosed(_ sender: NSApplication) -> Bool { true }

    func applicationWillTerminate(_ note: Notification) {
        guard let p = server, p.isRunning else { return }
        p.terminate()  // SIGTERM: the server removes its token files; terminals keep running
        let deadline = Date().addingTimeInterval(3)
        while p.isRunning && Date() < deadline { Thread.sleep(forTimeInterval: 0.05) }
    }

    @objc func reload(_ sender: Any?) { webView.reload() }

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
