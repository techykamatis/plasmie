---
name: verify
description: Check a Plasmie change is correct and ready to commit or push. Runs the Python test suite in throwaway PLASMIE_HOME/PLASMIE_LOGS dirs, bash -n on every shell script, py_compile, ruff against the baseline, the Swift build with app/make-app.sh, a strict codesign check, and the personal-data scan. Use whenever the user says /verify, "check this", "is it ready", "run the tests", or before any commit or /release. Takes an optional pytest filter or file path to narrow the test step.
---

# /verify: is this Plasmie change ready?

Run from the repo root. Stop at the first failure and report the exact error, file and line.

`$ARGUMENTS` (optional) narrows step 1: a test file, `-k` expression or path.

1. **Tests.** Never point them at the real `~/Library/Application Support/Plasmie` or `~/Library/Logs/Plasmie`:

       PLASMIE_HOME=$(mktemp -d) PLASMIE_LOGS=$(mktemp -d) python3 -m pytest -q $ARGUMENTS

   `test_no_personal.py` is part of this. It reads the owner's terms from the git-ignored
   `.personal-deny.txt`; if that file is missing the owner scan skips with a notice, which is
   expected on a fresh clone.

2. **Shell syntax.** `bash -n` on `*.sh`, `launchd/*.sh` and `app/*.sh` (skip globs that match nothing).

3. **Python compiles.** `python3 -m py_compile *.py .claude/skills/*/scripts/*.py`

4. **Lint.** `ruff check .` must not report more errors than `RUFF_BASELINE` in
   `app/make-release.sh`. If ruff isn't installed, say so; don't fail on it.

5. **App builds.** Only when Swift, the bundle, `make-app.sh` or bundled runtimes changed:

       app/make-app.sh
       codesign --verify --deep --strict app/build/Plasmie.app

   `make-app.sh` wipes `app/build`, including any installer the user is testing. Say so before
   running it if `app/build/Plasmie.dmg` exists.

6. **No traces.** `git grep --untracked -I -l -i -f .personal-deny.txt -- . ':!.personal-deny.txt' ':!.gitignore'`
   must print nothing (skip if the file is missing).

## Report

List each step and its result, any warnings (for example ruff missing, steps skipped), and a
confidence of high, medium or low with one sentence why. Don't commit or push; that's the
user's call.
