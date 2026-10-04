"""plasmie-migrate: each step once, in order; a failure is retried next time."""
import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent


def load(monkeypatch, tmp_path):
    monkeypatch.setenv("PLASMIE_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("PLASMIE_LOGS", str(tmp_path / "logs"))
    spec = importlib.util.spec_from_file_location("plasmie_migrate", HERE / "plasmie-migrate.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_steps_run_once_in_order(monkeypatch, tmp_path):
    km = load(monkeypatch, tmp_path)
    ran = []
    steps = [(1, "a", lambda: ran.append(1)), (2, "b", lambda: ran.append(2))]
    vf = tmp_path / "v"
    assert km.migrate(steps, vf) == {"ok": True, "version": 2, "latest": 2, "applied": ["a", "b"]}
    assert km.migrate(steps, vf)["applied"] == [] and ran == [1, 2]


def test_a_failed_step_stops_and_is_retried(monkeypatch, tmp_path):
    km = load(monkeypatch, tmp_path)
    calls = {"n": 0}

    def flaky():
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("disk busy")

    ran = []
    steps = [(1, "a", lambda: None), (2, "flaky", flaky), (3, "c", lambda: ran.append(3))]
    vf = tmp_path / "v"
    r = km.migrate(steps, vf)
    assert not r["ok"] and r["version"] == 1 and r["failed"] == 2 and ran == []
    r = km.migrate(steps, vf)
    assert r["ok"] and r["version"] == 3 and r["applied"] == ["flaky", "c"]


def test_registry_is_numbered_without_gaps():
    import ast
    tree = ast.parse((HERE / "plasmie-migrate.py").read_text())
    steps = next(n for n in ast.walk(tree) if isinstance(n, ast.Assign) and getattr(n.targets[0], "id", "") == "STEPS")
    nums = [e.elts[0].value for e in steps.value.elts]
    assert nums == list(range(1, len(nums) + 1))


# --- step 4: Plasmie's com.plasmie.* jobs (ADR 0027), against a fake launchctl on PATH ---------
FAKE_LAUNCHCTL = """#!/bin/bash
# loaded jobs are files in $FAKE_LAUNCHD; every call is logged
echo "$*" >> "$FAKE_LAUNCHD/calls"
label="${2##*/}"
case "$1" in
  bootout) [ -f "$FAKE_LAUNCHD/$label" ] || { echo "Boot-out failed: 3: No such process" >&2; exit 3; }
           [ -f "$FAKE_LAUNCHD/$label.stuck" ] || rm -f "$FAKE_LAUNCHD/$label" ;;
  print)   [ -f "$FAKE_LAUNCHD/$label" ] || { echo "Could not find service" >&2; exit 113; } ;;
esac
"""


def fake_launchd(monkeypatch, tmp_path, loaded=(), stuck=()):
    state, bin_ = tmp_path / "launchd", tmp_path / "bin"
    state.mkdir()
    bin_.mkdir()
    for label in loaded:
        (state / label).write_text("")
    for label in stuck:
        (state / f"{label}.stuck").write_text("")
    exe = bin_ / "launchctl"
    exe.write_text(FAKE_LAUNCHCTL)
    exe.chmod(0o755)
    monkeypatch.setenv("FAKE_LAUNCHD", str(state))
    monkeypatch.setenv("PATH", f"{bin_}:/usr/bin:/bin")
    return state


def loaded_now(state):
    return sorted(p.name for p in state.iterdir() if p.name != "calls" and not p.name.endswith(".stuck"))


def test_step4_boots_out_every_loaded_plasmie_job_and_nothing_else(monkeypatch, tmp_path):
    km = load(monkeypatch, tmp_path)
    state = fake_launchd(monkeypatch, tmp_path, loaded=["com.plasmie.ingest", "com.plasmie.promote", "com.plasmie.ingest"])
    km.m4_retire_plasmie_jobs()
    assert loaded_now(state) == ["com.plasmie.ingest"]
    calls = (state / "calls").read_text().splitlines()
    for name in km.PLASMIE_JOBS:
        assert f"bootout gui/{os.getuid()}/com.plasmie.{name}" in calls


def test_step4_with_nothing_loaded_succeeds_and_can_rerun(monkeypatch, tmp_path):
    km = load(monkeypatch, tmp_path)
    fake_launchd(monkeypatch, tmp_path)
    km.m4_retire_plasmie_jobs()                    # "No such process" is not an error
    km.m4_retire_plasmie_jobs()


def test_step4_fails_while_a_plasmie_job_stays_loaded_so_it_is_retried(monkeypatch, tmp_path):
    km = load(monkeypatch, tmp_path)
    fake_launchd(monkeypatch, tmp_path, loaded=["com.plasmie.ingest"], stuck=["com.plasmie.ingest"])
    vf = tmp_path / "v"
    vf.write_text("3\n")
    r = km.migrate(km.STEPS, vf)
    assert not r["ok"] and r["failed"] == 4 and "com.plasmie.ingest" in r["error"] and km.current(vf) == 3


def test_an_install_at_version_3_runs_step4_onward(monkeypatch, tmp_path):
    km = load(monkeypatch, tmp_path)
    state = fake_launchd(monkeypatch, tmp_path, loaded=["com.plasmie.summarize"])
    vf = tmp_path / "v"
    vf.write_text("3\n")
    r = km.migrate(km.STEPS, vf)
    assert r["ok"] and r["version"] == 7 and r["applied"][0] == "retire Plasmie's com.plasmie background jobs"
    assert loaded_now(state) == []


@pytest.mark.parametrize("flag", ["--retire-old-jobs", "--retire-plasmie-jobs"])
def test_retire_flag_runs_steps_4_and_6_alone(monkeypatch, tmp_path, flag):
    state = fake_launchd(monkeypatch, tmp_path, loaded=["com.plasmie.snapshot", "com.plasmie.ingest", "com.plasmie.ingest"])
    env = {**os.environ, "PLASMIE_HOME": str(tmp_path / "home"), "PLASMIE_LOGS": str(tmp_path / "logs")}
    out = subprocess.run([sys.executable, str(HERE / "plasmie-migrate.py"), flag],
                         capture_output=True, text=True, env=env, timeout=60)
    assert out.returncode == 0 and json.loads(out.stdout) == {"ok": True}
    assert loaded_now(state) == ["com.plasmie.ingest"]
    assert not (tmp_path / "home" / ".schema-version").exists()       # not a versioned run


# --- step 6: Plasmie's com.plasmie.* jobs (ADR 0028) ------------------------------------------
def test_step6_boots_out_every_loaded_plasmie_job_and_nothing_else(monkeypatch, tmp_path):
    km = load(monkeypatch, tmp_path)
    state = fake_launchd(monkeypatch, tmp_path,
                         loaded=["com.plasmie.ingest", "com.plasmie.snapshot", "com.plasmie.ingest", "com.plasmie.promote"])
    km.m6_retire_plasmie_jobs()
    assert loaded_now(state) == ["com.plasmie.promote", "com.plasmie.ingest"]       # step 4's job, not 6's
    calls = (state / "calls").read_text().splitlines()
    for name in km.PLASMIE_JOBS:
        assert f"bootout gui/{os.getuid()}/com.plasmie.{name}" in calls


def test_the_owners_plasmie_install_at_version_5_runs_steps_6_and_7(monkeypatch, tmp_path):
    km = load(monkeypatch, tmp_path)
    state = fake_launchd(monkeypatch, tmp_path, loaded=["com.plasmie.ingest", "com.plasmie.promote"])
    adopted = []
    monkeypatch.setattr(km, "m7_adopt_old_signins", lambda: adopted.append(True))
    steps = [(n, what, km.m7_adopt_old_signins if n == 7 else fn) for n, what, fn in km.STEPS]
    vf = tmp_path / "v"
    vf.write_text("5\n")
    r = km.migrate(steps, vf)
    assert r["ok"] and r["version"] == 7 and r["applied"] == [
        "retire Plasmie's com.plasmie background jobs", "copy Plasmie and Plasmie sign-ins in the Keychain"]
    assert loaded_now(state) == [] and adopted == [True]


def test_step6_fails_while_a_plasmie_job_stays_loaded(monkeypatch, tmp_path):
    km = load(monkeypatch, tmp_path)
    fake_launchd(monkeypatch, tmp_path, loaded=["com.plasmie.ingest"], stuck=["com.plasmie.ingest"])
    vf = tmp_path / "v"
    vf.write_text("5\n")
    r = km.migrate(km.STEPS, vf)
    assert not r["ok"] and r["failed"] == 6 and "com.plasmie.ingest" in r["error"] and km.current(vf) == 5
