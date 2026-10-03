#!/usr/bin/env python3
"""Apple Foundation Models (on-device) — Plasmie's ONLY generation backend.

macOS 26+ exposes the model behind Apple Intelligence through the
FoundationModels framework. Plasmie reaches it through `plasmie-fm`, a tiny Swift
helper built by app/build-fm.sh and shipped inside Plasmie.app, so a stock Mac
needs no Xcode, Homebrew or model download (ADR 0021). Apple's Python SDK
(`apple-fm-sdk`) is kept only as an optional dev fallback (fm_sdk.py): it
installs only with a full Xcode, which friends won't have.

Every caller goes through here, so everyone gets the same answer to "can we use
it right now?" and the same contract around a call: the busy/thermal guard for
background jobs, a hard timeout, an audit line, and a transcript of exactly
what crossed into the model. On-device is not the same as auditable; the
transcript is what makes the privacy claim checkable.

Why a call can fail, which look identical from outside and cost real time to
tell apart (probe() names each):
  - the helper is missing (broken install, or a dev checkout never built it);
  - macOS is older than 26, or the Mac can't run Apple Intelligence;
  - Apple Intelligence is off, or on but the model is still downloading.

  python3 fm.py        -> JSON probe (also what plasmie-doctor.py reports)

Log retention: summarize.sh prunes audit-*; transcript-* is pruned here.
"""
import datetime
import json
import os
import platform
import re
import subprocess
import threading
import time
from pathlib import Path
from typing import Any, Callable, Optional

SELF = Path(__file__).resolve().parent
LOGS = Path(os.path.expanduser(os.environ.get("PLASMIE_LOGS") or "~/Library/Logs/Plasmie"))

# Helper status word -> reason name (plasmie-doctor and the setup check key off these).
_STATUS_REASON = {
    "appleIntelligenceNotEnabled": "APPLE_INTELLIGENCE_NOT_ENABLED",
    "deviceNotEligible": "DEVICE_NOT_ELIGIBLE",
    "modelNotReady": "MODEL_NOT_READY",
    "unsupportedOS": "UNSUPPORTED_OS",
}
_REASON_HINT = {
    "APPLE_INTELLIGENCE_NOT_ENABLED":
        "Turn on Apple Intelligence in System Settings > Apple Intelligence & Siri.",
    "DEVICE_NOT_ELIGIBLE":
        "This Mac can't run Apple Intelligence, so Plasmie can't summarize, file or answer.",
    "MODEL_NOT_READY":
        "Apple Intelligence is on but the model is still downloading — retry later.",
    "UNSUPPORTED_OS":
        "Apple's on-device model needs macOS 26 or later. Update macOS in System Settings.",
    "HELPER_MISSING":
        "Plasmie's model bridge (plasmie-fm) is missing: reinstall Plasmie from the DMG. "
        "In a dev checkout, run app/build-fm.sh.",
    "UNKNOWN":
        "No reason given. Check System Settings > Apple Intelligence & Siri.",
}

# Tokens held back from the context window for the model's own answer.
RESPONSE_MARGIN = 512
# Conservative chars/token for budgeting without a model call: markdown,
# identifiers and paths tokenize worse than prose. Overshooting only splits a
# little earlier; undershooting costs an over_budget round trip.
CHARS_PER_TOKEN = 3.0
TRANSCRIPT_DAYS = 30


def _default_timeout() -> float:
    """Read per call, never frozen at import (the .env sourcing incident)."""
    try:
        return float(os.environ.get("PLASMIE_FM_TIMEOUT", "20"))
    except ValueError:
        return 20.0


def helper_path() -> Optional[str]:
    """plasmie-fm: $PLASMIE_FM_BIN, else the app bundle this engine runs from, else a
    dev build, else an installed Plasmie.app. None when none is executable."""
    env = os.environ.get("PLASMIE_FM_BIN")
    if env:
        return env if os.access(env, os.X_OK) else None
    for p in (SELF.parent.parent / "MacOS" / "plasmie-fm",          # Contents/Resources/backend
              SELF / "app" / "build" / "plasmie-fm",                 # app/build-fm.sh
              SELF / "app" / "build" / "Plasmie.app" / "Contents" / "MacOS" / "plasmie-fm",
              Path("/Applications/Plasmie.app/Contents/MacOS/plasmie-fm")):
        if os.access(p, os.X_OK):
            return str(p)
    return None


def _sdk():
    """The optional dev fallback, or None. Imported lazily: it is never required."""
    try:
        import fm_sdk
        return fm_sdk if fm_sdk.importable() else None
    except Exception:
        return None


def _versions() -> str:
    """macOS + backend, so a quality regression can be tied to an update."""
    via = "plasmie-fm" if helper_path() else ("apple-fm-sdk" if _sdk() else "none")
    return f"macOS {platform.mac_ver()[0]}, {via}"


def _log(name: str, body: str) -> None:
    """Append to an owner-only daily log. Never raises — logging must not break
    the caller it exists to make debuggable."""
    try:
        LOGS.mkdir(parents=True, exist_ok=True)
        p = LOGS / f"{name}-{datetime.date.today().isoformat()}.log"
        fd = os.open(p, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
        with os.fdopen(fd, "a", encoding="utf-8") as fh:
            fh.write(body)
    except OSError:
        pass


def _audit(outcome: str) -> None:
    _log("audit", f"{datetime.datetime.now():%F %T} | fm | {outcome}\n")


def _prune_transcripts() -> None:
    cutoff = time.time() - TRANSCRIPT_DAYS * 86400
    try:
        for p in LOGS.glob("transcript-*.log"):
            if p.stat().st_mtime < cutoff:
                p.unlink()
    except OSError:
        pass


def _transcript(prompt: str, response: str, meta: str) -> None:
    """What actually crossed into the model, byte for byte — what makes the
    privacy claim verifiable rather than merely asserted."""
    _log("transcript",
         f"\n========== {datetime.datetime.now():%F %T} | {meta} ==========\n"
         f"----- REQUEST (on-device model) -----\n{prompt}\n"
         f"----- RESPONSE -----\n{response}\n")
    _prune_transcripts()


def _run(cmd: list[str], timeout: float) -> Optional[str]:
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout).stdout
    except (OSError, subprocess.SubprocessError):
        return None


def machine_busy() -> bool:
    """True when a BACKGROUND job should defer: thermal pressure, a 1-minute load
    at or above the core count, or under 15% free RAM. The model runs in an OS
    service (nothing to load), so the RAM arm only guards against swap storms.
    Interactive callers (Ask, fun facts) skip this on purpose: a person is waiting."""
    therm = _run(["pmset", "-g", "therm"], 10) or ""
    if re.search(r"(thermal|performance) warning level [1-9]", therm, re.I):
        return True
    try:
        if os.getloadavg()[0] >= (os.cpu_count() or 1):
            return True
    except OSError:
        pass
    mp = _run(["memory_pressure"], 10) or ""
    m = re.search(r"free percentage:\s*(\d+)", mp, re.I)
    return bool(m and int(m.group(1)) < 15)


def _guard_ok() -> bool:
    """PLASMIE_FM_GUARD=off skips the guard for a manual run you are watching (and tests)."""
    if os.environ.get("PLASMIE_FM_GUARD", "").lower() == "off":
        return True
    try:
        return not machine_busy()
    except Exception:
        return True       # a broken guard must not block the pipeline


def _call_helper(binary: str, req: dict, timeout: float,
                 on_delta: Optional[Callable[[str], None]]) -> dict:
    """One request to plasmie-fm. Always returns a dict: the helper's final object,
    or {"error": "timeout"|"failed", ...}. Streams {"delta"} lines to on_delta."""
    try:
        proc = subprocess.Popen([binary], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                stderr=subprocess.PIPE, text=True)
    except OSError as e:
        return {"error": "failed", "reason": f"could not start plasmie-fm: {e}"}
    timed_out = threading.Event()

    def _kill():
        timed_out.set()
        proc.kill()
    timer = threading.Timer(timeout, _kill)
    timer.start()
    final: dict = {}
    try:
        proc.stdin.write(json.dumps(req))
        proc.stdin.close()
        for line in proc.stdout:
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                continue
            if "delta" in obj:
                if on_delta:
                    on_delta(obj["delta"])
            else:
                final = obj
        proc.wait()
    except (OSError, ValueError) as e:
        final = final or {"error": "failed", "reason": str(e)}
    finally:
        timer.cancel()
    if timed_out.is_set():
        return {"error": "timeout", "reason": f"no answer within {timeout:.0f}s"}
    if not final:
        err = (proc.stderr.read() if proc.stderr else "")[-300:]
        return {"error": "failed", "reason": f"plasmie-fm exited {proc.returncode}: {err.strip()}"}
    return final


def call(req: dict, timeout: float,
         on_delta: Optional[Callable[[str], None]] = None) -> dict:
    """Route one request to the helper (or the dev SDK fallback)."""
    binary = helper_path()
    if binary:
        return _call_helper(binary, req, timeout, on_delta)
    sdk = _sdk()
    if sdk:
        return sdk.call(req, timeout, on_delta)
    return {"error": "unavailable", "reason": "helper_missing"}


def probe() -> dict[str, Any]:
    """Report whether the on-device model is usable, and why not when it isn't.

    Returns {"installed", "available", "reason", "detail", "hint",
             "context_size", "backend"}. `available` is None only when we couldn't ask.
    """
    binary = helper_path()
    if binary:
        raw = _run([binary, "--probe"], 15)
        try:
            got = json.loads(raw or "")
        except json.JSONDecodeError:
            return {"installed": True, "available": None, "reason": "PROBE_FAILED",
                    "detail": f"plasmie-fm --probe gave no answer ({binary})",
                    "hint": _REASON_HINT["HELPER_MISSING"], "context_size": None,
                    "backend": "plasmie-fm"}
        backend = "plasmie-fm"
    else:
        sdk = _sdk()
        if not sdk:
            return {"installed": False, "available": False, "reason": "HELPER_MISSING",
                    "detail": "plasmie-fm not found (PLASMIE_FM_BIN, the app bundle, app/build).",
                    "hint": _REASON_HINT["HELPER_MISSING"], "context_size": None,
                    "backend": None}
        got, backend = sdk.probe(), "apple-fm-sdk"
    status = got.get("status")
    if status == "available":
        # The ceiling the whole design bends around. Apple's docs say 4096;
        # macOS 27.0 measured 8192. Trust this value, never the article.
        ctx = got.get("context_size")
        return {"installed": True, "available": True, "reason": None,
                "detail": "On-device model ready"
                          + (f"; context window {ctx} tokens." if ctx else "."),
                "hint": "", "context_size": ctx, "backend": backend}
    reason = _STATUS_REASON.get(status or "", "UNKNOWN")
    detail = (f"Apple Intelligence unavailable: {reason}." if reason != "UNKNOWN" else
              f"Apple Intelligence unavailable; backend said {status!r}.")
    return {"installed": True, "available": False, "reason": reason, "detail": detail,
            "hint": _REASON_HINT[reason], "context_size": None, "backend": backend}


def available() -> bool:
    """True only when the model can be used right now. Never raises."""
    try:
        return probe().get("available") is True
    except Exception:
        return False


def context_size() -> Optional[int]:
    """Live context window in tokens (None when the model isn't usable).

    Read per call, never hardcoded: Apple documents 4096 and macOS 27 measured
    8192, so callers that budget prompts must ask the OS.
    """
    try:
        return probe().get("context_size")
    except Exception:
        return None


def estimate_tokens(text: str) -> int:
    """Conservative token estimate with no model call (budgeting, chunking)."""
    return int(len(text or "") / CHARS_PER_TOKEN) + 1


def count_tokens(text: str) -> int:
    """Real token count from the model when it can say (macOS 26.4+), else the
    conservative estimate. Never raises."""
    res = call({"op": "count", "prompt": text or ""}, timeout=15)
    n = res.get("tokens")
    return int(n) if isinstance(n, int) else estimate_tokens(text)


def normalize_tag(t: str) -> str:
    """Model phrasing -> tag shape: lowercase, spaces and slashes to hyphens.

    The content-tagging model emits phrases ("connection pool", "ci/cd
    pipelines"). reindex.safe_tag() rejects anything containing a space — and it
    must, since a tag becomes a filename and `../../../pwned` was a real escape
    (reindex.py:62). So the phrase is reshaped into a legal slug here rather
    than the check being loosened.
    """
    t = t.strip().strip("\"'“”").lower()
    t = re.sub(r"[\s/]+", "-", t)
    # `..` is the traversal primitive safe_tag bans outright. A single dot
    # is legal (node.js), a run of them never is — collapse rather than emit
    # something the gate will reject, so this cannot launder a hostile tag.
    t = re.sub(r"\.{2,}", "-", t)
    t = re.sub(r"-{2,}", "-", t)
    return re.sub(r"^[^a-z0-9]+|[^a-z0-9)\]]+$", "", t)


def _clean(raw: str, max_tags: int) -> Optional[list[str]]:
    seen: set[str] = set()
    out: list[str] = []
    for part in raw.split(","):
        t = normalize_tag(part)
        if t and t not in seen:
            seen.add(t)
            out.append(t)
    return out[:max_tags] or None


def _fit(text: str, ctx: Optional[int]) -> str:
    """Trim `text` to the context window, deterministically and audibly."""
    budget_chars = int(((ctx or 4096) - RESPONSE_MARGIN) * CHARS_PER_TOKEN)
    if len(text) <= budget_chars:
        return text
    _audit(f"truncated: {len(text)} chars > {budget_chars} budget")
    return text[:budget_chars]


def tag(text: str, max_tags: int = 8,
        timeout: Optional[float] = None) -> Optional[list[str]]:
    """Topic tags for `text` via the on-device content-tagging model.

    Returns lowercase slug tags, or None when the model is unavailable, the
    machine is busy, the call times out, or the model misbehaves — callers fall
    back to the existing normalizer on None. Every outcome is audited.

    **Plain text in, comma-separated tags out — deliberately NOT guided
    generation.** Measured 2026-09-18 on macOS 27.0: the same note tagged 8x
    through a schema hung 6 times and the 2 that returned were corrupted; plain
    mode went 8/8 in ~1.2s. Re-test after an OS model update.
    """
    if not text or not text.strip():
        return None
    timeout = _default_timeout() if timeout is None else timeout
    if not _guard_ok():
        _audit("skip: machine busy/hot (guard)")
        return None
    prompt = _fit(text, context_size())
    started = time.monotonic()
    res = call({"prompt": prompt, "use_case": "content_tagging", "max_tokens": 120},
               timeout)
    if "error" in res:
        _audit(f"tag {res['error']}: {res.get('reason', '')} | {_versions()}")
        return None
    raw = str(res.get("text", ""))
    tags = _clean(raw, max_tags)
    elapsed = time.monotonic() - started
    _audit(f"ok: {len(tags or [])} tags in {elapsed:.1f}s ({len(prompt)} chars) | {_versions()}")
    _transcript(prompt, raw, f"content-tagging | {elapsed:.1f}s | {_versions()}")
    return tags


def respond(prompt: str, timeout: Optional[float] = None, max_tokens: int = 1024,
            on_chunk: Optional[Callable[[str], None]] = None, guard: bool = True,
            instructions: Optional[str] = None, permissive: bool = False) -> dict:
    """One generation with the full contract; returns the raw result dict.

    {"text": ...} on success, else {"error": code, "reason": ...} where code is
    one of: busy, empty, unavailable, over_budget, context_exceeded, guardrail,
    refusal, unsupported_language, rate_limited, timeout, failed. Map-reduce
    callers use the code to decide between "split and retry" and "skip".

    permissive=True selects Apple's permissiveContentTransformations guardrails:
    meant for summarizing/extracting from text the user supplied, which is what
    digests and promote do, and what the default guardrails over-refuse.
    """
    if not prompt or not prompt.strip():
        return {"error": "empty", "reason": "empty prompt"}
    timeout = _default_timeout() if timeout is None else timeout
    if guard and not _guard_ok():
        _audit("generate skip: machine busy/hot (guard)")
        return {"error": "busy", "reason": "machine busy/hot (guard)"}
    req = {"prompt": prompt, "max_tokens": max_tokens, "greedy": True,
           "stream": on_chunk is not None,
           "guardrails": "permissive" if permissive else "default"}
    if instructions:
        req["instructions"] = instructions
    started = time.monotonic()
    res = call(req, timeout, on_chunk)
    elapsed = time.monotonic() - started
    sent = (f"[instructions]\n{instructions}\n[prompt]\n{prompt}" if instructions else prompt)
    if "error" in res:
        if res["error"] == "over_budget":
            _audit(f"generate skip: {res.get('tokens')} tokens > "
                   f"{(res.get('context_size') or 0) - max_tokens} budget | {_versions()}")
        else:
            _audit(f"generate {res['error']}: {str(res.get('reason', ''))[:200]} "
                   f"({len(prompt)} chars, {elapsed:.1f}s) | {_versions()}")
        return res
    out = str(res.get("text", "")).strip()
    _audit(f"generate ok: {len(out)} chars in {elapsed:.1f}s "
           f"({len(prompt)} chars in) | {_versions()}")
    _transcript(sent, out, f"general | {elapsed:.1f}s | {_versions()}")
    return {**res, "text": out}


def generate(prompt: str, timeout: Optional[float] = None,
             max_tokens: int = 1024, on_chunk=None,
             guard: bool = True, instructions: Optional[str] = None,
             permissive: bool = False) -> Optional[str]:
    """Free-text answer from the general on-device model, or None.

    None covers every failure (each one audited by respond()): unavailable,
    busy, over the context window, timeout, guardrail. An oversized prompt is
    NOT trimmed: callers put the instruction or question at the END (ask.py,
    summarize), so cutting the tail would answer a question nobody asked.
    Callers that can split their input use respond() and map-reduce instead.

    Greedy sampling: the same input gives the same digest, so a regenerated
    rollup only changes when the activity did, and A/B runs are reproducible.

    guard=False skips the busy/thermal guard. It exists for unattended
    background jobs; an interactive ask has a person waiting.

    on_chunk(delta) streams the answer as it is generated.
    """
    res = respond(prompt, timeout=timeout, max_tokens=max_tokens, on_chunk=on_chunk,
                  guard=guard, instructions=instructions, permissive=permissive)
    return res.get("text") or None


if __name__ == "__main__":
    print(json.dumps(probe(), indent=2))
