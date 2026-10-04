import Foundation

/// Connector credentials in the login Keychain: generic passwords, service "Plasmie",
/// account = the env var name. The Swift twin of keychain.py; plasmie-env.sh reads the same.
///
/// Every call goes through /usr/bin/security, never Security.framework. Plasmie is ad-hoc
/// signed, so its code identity changes with every build: an item the app created itself
/// would trust only that build, and both the next app update and the background jobs
/// (which read through `security`) would hit an "allow access?" prompt. An item that
/// `security` creates trusts exactly that tool, by Apple's code requirement, so with one
/// stable system binary as the only reader and writer nothing prompts. (No `-T`: an
/// explicit list makes every later `-U` update prompt.)
///
/// Writes go to `security -i` on stdin, so a token never shows in `ps`. Lines over 4096
/// bytes are dropped by `security -i`; a longer value falls back to the argument list
/// (same-user processes only, which could read the item through `security` anyway).
enum Keychain {
    static let service = Brand.name
    static let tool = "/usr/bin/security"
    /// Mirrors keychain.SECRETS and PLASMIE_SECRETS in plasmie-env.sh (a test keeps them equal).
    static let secrets = ["SLACK_USER_TOKEN", "JIRA_API_TOKEN", "CONFLUENCE_API_TOKEN", "MS_REFRESH_TOKEN",
                          "JIRA_EMAIL", "CONFLUENCE_EMAIL", "GITHUB_TOKEN"]
    private static let maxLine = 4000

    enum Failure: LocalizedError {
        case invalid(String), notStored(String)
        var errorDescription: String? {
            switch self {
            case .invalid(let n):   return "\(n) is empty or contains control characters."
            case .notStored(let n): return "The Keychain did not keep \(n). Is it locked?"
            }
        }
    }

    /// PLASMIE_KEYCHAIN points at another keychain file (tests); unset = the login keychain.
    /// nil = set but missing: refuse, because `security` would fall back to the login one.
    private static var keychainArg: [String]? {
        guard let p = ProcessInfo.processInfo.environment["PLASMIE_KEYCHAIN"] else { return [] }
        return FileManager.default.fileExists(atPath: p) ? [p] : nil
    }

    private static func quote(_ s: String) -> String {
        "\"" + s.replacingOccurrences(of: "\\", with: "\\\\").replacingOccurrences(of: "\"", with: "\\\"") + "\""
    }

    @discardableResult
    private static func run(_ args: [String], stdin: String? = nil) -> (status: Int32, out: String) {
        let p = Process()
        p.executableURL = URL(fileURLWithPath: tool)
        p.arguments = args
        let out = Pipe(), inp = Pipe()
        p.standardOutput = out
        p.standardError = FileHandle.nullDevice
        if stdin != nil { p.standardInput = inp }
        do { try p.run() } catch { return (-1, "") }
        if let s = stdin {
            inp.fileHandleForWriting.write(Data(s.utf8))
            try? inp.fileHandleForWriting.close()
        }
        let data = out.fileHandleForReading.readDataToEndOfFile()
        p.waitUntilExit()
        return (p.terminationStatus, String(data: data, encoding: .utf8) ?? "")
    }

    /// The stored value, or nil. The app reads only to verify a write and to prefill the
    /// Atlassian email; tokens are never shown.
    static func get(_ name: String) -> String? {
        guard let kc = keychainArg else { return nil }
        let r = run(["find-generic-password", "-s", service, "-a", name, "-w"] + kc)
        let v = r.out.hasSuffix("\n") ? String(r.out.dropLast()) : r.out
        return r.status == 0 && !v.isEmpty ? v : nil
    }

    /// Create or replace; throws unless the value reads back identical
    /// (`security -i` exits 0 even when a command inside it fails).
    static func set(_ name: String, _ value: String) throws {
        guard !value.isEmpty, !value.unicodeScalars.contains(where: { $0.value < 32 || $0.value == 127 })
        else { throw Failure.invalid(name) }
        guard let kc = keychainArg else { throw Failure.notStored(name) }
        let line = (["add-generic-password", "-U", "-s", service, "-a", name, "-w", quote(value)]
                    + kc.map(quote)).joined(separator: " ")
        if line.utf8.count <= maxLine {
            run(["-i"], stdin: line + "\n")
        } else {
            run(["add-generic-password", "-U", "-s", service, "-a", name, "-w", value] + kc)
        }
        guard get(name) == value else { throw Failure.notStored(name) }
    }

    static func delete(_ name: String) {
        guard let kc = keychainArg else { return }
        run(["delete-generic-password", "-s", service, "-a", name] + kc)
    }
}
