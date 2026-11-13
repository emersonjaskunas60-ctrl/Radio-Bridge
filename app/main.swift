import Cocoa

// Menu bar app that starts and stops bridge.py and flips its two switches.

// The app lives in the project folder, next to bridge.py.
let bridgeDir = Bundle.main.bundleURL.deletingLastPathComponent().path

// Apps launched from Finder don't get the shell's PATH, so look in the usual places.
let pythonPath: String = {
    let candidates = [
        "/Library/Frameworks/Python.framework/Versions/Current/bin/python3",
        "/opt/homebrew/bin/python3",
        "/usr/local/bin/python3",
        "/usr/bin/python3",
    ]
    return candidates.first { FileManager.default.isExecutableFile(atPath: $0) } ?? "/usr/bin/python3"
}()
let settingsPath = bridgeDir + "/settings.json"
let logPath = bridgeDir + "/bridge.log"

final class AppDelegate: NSObject, NSApplicationDelegate, NSMenuDelegate {
    var statusItem: NSStatusItem!
    var process: Process?
    var savePlaylist = true
    var addQueue = true

    let stateItem = NSMenuItem(title: "", action: nil, keyEquivalent: "")
    let toggleItem = NSMenuItem(title: "", action: #selector(toggleRunning), keyEquivalent: "s")
    let playlistItem = NSMenuItem(title: "Save songs to playlist", action: #selector(togglePlaylist), keyEquivalent: "")
    let queueItem = NSMenuItem(title: "Add songs to Up Next", action: #selector(toggleQueue), keyEquivalent: "")
    let lastItem = NSMenuItem(title: "", action: nil, keyEquivalent: "")

    var running: Bool { process?.isRunning ?? false }

    func applicationDidFinishLaunching(_ note: Notification) {
        loadSettings()
        statusItem = NSStatusBar.system.statusItem(withLength: NSStatusItem.variableLength)
        let menu = NSMenu()
        menu.delegate = self
        menu.autoenablesItems = false
        stateItem.isEnabled = false
        lastItem.isEnabled = false
        for item in [toggleItem, playlistItem, queueItem] { item.target = self }
        menu.addItem(stateItem)
        menu.addItem(toggleItem)
        menu.addItem(.separator())
        menu.addItem(playlistItem)
        menu.addItem(queueItem)
        menu.addItem(.separator())
        menu.addItem(lastItem)
        let logItem = NSMenuItem(title: "Open Log", action: #selector(openLog), keyEquivalent: "l")
        logItem.target = self
        menu.addItem(logItem)
        menu.addItem(.separator())
        let quit = NSMenuItem(title: "Quit Radio Bridge", action: #selector(quit), keyEquivalent: "q")
        quit.target = self
        menu.addItem(quit)
        statusItem.menu = menu
        if CommandLine.arguments.contains("--start") { start() }
        refresh()
    }

    func applicationWillTerminate(_ note: Notification) {
        stop()
    }

    func menuWillOpen(_ menu: NSMenu) {
        refresh()
    }

    // MARK: settings

    func loadSettings() {
        guard let data = FileManager.default.contents(atPath: settingsPath),
              let obj = try? JSONSerialization.jsonObject(with: data) as? [String: Any] else {
            saveSettings()
            return
        }
        savePlaylist = obj["playlist"] as? Bool ?? true
        addQueue = obj["queue"] as? Bool ?? true
    }

    func saveSettings() {
        let obj: [String: Any] = ["playlist": savePlaylist, "queue": addQueue]
        if let data = try? JSONSerialization.data(withJSONObject: obj, options: [.prettyPrinted]) {
            try? data.write(to: URL(fileURLWithPath: settingsPath), options: .atomic)
        }
    }

    // MARK: actions

    @objc func toggleRunning() {
        if running { stop() } else { start() }
        refresh()
    }

    @objc func togglePlaylist() {
        savePlaylist.toggle()
        saveSettings()
        refresh()
    }

    @objc func toggleQueue() {
        addQueue.toggle()
        saveSettings()
        refresh()
    }

    @objc func openLog() {
        NSWorkspace.shared.open(URL(fileURLWithPath: logPath))
    }

    @objc func quit() {
        NSApp.terminate(nil)
    }

    func start() {
        guard !running else { return }
        let p = Process()
        p.executableURL = URL(fileURLWithPath: pythonPath)
        p.arguments = ["-u", bridgeDir + "/bridge.py", "--settings", settingsPath]
        p.currentDirectoryURL = URL(fileURLWithPath: bridgeDir)
        p.standardOutput = FileHandle.nullDevice
        p.standardError = FileHandle.nullDevice
        p.terminationHandler = { [weak self] _ in
            DispatchQueue.main.async { self?.refresh() }
        }
        do {
            try p.run()
            process = p
        } catch {
            let alert = NSAlert()
            alert.messageText = "Could not start the bridge"
            alert.informativeText = error.localizedDescription
            alert.runModal()
        }
    }

    func stop() {
        guard let p = process, p.isRunning else { return }
        p.interrupt()
        process = nil
    }

    // MARK: display

    func lastLogLine() -> String {
        guard let handle = FileHandle(forReadingAtPath: logPath) else { return "No activity yet" }
        defer { try? handle.close() }
        let size = handle.seekToEndOfFile()
        handle.seek(toFileOffset: size > 2000 ? size - 2000 : 0)
        let text = String(decoding: handle.readDataToEndOfFile(), as: UTF8.self)
        guard let line = text.split(separator: "\n").last else { return "No activity yet" }
        // Drop the date, keep the time and message, and keep the menu a sane width.
        let trimmed = line.count > 11 ? String(line.dropFirst(11)) : String(line)
        return trimmed.count > 70 ? String(trimmed.prefix(70)) + "…" : trimmed
    }

    func refresh() {
        let on = running
        stateItem.title = on ? "Bridge is on" : "Bridge is off"
        toggleItem.title = on ? "Turn Off" : "Turn On"
        playlistItem.state = savePlaylist ? .on : .off
        queueItem.state = addQueue ? .on : .off
        lastItem.title = lastLogLine()
        if let button = statusItem.button {
            button.image = bridgeIcon(on: on)
            button.toolTip = on ? "Radio Bridge: on" : "Radio Bridge: off"
        }
    }
}

// Menu bar icon: an arch bridge. Solid when the bridge is on, faded when it is off.
func drawBridge(on: Bool) {
    // Fade the whole drawing as one layer, so overlapping lines don't show darker joints.
    let ctx = NSGraphicsContext.current!.cgContext
    ctx.saveGState()
    ctx.setAlpha(on ? 1.0 : 0.35)
    ctx.beginTransparencyLayer(auxiliaryInfo: nil)
    defer {
        ctx.endTransparencyLayer()
        ctx.restoreGState()
    }
    NSColor.black.setStroke()

    let frame = NSBezierPath()
    frame.lineWidth = 1.7
    frame.lineCapStyle = .round
    frame.lineJoinStyle = .round
    frame.move(to: NSPoint(x: 1.5, y: 5.5))      // deck
    frame.line(to: NSPoint(x: 20.5, y: 5.5))
    frame.move(to: NSPoint(x: 3, y: 5.5))        // arch
    frame.curve(to: NSPoint(x: 19, y: 5.5),
                controlPoint1: NSPoint(x: 6.5, y: 16.8),
                controlPoint2: NSPoint(x: 15.5, y: 16.8))
    frame.move(to: NSPoint(x: 3, y: 5.5))        // legs
    frame.line(to: NSPoint(x: 3, y: 2.5))
    frame.move(to: NSPoint(x: 19, y: 5.5))
    frame.line(to: NSPoint(x: 19, y: 2.5))
    frame.stroke()

    let cables = NSBezierPath()
    cables.lineWidth = 1.1
    cables.lineCapStyle = .round
    for (x, top) in [(7.3, 12.0), (11.0, 13.4), (14.7, 12.0)] {
        cables.move(to: NSPoint(x: x, y: 5.5))
        cables.line(to: NSPoint(x: x, y: top))
    }
    cables.stroke()
}

func bridgeIcon(on: Bool) -> NSImage {
    let image = NSImage(size: NSSize(width: 22, height: 18), flipped: false) { _ in
        drawBridge(on: on)
        return true
    }
    image.isTemplate = true
    image.accessibilityDescription = "Radio Bridge"
    return image
}

// `RadioBridge --render-icon <folder>` writes enlarged previews of both states and exits.
if let i = CommandLine.arguments.firstIndex(of: "--render-icon"), CommandLine.arguments.count > i + 1 {
    let scale = 16
    for on in [true, false] {
        let rep = NSBitmapImageRep(bitmapDataPlanes: nil, pixelsWide: 22 * scale, pixelsHigh: 18 * scale,
                                   bitsPerSample: 8, samplesPerPixel: 4, hasAlpha: true, isPlanar: false,
                                   colorSpaceName: .deviceRGB, bytesPerRow: 0, bitsPerPixel: 0)!
        NSGraphicsContext.saveGraphicsState()
        NSGraphicsContext.current = NSGraphicsContext(bitmapImageRep: rep)
        NSColor.white.setFill()
        NSRect(x: 0, y: 0, width: 22 * scale, height: 18 * scale).fill()
        let t = NSAffineTransform()
        t.scale(by: CGFloat(scale))
        t.concat()
        drawBridge(on: on)
        NSGraphicsContext.restoreGraphicsState()
        let path = CommandLine.arguments[i + 1] + (on ? "/icon-on.png" : "/icon-off.png")
        try? rep.representation(using: .png, properties: [:])?.write(to: URL(fileURLWithPath: path))
    }
    exit(0)
}

let app = NSApplication.shared
let delegate = AppDelegate()
app.delegate = delegate
app.setActivationPolicy(.accessory)
app.run()
