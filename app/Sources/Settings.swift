import AppKit
import Carbon.HIToolbox
import Foundation
import SwiftUI

// MARK: - configuration store (connectors + sync)

/// Reads/writes the loop's configuration, which lives in two plain files:
///   ~/.plasmie/config.env  — VAULT_DIR, PLASMIE_DISABLED_SOURCES (quoted, spaces-safe)
///   ~/.claude/.env                — connector secrets, SHARED with other tools; we
///                                   upsert only our own keys and preserve the rest.
enum ConfigStore {
    static var home: String { NSHomeDirectory() }
    static var configEnv: String { "\(home)/.plasmie/config.env" }
    static var dotEnv: String { "\(home)/.claude/.env" }

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

    /// Upsert keys, preserving every other line (critical for the shared .env).
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
                lines.append((exportPrefix ? "export " : "") + k + "=" + (quoted ? "\"\(v)\"" : v))
            }
        }
        var out = lines.joined(separator: "\n").trimmingCharacters(in: .newlines)
        out += "\n"
        try? out.write(toFile: path, atomically: true, encoding: .utf8)
        if let p = perms { try? FileManager.default.setAttributes([.posixPermissions: p], ofItemAtPath: path) }
    }
}

// MARK: - settings / first-run connector wizard

/// Shows the settings window. `firstRun` gives it a welcome header + "Finish"
/// button; the menu opens it in plain edit mode.
final class SettingsController {
    static let shared = SettingsController()
    private var win: NSWindow?
    func show(firstRun: Bool = false) {
        if let w = win { NSApp.activate(ignoringOtherApps: true); w.makeKeyAndOrderFront(nil); return }
        let w = NSWindow(contentRect: NSRect(x: 0, y: 0, width: 560, height: 680),
                         styleMask: [.titled, .closable], backing: .buffered, defer: false)
        w.title = firstRun ? "Set up connectors" : "Plasmie Settings"
        w.center(); w.isReleasedWhenClosed = false; w.level = .floating
        w.contentView = NSHostingView(rootView: SettingsView(firstRun: firstRun) { [weak self] in
            self?.win?.orderOut(nil); self?.win = nil
        })
        win = w
        NSApp.activate(ignoringOtherApps: true)
        w.makeKeyAndOrderFront(nil)
    }
}

/// One config UI, two roles: the first-run connector wizard and the editable
/// settings window. Secrets are never loaded back into the UI — a blank token
/// field keeps the existing value; you only ever type a *new* one.
struct SettingsView: View {
    let firstRun: Bool
    let onDone: () -> Void

    @StateObject private var conn = ConnectorsModel()
    @State private var tab = 0

    private var loop: String { "\(NSHomeDirectory())/.plasmie" }

    // non-secret (prefilled)
    @State private var vaultDir = ""
    @State private var jiraBase = ""
    @State private var jiraEmail = ""
    @State private var githubOrgs = ""
    @State private var gitRoots = ""
    // secret (write-only — blank means "keep")
    @State private var slackToken = ""
    @State private var jiraToken = ""
    // transient
    @State private var saved = false
    @State private var outlookLog = ""
    @State private var connecting = false

    var body: some View {
        VStack(spacing: 0) {
            titleBar
            Picker("", selection: $tab) {
                Text("Connectors").tag(0)
                Text("Vault").tag(1)
            }
            .pickerStyle(.segmented).labelsHidden()
            .padding(.horizontal, 20).padding(.bottom, 12)
            Divider()
            ScrollView {
                Group {
                    if tab == 0 { connectorsPage } else { vaultPage }
                }
                .padding(20)
            }
            Divider()
            footer
        }
        .frame(width: 560, height: 680)
        .onAppear { load(); conn.refresh() }
    }

    // MARK: header / footer

    private var titleBar: some View {
        VStack(alignment: .leading, spacing: 6) {
            HStack(spacing: 10) {
                Image(nsImage: kLogo)
                Text(firstRun ? "Set up your connectors" : "Settings")
                    .font(.system(size: 16, weight: .semibold))
                Spacer()
            }
            if firstRun {
                Text("Choose what Plasmie pulls into your vault. Everything here is optional and can be changed later from the menu.")
                    .font(.system(size: 12)).foregroundStyle(.secondary)
                    .fixedSize(horizontal: false, vertical: true)
            }
        }
        .padding(.horizontal, 20).padding(.top, 18).padding(.bottom, 12)
    }

    private var footer: some View {
        HStack {
            if saved { Text("Saved ✓").font(.caption).foregroundStyle(.green) }
            Spacer()
            Button(firstRun ? "Finish" : "Save") { save(); if firstRun { onDone() } }
                .keyboardShortcut(.defaultAction)
            if !firstRun { Button("Close") { onDone() } }
        }
        .padding(.horizontal, 20).padding(.vertical, 12)
    }

    // MARK: connectors page

    private var connectorsPage: some View {
        VStack(alignment: .leading, spacing: 12) {
            ConnectorsSummary(conn: conn)
            ForEach(Connector.all) { c in card(for: c) }
            Text("On/Off switches apply immediately; token changes on Save. Both take effect from the next hourly ingest. Use Test to check a connector right now.")
                .font(.system(size: 10.5)).foregroundStyle(.secondary)
        }
    }

    @ViewBuilder private func card(for c: Connector) -> some View {
        switch c.id {
        case "slack":
            ConnectorCard(c: c, m: conn, onDisconnect: { disconnect(["SLACK_USER_TOKEN": ""]) }) {
                SecureField(conn.health["slack"]?.configured == true
                            ? "Connected — paste a new token to replace"
                            : "Paste SLACK_USER_TOKEN (xoxp-…)", text: $slackToken)
                    .textFieldStyle(.roundedBorder)
            }
        case "github":
            ConnectorCard(c: c, m: conn, onDisconnect: nil) {
                labeled("Organisations (comma-separated)") {
                    TextField("fabrikam", text: $githubOrgs).textFieldStyle(.roundedBorder)
                }
                Text("Signed in with the `gh` CLI. An org you are not a member of fails every run — Test names it.")
                    .font(.system(size: 10.5)).foregroundStyle(.secondary)
                    .fixedSize(horizontal: false, vertical: true)
            }
        case "git":
            ConnectorCard(c: c, m: conn, onDisconnect: nil) {
                labeled("Folders to scan (comma-separated)") {
                    TextField("~/code", text: $gitRoots).textFieldStyle(.roundedBorder)
                }
                Text("Only commits authored by you, with a real explanation in the message — one-liners and mechanical chores are filtered out.")
                    .font(.system(size: 10.5)).foregroundStyle(.secondary)
                    .fixedSize(horizontal: false, vertical: true)
            }
        case "confluence":
            ConnectorCard(c: c, m: conn, onDisconnect: { disconnect(["JIRA_API_TOKEN": "", "CONFLUENCE_API_TOKEN": ""]) }) {
                labeled("Site URL") { TextField("https://your-site.atlassian.net", text: $jiraBase).textFieldStyle(.roundedBorder) }
                labeled("Email") { TextField("you@company.com", text: $jiraEmail).textFieldStyle(.roundedBorder) }
                SecureField(conn.health["confluence"]?.configured == true
                            ? "Connected — paste a new API token to replace"
                            : "Atlassian API token", text: $jiraToken)
                    .textFieldStyle(.roundedBorder)
            }
        case "outlook":
            ConnectorCard(c: c, m: conn, onDisconnect: { disconnect(["MS_REFRESH_TOKEN": ""]) }) {
                HStack {
                    Button(connecting ? "Connecting…" : (conn.health["outlook"]?.configured == true ? "Reconnect" : "Connect Outlook")) {
                        connectOutlook()
                    }
                    .disabled(connecting)
                    Spacer()
                }
                if !outlookLog.isEmpty {
                    Text(outlookLog).font(.system(size: 11, design: .monospaced))
                        .foregroundStyle(.secondary).textSelection(.enabled)
                        .fixedSize(horizontal: false, vertical: true)
                }
            }
        default:
            ConnectorCard(c: c, m: conn, onDisconnect: nil) { EmptyView() }
        }
    }

    // MARK: vault page

    private var vaultPage: some View {
        VStack(alignment: .leading, spacing: 16) {
            group("Vault") {
                labeled("Vault folder") { TextField("~/knowledge", text: $vaultDir).textFieldStyle(.roundedBorder) }
                Text("Keep the vault on local disk. Background jobs cannot read from iCloud/OneDrive folders.")
                    .font(.system(size: 10.5)).foregroundStyle(.secondary)
                    .fixedSize(horizontal: false, vertical: true)
            }
            group("Where things live") {
                pathRow("Vault", conn.status.vault.isEmpty ? vaultDir : conn.status.vault)
                pathRow("Loop", loop)
                pathRow("Secrets", "\(NSHomeDirectory())/.claude/.env")
            }
        }
    }

    @ViewBuilder private func pathRow(_ label: String, _ path: String) -> some View {
        HStack(spacing: 6) {
            Text(label).font(.system(size: 11)).foregroundStyle(.secondary).frame(width: 54, alignment: .leading)
            Text(path).font(.system(size: 11, design: .monospaced)).textSelection(.enabled)
                .lineLimit(1).truncationMode(.middle)
            Spacer(minLength: 0)
            Button {
                openExternal((path as NSString).deletingLastPathComponent)
            } label: { Image(systemName: "folder") }.buttonStyle(.borderless)
        }
    }

    // MARK: helpers

    @ViewBuilder private func group<C: View>(_ title: String, @ViewBuilder _ content: () -> C) -> some View {
        VStack(alignment: .leading, spacing: 8) {
            Text(title.uppercased()).font(.system(size: 10, weight: .semibold)).foregroundStyle(.secondary)
            content()
        }
    }
    @ViewBuilder private func labeled<C: View>(_ label: String, @ViewBuilder _ content: () -> C) -> some View {
        VStack(alignment: .leading, spacing: 2) {
            Text(label).font(.system(size: 11)).foregroundStyle(.secondary)
            content()
        }
    }

    private func load() {
        let cfg = ConfigStore.read(ConfigStore.configEnv)
        vaultDir = cfg["VAULT_DIR"] ?? "\(NSHomeDirectory())/knowledge"
        let env = ConfigStore.read(ConfigStore.dotEnv)
        jiraBase = env["JIRA_BASE_URL"] ?? ""
        jiraEmail = env["JIRA_EMAIL"] ?? ""
        githubOrgs = env["PLASMIE_GITHUB_ORGS"] ?? "fabrikam"
        gitRoots = env["PLASMIE_GIT_ROOTS"] ?? "~/code"
    }

    private func save() {
        ConfigStore.upsert(ConfigStore.configEnv, [
            "VAULT_DIR": vaultDir.trimmingCharacters(in: .whitespaces),
        ], exportPrefix: false, quoted: true)

        // Connector settings go in ~/.claude/.env, NOT config.env: run-ingest.sh
        // sources .env under `set -a` (exported, so loop-ingest.py sees it) but
        // sources config.env without it — a key written there would never arrive.
        var env: [String: String] = [
            "JIRA_BASE_URL": jiraBase.trimmingCharacters(in: .whitespaces),
            "JIRA_EMAIL": jiraEmail.trimmingCharacters(in: .whitespaces),
            "PLASMIE_GITHUB_ORGS": githubOrgs.trimmingCharacters(in: .whitespaces),
            "PLASMIE_GIT_ROOTS": gitRoots.trimmingCharacters(in: .whitespaces),
        ]
        if !slackToken.isEmpty { env["SLACK_USER_TOKEN"] = slackToken.trimmingCharacters(in: .whitespaces) }
        if !jiraToken.isEmpty { env["JIRA_API_TOKEN"] = jiraToken.trimmingCharacters(in: .whitespaces) }
        ConfigStore.upsert(ConfigStore.dotEnv, env, exportPrefix: true, quoted: false, perms: 0o600)

        slackToken = ""; jiraToken = ""; load()
        saved = true
        conn.refresh()
        DispatchQueue.main.asyncAfter(deadline: .now() + 2) { saved = false }
    }

    /// Empty value removes the key (ConfigStore.upsert contract), so this really
    /// does disconnect rather than blanking a field in the UI only.
    private func disconnect(_ keys: [String: String]) {
        ConfigStore.upsert(ConfigStore.dotEnv, keys, exportPrefix: true, quoted: false, perms: 0o600)
        conn.refresh()
    }

    /// Device-code login (msgraph.py) — streams the "open this URL, enter this code"
    /// message; on success the script writes MS_REFRESH_TOKEN to ~/.claude/.env.
    private func connectOutlook() {
        connecting = true; outlookLog = "Starting…"
        let py = FileManager.default.fileExists(atPath: "\(loop)/.venv/bin/python3")
            ? "\(loop)/.venv/bin/python3" : "/usr/bin/python3"
        runStreaming(py, ["\(loop)/msgraph.py", "login"],
            onStatus: { _ in },
            onChunk: { full in outlookLog = full.trimmingCharacters(in: .whitespacesAndNewlines) },
            onDone: { connecting = false; conn.refresh(["outlook"]) })
    }
}

/// Wires the global hotkey to the overlay at launch (the MenuBarExtra scene stays).
