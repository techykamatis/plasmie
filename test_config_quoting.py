"""config.env is sourced by bash: single-quoted values stay literal and read back exactly."""
import subprocess

import paths


def test_single_quoted_values_never_execute_and_round_trip(tmp_path):
    cfg = tmp_path / "config.env"
    marker = tmp_path / "pwned"
    cfg.write_text(f"VAULT_DIR='/Users/example/Alex'\\''s notes'\nJIRA_BASE_URL='$(touch {marker})'\n")
    out = subprocess.run(["bash", "-c", f'set -a; . "{cfg}"; printf %s "$VAULT_DIR"'],
                         capture_output=True, text=True).stdout
    assert out == "/Users/example/Alex's notes" and not marker.exists()
    got = paths.read_config(str(cfg))
    assert got == {"VAULT_DIR": "/Users/example/Alex's notes", "JIRA_BASE_URL": f"$(touch {marker})"}
