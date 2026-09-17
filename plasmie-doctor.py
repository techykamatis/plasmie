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
import urllib.error
import urllib.parse
import urllib.request

H = os.path.expanduser("~")
TIMEOUT = 15


def _load_env():
    """Mirror run-ingest.sh: ~/.claude/.env, tolerating `export ` and quotes.

    Parsed line-by-line rather than sourced, so one malformed value cannot
    silently truncate everything below it the way `.` does in a shell.
    """
    for path in (f"{H}/.claude/.env", f"{H}/.plasmie/config.env"):
        try:
            with open(path, encoding="utf-8", errors="replace") as fh:
                for raw in fh:
                    line = raw.strip()
                    if not line or line.startswith("#"):
                        continue
                    if line.startswith("export "):
                        line = line[7:]
                    k, _, v = line.partition("=")
                    if not _:
                        continue
                    v = v.strip()
                    if len(v) >= 2 and v[0] == v[-1] and v[0] in "\"'":
                        v = v[1:-1]
                    os.environ.setdefault(k.strip(), v)
        except OSError:
            pass


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


CHECKS = {
    "slack": check_slack,
    "confluence": check_confluence,
    "github": check_github,
    "outlook": check_outlook,
    "claude": check_claude,
}


def main():
    _load_env()
    want = [a for a in sys.argv[1:] if a in CHECKS] or list(CHECKS)
    out = {}
    for name in want:
        try:
            out[name] = CHECKS[name]()
        except Exception as e:                    # a probe must never take the page down
            out[name] = _result(True, False, f"Check failed: {e}")
    print(json.dumps(out))


if __name__ == "__main__":
    main()
