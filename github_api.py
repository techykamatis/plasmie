"""GitHub REST access for the GitHub connector.

With GITHUB_TOKEN (a personal access token the user pastes in Settings, kept in the
Keychain) Plasmie calls api.github.com directly: no `gh` CLI, nothing to install, which
is what a friend's Mac has. Without a token it falls back to the `gh` CLI if it's signed
in (the owner's dev setup). Read-only GETs only.

  get(path, params) -> parsed JSON          raises GitHubError
  pages(path, params) -> [page bodies]      follows Link: rel="next" (up to max_pages)
"""
import json
import os
import re
import shutil
import subprocess
import urllib.error
import urllib.parse
import urllib.request

import paths

API = "https://api.github.com"
TIMEOUT = 30
GH_BIN = shutil.which("gh") or next(
    (p for p in ("/opt/homebrew/bin/gh", "/usr/local/bin/gh") if os.path.exists(p)), "")


class GitHubError(RuntimeError):
    pass


def token():
    return os.environ.get("GITHUB_TOKEN", "").strip()


def available():
    """True when there's a way to call GitHub at all (a token, or a gh CLI)."""
    return bool(token() or GH_BIN)


def _url(path, params):
    q = urllib.parse.urlencode(params or {})
    return f"{API}/{path.lstrip('/')}" + (f"?{q}" if q else "")


def _http(url):
    req = urllib.request.Request(url, headers={
        "Authorization": f"Bearer {token()}", "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28", "User-Agent": paths.APP_NAME})
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
            return json.loads(r.read() or b"null"), r.headers.get("Link", "")
    except urllib.error.HTTPError as e:
        msg = {401: "token rejected (expired or revoked?)", 403: "forbidden or rate-limited",
               422: "search not allowed (an org you can't see?)"}.get(e.code, f"HTTP {e.code}")
        raise GitHubError(msg) from None
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        raise GitHubError(f"network: {getattr(e, 'reason', e)}") from None


def _gh(path, params):
    if not GH_BIN:
        raise GitHubError(f"not signed in: add a GitHub token in {paths.APP_NAME} > Connectors")
    args = [GH_BIN, "api", "-H", "Accept: application/vnd.github+json", path, "-X", "GET"]
    for k, v in (params or {}).items():
        args += ["-f", f"{k}={v}"]
    r = subprocess.run(args, capture_output=True, text=True, timeout=60)
    if r.returncode != 0:
        err = (r.stderr or "gh failed").strip()
        if paths.is_offline(err):                # offline gh can mention auth; it isn't signed out
            raise GitHubError(f"network: {err.splitlines()[-1]}")
        last = err.splitlines()[-1]
        raise GitHubError("gh not authenticated (`gh auth login`)" if "auth" in last.lower() else last)
    return json.loads(r.stdout or "null")


def get(path, params=None):
    return _http(_url(path, params))[0] if token() else _gh(path, params)


def pages(path, params=None, max_pages=10):
    """Every page of a list/search endpoint (token path follows Link headers; the gh
    path pages by number)."""
    out = []
    if token():
        url = _url(path, params)
        while url and len(out) < max_pages:
            body, link = _http(url)
            out.append(body)
            m = re.search(r'<([^>]+)>;\s*rel="next"', link or "")
            url = m.group(1) if m else None
        return out
    p = dict(params or {})
    for n in range(1, max_pages + 1):
        p["page"] = n
        body = _gh(path, p)
        out.append(body)
        items = body.get("items", body) if isinstance(body, dict) else body
        if not isinstance(items, list) or len(items) < int(p.get("per_page", 30)):
            break
    return out


def login():
    return (get("user") or {}).get("login", "")
