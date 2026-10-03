#!/usr/bin/env python3
"""Probe each connector and say whether it actually works. Pure stdlib, read-only.

`plasmie-status.py` answers "is data arriving?" from feed.log. That cannot separate a
quiet source from a broken one — which cost this project 43 days of a phantom
GitHub error and, before that, weeks of dead Confluence ingest. This answers the
other half: "can we reach it right now, with these credentials?"

  plasmie-doctor.py            -> JSON for every connector
  plasmie-doctor.py github     -> JSON for one (the Settings "Test" button)

Each connector reports: configured (creds present), ok (reachable), and a short
human detail. `ok` is null when unconfigured — unknown, not broken.
"""
import base64
import glob
import json
import os
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import paths  # noqa: E402

H = os.path.expanduser("~")
TIMEOUT = 15


def _load_env():
    """Mirror run-ingest.sh: ~/.claude/.env then config.env, via paths.read_config —
    line by line, so one malformed value can't truncate everything below it."""
    for path in (f"{H}/.claude/.env", paths.CONFIG):
        for k, v in paths.read_config(path).items():
            os.environ.setdefault(k, v)


def _result(configured, ok, detail, hint=""):
    return {"configured": configured, "ok": ok, "detail": detail, "hint": hint}


def _get_json(url, headers=None, data=None):
    req = urllib.request.Request(url, data=data, headers=headers or {})
    with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
        return json.load(r)


# --- probes -----------------------------------------------------------------

def check_slack():
    tok = os.environ.get("SLACK_USER_TOKEN", "")
    if not tok:
        return _result(False, None, "No token set.", "Paste a user token (xoxp-…) below.")
    try:
        r = _get_json("https://slack.com/api/auth.test",
                      headers={"Authorization": "Bearer " + tok}, data=b"")
    except Exception as e:
        return _result(True, False, f"Could not reach Slack: {e}", "Usually no network — it self-heals.")
    if not r.get("ok"):
        err = r.get("error", "unknown")
        hint = "Token expired or revoked — paste a new one." if err in ("invalid_auth", "token_revoked") else ""
        return _result(True, False, f"Slack rejected the token ({err}).", hint)
    return _result(True, True, f"Signed in as {r.get('user')} in {r.get('team')}.")


def check_confluence():
    base = os.environ.get("CONFLUENCE_BASE_URL", "").rstrip("/")
    jira = os.environ.get("JIRA_BASE_URL", "").rstrip("/")
    base = base or (jira + "/wiki" if jira else "")
    email = os.environ.get("CONFLUENCE_EMAIL") or os.environ.get("JIRA_EMAIL", "")
    tok = os.environ.get("CONFLUENCE_API_TOKEN") or os.environ.get("JIRA_API_TOKEN", "")
    if not (base and email and tok):
        missing = [n for n, v in (("site URL", base), ("email", email), ("API token", tok)) if not v]
        return _result(False, None, "Missing " + ", ".join(missing) + ".")
    auth = base64.b64encode(f"{email}:{tok}".encode()).decode()
    try:
        r = _get_json(base + "/rest/api/content?limit=1",
                      headers={"Authorization": "Basic " + auth, "Accept": "application/json"})
    except urllib.error.HTTPError as e:
        hint = "Check the email + API token pair." if e.code in (401, 403) else \
               "Check the site URL — it should end in /wiki." if e.code == 404 else ""
        return _result(True, False, f"HTTP {e.code} from Confluence.", hint)
    except Exception as e:
        return _result(True, False, f"Could not reach Confluence: {e}", "Usually no network — it self-heals.")
    return _result(True, True, f"Reachable — {r.get('size', 0)} page(s) in the first slice.")


def check_github():
    """Also validates each org. An org you cannot search returns 422 forever and
    the summary line looks identical to a quiet hour — the exact failure that
    went unnoticed from 2026-08-05 to 2026-09-17."""
    gh = shutil.which("gh") or next(
        (p for p in ("/opt/homebrew/bin/gh", "/usr/local/bin/gh") if os.path.exists(p)), "")
    if not gh:
        return _result(False, None, "The `gh` CLI is not installed.", "brew install gh")
    who = subprocess.run([gh, "api", "user", "--jq", ".login"],
                         capture_output=True, text=True, timeout=30)
    user = who.stdout.strip()
    if who.returncode != 0 or not user:
        msg = (who.stderr or "").strip().splitlines()[-1:] or ["gh is not authenticated"]
        # `gh api user` reports a DNS failure as an auth error; don't send people
        # to `gh auth login` when the real problem is that the network is down.
        detail = "Not signed in, or the network is down." if "not authenticated" in msg[0] else msg[0]
        return _result(True, False, detail, "Run `gh auth login` if this persists while online.")
    orgs = [o.strip() for o in os.environ.get("PLASMIE_GITHUB_ORGS", "fabrikam").split(",") if o.strip()]
    good, bad = [], []
    for org in orgs:
        r = subprocess.run([gh, "api", "search/issues", "-X", "GET",
                            "-f", f"q=author:{user} org:{org}", "-f", "per_page=1"],
                           capture_output=True, text=True, timeout=30)
        (good if r.returncode == 0 else bad).append(org)
    if bad:
        return _result(True, False,
                       f"Signed in as {user}, but cannot search: {', '.join(bad)}.",
                       "You are not a member of that org (or it is misspelled). Remove it, or ask for an invite.")
    return _result(True, True, f"Signed in as {user} — searching {', '.join(good)}.")


def check_outlook():
    rt = os.environ.get("MS_REFRESH_TOKEN", "")
    if not rt:
        return _result(False, None, "Not connected.", "Click Connect and approve the sign-in code.")
    sys.path.insert(0, f"{H}/.plasmie")
    try:
        import msgraph
        tok, _ = msgraph.access_token(rt)
        me = msgraph.get("/me", tok)
    except Exception as e:
        return _result(True, False, f"Sign-in failed: {e}", "The refresh token expired — reconnect.")
    return _result(True, True, f"Connected as {me.get('userPrincipalName') or me.get('displayName')}.")


def check_claude():
    root = os.path.expanduser("~/.claude/projects")
    if not os.path.isdir(root):
        return _result(False, None, "No Claude Code sessions folder found.")
    n = len(glob.glob(os.path.join(root, "*", "*.jsonl")))
    return _result(True, True, f"{n} session file(s) on disk. Always on — no setup needed.")



def check_agentcli():
    db = os.path.expanduser(os.environ.get("PLASMIE_AGENTCLI_DB", "~/.agentcli/cli/db/db.sqlite"))
    if not os.path.exists(db):
        return _result(False, None, "No AgentCLI session database found.", "Install AgentCLI and run a session.")
    import sqlite3
    try:
        con = sqlite3.connect(f"file:{db}?mode=ro", uri=True, timeout=5)
        n = con.execute("select count(*) from session where parent_id is null").fetchone()[0]
        con.close()
    except sqlite3.Error as e:
        return _result(True, False, f"Can't read the session database: {e}")
    return _result(True, True, f"{n} session(s) on disk. Always on — no setup needed.")


def check_git():
    """Local clones — no network, no token. The failure mode is not auth but
    "pointed at the wrong folder", so report what it can actually see."""
    roots = [os.path.expanduser(r.strip())
             for r in os.environ.get("PLASMIE_GIT_ROOTS", "~/code").split(",") if r.strip()]
    missing = [r for r in roots if not os.path.isdir(r)]
    if missing:
        return _result(False, False, "Folder not found: " + ", ".join(missing),
                       "Set PLASMIE_GIT_ROOTS to where your repos live.")
    repos = [d for r in roots for d in glob.glob(os.path.join(r, "*"))
             if os.path.isdir(os.path.join(d, ".git"))]
    if not repos:
        return _result(False, None, "No git repositories found in " + ", ".join(roots),
                       "Set PLASMIE_GIT_ROOTS to where your repos live.")
    git = shutil.which("git") or "/usr/bin/git"
    recent = 0
    for d in repos:
        try:
            email = subprocess.run([git, "-C", d, "config", "user.email"],
                                   capture_output=True, text=True, timeout=10).stdout.strip()
            if not email:
                continue
            out = subprocess.run([git, "-C", d, "log", f"--author={email}",
                                  "--since=30 days ago", "--no-merges", "--oneline"],
                                 capture_output=True, text=True, timeout=20).stdout
            recent += len([l for l in out.splitlines() if l.strip()])
        except Exception:
            continue
    return _result(True, True, f"{len(repos)} repo(s) in {', '.join(roots)} — "
                               f"{recent} of your commits in the last 30 days.")


def check_foundationmodels():
    """Apple's on-device model — a capability, not a data source.

    Reported here because the failure modes are indistinguishable from outside:
    "no Xcode so the SDK never installed", "Apple Intelligence off" and "model
    still downloading" all present as silence. `fm.py` owns the distinction.

    Not-set-up reports ok=null (unknown, not broken) so the menu-bar app doesn't
    paint a red error for a feature nobody enabled; only a Mac that genuinely
    can't run it, or a probe that blew up, reports ok=false.
    """
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    try:
        import fm
    except ImportError as e:
        return _result(False, None, f"fm.py not importable: {e}")
    p = fm.probe()
    if p["available"] is True:
        return _result(True, True, p["detail"])
    # UNKNOWN means the SDK gave no reason — that is a fault, not "the user
    # hasn't switched it on". Filing it under not-configured would be exactly
    # the phantom-green this whole file exists to kill.
    if p["reason"] in ("DEVICE_NOT_ELIGIBLE", "PROBE_FAILED", "UNKNOWN"):
        return _result(True, False, p["detail"], p["hint"])
    return _result(False, None, p["detail"], p["hint"])


CHECKS = {
    "slack": check_slack,
    "confluence": check_confluence,
    "github": check_github,
    "outlook": check_outlook,
    "claude": check_claude,
    "agentcli": check_agentcli,
    "git": check_git,
    "foundationmodels": check_foundationmodels,
}

# Reachable is not the same as arriving. Confluence sat green for 2.5 months while its
# mirror hadn't moved since 2026-07-02 — the same phantom-green class this file was
# written to kill. So also ask: when did this source last actually land a file?
RAW_DIR = {
    "slack": "raw/slack", "confluence": "raw/confluence", "github": "raw/github",
    "outlook": "raw/outlook", "claude": "raw/claude", "agentcli": "raw/claude", "git": "raw/git",
}
STALE_AFTER_DAYS = int(os.environ.get("PLASMIE_STALE_AFTER_DAYS", "7"))


def _age_days(name):
    """Days since this source last wrote a file into raw/, or None if it never has.

    Not every check is a data source — a capability probe (foundationmodels) has
    no raw/ dir, and an empty RAW_DIR lookup would glob the whole vault and
    report unrelated activity as this check's freshness.
    """
    if name not in RAW_DIR:
        return None
    d = os.path.join(paths.vault(), RAW_DIR[name])
    newest = max((os.path.getmtime(f) for f in glob.iglob(d + "/**/*.md", recursive=True)),
                 default=None)
    return None if newest is None else (time.time() - newest) / 86400


def main():
    _load_env()
    want = [a for a in sys.argv[1:] if a in CHECKS] or list(CHECKS)
    off = paths.disabled_sources()
    out = {}
    for name in want:
        if name in off:                           # switched Off in the app: don't probe
            out[name] = {**_result(True, None, "Switched off — not ingested."),
                         "enabled": False, "age_days": None, "stale": False}
            continue
        try:
            out[name] = CHECKS[name]()
        except Exception as e:                    # a probe must never take the page down
            out[name] = _result(True, False, f"Check failed: {e}")
        try:                                      # freshness never fails the probe
            age = _age_days(name)
        except OSError:
            age = None
        r = out[name]
        r["enabled"] = True
        r["age_days"] = None if age is None else round(age, 1)
        # Stale = it used to deliver and has stopped. Two shapes: reachable but not
        # arriving, and (the 93-day Confluence blind spot) credentials gone after it
        # had delivered. Never-configured has no data, so it is not stale.
        old = age is not None and age > STALE_AFTER_DAYS
        r["stale"] = bool(old and r.get("ok") is not False and (r.get("ok") or not r.get("configured")))
        if r["stale"] and r.get("ok"):
            r["detail"] += f" Last file landed {int(age)}d ago — reachable but not arriving."
            r["hint"] = r["hint"] or "Credentials work; the ingest for this source is not running."
        elif r["stale"]:
            r["detail"] += f" It was delivering until {int(age)}d ago."
            r["hint"] = r["hint"] or "Reconnect it, or switch it Off if you no longer want it."
    print(json.dumps(out))


if __name__ == "__main__":
    main()
