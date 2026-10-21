"""plasmie-status.py's reasons are what the island shows: plain words + a next step, never a
log code; a promote skipped because the Mac was busy is not an error."""
import json
import os
import subprocess
import sys

import pytest
from support import ENGINE, ROOT

HELPER = ROOT / "app/build/Plasmie.app/Contents/MacOS/plasmie-fm"
pytestmark = pytest.mark.skipif(not HELPER.exists(), reason="needs a built plasmie-fm (app/make-app.sh)")


def status(tmp_path, feed_lines, activity=""):
    home = tmp_path / "home"
    home.mkdir()
    (home / "feed.log").write_text("\n".join(feed_lines) + "\n")
    if activity:
        (home / ".status").write_text(f"{int(__import__('time').time())}|{activity}")
    env = {**os.environ, "PLASMIE_HOME": str(home), "PLASMIE_LOGS": str(tmp_path / "logs"),
           "PLASMIE_FM_BIN": str(HELPER)}
    out = subprocess.run([sys.executable, str(ENGINE / "plasmie-status.py")], env=env, capture_output=True, text=True)
    return json.loads(out.stdout)


def now_line(rest):
    import datetime
    return f"{datetime.datetime.now():%Y-%m-%d %H:%M:%S} | exit 0 | {rest}"


def test_error_reason_names_the_source_in_plain_words(tmp_path):
    s = status(tmp_path, [now_line("errors 1 | slack 0 convos · CONF-ERR Confluence creds not set")])
    assert s["state"] == "error"
    assert "Confluence" in s["reason"] and "CONF" not in s["reason"] and "Test" in s["reason"]


def test_busy_promote_skip_is_not_an_error(tmp_path):
    s = status(tmp_path, [now_line("errors 0 | slack 0 convos")], activity="Skipped — machine busy")
    assert not (s["state"] == "error" and "Promote" in s["reason"])
