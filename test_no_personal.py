#!/usr/bin/env python3
"""Nothing about the owner is baked into code or defaults Plasmie ships to friends.

A default org, a home path or a company domain in code becomes every new user's
setting. This fails on any of them in a tracked code file. (The com.legacy launchd
labels and bundle id are tracked separately; they move with the SMAppService work.)

Usage:  pytest test_no_personal.py
"""
import os
import subprocess

HERE = os.path.dirname(os.path.abspath(__file__))
# assembled from pieces so this file doesn't match itself
DENY = ["frog" + "asia", "frog" + "education", "Contoso" + "-Labs", "contoso" + "ailabs",
        "vhen" + ".joseph", "-Users-" + "vhen", "techy" + "tomato"]


def test_no_owner_specific_values_in_code():
    files = subprocess.run(["git", "ls-files", "*.py", "*.sh", "*.swift"], cwd=HERE,
                           capture_output=True, text=True).stdout.split()
    hits = []
    for f in files:
        try:
            text = open(os.path.join(HERE, f), encoding="utf-8", errors="replace").read().lower()
        except OSError:
            continue
        hits += [f"{f}: {d}" for d in DENY if d.lower() in text]
    assert hits == []
