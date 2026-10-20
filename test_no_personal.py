#!/usr/bin/env python3
"""Nothing about the owner is baked into what Plasmie ships.

A default org, a home path or a company domain in code becomes every new user's
setting, and one in a doc or the vault template is published with the repo. This scans
every file in the tree (tracked, plus new files not yet committed): code, docs, JSON,
HTML, plists and everything under vault-template/.

The owner-specific terms (employer, internal tools, handles, home folder name) are not
in this file: listing them here would publish them. They live one per line in
`.personal-deny.txt` next to this file, which is git-ignored. Without it the owner scan
is skipped with a notice, so a fresh clone still runs the suite; the generic checks
below always run.

Usage:  pytest test_no_personal.py
"""
import os
import subprocess

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
DENY_FILE = os.path.join(HERE, ".personal-deny.txt")
SELF = os.path.basename(__file__)
PATTERNS = ["*.py", "*.sh", "*.swift", "*.md", "*.json", "*.html", "*.plist", "*.txt",
            "*.toml", "*.yml", "*.yaml", "vault-template/*"]
# Not personal, but never true of this project and never fit to ship: Plasmie is built
# and used on a personal Mac. (Assembled from parts so this file doesn't match itself.)
GENERIC = ["company" + " laptop", "company" + " mac", "work" + " laptop"]


def _files():
    out = subprocess.run(["git", "ls-files", "--cached", "--others", "--exclude-standard", "--", *PATTERNS],
                         cwd=HERE, capture_output=True, text=True, check=True).stdout.splitlines()
    return sorted({f for f in out if f != SELF})


# The owner's public name may appear in these files only (copyright and contact lines).
# Which name is allowed comes from "allow:" lines in the deny file, so it isn't spelled out here.
PUBLIC_IDENTITY = {"LICENSE", "README.md", "TRADEMARK.md", "CONTRIBUTING.md"}


def _hits(terms, allowed=()):
    hits = []
    for f in _files():
        try:
            text = open(os.path.join(HERE, f), encoding="utf-8", errors="replace").read()
        except OSError:                       # deleted in the working tree, or not a file
            continue
        text = f"{f}\n{text}".lower()        # a file's name ships too
        if f in PUBLIC_IDENTITY:
            for name in allowed:
                text = text.replace(name, "")
        hits += [f"{f}: {t}" for t in terms if t in text]
    return hits


def _deny_terms():
    try:
        lines = open(DENY_FILE, encoding="utf-8").read().splitlines()
    except OSError:
        return None
    rows = [ln.strip().lower() for ln in lines if ln.strip() and not ln.lstrip().startswith("#")]
    allowed = [r[len("allow:"):].strip() for r in rows if r.startswith("allow:")]
    return [r for r in rows if not r.startswith("allow:")], allowed


def test_no_owner_specific_values_anywhere():
    found = _deny_terms()
    if found is None:
        pytest.skip(f"{os.path.basename(DENY_FILE)} not found: owner-specific scan skipped "
                    "(create it, one term per line, to run it)")
    terms, allowed = found
    assert _hits(terms, allowed) == []


def test_nothing_says_it_runs_on_a_work_machine():
    assert _hits(GENERIC) == []
