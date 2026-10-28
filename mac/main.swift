// 3D Terminal for macOS — a small native window around Session Cube's shared core (server.py + index.html), so Mac and Linux
// share one cube and only this launcher is Mac-specific. Starts the server on port 8782, shows the page, stops the server on quit
// (which ends every shell on the cube). Lyra for Chris, 2026-10-27.
import AppKit
import WebKit

final class AppDelegate: NSObject, NSApplicationDelegate {
    var window: NSWindow!
    var web: WKWebView!
    var server: Process?

    func applicationDidFinishLaunching(_ note: Notification) {
        web = WKWebView(frame: .zero, configuration: WKWebViewConfiguration())
        window = NSWindow(contentRect: NSRect(x: 0, y: 0, width: 1400, height: 900),
                          styleMask: [.titled, .closable, .resizable, .miniaturizable], backing: .buffered, defer: false)
        window.title = "3D Terminal"
        window.backgroundColor = .black
        window.collectionBehavior = [.fullScreenPrimary]
        window.contentView = web
        window.center()
        window.makeKeyAndOrderFront(nil)
        NSApp.activate(ignoringOtherApps: true)
        startServer()
    }

    // The core lives in the app's Resources/core. Python with hidapi (for the Spaceball / PowerMate) is the private venv that
    // build.sh makes; without it, plain python3 still runs the cube (keyboard + mouse only).
    func startServer() {
        let core = Bundle.main.resourceURL!.appendingPathComponent("core")
        let venv = FileManager.default.homeDirectoryForCurrentUser
            .appendingPathComponent("Library/Application Support/3D Terminal/venv/bin/python3").path
        let p = Process()
        let script = core.appendingPathComponent("server.py").path
        if FileManager.default.isExecutableFile(atPath: venv) {
            p.executableURL = URL(fileURLWithPath: venv); p.arguments = ["-I", script, "--port", "8782"]
        } else {
            p.executableURL = URL(fileURLWithPath: "/usr/bin/env"); p.arguments = ["python3", "-I", script, "--port", "8782"]
        }
        let out = Pipe(); p.standardOutput = out
        do { try p.run() } catch { showError("Couldn't start the cube's server: \(error)"); return }
        server = p
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
let edit = NSMenu(title: "Edit")
edit.addItem(withTitle: "Copy", action: #selector(NSText.copy(_:)), keyEquivalent: "c")
edit.addItem(withTitle: "Paste", action: #selector(NSText.paste(_:)), keyEquivalent: "v")
edit.addItem(withTitle: "Select All", action: #selector(NSText.selectAll(_:)), keyEquivalent: "a")
editItem.submenu = edit
let viewItem = NSMenuItem(); menu.addItem(viewItem)
let view = NSMenu(title: "View")
view.addItem(withTitle: "Enter Full Screen", action: #selector(NSWindow.toggleFullScreen(_:)), keyEquivalent: "f").keyEquivalentModifierMask = [.command, .control]
viewItem.submenu = view
app.mainMenu = menu
app.run()
