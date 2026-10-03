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
