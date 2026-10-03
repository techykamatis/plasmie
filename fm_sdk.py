#!/usr/bin/env python3
"""Dev-only fallback: Apple's Python SDK (`apple-fm-sdk`) speaking plasmie-fm's protocol.

fm.py prefers the bundled plasmie-fm helper. This exists so a dev checkout whose
venv already has the SDK (it only installs with a full Xcode) keeps working
before app/build-fm.sh has run. It is never installed for users and nothing
requires it. Same request/response dicts as plasmie-fm (see app/fm/main.swift).
"""
import asyncio
from typing import Callable, Optional

# SDK reason enum name -> plasmie-fm status word
_STATUS = {"APPLE_INTELLIGENCE_NOT_ENABLED": "appleIntelligenceNotEnabled",
           "DEVICE_NOT_ELIGIBLE": "deviceNotEligible",
           "MODEL_NOT_READY": "modelNotReady"}


def importable() -> bool:
    try:
        import apple_fm_sdk  # noqa: F401
        return True
    except Exception:
        return False


def probe() -> dict:
    import apple_fm_sdk as fm
    try:
        model = fm.SystemLanguageModel()
        ok, reason = model.is_available()
    except Exception as e:  # the bindings can raise anything from the Swift side
        return {"status": "probeFailed", "detail": f"{e.__class__.__name__}: {e}"}
    if ok:
        try:
            return {"status": "available", "context_size": int(model.context_size)}
        except Exception:
            return {"status": "available", "context_size": None}
    return {"status": _STATUS.get(getattr(reason, "name", ""), "unknown")}


def _classify(e: Exception) -> str:
    d = f"{e.__class__.__name__} {e}".lower()
    for key, code in (("context", "context_exceeded"), ("guardrail", "guardrail"),
                      ("refusal", "refusal"), ("language", "unsupported_language")):
        if key in d:
            return code
    return "failed"


def call(req: dict, timeout: float,
         on_delta: Optional[Callable[[str], None]] = None) -> dict:
    import apple_fm_sdk as fm

    async def _run() -> dict:
        tagging = req.get("use_case") == "content_tagging"
        model = (fm.SystemLanguageModel(use_case=fm.SystemLanguageModelUseCase.CONTENT_TAGGING)
                 if tagging else fm.SystemLanguageModel())
        prompt = req.get("prompt", "")
        try:
            used = int(await model.token_count(prompt))
            ctx = int(model.context_size)
        except Exception:
            used, ctx = None, None
        if req.get("op") == "count":
            return ({"tokens": used, "context_size": ctx} if used is not None
                    else {"error": "failed", "reason": "token counting unavailable"})
        max_tokens = int(req.get("max_tokens", 1024))
        if used is not None and ctx and used + max_tokens > ctx:
            return {"error": "over_budget", "tokens": used, "context_size": ctx,
                    "reason": f"{used} + {max_tokens} > {ctx}"}
        instructions = req.get("instructions")
        session = (fm.LanguageModelSession(model=model, instructions=instructions)
                   if instructions else fm.LanguageModelSession(model=model))
        opts = fm.GenerationOptions(sampling=fm.SamplingMode.greedy(),
                                    maximum_response_tokens=max_tokens)
        if not req.get("stream"):
            return {"text": str(await session.respond(prompt, options=opts))}
        text = ""
        async for snap in session.stream_response(prompt, options=opts):
            snap = str(snap)          # cumulative snapshots -> emit the new suffix
            if snap.startswith(text) and len(snap) > len(text) and on_delta:
                on_delta(snap[len(text):])
            text = snap
        return {"text": text}

    try:
        return asyncio.run(asyncio.wait_for(_run(), timeout=timeout))
    except (TimeoutError, asyncio.TimeoutError):
        return {"error": "timeout", "reason": f"no answer within {timeout:.0f}s"}
    except Exception as e:
        return {"error": _classify(e), "reason": f"{e.__class__.__name__}: {e}"}
