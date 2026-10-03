"""plasmie-job.sh: background jobs get a hard time limit; the whole process group stops."""
import os
import subprocess
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent


def run(tmp_name, body, secs, tmp_path):
    script = HERE / tmp_name
    script.write_text(body)
    try:
        env = {**os.environ, "PLASMIE_JOB_SECS": str(secs), "PLASMIE_JOB_GRACE": "1"}
        t = time.time()
        r = subprocess.run([str(HERE / "plasmie-job.sh"), "1", tmp_name], env=env, capture_output=True, text=True,
                           timeout=60)
        return r, time.time() - t
    finally:
        script.unlink()


def test_overrunning_job_and_its_children_are_stopped(tmp_path):
    pidfile = tmp_path / "child.pid"
    r, took = run("plasmie-test-overrun.sh", f"sleep 300 &\necho $! > {pidfile}\nwait\n", 1, tmp_path)
    assert r.returncode == 124 and took < 10 and "time limit" in r.stderr
    time.sleep(0.5)
    child = int(pidfile.read_text())
    assert subprocess.run(["kill", "-0", str(child)]).returncode != 0      # child gone too


def test_exit_status_passes_through(tmp_path):
    r, _ = run("plasmie-test-exit.sh", "exit 7\n", 30, tmp_path)
    assert r.returncode == 7
