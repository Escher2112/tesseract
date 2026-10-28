// 3D Terminal for macOS — a small native window around Session Cube's shared core (server.py + index.html), so Mac and Linux
// share one cube and only this launcher is Mac-specific. Starts the server on port 8782, shows the page, stops the server on quit
// (which ends every shell on the cube). Lyra for Chris, 2026-10-27.
//
// 2026-10-28 MINI-BROWSER FACES (Chris: "if you can embed the browser into the actual app — then yes… not streaming from an existing
// open Chrome window… can you do it as a mini browser?"). Each browser face is a real WKWebView OWNED BY THIS APP: it lives behind the
// cube (loaded, logged in, running), the page shows a snapshot of it on its face, and in full screen this app lays the live view
// exactly over the face's area under the page's own address bar (back / forward / reload / type a URL or a search). Logins persist
// in the app's own website data store. The page talks to us through one message channel, "tdt":
//   {op:"open", face, url} · {op:"show", face, rect:{x,y,w,h}} · {op:"hide", face} · {op:"snap", face}
//   {op:"nav", face, go:"back"|"forward"|"reload"} · {op:"close", face}
// and we answer with window.webSnap(face, dataURL, title, url) (a picture) and window.webNav(face, title, url) (after every page load).
import AppKit
import WebKit

final class AppDelegate: NSObject, NSApplicationDelegate, WKScriptMessageHandler, WKUIDelegate, WKNavigationDelegate {
    var window: NSWindow!
    var web: WKWebView!
    var container: NSView!
    var server: Process?
    var browsers: [Int: WKWebView] = [:]
    var shown: Int? = nil

    func applicationDidFinishLaunching(_ note: Notification) {
        let cfg = WKWebViewConfiguration()
        cfg.userContentController.add(self, name: "tdt")
        web = WKWebView(frame: .zero, configuration: cfg)
        window = NSWindow(contentRect: NSRect(x: 0, y: 0, width: 1400, height: 900),
                          styleMask: [.titled, .closable, .resizable, .miniaturizable], backing: .buffered, defer: false)
        window.title = "3D Terminal"
        window.backgroundColor = .black
        window.collectionBehavior = [.fullScreenPrimary]
        container = NSView(frame: NSRect(x: 0, y: 0, width: 1400, height: 900))
        web.frame = container.bounds; web.autoresizingMask = [.width, .height]
        container.addSubview(web)
        window.contentView = container
        window.center()
        // TDT_BACKGROUND (testing): open without taking the keyboard from whatever Chris is typing in
        if ProcessInfo.processInfo.environment["TDT_BACKGROUND"] == nil { window.makeKeyAndOrderFront(nil); NSApp.activate(ignoringOtherApps: true) }
        else { window.orderBack(nil) }
        startServer()
    }

    // ---------- mini-browser faces
    func browser(_ face: Int) -> WKWebView {
        if let b = browsers[face] { return b }
        let cfg = WKWebViewConfiguration()
        cfg.websiteDataStore = .default()                       // logins persist across restarts (the app's own store)
        cfg.preferences.isElementFullscreenEnabled = true
        let b = WKWebView(frame: container.bounds, configuration: cfg)
        b.customUserAgent = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.0 Safari/605.1.15"
        b.uiDelegate = self; b.navigationDelegate = self
        b.autoresizingMask = [.width, .height]
        container.addSubview(b, positioned: .below, relativeTo: web)   // behind the cube: loaded and running, out of sight
        browsers[face] = b
        return b
    }
    func tell(_ fn: String, _ args: [Any]) {
        if let d = try? JSONSerialization.data(withJSONObject: args), let js = String(data: d, encoding: .utf8) {
            web.evaluateJavaScript("window.\(fn) && window.\(fn)(...\(js))")
        }
    }
    func userContentController(_ ucc: WKUserContentController, didReceive message: WKScriptMessage) {
        guard let m = message.body as? [String: Any], let op = m["op"] as? String, let face = m["face"] as? Int else { return }
        switch op {
        case "open":
            if let s = m["url"] as? String, let u = URL(string: s) { let b = browser(face); if b.url?.absoluteString != s { b.load(URLRequest(url: u)) } }
        case "show":
            guard let r = m["rect"] as? [String: Double], let b = browsers[face] else { return }
            let h = container.bounds.height
            b.autoresizingMask = []
            b.frame = NSRect(x: r["x"] ?? 0, y: h - (r["y"] ?? 0) - (r["h"] ?? 0), width: r["w"] ?? 100, height: r["h"] ?? 100)
            container.addSubview(b, positioned: .above, relativeTo: web)    // over the page, exactly on the face's area
            shown = face; window.makeFirstResponder(b)
        case "hide":
            guard let b = browsers[face] else { return }
            b.frame = container.bounds; b.autoresizingMask = [.width, .height]
            container.addSubview(b, positioned: .below, relativeTo: web)
            if shown == face { shown = nil; window.makeFirstResponder(web) }
        case "snap":
            guard let b = browsers[face] else { return }
            let c = WKSnapshotConfiguration(); c.snapshotWidth = 900
            b.takeSnapshot(with: c) { img, _ in
                guard let img = img, let tiff = img.tiffRepresentation, let rep = NSBitmapImageRep(data: tiff),
                      let jpg = rep.representation(using: .jpeg, properties: [.compressionFactor: 0.72]) else { return }
                if let dir = ProcessInfo.processInfo.environment["TDT_SNAPDIR"] {   // testing: keep a copy to look at
                    try? jpg.write(to: URL(fileURLWithPath: dir).appendingPathComponent("face-\(face + 1).jpg"))
                }
                self.tell("webSnap", [face, "data:image/jpeg;base64," + jpg.base64EncodedString(), b.title ?? "", b.url?.absoluteString ?? ""])
            }
        case "nav":
            guard let b = browsers[face], let go = m["go"] as? String else { return }
            if go == "back" { b.goBack() } else if go == "forward" { b.goForward() } else { b.reload() }
        case "close":
            browsers[face]?.removeFromSuperview(); browsers[face] = nil; if shown == face { shown = nil; window.makeFirstResponder(web) }
        default: break
        }
    }
    // after every page load: the page's address bar and the face's title follow along
    func webView(_ w: WKWebView, didFinish nav: WKNavigation!) {
        if let face = browsers.first(where: { $0.value === w })?.key { tell("webNav", [face, w.title ?? "", w.url?.absoluteString ?? "", w.canGoBack, w.canGoForward]) }
    }
    // A page that opens a new window. A sign-in POPUP (Google / Apple / X buttons) must stay linked to the page that opened it (it reports
    // back through window.opener), so it gets a real small window built from the configuration WebKit hands us. A plain link that just
    // wants a new tab (no window size asked for) opens in the same face instead. (Chris 08:42: "will OAuth work… Google login?")
    var popups: [NSWindow] = []
    func webView(_ w: WKWebView, createWebViewWith c: WKWebViewConfiguration, for a: WKNavigationAction, windowFeatures f: WKWindowFeatures) -> WKWebView? {
        if f.width == nil && f.height == nil { if let u = a.request.url { w.load(URLRequest(url: u)) }; return nil }
        let size = NSSize(width: CGFloat(f.width?.doubleValue ?? 520), height: CGFloat(f.height?.doubleValue ?? 680))
        let pw = NSWindow(contentRect: NSRect(origin: .zero, size: size), styleMask: [.titled, .closable, .resizable], backing: .buffered, defer: false)
        let pv = WKWebView(frame: NSRect(origin: .zero, size: size), configuration: c)
        pv.customUserAgent = w.customUserAgent; pv.uiDelegate = self; pv.autoresizingMask = [.width, .height]
        pw.contentView = pv; pw.title = "Sign in"; pw.isReleasedWhenClosed = false; pw.center(); pw.makeKeyAndOrderFront(nil)
        popups.append(pw); return pv
    }
    func webViewDidClose(_ w: WKWebView) {                    // the popup finished (window.close()): take its window away
        if let i = popups.firstIndex(where: { $0.contentView === w }) { popups[i].close(); popups.remove(at: i) }
    }
    // the mic / camera for voice modes: macOS asks Chris once (the reasons are in Info.plist)
    func webView(_ w: WKWebView, requestMediaCapturePermissionFor o: WKSecurityOrigin, initiatedByFrame f: WKFrameInfo,
                 type: WKMediaCaptureType, decisionHandler: @escaping (WKPermissionDecision) -> Void) { decisionHandler(.prompt) }
    @objc func backToCube(_ s: Any?) { web.evaluateJavaScript("fullFace >= 0 && toggleFull()") }   // ⌘⌥↩: works even while a browser has the keyboard

    // The core (server.py, index.html, vendor/) lives OUTSIDE the app, in ~/Library/Application Support/3D Terminal/core (build.sh puts
    // it there). 2026-10-28 Chris: "every time I restart the app it asks like three different 'allow' items". macOS remembers those
    // answers for a self-signed app by a fingerprint of the WHOLE bundle, so every page/server update made it a new app. Now updates
    // only touch that folder and the bundle (this launcher + icon) stays the same. Python with hidapi (Spaceball / PowerMate) is the
    // private venv build.sh makes beside it; without it, plain python3 still runs the cube (keyboard + mouse only).
    func startServer() {
        let support = FileManager.default.homeDirectoryForCurrentUser.appendingPathComponent("Library/Application Support/3D Terminal")
        var core = support.appendingPathComponent("core")
        if !FileManager.default.fileExists(atPath: core.appendingPathComponent("server.py").path) {
            core = Bundle.main.resourceURL!.appendingPathComponent("core")   // older builds kept it inside the app
        }
        let venv = support.appendingPathComponent("venv/bin/python3").path
        let p = Process()
        let me = String(ProcessInfo.processInfo.processIdentifier)   // the server stops itself if this app ever dies
        let script = core.appendingPathComponent("server.py").path
        let port = ProcessInfo.processInfo.environment["TDT_PORT"] ?? "8782"   // (a test copy runs on another port, with TDT_HOME set)
        if FileManager.default.isExecutableFile(atPath: venv) {
            p.executableURL = URL(fileURLWithPath: venv); p.arguments = ["-I", script, "--port", port, "--parent", me]
        } else {
            p.executableURL = URL(fileURLWithPath: "/usr/bin/env"); p.arguments = ["python3", "-I", script, "--port", port, "--parent", me]
        }
        let out = Pipe(); p.standardOutput = out
        do { try p.run() } catch { showError("Couldn't start the cube's server: \(error)"); return }
        server = p
        DispatchQueue.main.asyncAfter(deadline: .now() + 15) {       // still nothing after 15 s: tell the user instead of a black window
            if self.web.url == nil {
                self.showError("3D Terminal's helper didn't start.<br><br>It needs Python 3 (the Xcode command-line tools include it).<br>Quit and reopen to try again.")
            }
        }
        p.terminationHandler = { proc in                             // the helper died while the app is open
            DispatchQueue.main.async { if proc.terminationReason != .exit || proc.terminationStatus != 0 { self.showError("3D Terminal's helper stopped unexpectedly. Quit and reopen to restart it.") } }
        }
        DispatchQueue.global().async {                      // wait for the line with the URL (it carries a per-run key)
            let h = out.fileHandleForReading; var seen = ""
            while true {
                let d = h.availableData; if d.isEmpty { break }
                seen += String(decoding: d, as: UTF8.self)
                if let r = seen.range(of: "http://127.0.0.1:[0-9]+/\\?k=[A-Za-z0-9_-]+", options: .regularExpression),
                   let url = URL(string: String(seen[r])) {
                    DispatchQueue.main.async { self.web.load(URLRequest(url: url)) }
                    while !h.availableData.isEmpty {}       // keep draining so the server never blocks on a full pipe
                    break
                }
            }
        }
    }

    func showError(_ msg: String) {
        web.loadHTMLString("<body style='background:#000;color:#ccc;font:16px Menlo;padding:40px'>\(msg)</body>", baseURL: nil)
    }

    func applicationShouldTerminateAfterLastWindowClosed(_ app: NSApplication) -> Bool { true }
    func applicationWillTerminate(_ note: Notification) { server?.terminate() }
}

let app = NSApplication.shared
let delegate = AppDelegate()
app.delegate = delegate
app.setActivationPolicy(.regular)
let menu = NSMenu()
let appItem = NSMenuItem(); menu.addItem(appItem)
let appMenu = NSMenu(); appMenu.addItem(withTitle: "Quit 3D Terminal", action: #selector(NSApplication.terminate(_:)), keyEquivalent: "q")
appItem.submenu = appMenu
let editItem = NSMenuItem(); menu.addItem(editItem)
let edit = NSMenu(title: "Edit")                                  // (cut / undo too: the mini-browsers' text fields need them)
edit.addItem(withTitle: "Undo", action: Selector(("undo:")), keyEquivalent: "z")
edit.addItem(withTitle: "Cut", action: #selector(NSText.cut(_:)), keyEquivalent: "x")
edit.addItem(withTitle: "Copy", action: #selector(NSText.copy(_:)), keyEquivalent: "c")
edit.addItem(withTitle: "Paste", action: #selector(NSText.paste(_:)), keyEquivalent: "v")
edit.addItem(withTitle: "Select All", action: #selector(NSText.selectAll(_:)), keyEquivalent: "a")
editItem.submenu = edit
let viewItem = NSMenuItem(); menu.addItem(viewItem)
let view = NSMenu(title: "View")
view.addItem(withTitle: "Reload", action: #selector(WKWebView.reload(_:)), keyEquivalent: "r")   // the shells keep running
view.addItem(withTitle: "Enter Full Screen", action: #selector(NSWindow.toggleFullScreen(_:)), keyEquivalent: "f").keyEquivalentModifierMask = [.command, .control]
let back = view.addItem(withTitle: "Back to the Cube", action: #selector(AppDelegate.backToCube(_:)), keyEquivalent: "\r"); back.keyEquivalentModifierMask = [.command, .option]; back.target = delegate
viewItem.submenu = view
app.mainMenu = menu
app.run()
