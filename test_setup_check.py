"""app-setup.sh --check: the first-run checklist the app renders (Setup.swift).

Apple Intelligence is a REQUIRED check answered by the bundled plasmie-fm helper
(ADR 0021); Claude Code is no longer a prerequisite. The CHECK line format is a
contract with SetupCheck.parse: CHECK:<id>:<ok|missing|warn>:<required|recommended>:<label>:<detail>.
"""
import os
import subprocess
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent


def _checks(tmp_path, fake_fm, status=None, helper=True):
    res = tmp_path / "Resources"
    res.mkdir(exist_ok=True)
    if not (res / "backend").exists():
        (res / "backend").symlink_to(HERE)
    if status:
        fake_fm.set(probe={"status": status, "context_size": 8192})
    env = {**os.environ, "PLASMIE_HOME": str(tmp_path / "home"), "PLASMIE_LOGS": str(tmp_path / "logs"),
           "PLASMIE_FM_BIN": fake_fm.bin if helper else str(tmp_path / "missing"),
           "FAKE_FM_DIR": fake_fm.dir}
    out = subprocess.run(["bash", str(HERE / "app-setup.sh"), "--check", str(res)],
                         capture_output=True, text=True, env=env, timeout=60).stdout
    rows = {}
    for line in out.splitlines():
        f = line.split(":", 5)
        if len(f) == 6 and f[0] == "CHECK":
            rows[f[1]] = f[2:]
    return rows


@pytest.mark.parametrize("status,state,need,detail", [
    ("available", "ok", "required", "ready"),
    ("appleIntelligenceNotEnabled", "missing", "required", "System Settings › Apple Intelligence & Siri"),
    ("modelNotReady", "warn", "recommended", "downloading"),
    ("deviceNotEligible", "missing", "required", "can't run Apple Intelligence"),
])
def test_apple_intelligence_check(tmp_path, fake_fm, status, state, need, detail):
    rows = _checks(tmp_path, fake_fm, status)
    st, req, label, text = rows["ai"]
    assert (st, req, label) == (state, need, "Apple Intelligence")
    assert detail in text


def test_old_macos_gets_its_own_row_with_an_update_fix(tmp_path, fake_fm):
    rows = _checks(tmp_path, fake_fm, "unsupportedOS")
    assert rows["macos"][:2] == ["missing", "required"] and "macOS 26" in rows["macos"][3]


def test_missing_helper_blocks_setup_with_a_reinstall_hint(tmp_path, fake_fm):
    rows = _checks(tmp_path, fake_fm, helper=False)
    assert rows["ai"][:2] == ["missing", "required"] and "Reinstall" in rows["ai"][3]


def test_no_claude_code_and_no_answer_model_download(tmp_path, fake_fm):
    rows = _checks(tmp_path, fake_fm, "available")
    assert "claude" not in rows
    assert "6 GB" in rows["disk"][3]                      # search models only, no 4.9 GB model
    src = (HERE / "app-setup.sh").read_text().lower()
    assert "gemma" not in src and "mlx" not in src and "hf download" not in src
    assert ".setup-complete" in src                       # Setup.swift's ready marker


def test_setup_swift_maps_the_new_checks_to_fix_buttons():
    swift = (HERE / "app" / "Sources" / "Setup.swift").read_text()
    assert 'case "ai":' in swift and "com.apple.Siri-Settings.extension" in swift
    assert 'case "macos":' in swift and 'case "claude":' not in swift
    assert "gemma" not in swift.lower() and ".setup-complete" in swift
