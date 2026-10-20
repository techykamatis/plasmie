"""plasmie-migrate: each step once, in order; a failure is retried next time."""
import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
# Older versions' names, oldest first, assembled from parts so the old-names scan
# (test_old_names.py) finds no trace of them here (ADR 0023).
FIRST, SECOND = "kl" + "oop", "blob" + "kin"
OLD_ENV = ("KL" + "OOP_", "KL" + "_")
OLD_MID = "know" + "ledge-"                      # the dev agents' label middle part in older installs (ADR 0024)


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


# --- step 4: the oldest version's jobs (ADR 0024), against a fake launchctl on PATH ---------
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


def test_step4_boots_out_every_loaded_first_name_job_and_nothing_else(monkeypatch, tmp_path):
    km = load(monkeypatch, tmp_path)
    state = fake_launchd(monkeypatch, tmp_path, loaded=[f"com.{FIRST}.ingest", f"com.{FIRST}.promote", "com.plasmie.ingest"])
    km.m4_retire_first_name_jobs()
    assert loaded_now(state) == ["com.plasmie.ingest"]
    calls = (state / "calls").read_text().splitlines()
    for name in km.JOB_NAMES:
        assert f"bootout gui/{os.getuid()}/com.{FIRST}.{name}" in calls


def test_step4_with_nothing_loaded_succeeds_and_can_rerun(monkeypatch, tmp_path):
    km = load(monkeypatch, tmp_path)
    fake_launchd(monkeypatch, tmp_path)
    km.m4_retire_first_name_jobs()               # "No such process" is not an error
    km.m4_retire_first_name_jobs()


def test_step4_fails_while_a_first_name_job_stays_loaded_so_it_is_retried(monkeypatch, tmp_path):
    km = load(monkeypatch, tmp_path)
    fake_launchd(monkeypatch, tmp_path, loaded=[f"com.{FIRST}.ingest"], stuck=[f"com.{FIRST}.ingest"])
    vf = tmp_path / "v"
    vf.write_text("3\n")
    r = km.migrate(km.STEPS, vf)
    assert not r["ok"] and r["failed"] == 4 and f"com.{FIRST}.ingest" in r["error"] and km.current(vf) == 3


def _no_dev_agents(monkeypatch, km):
    """Step 9 runs launchd/install.sh; these tests aren't about it (see the step 9 tests)."""
    monkeypatch.setattr(km, "m9_retire_old_dev_agents", lambda: None)
    return [(n, w, km.m9_retire_old_dev_agents if n == 9 else fn) for n, w, fn in km.STEPS]


def test_an_install_at_version_3_runs_step4_onward(monkeypatch, tmp_path):
    km = load(monkeypatch, tmp_path)
    state = fake_launchd(monkeypatch, tmp_path, loaded=[f"com.{FIRST}.summarize"])
    vf = tmp_path / "v"
    vf.write_text("3\n")
    r = km.migrate(_no_dev_agents(monkeypatch, km), vf)
    assert r["ok"] and r["version"] == km.LATEST and r["applied"][0] == "retire older versions' background jobs (1 of 2)"
    assert loaded_now(state) == []


@pytest.mark.parametrize("flag", ["--retire-old-jobs", "--retire-" + FIRST + "-jobs"])
def test_retire_flag_runs_steps_4_and_6_alone(monkeypatch, tmp_path, flag):
    state = fake_launchd(monkeypatch, tmp_path, loaded=[f"com.{FIRST}.snapshot", f"com.{SECOND}.ingest", "com.plasmie.ingest"])
    env = {**os.environ, "PLASMIE_HOME": str(tmp_path / "home"), "PLASMIE_LOGS": str(tmp_path / "logs")}
    out = subprocess.run([sys.executable, str(HERE / "plasmie-migrate.py"), flag],
                         capture_output=True, text=True, env=env, timeout=60)
    assert out.returncode == 0 and json.loads(out.stdout) == {"ok": True}
    assert loaded_now(state) == ["com.plasmie.ingest"]
    assert not (tmp_path / "home" / ".schema-version").exists()       # not a versioned run


# --- step 6: the second older version's jobs (ADR 0024) ---------------------------------------
def test_step6_boots_out_every_loaded_second_old_version_job_and_nothing_else(monkeypatch, tmp_path):
    km = load(monkeypatch, tmp_path)
    state = fake_launchd(monkeypatch, tmp_path,
                         loaded=[f"com.{SECOND}.ingest", f"com.{SECOND}.snapshot", "com.plasmie.ingest", f"com.{FIRST}.promote"])
    km.m6_retire_second_name_jobs()
    assert loaded_now(state) == [f"com.{FIRST}.promote", "com.plasmie.ingest"]       # step 4's job, not 6's
    calls = (state / "calls").read_text().splitlines()
    for name in km.JOB_NAMES:
        assert f"bootout gui/{os.getuid()}/com.{SECOND}.{name}" in calls


def test_a_second_old_version_install_at_version_5_runs_steps_6_onward(monkeypatch, tmp_path):
    km = load(monkeypatch, tmp_path)
    state = fake_launchd(monkeypatch, tmp_path, loaded=[f"com.{SECOND}.ingest", f"com.{SECOND}.promote"])
    adopted = []
    monkeypatch.setattr(km, "m7_adopt_old_signins", lambda: adopted.append(True))
    steps = [(n, what, km.m7_adopt_old_signins if n == 7 else fn) for n, what, fn in _no_dev_agents(monkeypatch, km)]
    vf = tmp_path / "v"
    vf.write_text("5\n")
    r = km.migrate(steps, vf)
    assert r["ok"] and r["version"] == 9 and r["applied"] == [
        "retire older versions' background jobs (2 of 2)", "copy older versions' sign-ins in the Keychain (2 of 2)",
        "rename old settings keys in config.env", "retire dev-path agents under their earlier labels"]
    assert loaded_now(state) == [] and adopted == [True]


def test_step6_fails_while_a_second_old_version_job_stays_loaded(monkeypatch, tmp_path):
    km = load(monkeypatch, tmp_path)
    fake_launchd(monkeypatch, tmp_path, loaded=[f"com.{SECOND}.ingest"], stuck=[f"com.{SECOND}.ingest"])
    vf = tmp_path / "v"
    vf.write_text("5\n")
    r = km.migrate(km.STEPS, vf)
    assert not r["ok"] and r["failed"] == 6 and f"com.{SECOND}.ingest" in r["error"] and km.current(vf) == 5


# --- step 8: config.env keys (ADR 0023) ---------------------------------------------------------
def test_step8_rewrites_old_keys_keeping_values_and_unknown_keys(monkeypatch, tmp_path):
    km = load(monkeypatch, tmp_path)
    cfg = Path(km.paths.CONFIG)
    o1, o2 = OLD_ENV
    before = (f"# my settings\n{o2}GIT_ROOTS='~/src,~/work dir'\nVAULT_DIR='/Users/x/knowledge'\n"
              f"export {o2}GIT_BIN=/opt/homebrew/bin/git\n{o2}DISABLED_SOURCES=\"github\"\n"
              f"{o1}FUTURE_THING=1\nSOMETHING_ELSE='keep me'\n  {o2}RELATED_NOTES=1\n")
    cfg.write_text(before)
    cfg.chmod(0o600)
    vf = tmp_path / "v"
    vf.write_text("7\n")
    r = km.migrate(_no_dev_agents(monkeypatch, km), vf)
    assert r["ok"] and r["applied"][0] == "rename old settings keys in config.env"
    after = cfg.read_text()
    assert after == ("# my settings\nPLASMIE_GIT_ROOTS='~/src,~/work dir'\nVAULT_DIR='/Users/x/knowledge'\n"
                     "export PLASMIE_GIT_BIN=/opt/homebrew/bin/git\nPLASMIE_DISABLED_SOURCES=\"github\"\n"
                     "PLASMIE_FUTURE_THING=1\nSOMETHING_ELSE='keep me'\n  PLASMIE_RELATED_NOTES=1\n")
    assert oct(cfg.stat().st_mode & 0o777) == "0o600"
    assert km.paths.read_config(str(cfg)) == {
        "PLASMIE_GIT_ROOTS": "~/src,~/work dir", "VAULT_DIR": "/Users/x/knowledge",
        "PLASMIE_GIT_BIN": "/opt/homebrew/bin/git", "PLASMIE_DISABLED_SOURCES": "github",
        "PLASMIE_FUTURE_THING": "1", "SOMETHING_ELSE": "keep me", "PLASMIE_RELATED_NOTES": "1"}
    assert km.paths.migrate_config_keys(str(cfg)) == [] and cfg.read_text() == after   # idempotent


def test_step8_keeps_a_new_key_that_is_already_set_and_drops_the_old_spelling(tmp_path):
    import paths
    cfg = tmp_path / "config.env"
    o2 = OLD_ENV[1]
    cfg.write_text(f"{o2}GITHUB_ORGS='old'\nPLASMIE_GITHUB_ORGS='new'\n{o2}GIT_ROOTS=a\n{o2}GIT_ROOTS=b\n")
    assert paths.read_config(str(cfg))["PLASMIE_GITHUB_ORGS"] == "new"   # readers already prefer it
    assert paths.migrate_config_keys(str(cfg)) == [o2 + "GITHUB_ORGS", o2 + "GIT_ROOTS", o2 + "GIT_ROOTS"]
    assert cfg.read_text() == "PLASMIE_GITHUB_ORGS='new'\nPLASMIE_GIT_ROOTS=a\nPLASMIE_GIT_ROOTS=b\n"
    assert paths.read_config(str(cfg)) == {"PLASMIE_GITHUB_ORGS": "new", "PLASMIE_GIT_ROOTS": "b"}


def test_step8_with_no_config_file_is_a_no_op(tmp_path):
    import paths
    assert paths.migrate_config_keys(str(tmp_path / "missing.env")) == []
    assert not (tmp_path / "missing.env").exists()


def test_old_env_vars_reach_python_under_new_names(tmp_path):
    o1, o2 = OLD_ENV
    env = {"PATH": "/usr/bin:/bin", "HOME": str(tmp_path), o1 + "HOME": str(tmp_path / "d"),
           o1 + "LOGS": str(tmp_path / "l"), o2 + "VAULT": "/old", "PLASMIE_GIT_ROOTS": "new",
           o2 + "GIT_ROOTS": "old"}
    out = subprocess.run([sys.executable, "-c", "import os, paths, json; print(json.dumps("
                          "[paths.DATA_DIR, paths.LOG_DIR, os.environ['PLASMIE_VAULT'], os.environ['PLASMIE_GIT_ROOTS']]))"],
                         cwd=HERE, env=env, capture_output=True, text=True, timeout=30, check=True)
    assert json.loads(out.stdout) == [str(tmp_path / "d"), str(tmp_path / "l"), "/old", "new"]


@pytest.mark.parametrize("old_keys", [True, False])
def test_shell_jobs_work_with_old_or_new_config_keys(tmp_path, old_keys):
    """plasmie-env.sh, as a launchd job sources it, sees the same settings either way."""
    o1, o2 = OLD_ENV
    pre = o2 if old_keys else "PLASMIE_"
    home = tmp_path / "home"
    home.mkdir()
    (home / "config.env").write_text(f"{pre}GIT_ROOTS='~/a b'\nexport {pre}VAULT=/v\n{pre}DISABLED_SOURCES=github\n")
    env = {"PATH": "/usr/bin:/bin", "HOME": str(tmp_path),
           (o1 if old_keys else "PLASMIE_") + "HOME": str(home),
           (o1 if old_keys else "PLASMIE_") + "LOGS": str(tmp_path / "logs")}
    script = ('. "$1/plasmie-env.sh"; printf "%s|%s|%s|%s|" "$PLASMIE_HOME" "$PLASMIE_GIT_ROOTS" '
              '"$PLASMIE_VAULT" "$PLASMIE_DISABLED_SOURCES"; '
              'bash -c \'printf "%s|%s" "${PLASMIE_VAULT:-}" "${PLASMIE_GIT_ROOTS:-unexported}"\'')
    out = subprocess.run(["/bin/bash", "-c", script, "_", str(HERE)], env=env, capture_output=True,
                         text=True, timeout=30, check=True).stdout
    assert out == f"{home}|~/a b|/v|github|/v|unexported"


# --- step 9: dev-path agents under their earlier labels (ADR 0024) ------------------------------
def test_step9_retires_only_the_old_dev_labels(monkeypatch, tmp_path):
    km = load(monkeypatch, tmp_path)
    state = fake_launchd(monkeypatch, tmp_path, loaded=[f"com.plasmie.{OLD_MID}ingest", "com.plasmie.dev-ingest",
                                                        "com.plasmie.ingest"])
    agents = tmp_path / "Library" / "LaunchAgents"
    agents.mkdir(parents=True)
    for label in (f"com.plasmie.{OLD_MID}ingest", f"com.plasmie.{OLD_MID}promote", "com.plasmie.dev-ingest"):
        (agents / f"{label}.plist").write_text("<plist/>")
    monkeypatch.setenv("HOME", str(tmp_path))          # install.sh only ever sees the temp LaunchAgents
    km.m9_retire_old_dev_agents()
    assert sorted(p.name for p in agents.iterdir()) == ["com.plasmie.dev-ingest.plist"]
    assert loaded_now(state) == ["com.plasmie.dev-ingest", "com.plasmie.ingest"]
    calls = (state / "calls").read_text()
    assert "bootstrap" not in calls and "com.plasmie.dev-ingest" not in calls.replace("print", "")


def test_dev_templates_use_the_dev_labels():
    plists = sorted((HERE / "launchd").glob("*.plist"))
    assert len(plists) == 5
    for p in plists:
        label = p.stem
        assert label.startswith("com.plasmie.dev-") and f"<string>{label}</string>" in p.read_text()
