#!/usr/bin/env python3
"""Tests for the Apple Foundation Models chokepoint.

The SDK only installs with a full Xcode, so these inject a fake module to cover
the branches. Read the limits honestly: a fake can prove the *mapping and
plumbing* are right, and nothing more. Two facts about the REAL binding were
measured separately and are recorded in docs/fm-baseline.md rather than
asserted here, because no fixture can establish them:

  - all four SystemLanguageModelUnavailableReason members expose `.name`;
  - asyncio.wait_for genuinely preempts a hung respond() — verified against the
    real SDK at a 3.0s deadline across repeated hangs, thread count flat at 1,
    process exiting rc=0.

Usage:  pytest test_fm.py
"""
import importlib.util
import pathlib
import sys
import types

import pytest

import fm


@pytest.fixture(autouse=True)
def _isolate_logs(tmp_path, monkeypatch):
    """Never let a test write into the real logs/.

    The audit log is diagnostic evidence — a test-generated "timeout" line
    sitting in it would misdirect a real investigation later.
    """
    monkeypatch.setattr(fm, "LOGS", tmp_path)


class _Reason:
    """Stands in for SystemLanguageModelUnavailableReason (has .name)."""

    def __init__(self, name):
        self.name = name


def _fake_sdk(available, reason=None, context_size=8192, raises=None):
    mod = types.ModuleType("apple_fm_sdk")

    class Model:
        def __init__(self, *a, **kw):
            if raises:
                raise raises

        def is_available(self):
            return (available, reason)

        @property
        def context_size(self):
            return context_size

    mod.SystemLanguageModel = Model
    return mod


def _load_doctor():
    """plasmie-doctor.py has a hyphen, so it loads by path rather than by import."""
    spec = importlib.util.spec_from_file_location(
        "plasmie_doctor", pathlib.Path(__file__).with_name("plasmie-doctor.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _probe_with(monkeypatch, mod):
    monkeypatch.setitem(sys.modules, "apple_fm_sdk", mod)
    return fm.probe()


# --- probe ------------------------------------------------------------------

def test_not_installed_names_xcode_when_only_clt(monkeypatch):
    """The most common failure: CLT instead of Xcode, so the SDK never built."""
    monkeypatch.setitem(sys.modules, "apple_fm_sdk", None)   # import raises
    monkeypatch.setattr(fm, "_xcode_path", lambda: "/Library/Developer/CommandLineTools")
    p = fm.probe()
    assert p["installed"] is False and p["available"] is False
    assert p["reason"] == "SDK_NOT_INSTALLED"
    assert "Xcode" in p["hint"]
    assert p["context_size"] is None


def test_available_reports_context_size(monkeypatch):
    p = _probe_with(monkeypatch, _fake_sdk(True, context_size=8192))
    assert p["available"] is True and p["reason"] is None
    assert p["context_size"] == 8192 and "8192" in p["detail"]


def test_each_unavailable_reason_gets_an_actionable_hint(monkeypatch):
    for name in ("APPLE_INTELLIGENCE_NOT_ENABLED", "DEVICE_NOT_ELIGIBLE",
                 "MODEL_NOT_READY", "UNKNOWN"):
        p = _probe_with(monkeypatch, _fake_sdk(False, _Reason(name)))
        assert p["installed"] is True and p["available"] is False
        assert p["reason"] == name
        assert p["hint"], f"{name} left the user with no next step"


def test_reason_without_name_stays_diagnosable(monkeypatch):
    """A future SDK returning a bare int must not collapse into a silent UNKNOWN
    with no trace of what it actually said."""
    p = _probe_with(monkeypatch, _fake_sdk(False, 0))
    assert p["reason"] == "UNKNOWN"
    assert "0" in p["detail"] and "no .name" in p["detail"]


def test_probe_never_raises_when_bindings_explode(monkeypatch):
    p = _probe_with(monkeypatch, _fake_sdk(True, raises=RuntimeError("swift blew up")))
    assert p["available"] is None and p["reason"] == "PROBE_FAILED"
    assert "swift blew up" in p["detail"]


def test_available_is_false_for_every_non_ready_state(monkeypatch):
    monkeypatch.setattr(fm, "probe", lambda: {"available": None})
    assert fm.available() is False
    monkeypatch.setattr(fm, "probe", lambda: (_ for _ in ()).throw(OSError("boom")))
    assert fm.available() is False          # must not take a caller down


# --- plasmie-doctor surfacing ----------------------------------------------------

def test_doctor_reports_not_set_up_as_unknown_not_broken(monkeypatch):
    """A Mac with Apple Intelligence off is not an error to paint red."""
    doctor = _load_doctor()
    monkeypatch.setattr(fm, "probe", lambda: {
        "available": False, "reason": "APPLE_INTELLIGENCE_NOT_ENABLED",
        "detail": "off", "hint": "turn it on", "context_size": None})
    r = doctor.check_foundationmodels()
    assert r["configured"] is False and r["ok"] is None


def test_doctor_reports_real_faults_as_failures(monkeypatch):
    """DEVICE_NOT_ELIGIBLE, PROBE_FAILED and UNKNOWN are faults, not 'unset'.

    UNKNOWN especially: "the SDK gave no reason" filed as benign is the
    phantom-green this file exists to prevent.
    """
    doctor = _load_doctor()
    for reason in ("DEVICE_NOT_ELIGIBLE", "PROBE_FAILED", "UNKNOWN"):
        monkeypatch.setattr(fm, "probe", lambda reason=reason: {
            "available": False, "reason": reason,
            "detail": "d", "hint": "h", "context_size": None})
        assert doctor.check_foundationmodels()["ok"] is False, reason


# --- tag normalisation ------------------------------------------------------

def test_normalize_tag_slugs_phrases_not_loosens_safe_tag():
    import reindex
    for phrase, want in [("connection pool", "connection-pool"),
                         ("ci/cd pipelines", "ci-cd-pipelines"),
                         ("  Automatic-Failover ", "automatic-failover"),
                         ('"Terraform”', "terraform")]:
        got = fm.normalize_tag(phrase)
        assert got == want, f"{phrase!r} -> {got!r}"
        assert reindex.safe_tag(got), f"{got!r} must survive the path-safety check"


def test_normalize_tag_strips_trailing_junk_the_model_emits():
    assert fm.normalize_tag('automatic-failover”,  ') == "automatic-failover"
    assert fm.normalize_tag("scaling.") == "scaling"


def test_normalize_tag_never_yields_a_traversal():
    import reindex
    for hostile in ("../../../pwned", "..", "/etc/passwd", "a/../b"):
        got = fm.normalize_tag(hostile)
        assert not got or reindex.safe_tag(got), f"{hostile!r} -> {got!r}"


# --- tag() ------------------------------------------------------------------

def _tagging_sdk(reply, sleep=None):
    mod = types.ModuleType("apple_fm_sdk")

    class Session:
        def __init__(self, *a, **kw):
            pass

        async def respond(self, text):
            if sleep:
                import asyncio as _a
                await _a.sleep(sleep)
            return reply

    class Model:
        def __init__(self, *a, **kw):
            pass

        @property
        def context_size(self):
            return 8192

        async def token_count(self, text):
            return len(text) // 4

    mod.SystemLanguageModel = Model
    mod.LanguageModelSession = Session
    mod.SystemLanguageModelUseCase = types.SimpleNamespace(CONTENT_TAGGING=1)
    return mod


def test_tag_parses_dedupes_and_slugs(monkeypatch):
    monkeypatch.setattr(fm, "_guard_ok", lambda: True)
    monkeypatch.setitem(sys.modules, "apple_fm_sdk",
                        _tagging_sdk('ElastiCache, Redis, redis, "Terraform”, connection pool, '))
    assert fm.tag("a real note body") == [
        "elasticache", "redis", "terraform", "connection-pool"]


def test_tag_respects_max_tags(monkeypatch):
    monkeypatch.setattr(fm, "_guard_ok", lambda: True)
    monkeypatch.setitem(sys.modules, "apple_fm_sdk", _tagging_sdk("a, b, c, d, e"))
    assert fm.tag("body", max_tags=3) == ["a", "b", "c"]


def test_tag_returns_none_on_timeout(monkeypatch):
    """Proves the wrapper maps a TimeoutError to a fallback — NOT that the real
    native call is cancellable. asyncio.sleep is cooperative by construction;
    the real binding was verified separately (see module docstring)."""
    monkeypatch.setattr(fm, "_guard_ok", lambda: True)
    monkeypatch.setitem(sys.modules, "apple_fm_sdk", _tagging_sdk("x", sleep=5))
    assert fm.tag("body", timeout=0.05) is None


def test_tag_skips_when_the_machine_is_busy(monkeypatch):
    """Parity with gen.sh: an unattended job must not fight the user for the Mac."""
    monkeypatch.setattr(fm, "_guard_ok", lambda: False)
    called = []
    monkeypatch.setitem(sys.modules, "apple_fm_sdk", _tagging_sdk("a, b"))
    monkeypatch.setattr(fm, "_audit", lambda m: called.append(m))
    assert fm.tag("body") is None
    assert any("guard" in c for c in called)


def test_tag_audits_every_outcome(monkeypatch):
    """Silent fallback forever is the failure this repo keeps re-learning."""
    monkeypatch.setattr(fm, "_guard_ok", lambda: True)
    lines = []
    monkeypatch.setattr(fm, "_audit", lambda m: lines.append(m))
    monkeypatch.setattr(fm, "_transcript", lambda *a: None)
    monkeypatch.setitem(sys.modules, "apple_fm_sdk", _tagging_sdk("a, b"))
    fm.tag("body")
    assert any(m.startswith("ok:") for m in lines)

    lines.clear()
    monkeypatch.setitem(sys.modules, "apple_fm_sdk", _tagging_sdk("x", sleep=5))
    fm.tag("body", timeout=0.05)
    assert any("timeout" in m for m in lines)


def test_tag_writes_a_transcript(monkeypatch):
    """On-device is not the same as auditable — gen.sh parity."""
    monkeypatch.setattr(fm, "_guard_ok", lambda: True)
    seen = {}
    monkeypatch.setattr(fm, "_audit", lambda m: None)
    monkeypatch.setattr(fm, "_transcript",
                        lambda p, r, m: seen.update(prompt=p, response=r))
    monkeypatch.setitem(sys.modules, "apple_fm_sdk", _tagging_sdk("a, b"))
    fm.tag("the note body")
    assert seen["prompt"] == "the note body" and seen["response"] == "a, b"


def test_tag_truncates_oversized_input(monkeypatch):
    """Overflow must be deterministic and logged, not another indistinguishable
    None."""
    monkeypatch.setattr(fm, "_guard_ok", lambda: True)
    lines = []
    monkeypatch.setattr(fm, "_audit", lambda m: lines.append(m))
    sent = {}
    monkeypatch.setattr(fm, "_transcript", lambda p, r, m: sent.update(prompt=p))
    monkeypatch.setitem(sys.modules, "apple_fm_sdk", _tagging_sdk("a"))
    huge = "word " * 20000                      # ~25k tokens at the fake's len//4
    fm.tag(huge)
    assert any("truncated" in m for m in lines)
    assert len(sent["prompt"]) < len(huge)


def test_tag_ignores_empty_input():
    assert fm.tag("") is None and fm.tag("   ") is None


def test_timeout_is_read_per_call_not_frozen_at_import(monkeypatch):
    """The .env incident: config that looks set but was baked in at import."""
    monkeypatch.setenv("PLASMIE_FM_TIMEOUT", "7.5")
    assert fm._default_timeout() == 7.5
    monkeypatch.setenv("PLASMIE_FM_TIMEOUT", "nonsense")
    assert fm._default_timeout() == 20.0


# --- generate() ---------------------------------------------------------------

def _general_sdk(reply, tokens=100, snaps=None, sleep=None):
    mod = _tagging_sdk(reply, sleep=sleep)
    Model = mod.SystemLanguageModel

    class Session(mod.LanguageModelSession):
        async def respond(self, text, options=None):
            if sleep:
                import asyncio as _a
                await _a.sleep(sleep)
            return reply

        async def stream_response(self, text, options=None):
            for s in snaps or [reply]:
                yield s

    class Big(Model):
        async def token_count(self, text):
            return tokens

    mod.SystemLanguageModel = Big
    mod.LanguageModelSession = Session
    mod.GenerationOptions = lambda **kw: kw
    mod.SamplingMode = types.SimpleNamespace(greedy=lambda: "greedy")
    return mod


def test_generate_returns_text(monkeypatch):
    monkeypatch.setattr(fm, "_guard_ok", lambda: True)
    monkeypatch.setitem(sys.modules, "apple_fm_sdk", _general_sdk("  - a bullet\n"))
    assert fm.generate("prompt") == "- a bullet"


def test_generate_streams_deltas_not_cumulative_snapshots(monkeypatch):
    """The real SDK yields '1,2' then '1,2,3' — on_chunk must get only the new part."""
    monkeypatch.setattr(fm, "_guard_ok", lambda: True)
    monkeypatch.setitem(sys.modules, "apple_fm_sdk",
                        _general_sdk("", snaps=["1,2", "1,2,3", "1,2,3", "1,2,3,4"]))
    got = []
    assert fm.generate("p", on_chunk=got.append) == "1,2,3,4"
    assert got == ["1,2", ",3", ",4"]


def test_generate_over_budget_falls_back_instead_of_truncating(monkeypatch):
    """The question sits at the END of an ask prompt; trimming it would answer
    a question nobody asked. None -> the caller's Gemma path."""
    monkeypatch.setattr(fm, "_guard_ok", lambda: True)
    lines = []
    monkeypatch.setattr(fm, "_audit", lambda m: lines.append(m))
    monkeypatch.setitem(sys.modules, "apple_fm_sdk", _general_sdk("x", tokens=9000))
    assert fm.generate("p") is None
    assert any("budget" in m for m in lines)


def test_generate_none_on_timeout_busy_and_empty(monkeypatch):
    monkeypatch.setattr(fm, "_guard_ok", lambda: True)
    monkeypatch.setitem(sys.modules, "apple_fm_sdk", _general_sdk("x", sleep=5))
    assert fm.generate("p", timeout=0.05) is None
    monkeypatch.setattr(fm, "_guard_ok", lambda: False)
    assert fm.generate("p") is None
    assert fm.generate("   ") is None


def test_generate_guard_false_skips_the_background_guard(monkeypatch):
    """Interactive asks must not be refused by the busy/hot guard."""
    monkeypatch.setattr(fm, "_guard_ok", lambda: False)
    monkeypatch.setitem(sys.modules, "apple_fm_sdk", _general_sdk("answer"))
    assert fm.generate("p") is None
    assert fm.generate("p", guard=False) == "answer"


def test_context_size_reads_live_value(monkeypatch):
    monkeypatch.setitem(sys.modules, "apple_fm_sdk", _fake_sdk(True, context_size=4096))
    assert fm.context_size() == 4096
    monkeypatch.setitem(sys.modules, "apple_fm_sdk", _fake_sdk(False, _Reason("MODEL_NOT_READY")))
    assert fm.context_size() is None
