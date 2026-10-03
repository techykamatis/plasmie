#!/usr/bin/env python3
"""Apple Foundation Models (on-device) — the one chokepoint for the FM SDK.

macOS 26+ exposes the model behind Apple Intelligence through the
FoundationModels framework; `apple-fm-sdk` (Apple's official Python bindings)
brings it to Python. This module is the ONLY place that imports it, so every
caller gets the same answer to "can we use it right now?" and the loop keeps
running on the local Gemma when the answer is no.

Three distinct "no"s, which look identical from the outside and cost real time
to tell apart:
  - the SDK isn't importable — usually because `pip install apple-fm-sdk`
    needs a FULL Xcode (it compiles Swift bindings at install time) and the
    machine only has CommandLineTools;
  - the SDK works but Apple Intelligence is off, or the device isn't eligible;
  - Apple Intelligence is on but the model is still downloading.

Parity with gen.sh is deliberate — these run unattended from launchd, so an FM
call gets what a Gemma call gets: the thermal/load guard first, a hard timeout,
an audit line, and a transcript of exactly what crossed into the model.
On-device is not the same as auditable; the transcript is what makes the
privacy claim checkable.

  python3 fm.py        -> JSON probe (also what plasmie-doctor.py reports)

Log retention is handled by the existing hourly jobs (gen.sh prunes
transcript-*, summarize.sh prunes audit-*), which is why this writes to those
two files rather than inventing its own.
"""
import asyncio
import datetime
import json
import os
import platform
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any, Optional

SELF = Path(__file__).resolve().parent
LOGS = Path(os.path.expanduser(os.environ.get("PLASMIE_LOGS") or "~/Library/Logs/Plasmie"))

# Reasons the SDK reports, mapped to something a human can act on. Mirrors
# apple_fm_sdk.SystemLanguageModelUnavailableReason. Verified against the real
# SDK on macOS 27.0: all four members expose `.name`, including the 0-valued
# APPLE_INTELLIGENCE_NOT_ENABLED. See docs/fm-baseline.md.
_REASON_HINT = {
    "APPLE_INTELLIGENCE_NOT_ENABLED":
        "Turn on Apple Intelligence in System Settings > Apple Intelligence & Siri.",
    "DEVICE_NOT_ELIGIBLE":
        "This Mac can't run Apple Intelligence; the local Gemma path stays in use.",
    "MODEL_NOT_READY":
        "Apple Intelligence is on but the model is still downloading — retry later.",
    "UNKNOWN":
        "The SDK gave no reason. Check System Settings > Apple Intelligence & Siri.",
}

# Tokens held back from context_size for the model's own answer. Tags are short,
# but a trimmed prompt is cheaper than an overflow we cannot diagnose.
RESPONSE_MARGIN = 512


def _default_timeout() -> float:
    """Read per call, never frozen at import.

    A module-level default would bake in whatever the environment looked like
    when the first importer ran — the same class of bug as the .env sourcing
    incident, where config that looked set silently was not.
    """
    try:
        return float(os.environ.get("PLASMIE_FM_TIMEOUT", "20"))
    except ValueError:
        return 20.0


def _versions() -> str:
    """macOS + SDK version, so a quality regression can be tied to an update.

    apple_fm_sdk.__version__ disagrees with the installed distribution (reports
    0.1.0 for the 0.2.1 wheel), so the package metadata wins.
    """
    try:
        from importlib.metadata import version
        sdk = version("apple-fm-sdk")
    except Exception:
        sdk = "?"
    return f"macOS {platform.mac_ver()[0]}, apple-fm-sdk {sdk}"


def _log(name: str, body: str) -> None:
    """Append to an owner-only daily log. Never raises — logging must not break
    the caller it exists to make debuggable."""
    try:
        LOGS.mkdir(exist_ok=True)
        p = LOGS / f"{name}-{datetime.date.today().isoformat()}.log"
        fd = os.open(p, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
        with os.fdopen(fd, "a", encoding="utf-8") as fh:
            fh.write(body)
    except OSError:
        pass


def _audit(outcome: str) -> None:
    _log("audit", f"{datetime.datetime.now():%F %T} | fm | {outcome}\n")


def _transcript(prompt: str, response: str, meta: str) -> None:
    """What actually crossed into the model, byte for byte — the same contract
    as gen.sh's transcript log, which is what makes the privacy claim
    verifiable rather than merely asserted."""
    _log("transcript",
         f"\n========== {datetime.datetime.now():%F %T} | {meta} ==========\n"
         f"----- REQUEST (on-device model) -----\n{prompt}\n"
         f"----- RESPONSE -----\n{response}\n")


def _guard_ok() -> bool:
    """Defer to the same thermal/load/RAM guard every Gemma call respects.

    FM does not load a 5 GB model, so the RAM arm is stricter than it needs to
    be — but one guard beats a second, subtly different definition of "the
    machine is busy", and a hot machine is a hot machine either way.
    """
    guard = SELF / "mlx-ctl.sh"
    if not guard.exists():
        return True
    try:
        out = subprocess.run([str(guard), "guard"], capture_output=True,
                             text=True, timeout=15)
        return out.stdout.strip() == "ok"
    except (OSError, subprocess.SubprocessError):
        return True     # the guard itself is broken — don't block the pipeline


def _xcode_path() -> Optional[str]:
    """Active developer dir, or None. CommandLineTools cannot build the SDK."""
    xs = shutil.which("xcode-select")
    if not xs:
        return None
    try:
        p = subprocess.run([xs, "-p"], capture_output=True, text=True, timeout=10)
        return p.stdout.strip() or None
    except (OSError, subprocess.SubprocessError):
        return None


def probe() -> dict[str, Any]:
    """Report whether the on-device model is usable, and why not when it isn't.

    Returns {"installed", "available", "reason", "detail", "hint",
             "context_size"}. `available` is None only when we couldn't ask.
    """
    try:
        import apple_fm_sdk as fm
    except ImportError as e:
        dev = _xcode_path()
        needs_xcode = bool(dev and "CommandLineTools" in dev)
        hint = ("Install Xcode 27, open it once to accept the licence, then "
                "`sudo xcode-select -s /Applications/Xcode.app` and "
                "`.venv/bin/pip install apple-fm-sdk`. The SDK builds Swift "
                "bindings, so CommandLineTools is not enough."
                if needs_xcode else
                "Install with `.venv/bin/pip install apple-fm-sdk` (needs a full Xcode).")
        return {"installed": False, "available": False, "reason": "SDK_NOT_INSTALLED",
                "detail": f"apple-fm-sdk not importable ({e.__class__.__name__})"
                          + (f"; xcode-select -p = {dev}" if dev else ""),
                "hint": hint, "context_size": None}

    try:
        model = fm.SystemLanguageModel()
        ok, reason = model.is_available()
    except Exception as e:  # the bindings can raise anything from the Swift side
        return {"installed": True, "available": None, "reason": "PROBE_FAILED",
                "detail": f"{e.__class__.__name__}: {e}",
                "hint": "SDK is installed but the probe itself failed.",
                "context_size": None}

    if ok:
        # The ceiling the whole design bends around. Apple's docs say 4096;
        # macOS 27.0 measured 8192. Trust this value, never the article, and
        # report it so an OS model update that changes it gets noticed.
        try:
            ctx = int(model.context_size)
        except Exception:
            ctx = None
        return {"installed": True, "available": True, "reason": None,
                "detail": "On-device model ready"
                          + (f"; context window {ctx} tokens." if ctx else "."),
                "hint": "", "context_size": ctx}

    # `.name` is verified present on every real enum member; the value fallback
    # exists so a future SDK returning a bare int stays diagnosable instead of
    # silently collapsing into the generic UNKNOWN hint.
    name = getattr(reason, "name", None)
    if name is None:
        val = getattr(reason, "value", reason)
        return {"installed": True, "available": False, "reason": "UNKNOWN",
                "detail": f"Apple Intelligence unavailable; SDK returned {val!r} "
                          "with no .name — the reason mapping may be stale.",
                "hint": _REASON_HINT["UNKNOWN"], "context_size": None}
    return {"installed": True, "available": False, "reason": name,
            "detail": f"Apple Intelligence unavailable: {name}.",
            "hint": _REASON_HINT.get(name, _REASON_HINT["UNKNOWN"]),
            "context_size": None}


def available() -> bool:
    """True only when the model can be used right now. Never raises."""
    try:
        return probe().get("available") is True
    except Exception:
        return False


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


async def _fit(model, text: str) -> str:
    """Trim `text` to the model's context window, deterministically.

    Without this an oversized note overflows into whatever the SDK does on
    overflow — which, because every failure here returns None, would be
    indistinguishable from a timeout or a refusal.
    """
    try:
        budget = int(model.context_size) - RESPONSE_MARGIN
        used = int(await model.token_count(text))
    except Exception:
        return text                      # counting is best-effort, never fatal
    if used <= budget or used <= 0:
        return text
    keep = max(1, int(len(text) * budget / used))
    _audit(f"truncated: {used} tokens > {budget} budget, "
           f"kept {keep}/{len(text)} chars")
    return text[:keep]


def tag(text: str, max_tags: int = 8,
        timeout: Optional[float] = None) -> Optional[list[str]]:
    """Topic tags for `text` via the on-device content-tagging model.

    Returns lowercase slug tags, or None when the model is unavailable, the
    machine is busy, the call times out, or the model misbehaves — callers fall
    back to the existing normalizer on None. Every outcome is audited, so
    "silently fell back forever" becomes a state you can see rather than infer.

    **Plain text in, comma-separated tags out — deliberately NOT guided
    generation.** Apple's docs say the content-tagging model supports
    `Generable`, and it does not work: measured 2026-09-18 on macOS 27.0 with
    apple-fm-sdk 0.2.1, the same note tagged 8x through a schema hung 6 times
    (>15s, never returns) and the 2 that returned were both corrupted
    (`'automatic-failover", '`). The identical input in plain mode: 8/8 in
    ~1.2s, 7 byte-identical. Splitting a comma list in code is not a compromise
    here — it is the only mode that works. Re-test after an OS model update.
    """
    if not text or not text.strip():
        return None
    timeout = _default_timeout() if timeout is None else timeout
    if not _guard_ok():
        _audit("skip: machine busy/hot (guard)")
        return None
    try:
        import apple_fm_sdk as fm
    except ImportError:
        _audit("skip: apple-fm-sdk not installed")
        return None

    sent: dict[str, Any] = {}

    async def _run():
        model = fm.SystemLanguageModel(
            use_case=fm.SystemLanguageModelUseCase.CONTENT_TAGGING)
        prompt = await _fit(model, text)
        sent["prompt"] = prompt
        # Fresh session per call: the docs warn a reused session leaks tags
        # from the previous turn into the next one's answer.
        session = fm.LanguageModelSession(model=model)
        return await asyncio.wait_for(session.respond(prompt), timeout=timeout)

    started = datetime.datetime.now()
    try:
        raw = str(asyncio.run(_run()))
    except (TimeoutError, asyncio.TimeoutError):
        _audit(f"timeout after {timeout:.0f}s ({len(text)} chars) | {_versions()}")
        return None
    except Exception as e:               # guardrail, refusal, binding failure
        _audit(f"exception:{e.__class__.__name__}: {e} | {_versions()}")
        return None

    tags = _clean(raw, max_tags)
    elapsed = (datetime.datetime.now() - started).total_seconds()
    prompt = sent.get("prompt", text)
    _audit(f"ok: {len(tags or [])} tags in {elapsed:.1f}s "
           f"({len(prompt)} chars) | {_versions()}")
    _transcript(prompt, raw, f"content-tagging | {elapsed:.1f}s | {_versions()}")
    return tags


def context_size() -> Optional[int]:
    """Live context window in tokens (None when the model isn't usable).

    Read per call, never hardcoded: Apple documents 4096 and macOS 27 measured
    8192, so callers that budget prompts must ask the OS.
    """
    try:
        return probe().get("context_size")
    except Exception:
        return None


def generate(prompt: str, timeout: Optional[float] = None,
             max_tokens: int = 1024, on_chunk=None,
             guard: bool = True) -> Optional[str]:
    """Free-text answer from the GENERAL on-device model, or None to fall back.

    Same contract as tag(): guard first, hard timeout, every outcome audited,
    transcript of exactly what was sent. None means "use Gemma" — the caller
    never has to know why.

    An oversized prompt is NOT trimmed the way tag() trims: callers put the
    instruction or the question at the END (ask.py, summarize.sh), so cutting
    the tail would answer a question nobody asked. Over budget -> None, and the
    caller's Gemma path handles it.

    Greedy sampling: the same input gives the same digest, so a regenerated
    rollup only changes when the activity did, and A/B runs are reproducible.

    guard=False skips the thermal/load/RAM guard. That guard exists for
    unattended background jobs; an interactive ask has a person waiting, and a
    "busy" None would trigger the 5 GB Gemma load — the opposite of the point.

    on_chunk(delta) streams. The SDK yields cumulative snapshots, not deltas
    (measured: '1,2' -> '1,2,3,4,5,'), so the delta is the new suffix.
    """
    if not prompt or not prompt.strip():
        return None
    timeout = _default_timeout() if timeout is None else timeout
    if guard and not _guard_ok():
        _audit("generate skip: machine busy/hot (guard)")
        return None
    try:
        import apple_fm_sdk as fm
    except ImportError:
        _audit("generate skip: apple-fm-sdk not installed")
        return None

    async def _run():
        model = fm.SystemLanguageModel()
        try:
            used = int(await model.token_count(prompt))
            budget = int(model.context_size) - max_tokens
        except Exception:
            used, budget = 0, 1                # counting is best-effort
        if used > budget:
            _audit(f"generate skip: {used} tokens > {budget} budget | {_versions()}")
            return None
        session = fm.LanguageModelSession(model=model)
        opts = fm.GenerationOptions(sampling=fm.SamplingMode.greedy(),
                                    maximum_response_tokens=max_tokens)
        if on_chunk is None:
            return str(await session.respond(prompt, options=opts))
        text = ""
        async for snap in session.stream_response(prompt, options=opts):
            snap = str(snap)
            if snap.startswith(text) and len(snap) > len(text):
                on_chunk(snap[len(text):])
            text = snap
        return text

    started = datetime.datetime.now()
    try:
        out = asyncio.run(asyncio.wait_for(_run(), timeout=timeout))
    except (TimeoutError, asyncio.TimeoutError):
        _audit(f"generate timeout after {timeout:.0f}s ({len(prompt)} chars) | {_versions()}")
        return None
    except Exception as e:               # guardrail, refusal, overflow, binding
        _audit(f"generate exception:{e.__class__.__name__}: {e} | {_versions()}")
        return None
    if out is None:
        return None
    out = out.strip()
    elapsed = (datetime.datetime.now() - started).total_seconds()
    _audit(f"generate ok: {len(out)} chars in {elapsed:.1f}s "
           f"({len(prompt)} chars in) | {_versions()}")
    _transcript(prompt, out, f"general | {elapsed:.1f}s | {_versions()}")
    return out or None


if __name__ == "__main__":
    print(json.dumps(probe(), indent=2))
