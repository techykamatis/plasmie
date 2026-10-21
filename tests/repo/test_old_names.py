"""No trace of older versions' names is left anywhere in the repo (ADR 0023).

Older versions used other names, and in older installs the internal names (env vars,
config.env keys, defaults keys, file names, Swift types, dev-path job labels) carry them.
Everything follows the brand now. The old spellings survive only inside the migration code that carries
an older install over, and there only assembled from parts ("KL" + "_"), next to a comment
saying why, so this scan cannot see them. Anything it does find is a leftover.

It scans every file in the tree (tracked, plus new files not yet committed): code, docs,
plists, JSON, HTML, the vault template, and each file's path as well as its contents. The
patterns below are assembled from parts too, so this file doesn't match itself.
"""
import os
import re
import subprocess

import keychain
import paths
from support import ROOT


_K, _L = "kl", "oop"
OLD = re.compile("|".join([
    _K + _L,                                   # an older version's name, any case
    "know" + r"ledge[- ]?" + "loop",          # an older version's name, and its dot-folder
    r"\b" + _K + "[-_]",                      # the old script / function prefix
    "KL" + "_", "KL" + "OOP_",                # the old env var / config key prefixes
    "blob" + "kin",                           # an older version's name
    "loo" + "py",                             # the mascot's design-time name
    r"com\.plasmie\.know" + "ledge-",         # the dev-path job labels of older installs
]), re.I)


def _files():
    out = subprocess.run(["git", "ls-files", "--cached", "--others", "--exclude-standard"],
                         cwd=ROOT, capture_output=True, text=True, check=True).stdout.splitlines()
    return sorted(set(out))


def test_no_old_name_in_any_file_name():
    assert [f for f in _files() if OLD.search(f)] == []


def test_no_old_name_in_any_file():
    hits = []
    for f in _files():
        try:
            with open(os.path.join(ROOT, f), encoding="utf-8") as fh:
                text = fh.read()
        except (OSError, UnicodeDecodeError):      # deleted in the working tree, or binary
            continue
        for i, line in enumerate(text.splitlines(), 1):
            m = OLD.search(line)
            if m:
                hits.append(f"{f}:{i}: {m.group(0)!r}")
    assert hits == [], "older versions' names may only appear assembled from parts, in migration code"


def test_the_scan_would_catch_each_old_spelling():
    """Guards the guard: each pattern still matches what it is for."""
    for sample in [_K + _L + "-env.sh", "K" + "loop" + "Shapes", "Know" + "ledge Loop", "~/.know" + "ledge-loop",
                   _K + "-doctor.py", _K + "_native", "KL" + "_GIT_ROOTS", "KL" + "OOP_HOME",
                   "Blob" + "kin.app", "Loo" + "py", "com.plasmie.know" + "ledge-ingest"]:
        assert OLD.search(sample), sample
    for fine in ["plasmie-env.sh", "PLASMIE_HOME", "loop-ingest.py", ".loop-state.json", "~/knowledge",
                 "com.plasmie.dev-ingest", "the ingest loop"]:
        assert not OLD.search(fine), fine


def test_migration_constants_still_spell_the_old_names():
    """The assembled copies are what the migrations need, letter for letter."""
    assert [n.lower() for n in paths.PREVIOUS_NAMES] == [_K + _L, "blob" + "kin"]
    assert paths.OLD_ENV_PREFIXES == ("KL" + "OOP_", "KL" + "_")
    assert paths.renamed_key("KL" + "_GIT_ROOTS") == "PLASMIE_GIT_ROOTS"
    assert paths.renamed_key("KL" + "OOP_HOME") == "PLASMIE_HOME"
    assert paths.renamed_key("PLASMIE_HOME") is None and paths.renamed_key("KL" + "_") is None


def test_keychain_accounts_never_used_an_old_prefix():
    """Sign-ins are stored under the token's own name (SLACK_USER_TOKEN, ...), never under an
    old-prefixed account, so the upgrade has no Keychain items to move (older versions' service names are
    adopted by plasmie-migrate.py step 7)."""
    assert all(paths.renamed_key(s) is None and not s.startswith(paths.ENV_PREFIX) for s in keychain.SECRETS)
    assert all(paths.renamed_key(s) is None for s in keychain.SETTINGS)
