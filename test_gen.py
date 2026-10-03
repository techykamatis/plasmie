#!/usr/bin/env python3
"""gen.sh must return as soon as the model answers, not when its watchdog expires.

Regression (2026-10-03): the watchdog `( sleep $to; kill ... ) &` inherited gen.sh's
stdout. Killing the subshell orphaned its `sleep`, which kept the pipe open, so every
`out="$(gen.sh ...)"` caller (promote.sh, summarize.sh) blocked for the full timeout —
"Promote now" sat on "Generating draft (~1–2 min)" for 8 minutes.

Runs the real gen.sh in a temp dir with stub mlx-ctl.sh / cc-local.sh.

Usage:  pytest test_gen.py
"""
import os
import shutil
import subprocess
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent


def _stage(tmp_path, answer_cmd):
    shutil.copy(HERE / "gen.sh", tmp_path / "gen.sh")
    (tmp_path / "logs").mkdir()
    (tmp_path / "mlx-ctl.sh").write_text('#!/bin/bash\n[ "$1" = guard ] && echo ok\nexit 0\n')
    (tmp_path / "cc-local.sh").write_text(f"#!/bin/bash\n{answer_cmd}\n")
    for f in ("gen.sh", "mlx-ctl.sh", "cc-local.sh"):
        os.chmod(tmp_path / f, 0o755)


def _call(tmp_path, timeout_secs):
    t0 = time.monotonic()
    r = subprocess.run(["bash", "-c", f'out="$("{tmp_path}/gen.sh" {timeout_secs} "hi")"; rc=$?; printf "%s" "$out"; exit $rc'],
                       capture_output=True, text=True, timeout=60)
    return r, time.monotonic() - t0


def test_fast_answer_returns_fast_even_with_a_long_watchdog(tmp_path):
    _stage(tmp_path, "echo 'a draft'")
    r, took = _call(tmp_path, 30)
    assert r.returncode == 0 and r.stdout == "a draft"
    assert took < 5, f"gen.sh held the caller for {took:.1f}s (watchdog kept the pipe open)"


def test_slow_model_is_still_killed_at_the_timeout(tmp_path):
    _stage(tmp_path, "sleep 20; echo late")
    r, took = _call(tmp_path, 2)
    assert r.returncode != 0 and "late" not in r.stdout
    assert took < 8
