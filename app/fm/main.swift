// plasmie-fm — Plasmie's bridge to Apple's on-device Foundation Model.
//
// The Python SDK (apple-fm-sdk) only installs with a full Xcode, which a friend's
// Mac won't have. This helper links the system FoundationModels framework instead,
// so it ships inside Plasmie.app and needs nothing at runtime but macOS 26+ with
// Apple Intelligence on. fm.py is its only caller.
//
//   plasmie-fm --check          one word: available | appleIntelligenceNotEnabled |
//                             deviceNotEligible | modelNotReady | unsupportedOS
//                             (exit 0 only when available)
//   plasmie-fm --context-size   the live context window in tokens (never hard-code it:
//                             Apple documents 4096, macOS 27 reports 8192)
//   plasmie-fm --probe          {"status": ..., "context_size": N, "os": "27.0.1"}
//   plasmie-fm < request.json   one generation (or a token count), JSON in -> JSON out
//
// Request:  {"prompt": "...", "instructions": "...", "max_tokens": 800,
//            "greedy": true, "temperature": null, "use_case": "general"|"content_tagging",
//            "guardrails": "default"|"permissive", "stream": false, "op": "generate"|"count"}
// Response: {"text": "...", "elapsed": 1.2}                       on success
//           {"tokens": N, "context_size": M}                     for op=count
//           {"error": "<code>", "reason": "...", ...}            on failure, exit 1
//   stream=true writes NDJSON: {"delta": "..."} per new piece, then the final object.
//
// Error codes: unavailable, over_budget, context_exceeded, guardrail, refusal,
// unsupported_language, rate_limited, assets_unavailable, bad_request, failed.
//
// Built by app/build-fm.sh (swiftc, no Xcode project). Weak-linked so it still
// launches on macOS < 26 and says "unsupportedOS" instead of crashing in dyld.
@_weakLinked import FoundationModels
import Foundation

let out = FileHandle.standardOutput

func emit(_ obj: [String: Any]) {
    guard let data = try? JSONSerialization.data(withJSONObject: obj, options: []) else { return }
    out.write(data)
    out.write("\n".data(using: .utf8)!)
}

func fail(_ code: String, _ reason: String, _ extra: [String: Any] = [:]) -> Never {
    emit(["error": code, "reason": reason].merging(extra) { a, _ in a })
    exit(1)
}

func osVersion() -> String {
    let v = ProcessInfo.processInfo.operatingSystemVersion
    return "\(v.majorVersion).\(v.minorVersion).\(v.patchVersion)"
}

@available(macOS 26.0, *)
func status(_ model: SystemLanguageModel) -> String {
    switch model.availability {
    case .available: return "available"
    case .unavailable(let r):
        switch r {
        case .appleIntelligenceNotEnabled: return "appleIntelligenceNotEnabled"
        case .deviceNotEligible: return "deviceNotEligible"
        case .modelNotReady: return "modelNotReady"
        @unknown default: return "unknown"
        }
    }
}

/// Map a framework error to a stable code. Matching on the description keeps one
/// mapping across macOS 26 (GenerationError) and 27 (LanguageModelError).
func classify(_ error: Error) -> String {
    let d = String(describing: error).lowercased()
    if d.contains("context") { return "context_exceeded" }
    if d.contains("guardrail") { return "guardrail" }
    if d.contains("refusal") { return "refusal" }
    if d.contains("language") || d.contains("locale") { return "unsupported_language" }
    if d.contains("ratelimit") || d.contains("rate_limit") { return "rate_limited" }
    if d.contains("assets") { return "assets_unavailable" }
    return "failed"
}

@available(macOS 26.0, *)
func run(_ req: [String: Any]) async {
    let useCase: SystemLanguageModel.UseCase =
        (req["use_case"] as? String) == "content_tagging" ? .contentTagging : .general
    let guardrails: SystemLanguageModel.Guardrails =
        (req["guardrails"] as? String) == "permissive" ? .permissiveContentTransformations : .default
    let model = SystemLanguageModel(useCase: useCase, guardrails: guardrails)
    let st = status(model)
    guard st == "available" else { fail("unavailable", st) }

    let prompt = req["prompt"] as? String ?? ""
    let instructions = (req["instructions"] as? String).flatMap { $0.isEmpty ? nil : $0 }
    let maxTokens = req["max_tokens"] as? Int ?? 1024
    let ctx = model.contextSize

    // Count up front (macOS 26.4+): an overflow is reported as such, with numbers,
    // instead of surfacing as an opaque generation error after a slow prefill.
    var used: Int? = nil
    if #available(macOS 26.4, *) {
        do {
            var n = try await model.tokenCount(for: prompt)
            if let i = instructions { n += try await model.tokenCount(for: Instructions(i)) }
            used = n
        } catch {
            used = nil                       // counting is best-effort
        }
    }
    if (req["op"] as? String) == "count" {
        guard let n = used else { fail("failed", "token counting needs macOS 26.4+") }
        emit(["tokens": n, "context_size": ctx]); return
    }
    guard !prompt.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty else {
        fail("bad_request", "empty prompt")
    }
    if let n = used, n + maxTokens > ctx {
        fail("over_budget", "\(n) prompt tokens + \(maxTokens) reserved > \(ctx) context",
             ["tokens": n, "context_size": ctx])
    }

    let greedy = req["greedy"] as? Bool ?? true
    let temperature = req["temperature"] as? Double
    let opts = GenerationOptions(samplingMode: greedy ? .greedy : nil,
                                 temperature: greedy ? nil : temperature,
                                 maximumResponseTokens: maxTokens)
    let session = LanguageModelSession(model: model, instructions: instructions)
    let started = Date()
    do {
        var text = ""
        if req["stream"] as? Bool ?? false {
            // Snapshots are cumulative; emit only the new suffix as a delta.
            for try await snap in session.streamResponse(to: prompt, options: opts) {
                let s = snap.content
                if s.hasPrefix(text), s.count > text.count {
                    emit(["delta": String(s.dropFirst(text.count))])
                }
                text = s
            }
        } else {
            text = try await session.respond(to: prompt, options: opts).content
        }
        var res: [String: Any] = ["text": text, "elapsed": Date().timeIntervalSince(started),
                                  "context_size": ctx]
        if let n = used { res["prompt_tokens"] = n }
        emit(res)
    } catch {
        fail(classify(error), String(describing: error))
    }
}

@available(macOS 26.0, *)
func cli(_ args: ArraySlice<String>) async {
    if args.contains("--check") {
        let st = status(SystemLanguageModel.default)
        print(st)
        exit(st == "available" ? 0 : 1)
    }
    if args.contains("--context-size") {
        print(SystemLanguageModel.default.contextSize)
        exit(0)
    }
    if args.contains("--probe") {
        let m = SystemLanguageModel.default
        let st = status(m)
        emit(["status": st, "context_size": st == "available" ? m.contextSize : NSNull(),
              "os": osVersion()])
        exit(st == "available" ? 0 : 1)
    }
    if let a = args.first, a.hasPrefix("-") {
        FileHandle.standardError.write(
            "usage: plasmie-fm [--check|--context-size|--probe] < request.json\n".data(using: .utf8)!)
        exit(2)
    }
    let input = FileHandle.standardInput.readDataToEndOfFile()
    guard let req = (try? JSONSerialization.jsonObject(with: input)) as? [String: Any] else {
        fail("bad_request", "stdin is not a JSON object")
    }
    await run(req)
}

@main
struct PlasmieFM {
    static func main() async {
        let args = CommandLine.arguments.dropFirst()
        if #available(macOS 26.0, *) {
            await cli(args)
            exit(0)
        }
        if args.contains("--check") { print("unsupportedOS"); exit(1) }
        if args.contains("--probe") { emit(["status": "unsupportedOS", "os": osVersion()]); exit(1) }
        fail("unavailable", "unsupportedOS", ["os": osVersion()])
    }
}
