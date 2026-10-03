import AppKit
import SwiftUI

// Two setup steps between the prerequisite checklist and the install:
//  1. Where your notes live: pick (or keep) the vault folder. An existing Plasmie vault is
//     ADOPTED as-is (never overwritten; a restore point is taken before setup); cloud-
//     synced folders are refused (iCloud sync is a separate, opt-in mirror).
//  2. Your choices: macOS-level behavior is offered, never applied silently. The notch is
//     on by default (owner, 2026-10-04); open at login and iCloud sync start off.

/// What `plasmie-vault.py inspect` + `check-folder` say about a folder.
struct VaultCheck: Equatable {
    var path: String
    var ok = true
    var reason = ""
    var exists = false
    var plasmie = false
    var notes = 0
    var raw = 0

    /// One sentence on what setup will do with this folder.
    var plan: String {
        if !ok { return reason }
        if plasmie { return "Found your Plasmie vault: \(notes) notes and \(raw) captured files. I'll use it as is and never overwrite it." }
        if exists && !isEmpty { return "This folder already has files. I'll add Plasmie's folders beside them and won't touch what's there." }
        return "I'll create your vault here."
    }
    var isEmpty = true

    static func load(_ path: String) -> VaultCheck {
        let p = (path as NSString).expandingTildeInPath
        var c = VaultCheck(path: p)
        let folder = json(runCapture(PlasmiePaths.python, [PlasmiePaths.script("plasmie-vault.py"), "check-folder", p], timeout: 30))
        c.ok = folder["ok"] as? Bool ?? false
        c.reason = folder["reason"] as? String ?? "Couldn't check that folder."
        let info = json(runCapture(PlasmiePaths.python, [PlasmiePaths.script("plasmie-vault.py"), "inspect", p], timeout: 60))
        c.exists = info["exists"] as? Bool ?? false
        c.isEmpty = info["empty"] as? Bool ?? true
        c.plasmie = info["plasmie_vault"] as? Bool ?? false
        c.notes = info["wiki_notes"] as? Int ?? 0
        c.raw = info["raw_files"] as? Int ?? 0
        return c
    }

    private static func json(_ s: String) -> [String: Any] {
        guard let start = s.firstIndex(of: "{"), let d = String(s[start...]).data(using: .utf8),
              let o = try? JSONSerialization.jsonObject(with: d) as? [String: Any] else { return [:] }
        return o
    }
}

struct VaultStep: View {
    @Binding var path: String
    let onContinue: (String) -> Void
    @State private var check: VaultCheck?
    @State private var checking = false

    var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            Text("Where should your notes live?").font(.klHeading)
            Text("Plasmie keeps everything it learns as plain Markdown notes you can open in Obsidian. Pick a folder on this Mac, or point me at the vault you already have.")
                .klNote()
            HStack(spacing: 8) {
                Image(systemName: "folder").foregroundStyle(.secondary)
                Text((path as NSString).abbreviatingWithTildeInPath).font(.klBody).lineLimit(1).truncationMode(.middle)
                Spacer(minLength: 8)
                Button("Choose…", action: choose)
            }
            .padding(10)
            .background(RoundedRectangle(cornerRadius: 8).fill(Color.primary.opacity(0.05)))
            if checking {
                ProgressView().controlSize(.small)
            } else if let c = check {
                Label(c.plan, systemImage: c.ok ? (c.plasmie ? "checkmark.seal.fill" : "checkmark.circle") : "xmark.octagon.fill")
                    .font(.klLabel).foregroundStyle(c.ok ? Color.primary : Color.red)
                    .fixedSize(horizontal: false, vertical: true)
            }
            HStack {
                Spacer()
                Button("Continue") { onContinue(path) }
                    .keyboardShortcut(.defaultAction)
                    .disabled(checking || check?.ok != true)
            }
        }
        .onAppear { recheck() }
        .onChange(of: path) { _ in recheck() }
    }

    private func choose() {
        let panel = NSOpenPanel()
        panel.canChooseDirectories = true
        panel.canChooseFiles = false
        panel.canCreateDirectories = true
        panel.prompt = "Use this folder"
        panel.directoryURL = URL(fileURLWithPath: (path as NSString).expandingTildeInPath).deletingLastPathComponent()
        if panel.runModal() == .OK, let url = panel.url { path = url.path }
    }

    private func recheck() {
        checking = true
        let p = path
        DispatchQueue.global(qos: .userInitiated).async {
            let c = VaultCheck.load(p)
            DispatchQueue.main.async { if p == path { check = c; checking = false } }
        }
    }
}

struct ChoicesStep: View {
    @Binding var openAtLogin: Bool
    @Binding var icloud: Bool
    let onContinue: () -> Void

    var body: some View {
        VStack(alignment: .leading, spacing: 14) {
            Text("A couple of choices").font(.klHeading)
            Text("You can change these any time in the Plasmie window.").klNote()
            choice($openAtLogin, "Open Plasmie when you log in",
                   "So I keep catching your work after a restart. Shows in System Settings › Login Items.")
            choice($icloud, "Mirror your notes to iCloud Drive",
                   "Read them in Obsidian on your iPhone or iPad. Only your notes and daily digests are copied, never raw captures; your notes then also live in your iCloud account.")
            HStack {
                Spacer()
                Button("Set up Plasmie", action: onContinue).keyboardShortcut(.defaultAction)
            }
        }
    }

    private func choice(_ on: Binding<Bool>, _ title: String, _ detail: String) -> some View {
        Toggle(isOn: on) {
            VStack(alignment: .leading, spacing: 2) {
                Text(title).font(.klBody)
                Text(detail).klNote()
            }
        }
        .toggleStyle(.switch)
    }
}
