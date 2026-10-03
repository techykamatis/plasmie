"""Test-session guards: the suite never touches the owner's real data or Keychain.

Set before any test module imports paths.py (which reads PLASMIE_HOME at import):
  - PLASMIE_HOME / PLASMIE_LOGS default to a throwaway folder when the runner didn't set them;
  - PLASMIE_KEYCHAIN points at a keychain file that doesn't exist, so a stray read finds
    nothing and a stray write fails, instead of reaching the login keychain
    (test_keychain.py swaps in a real throwaway keychain per test);
  - PLASMIE_LEGACY_ENV hides ~/.claude/.env from the one-time migration.
Subprocesses (loop-ingest.py in test_ingest.py) inherit all four.
"""
import os
import tempfile

_tmp = tempfile.mkdtemp(prefix="plasmie-tests-")
os.environ.setdefault("PLASMIE_HOME", os.path.join(_tmp, "home"))
os.environ.setdefault("PLASMIE_LOGS", os.path.join(_tmp, "logs"))
os.environ["PLASMIE_KEYCHAIN"] = os.path.join(_tmp, "no-such.keychain-db")
os.environ["PLASMIE_LEGACY_ENV"] = os.path.join(_tmp, "no-such.env")

# --- fake plasmie-fm helper -------------------------------------------------------
# Shared test fixtures. `fake_fm` stands in for the plasmie-fm helper.
# 
# The fake is a real executable speaking plasmie-fm's protocol (app/fm/main.swift),
# pointed at through $PLASMIE_FM_BIN, so tests exercise fm.py's actual subprocess
# plumbing — spawning, JSON in/out, streamed deltas, timeouts — not a mock of it.
# What it cannot prove is how the real model answers; that is the dry-run and
# `plasmie-fm` smoke test's job (docs/decisions/0021).

import json
import stat
import sys
import textwrap

import pytest

_FAKE = textwrap.dedent('''\
    import json, os, sys, time
    d = os.environ["FAKE_FM_DIR"]
    cfg = json.load(open(os.path.join(d, "cfg.json")))
    args = sys.argv[1:]
    probe = cfg.get("probe", {"status": "available", "context_size": 8192})
    if "--probe" in args:
        print(json.dumps(probe)); sys.exit(0 if probe.get("status") == "available" else 1)
    if "--check" in args:
        print(probe.get("status")); sys.exit(0 if probe.get("status") == "available" else 1)
    if "--context-size" in args:
        print(probe.get("context_size") or 4096); sys.exit(0)
    req = json.load(sys.stdin)
    with open(os.path.join(d, "requests.jsonl"), "a") as fh:
        fh.write(json.dumps(req) + "\\n")
    if cfg.get("sleep"):
        time.sleep(cfg["sleep"])
    if req.get("op") == "count":
        print(json.dumps({"tokens": len(req.get("prompt", "")) // 4, "context_size": 8192})); sys.exit(0)
    replies = cfg.get("replies")
    if replies:                                  # one scripted reply per call, in order
        n = sum(1 for _ in open(os.path.join(d, "requests.jsonl"))) - 1
        out = replies[min(n, len(replies) - 1)]
    else:
        out = cfg.get("reply", {"text": "ok"})
    if req.get("stream"):
        for delta in cfg.get("deltas", []):
            print(json.dumps({"delta": delta}), flush=True)
    print(json.dumps(out)); sys.exit(1 if "error" in out else 0)
''')


class FakeFM:
    def __init__(self, d):
        self.dir = d
        self.bin = os.path.join(d, "plasmie-fm")
        script = os.path.join(d, "fake_fm.py")
        with open(script, "w") as fh:
            fh.write(_FAKE)
        # A shim, not a shebang: the venv's python lives under "Application Support",
        # and a shebang path cannot contain a space.
        with open(self.bin, "w") as fh:
            fh.write(f'#!/bin/sh\nexec "{sys.executable}" "{script}" "$@"\n')
        os.chmod(self.bin, os.stat(self.bin).st_mode | stat.S_IXUSR)
        self.set()

    def set(self, **cfg):
        """reply={...} | replies=[...] | deltas=[...] | probe={...} | sleep=secs"""
        with open(os.path.join(self.dir, "cfg.json"), "w") as fh:
            json.dump(cfg, fh)
        return self

    def requests(self):
        p = os.path.join(self.dir, "requests.jsonl")
        return [json.loads(ln) for ln in open(p)] if os.path.exists(p) else []


@pytest.fixture
def fake_fm(tmp_path, monkeypatch):
    import fm
    d = tmp_path / "fakefm"
    d.mkdir()
    fake = FakeFM(str(d))
    monkeypatch.setenv("PLASMIE_FM_BIN", fake.bin)
    monkeypatch.setenv("FAKE_FM_DIR", str(d))
    monkeypatch.setattr(fm, "LOGS", tmp_path / "logs")
    monkeypatch.setattr(fm, "_guard_ok", lambda: True)
    return fake
