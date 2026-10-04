import AppKit
import Carbon.HIToolbox
import Foundation
import SwiftUI

// MARK: - configuration store (connectors + sync)

/// Reads/writes the loop's non-secret configuration, in one plain file:
///   ~/Library/Application Support/Plasmie/config.env — VAULT_DIR, PLASMIE_DISABLED_SOURCES and the
///   connector settings (site URL, GitHub orgs, git folders); quoted, spaces-safe.
/// Credentials (tokens, the Atlassian email) live in the login Keychain: see Keychain.swift.
enum ConfigStore {
    static var configEnv: String { PlasmiePaths.config }

    /// Parse KEY=value, tolerating a leading `export ` and single/double quotes.
    static func read(_ path: String) -> [String: String] {
        guard let text = try? String(contentsOfFile: path, encoding: .utf8) else { return [:] }
        var out: [String: String] = [:]
        for raw in text.components(separatedBy: "\n") {
            var line = raw.trimmingCharacters(in: .whitespaces)
            if line.isEmpty || line.hasPrefix("#") { continue }
            if line.hasPrefix("export ") { line = String(line.dropFirst(7)) }
            guard let eq = line.firstIndex(of: "=") else { continue }
            let k = String(line[..<eq]).trimmingCharacters(in: .whitespaces)
            var v = String(line[line.index(after: eq)...]).trimmingCharacters(in: .whitespaces)
            if v.count >= 2, (v.hasPrefix("\"") && v.hasSuffix("\"")) || (v.hasPrefix("'") && v.hasSuffix("'")) {
                v = String(v.dropFirst().dropLast())
            }
            out[k] = v
        }
        return out
    }

    /// Upsert keys, preserving every other line.
    /// Empty value removes the key. `exportPrefix`/`quoted` match each file's style.
    static func upsert(_ path: String, _ kv: [String: String],
                       exportPrefix: Bool, quoted: Bool, perms: Int16? = nil) {
        var lines = (try? String(contentsOfFile: path, encoding: .utf8))?.components(separatedBy: "\n") ?? []
        func matches(_ line: String, _ k: String) -> Bool {
            let t = line.trimmingCharacters(in: .whitespaces)
            return t.hasPrefix("\(k)=") || t.hasPrefix("export \(k)=")
        }
        for (k, v) in kv {
            lines.removeAll { matches($0, k) }        // drop any existing definition
            if !v.isEmpty {
                // Single quotes: bash sources this file, so "$(...)" or a backtick typed into
                // a field must stay text. An apostrophe is written as '\'' (shell-standard).
                let safe = "'" + v.replacingOccurrences(of: "'", with: "'\\''").replacingOccurrences(of: "\n", with: " ") + "'"
                lines.append((exportPrefix ? "export " : "") + k + "=" + (quoted ? safe : v))
            }
        }
        var out = lines.joined(separator: "\n").trimmingCharacters(in: .newlines)
        out += "\n"
        try? out.write(toFile: path, atomically: true, encoding: .utf8)
        if let p = perms { try? FileManager.default.setAttributes([.posixPermissions: p], ofItemAtPath: path) }
    }
}

// MARK: - settings / first-run connector wizard

/// Shared between the window delegate and the view, so closing the window (red
/// button, Esc, ⌘W, Close) can ask the view whether there is anything unsaved.
final class SettingsState {
    var isDirty: () -> Bool = { false }
    var save: () -> Void = {}
}

/// Shows the settings window. `firstRun` gives it a welcome header + "Finish"
/// button; the menu opens it in plain edit mode.
final class SettingsController: NSObject, NSWindowDelegate {
    static let shared = SettingsController()
    private var win: NSWindow?
    private let state = SettingsState()
    var isOpen: Bool { win?.isVisible == true }

    /// The Plasmie window: everything the menu had (status, Run / Open / Maintain, held items)
    /// on the left, settings and connectors on the right. First run shows settings alone.
    func show(firstRun: Bool = false) {
        if let w = win { bringForward(w); return }
        let settings = SettingsView(
            firstRun: firstRun, state: state,
            onDone: { [weak self] in self?.win?.close() },
            onRequestClose: { [weak self] in self?.win?.performClose(nil) })
        let side: CGFloat = firstRun ? 0 : 320
        let w = NSWindow(contentRect: NSRect(x: 0, y: 0, width: 560 + side, height: 680),
                         styleMask: [.titled, .closable, .resizable], backing: .buffered, defer: false)
        w.title = firstRun ? "Set up connectors" : "Plasmie"
        w.center(); w.isReleasedWhenClosed = false
        w.contentMinSize = NSSize(width: 520 + side, height: 560)
        w.delegate = self
        w.contentView = firstRun ? NSHostingView(rootView: AnyView(settings)) : NSHostingView(rootView: AnyView(
            HStack(spacing: 0) {
                ScrollView { Panel(m: .shared, inWindow: true).padding(.top, 6) }
                    .frame(width: side)
                    .background(SidebarMaterial().ignoresSafeArea())
                Divider()
                settings
            }))
        win = w
        bringForward(w)
    }

    /// Unsaved edits get a Save / Discard / Cancel choice instead of vanishing.
    func windowShouldClose(_ sender: NSWindow) -> Bool {
        guard state.isDirty() else { return true }
        let alert = NSAlert()
        alert.messageText = "Save changes before closing?"
        alert.informativeText = "Unsaved token and field changes will be lost."
        alert.addButton(withTitle: "Save")                    // default, rightmost
        alert.addButton(withTitle: "Cancel")                  // Esc
        let dontSave = alert.addButton(withTitle: "Don\u{2019}t Save")   // leftmost per HIG
        dontSave.keyEquivalent = "d"
        dontSave.keyEquivalentModifierMask = .command
        dontSave.hasDestructiveAction = true
        switch alert.runModal() {
        case .alertFirstButtonReturn: state.save(); return true
        case .alertThirdButtonReturn: return true
        default: return false
        }
    }

    func windowWillClose(_ notification: Notification) {
        win?.delegate = nil
        win = nil
    }
}

/// The native sidebar backdrop, so the status column reads as the window's sidebar.
private struct SidebarMaterial: NSViewRepresentable {
    func makeNSView(context: Context) -> NSVisualEffectView {
        let v = NSVisualEffectView()
        v.material = .sidebar; v.blendingMode = .behindWindow; v.state = .followsWindowActiveState
        return v
    }
    func updateNSView(_ v: NSVisualEffectView, context: Context) {}
}

/// One config UI, two roles: the first-run connector wizard and the editable
/// settings window. Secrets are never loaded back into the UI — a blank token
/// field keeps the existing value; you only ever type a *new* one.
struct SettingsView: View {
    let firstRun: Bool
    let state: SettingsState
    let onDone: () -> Void
    let onRequestClose: () -> Void

    @StateObject private var conn = ConnectorsModel()
    @FocusState private var vaultFocused: Bool
    @AppStorage(NotchPrefs.key) private var notchOn = true


    /// The non-secret fields as `load()` last read them — the dirty baseline.
    private struct Fields: Equatable {
        var vaultDir = "", jiraBase = "", jiraEmail = "", githubOrgs = "", gitRoots = ""
    }
    @State private var baseline = Fields()

    // non-secret (prefilled)
    @State private var vaultDir = ""
    @State private var jiraBase = ""
    @State private var jiraEmail = ""
    @State private var githubOrgs = ""
    @State private var gitRoots = ""
    // secret (write-only — blank means "keep")
    @State private var slackToken = ""
    @State private var githubToken = ""
    @State private var jiraToken = ""
    // transient
    @State private var saved = false
    @State private var saveError = ""
    @State private var outlookLog = ""
    @State private var connecting = false

    private var current: Fields {
        Fields(vaultDir: vaultDir, jiraBase: jiraBase, jiraEmail: jiraEmail, githubOrgs: githubOrgs, gitRoots: gitRoots)
    }
    private var dirty: Bool { current != baseline || !slackToken.isEmpty || !jiraToken.isEmpty || !githubToken.isEmpty }

    var body: some View {
        VStack(spacing: 0) {
            if firstRun {
                titleBar
                Divider()
            }
            ScrollView {
                VStack(alignment: .leading, spacing: 28) {
                    connectorsPage
                    vaultPage
                    VStack(alignment: .leading, spacing: 6) {
                        Toggle("Plasmie in the notch", isOn: $notchOn).font(.klBody)
                        Text("Plasmie lives beside the notch and opens on hover, with Ask inside it. It replaces the menu-bar icon; turn this off to bring the icon back.").klNote()
                    }
                }
                .padding(.horizontal, 20).padding(.top, 20).padding(.bottom, 32)
            }
            Divider()
            footer
        }
        .frame(minWidth: 520, minHeight: 560)
        .background(shortcuts)
        .onAppear {
            load(); conn.refresh()
            migrateThenReload()
            // First run lands focus on content, not on the buttons. The everyday Plasmie window
            // focuses no field: it can come forward while you're typing elsewhere, and stray
            // keystrokes must not edit the vault path.
            if firstRun { DispatchQueue.main.async { vaultFocused = true } }
            state.isDirty = { dirty }
            state.save = { save() }
        }
    }

    // MARK: header / footer

    private var titleBar: some View {
        VStack(alignment: .leading, spacing: 6) {
            HStack(spacing: 10) {
                InteractivePlasmie(state: .idle, size: 52)
                Text("Set up your connectors").font(.klTitle)
                Spacer()
            }
            if firstRun {
                Text("Every connector starts off. Switch on the ones you want Plasmie to pull into your vault; you can change this any time from the menu.")
                    .klNote()
            }
        }
        .padding(.horizontal, 20).padding(.top, 18).padding(.bottom, 12)
    }

    private var footer: some View {
        HStack {
            if !saveError.isEmpty {
                Text(saveError).font(.klMeta).foregroundStyle(.red)
            } else if dirty {
                Text("Unsaved changes").font(.klMeta).foregroundStyle(.orange)
            } else if saved {
                Text("Saved ✓").font(.klMeta).foregroundStyle(.green)
            }
            Spacer()
            if !firstRun { Button("Close") { onRequestClose() } }
            Button(firstRun ? "Finish" : "Save") { save(); if firstRun { onDone() } }
                .keyboardShortcut(.defaultAction)
                .disabled(!firstRun && !dirty)
        }
        .padding(.horizontal, 20).padding(.vertical, 12)
    }

    /// Invisible buttons that carry the window shortcuts: ⌘S, and Esc / ⌘W both
    /// through the same dirty check as the Close button.
    private var shortcuts: some View {
        ZStack {
            Button("Save") { if dirty { save() } }.keyboardShortcut("s", modifiers: .command)
            Button("Close") { onRequestClose() }.keyboardShortcut("w", modifiers: .command)
            Button("Cancel") { onRequestClose() }.keyboardShortcut(.cancelAction)
        }
        .opacity(0).allowsHitTesting(false).accessibilityHidden(true)
    }

    // MARK: connectors section

    private var connectorsPage: some View {
        VStack(alignment: .leading, spacing: 12) {
            Text("Connectors").font(.klHeading)
            ConnectorsSummary(conn: conn)
            ForEach(Connector.all) { c in card(for: c) }
            Text("On/Off switches apply immediately; token and field changes apply on Save. Both take effect from the next hourly ingest. Use Test to check a connector right now.")
                .klNote()
        }
    }

    @ViewBuilder private func card(for c: Connector) -> some View {
        switch c.id {
        case "slack":
            ConnectorCard(c: c, m: conn, onDisconnect: { disconnect(["SLACK_USER_TOKEN"]) }) {
                SecureField(conn.health["slack"]?.configured == true
                            ? "Connected — paste a new token to replace"
                            : "Paste SLACK_USER_TOKEN (xoxp-…)", text: $slackToken)
                    .textFieldStyle(.roundedBorder)
            }
        case "github":
            ConnectorCard(c: c, m: conn, onDisconnect: { disconnect(["GITHUB_TOKEN"]) }) {
                SecureField(conn.health["github"]?.configured == true
                            ? "Connected — paste a new token to replace"
                            : "Paste a GitHub token (github_pat_… or ghp_…)", text: $githubToken)
                    .textFieldStyle(.roundedBorder)
                labeled("Organisations (comma-separated, optional)") {
                    TextField("Blank = all your activity, or e.g. my-org, other-org", text: $githubOrgs)
                        .textFieldStyle(.roundedBorder)
                }
                Text("Make a fine-grained token at github.com › Settings › Developer settings with read-only access; Plasmie only reads your issues and pull requests. List organisations to narrow it; one you aren't a member of fails every run, and Test names it.")
                    .klNote()
            }
        case "git":
            ConnectorCard(c: c, m: conn, onDisconnect: nil) {
                labeled("Folders to scan (comma-separated)") {
                    TextField("e.g. ~/code, ~/Developer", text: $gitRoots).textFieldStyle(.roundedBorder)
                }
                Text("Only commits authored by you, with a real explanation in the message — one-liners and mechanical chores are filtered out.")
                    .klNote()
            }
        case "confluence":
            ConnectorCard(c: c, m: conn, onDisconnect: { disconnect(["JIRA_API_TOKEN", "CONFLUENCE_API_TOKEN"]) }) {
                labeled("Site URL") { TextField("https://your-site.atlassian.net", text: $jiraBase).textFieldStyle(.roundedBorder) }
                labeled("Email") { TextField("you@company.com", text: $jiraEmail).textFieldStyle(.roundedBorder) }
                SecureField(conn.health["confluence"]?.configured == true
                            ? "Connected — paste a new API token to replace"
                            : "Atlassian API token", text: $jiraToken)
                    .textFieldStyle(.roundedBorder)
            }
        case "outlook":
            ConnectorCard(c: c, m: conn, onDisconnect: { disconnect(["MS_REFRESH_TOKEN"]) }) {
                HStack {
                    Button(connecting ? "Connecting…" : (conn.health["outlook"]?.configured == true ? "Reconnect" : "Connect Outlook")) {
                        connectOutlook()
                    }
                    .disabled(connecting)
                    Spacer()
                }
                if !outlookLog.isEmpty {
                    Text(outlookLog).font(.klMono)
                        .foregroundStyle(.secondary).textSelection(.enabled)
                        .fixedSize(horizontal: false, vertical: true)
                }
            }
        default:
            ConnectorCard(c: c, m: conn, onDisconnect: nil) { EmptyView() }
        }
    }

    // MARK: vault section

    private var vaultPage: some View {
        VStack(alignment: .leading, spacing: 12) {
            Text("Vault").font(.klHeading)
            labeled("Vault folder") { TextField("~/knowledge", text: $vaultDir).textFieldStyle(.roundedBorder).focused($vaultFocused) }
            Text("Keep the vault on local disk. Background jobs cannot read from iCloud/OneDrive folders.")
                .klNote()
            Text("Where things live").font(.klLabel).foregroundStyle(.secondary).padding(.top, 4)
            Grid(alignment: .leading, horizontalSpacing: 10, verticalSpacing: 6) {
                pathRow("Data", PlasmiePaths.home)
                pathRow("Logs", PlasmiePaths.logs)
                keychainRow
            }
        }
    }

    private func pathRow(_ label: String, _ path: String) -> some View {
        GridRow {
            Text(label).font(.klMeta).foregroundStyle(.secondary)
            Text(path).font(.klMono).textSelection(.enabled)
                .lineLimit(1).truncationMode(.middle).help(path)
                .frame(maxWidth: .infinity, alignment: .leading)
            Button {
                var isDir: ObjCBool = false
                let target = FileManager.default.fileExists(atPath: path, isDirectory: &isDir) && isDir.boolValue
                    ? path : (path as NSString).deletingLastPathComponent
                openExternal(target)
            } label: { Image(systemName: "folder") }
                .buttonStyle(.borderless)
                .accessibilityLabel("Show \(label) in Finder")
                .help("Show \(label) in Finder")
        }
    }

    /// Credentials aren't a file: point at Keychain Access, where the "Plasmie" items live.
    private var keychainRow: some View {
        GridRow {
            Text("Secrets").font(.klMeta).foregroundStyle(.secondary)
            Text("Login Keychain, items named \u{201C}\(Keychain.service)\u{201D}").font(.klMono)
                .frame(maxWidth: .infinity, alignment: .leading)
            Button {
                if let app = NSWorkspace.shared.urlForApplication(withBundleIdentifier: "com.apple.keychainaccess") {
                    NSWorkspace.shared.openApplication(at: app, configuration: .init())
                }
            } label: { Image(systemName: "key") }
                .buttonStyle(.borderless)
                .accessibilityLabel("Open Keychain Access")
                .help("Open Keychain Access")
        }
    }

    // MARK: helpers

    @ViewBuilder private func labeled<C: View>(_ label: String, @ViewBuilder _ content: () -> C) -> some View {
        VStack(alignment: .leading, spacing: 2) {
            Text(label).font(.klMeta).foregroundStyle(.secondary)
            content()
        }
    }

    private func load() {
        let cfg = ConfigStore.read(ConfigStore.configEnv)
        vaultDir = cfg["VAULT_DIR"] ?? "\(NSHomeDirectory())/knowledge"
        jiraBase = cfg["JIRA_BASE_URL"] ?? ""
        githubOrgs = cfg["PLASMIE_GITHUB_ORGS"] ?? ""
        gitRoots = cfg["PLASMIE_GIT_ROOTS"] ?? ""
        baseline = current
        DispatchQueue.global().async {               // the email is a credential: Keychain
            let email = Keychain.get("JIRA_EMAIL") ?? ""
            DispatchQueue.main.async {
                if jiraEmail == baseline.jiraEmail { jiraEmail = email }
                baseline.jiraEmail = email
            }
        }
    }

    /// An install from before the Keychain moves its ~/.claude/.env values over once
    /// (keychain.py; a no-op afterwards). Reload so the fields show what it brought.
    private func migrateThenReload() {
        let py = "\(PlasmiePaths.home)/venv/bin/python3"
        guard FileManager.default.isExecutableFile(atPath: py) else { return }
        DispatchQueue.global().async {
            _ = runCapture(py, [PlasmiePaths.script("keychain.py"), "migrate"])
            DispatchQueue.main.async { if !dirty { load() } }
        }
    }

    private func save() {
        // Settings → config.env (exported to every job by plasmie-env.sh). Only fields that
        // changed are written, so a value another process just wrote isn't clobbered.
        let trim = { (s: String) in s.trimmingCharacters(in: .whitespaces) }
        let now = current, was = baseline
        var cfg: [String: String] = [:]
        if now.vaultDir != was.vaultDir { cfg["VAULT_DIR"] = trim(now.vaultDir) }
        if now.jiraBase != was.jiraBase { cfg["JIRA_BASE_URL"] = trim(now.jiraBase) }
        if now.githubOrgs != was.githubOrgs { cfg["PLASMIE_GITHUB_ORGS"] = trim(now.githubOrgs) }
        if now.gitRoots != was.gitRoots { cfg["PLASMIE_GIT_ROOTS"] = trim(now.gitRoots) }
        if !cfg.isEmpty { ConfigStore.upsert(ConfigStore.configEnv, cfg, exportPrefix: false, quoted: true) }

        // Credentials → Keychain, off the main thread (each is a `security` call).
        var put: [String: String] = [:]
        var drop: [String] = []
        if !slackToken.isEmpty { put["SLACK_USER_TOKEN"] = trim(slackToken) }
        if !githubToken.isEmpty { put["GITHUB_TOKEN"] = trim(githubToken) }
        if !jiraToken.isEmpty { put["JIRA_API_TOKEN"] = trim(jiraToken) }
        if now.jiraEmail != was.jiraEmail {
            if trim(now.jiraEmail).isEmpty { drop.append("JIRA_EMAIL") } else { put["JIRA_EMAIL"] = trim(now.jiraEmail) }
        }
        saveError = ""
        DispatchQueue.global().async {
            var failure: String?
            for (k, v) in put {
                do { try Keychain.set(k, v) } catch { failure = error.localizedDescription }
            }
            drop.forEach(Keychain.delete)
            DispatchQueue.main.async {
                if let failure { saveError = failure } else { slackToken = ""; jiraToken = ""; githubToken = "" }
                load()
                saved = failure == nil
                conn.refresh()
                DispatchQueue.main.asyncAfter(deadline: .now() + 2) { saved = false }
            }
        }
    }

    /// Removes the credentials from the Keychain, so this really disconnects rather
    /// than blanking a field in the UI only.
    private func disconnect(_ keys: [String]) {
        DispatchQueue.global().async {
            keys.forEach(Keychain.delete)
            DispatchQueue.main.async { conn.refresh() }
        }
    }

    /// Device-code login (msgraph.py) — streams the "open this URL, enter this code"
    /// message; on success the script stores MS_REFRESH_TOKEN in the Keychain.
    private func connectOutlook() {
        connecting = true; outlookLog = "Starting…"
        runStreaming(PlasmiePaths.python, [PlasmiePaths.script("msgraph.py"), "login"],
            onStatus: { _ in },
            onChunk: { full in outlookLog = full.trimmingCharacters(in: .whitespacesAndNewlines) },
            onDone: { connecting = false; conn.refresh(["outlook"]) })
    }
}
