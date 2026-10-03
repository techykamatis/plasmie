#!/usr/bin/env python3
"""Tests for the Apple Foundation Models chokepoint (fm.py) over the plasmie-fm helper.

`fake_fm` (conftest.py) is a real executable speaking plasmie-fm's JSON protocol,
so these cover fm.py's subprocess plumbing end to end: probe mapping, streamed
deltas, timeouts, error codes, audit and transcript. Facts only the real model
can establish (that it answers, its live context size) are checked by the
helper smoke test and the promote dry-run recorded in ADR 0025.

Usage:  pytest test_fm.py
"""
import importlib.util
import pathlib
import sys
import types

import pytest

import fm


@pytest.fixture(autouse=True)
def _isolate(tmp_path, monkeypatch):
    """Never write into the real logs, and never find a real helper or SDK by
    accident: a test-generated "timeout" line in the audit log would misdirect
    a real investigation later."""
    monkeypatch.setattr(fm, "LOGS", tmp_path / "logs")
    monkeypatch.setenv("PLASMIE_FM_BIN", str(tmp_path / "no-such-helper"))
    monkeypatch.setitem(sys.modules, "apple_fm_sdk", None)


def _load_doctor():
    """plasmie-doctor.py has a hyphen, so it loads by path rather than by import."""
    spec = importlib.util.spec_from_file_location(
        "plasmie_doctor", pathlib.Path(__file__).with_name("plasmie-doctor.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# --- finding the helper -------------------------------------------------------

def test_env_override_wins_and_a_missing_one_is_not_silently_replaced(fake_fm, monkeypatch, tmp_path):
    assert fm.helper_path() == fake_fm.bin
    monkeypatch.setenv("PLASMIE_FM_BIN", str(tmp_path / "gone"))
    assert fm.helper_path() is None        # an explicit path that's missing is a fault


def test_bundle_layout_is_found(tmp_path, monkeypatch):
    """Installed: the engine runs from Plasmie.app/Contents/Resources/backend and the
    helper sits in Contents/MacOS."""
    app = tmp_path / "Plasmie.app" / "Contents"
    (app / "Resources" / "backend").mkdir(parents=True)
    (app / "MacOS").mkdir()
    helper = app / "MacOS" / "plasmie-fm"
    helper.write_text("#!/bin/sh\n")
    helper.chmod(0o755)
    monkeypatch.delenv("PLASMIE_FM_BIN")
    monkeypatch.setattr(fm, "SELF", app / "Resources" / "backend")
    assert fm.helper_path() == str(helper)


# --- probe --------------------------------------------------------------------

def test_missing_helper_says_how_to_fix_it():
    p = fm.probe()
    assert p["installed"] is False and p["available"] is False
    assert p["reason"] == "HELPER_MISSING" and "reinstall" in p["hint"].lower()
    assert p["context_size"] is None


def test_available_reports_live_context_size(fake_fm):
    fake_fm.set(probe={"status": "available", "context_size": 4096})
    p = fm.probe()
    assert p["available"] is True and p["reason"] is None
    assert p["context_size"] == 4096 and "4096" in p["detail"]
    assert fm.context_size() == 4096 and fm.available() is True


def test_each_unavailable_status_gets_an_actionable_hint(fake_fm):
    for status, reason in (("appleIntelligenceNotEnabled", "APPLE_INTELLIGENCE_NOT_ENABLED"),
                           ("deviceNotEligible", "DEVICE_NOT_ELIGIBLE"),
                           ("modelNotReady", "MODEL_NOT_READY"),
                           ("unsupportedOS", "UNSUPPORTED_OS"),
                           ("somethingNew", "UNKNOWN")):
        fake_fm.set(probe={"status": status})
        p = fm.probe()
        assert p["available"] is False and p["reason"] == reason, status
        assert p["hint"], f"{status} left the user with no next step"
        assert fm.context_size() is None
    assert "System Settings" in fm._REASON_HINT["APPLE_INTELLIGENCE_NOT_ENABLED"]
    assert "'somethingNew'" in p["detail"]       # an unmapped status stays diagnosable


def test_a_helper_that_answers_garbage_is_a_probe_failure(tmp_path, monkeypatch):
    bad = tmp_path / "plasmie-fm"
    bad.write_text("#!/bin/sh\necho not-json\n")
    bad.chmod(0o755)
    monkeypatch.setenv("PLASMIE_FM_BIN", str(bad))
    p = fm.probe()
    assert p["available"] is None and p["reason"] == "PROBE_FAILED"


def test_available_never_raises(monkeypatch):
    monkeypatch.setattr(fm, "probe", lambda: (_ for _ in ()).throw(OSError("boom")))
    assert fm.available() is False and fm.context_size() is None


# --- plasmie-doctor surfacing --------------------------------------------------------

def test_doctor_reports_not_set_up_as_unknown_not_broken(monkeypatch):
    """Apple Intelligence off, or still downloading, is not an error to paint red."""
    doctor = _load_doctor()
    for reason in ("APPLE_INTELLIGENCE_NOT_ENABLED", "MODEL_NOT_READY"):
        monkeypatch.setattr(fm, "probe", lambda reason=reason: {
            "available": False, "reason": reason, "detail": "off", "hint": "turn it on",
            "context_size": None})
        r = doctor.check_foundationmodels()
        assert r["configured"] is False and r["ok"] is None, reason


def test_doctor_reports_real_faults_as_failures(monkeypatch):
    """A Mac that can't run it, a broken install and a silent probe are faults:
    filing them as 'not set up' is the phantom-green this file exists to prevent."""
    doctor = _load_doctor()
    for reason in ("DEVICE_NOT_ELIGIBLE", "UNSUPPORTED_OS", "HELPER_MISSING",
                   "PROBE_FAILED", "UNKNOWN"):
        monkeypatch.setattr(fm, "probe", lambda reason=reason: {
            "available": False, "reason": reason, "detail": "d", "hint": "h",
            "context_size": None})
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

def test_tag_uses_the_tagging_model_and_slugs_its_answer(fake_fm):
    fake_fm.set(reply={"text": 'ElastiCache, Redis, redis, "Terraform”, connection pool, '})
    assert fm.tag("a real note body") == ["elasticache", "redis", "terraform", "connection-pool"]
    assert fake_fm.requests()[-1]["use_case"] == "content_tagging"


def test_tag_respects_max_tags(fake_fm):
    fake_fm.set(reply={"text": "a, b, c, d, e"})
    assert fm.tag("body", max_tags=3) == ["a", "b", "c"]


def test_tag_returns_none_on_timeout_and_audits_it(fake_fm, monkeypatch):
    lines = []
    monkeypatch.setattr(fm, "_audit", lines.append)
    fake_fm.set(reply={"text": "x"}, sleep=5)
    assert fm.tag("body", timeout=0.5) is None
    assert any("timeout" in m for m in lines)


def test_tag_skips_when_the_machine_is_busy(fake_fm, monkeypatch):
    """An unattended job must not fight the user for the Mac."""
    monkeypatch.setattr(fm, "_guard_ok", lambda: False)
    lines = []
    monkeypatch.setattr(fm, "_audit", lines.append)
    assert fm.tag("body") is None
    assert any("guard" in m for m in lines) and fake_fm.requests() == []


def test_tag_writes_a_transcript(fake_fm, monkeypatch):
    """On-device is not the same as auditable."""
    seen = {}
    monkeypatch.setattr(fm, "_transcript", lambda p, r, m: seen.update(prompt=p, response=r))
    fake_fm.set(reply={"text": "a, b"})
    fm.tag("the note body")
    assert seen == {"prompt": "the note body", "response": "a, b"}


def test_tag_truncates_oversized_input_audibly(fake_fm, monkeypatch):
    lines = []
    monkeypatch.setattr(fm, "_audit", lines.append)
    fake_fm.set(probe={"status": "available", "context_size": 4096}, reply={"text": "a"})
    huge = "word " * 20000
    fm.tag(huge)
    assert any("truncated" in m for m in lines)
    assert len(fake_fm.requests()[-1]["prompt"]) < len(huge)


def test_tag_ignores_empty_input(fake_fm):
    assert fm.tag("") is None and fm.tag("   ") is None and fake_fm.requests() == []


def test_timeout_is_read_per_call_not_frozen_at_import(monkeypatch):
    """The .env incident: config that looks set but was baked in at import."""
    monkeypatch.setenv("PLASMIE_FM_TIMEOUT", "7.5")
    assert fm._default_timeout() == 7.5
    monkeypatch.setenv("PLASMIE_FM_TIMEOUT", "nonsense")
    assert fm._default_timeout() == 20.0


# --- generate() / respond() ----------------------------------------------------

def test_generate_returns_stripped_text_and_sends_a_greedy_request(fake_fm):
    fake_fm.set(reply={"text": "  - a bullet\n"})
    assert fm.generate("prompt", max_tokens=300, instructions="be brief") == "- a bullet"
    req = fake_fm.requests()[-1]
    assert req["prompt"] == "prompt" and req["max_tokens"] == 300 and req["greedy"] is True
    assert req["instructions"] == "be brief" and req["guardrails"] == "default"
    assert req["stream"] is False


def test_permissive_selects_the_content_transformation_guardrails(fake_fm):
    fm.generate("summarise this", permissive=True)
    assert fake_fm.requests()[-1]["guardrails"] == "permissive"


def test_generate_streams_deltas(fake_fm):
    fake_fm.set(deltas=["1,", " 2,", " 3"], reply={"text": "1, 2, 3"})
    got = []
    assert fm.generate("p", on_chunk=got.append) == "1, 2, 3"
    assert got == ["1,", " 2,", " 3"] and fake_fm.requests()[-1]["stream"] is True


def test_over_budget_is_none_not_truncation_and_is_audited(fake_fm, monkeypatch):
    """The question sits at the END of an ask prompt; trimming it would answer
    a question nobody asked."""
    lines = []
    monkeypatch.setattr(fm, "_audit", lines.append)
    fake_fm.set(reply={"error": "over_budget", "tokens": 9000, "context_size": 8192,
                       "reason": "too long"})
    assert fm.generate("p") is None
    assert any("budget" in m for m in lines)
    assert fm.respond("p")["error"] == "over_budget"     # map-reduce callers see the code


def test_error_codes_pass_through_respond(fake_fm):
    for code in ("guardrail", "refusal", "context_exceeded", "unavailable"):
        fake_fm.set(reply={"error": code, "reason": "r"})
        assert fm.respond("p")["error"] == code
        assert fm.generate("p") is None


def test_none_on_timeout_busy_and_empty(fake_fm, monkeypatch):
    fake_fm.set(reply={"text": "x"}, sleep=5)
    assert fm.generate("p", timeout=0.5) is None
    assert fm.respond("p", timeout=0.5)["error"] == "timeout"
    monkeypatch.setattr(fm, "_guard_ok", lambda: False)
    assert fm.respond("p")["error"] == "busy"
    assert fm.respond("   ")["error"] == "empty"


def test_guard_false_skips_the_background_guard(fake_fm, monkeypatch):
    """Interactive asks must not be refused by the busy/hot guard."""
    monkeypatch.setattr(fm, "_guard_ok", lambda: False)
    fake_fm.set(reply={"text": "answer"})
    assert fm.generate("p") is None
    assert fm.generate("p", guard=False) == "answer"


def test_generate_without_any_backend_is_none(monkeypatch):
    assert fm.respond("p", guard=False) == {"error": "unavailable", "reason": "helper_missing"}


def test_transcript_records_instructions_and_prompt(fake_fm, monkeypatch):
    seen = {}
    monkeypatch.setattr(fm, "_transcript", lambda p, r, m: seen.update(prompt=p, response=r))
    fake_fm.set(reply={"text": "out"})
    fm.generate("the data", instructions="the rules")
    assert "the rules" in seen["prompt"] and "the data" in seen["prompt"]


def test_count_tokens_uses_the_model_then_falls_back_to_the_estimate(fake_fm, monkeypatch):
    assert fm.count_tokens("x" * 400) == 100
    monkeypatch.setenv("PLASMIE_FM_BIN", "/nonexistent")
    assert fm.count_tokens("x" * 300) == fm.estimate_tokens("x" * 300) == 101


# --- the busy guard -------------------------------------------------------------

def test_machine_busy_reads_thermal_load_and_memory(monkeypatch):
    out = {"pmset": "No thermal warning level has been recorded",
           "memory_pressure": "System-wide memory free percentage: 64%"}
    monkeypatch.setattr(fm, "_run", lambda cmd, t: out[cmd[0]])
    monkeypatch.setattr(fm.os, "getloadavg", lambda: (0.5, 0, 0))
    assert fm.machine_busy() is False
    out["pmset"] = "CPU_Speed_Limit\nThermal warning level 2 recorded"
    assert fm.machine_busy() is True
    out["pmset"] = ""
    out["memory_pressure"] = "System-wide memory free percentage: 9%"
    assert fm.machine_busy() is True
    out["memory_pressure"] = ""
    monkeypatch.setattr(fm.os, "getloadavg", lambda: (999.0, 0, 0))
    assert fm.machine_busy() is True


def test_a_broken_guard_never_blocks_the_pipeline(monkeypatch):
    monkeypatch.setattr(fm, "machine_busy", lambda: 1 / 0)
    assert fm._guard_ok() is True


# --- dev fallback: Apple's Python SDK, only when no helper is present --------------

def _sdk(reply="from the sdk", available=True):
    mod = types.ModuleType("apple_fm_sdk")

    class Model:
        def __init__(self, *a, **kw):
            pass

        def is_available(self):
            return (available, types.SimpleNamespace(name="APPLE_INTELLIGENCE_NOT_ENABLED"))

        context_size = 8192

        async def token_count(self, text):
            return len(text) // 4

    class Session:
        def __init__(self, *a, **kw):
            pass

        async def respond(self, text, options=None):
            return reply

    mod.SystemLanguageModel = Model
    mod.LanguageModelSession = Session
    mod.SystemLanguageModelUseCase = types.SimpleNamespace(CONTENT_TAGGING=1)
    mod.GenerationOptions = lambda **kw: kw
    mod.SamplingMode = types.SimpleNamespace(greedy=lambda: "greedy")
    return mod


def test_sdk_fallback_is_used_only_without_a_helper(monkeypatch):
    monkeypatch.setitem(sys.modules, "apple_fm_sdk", _sdk())
    assert fm.probe()["backend"] == "apple-fm-sdk" and fm.context_size() == 8192
    assert fm.generate("p", guard=False) == "from the sdk"
    monkeypatch.setitem(sys.modules, "apple_fm_sdk", _sdk(available=False))
    assert fm.probe()["reason"] == "APPLE_INTELLIGENCE_NOT_ENABLED"
