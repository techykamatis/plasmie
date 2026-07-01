#!/usr/bin/env python3
"""Minimal Microsoft Graph client (stdlib only).

Auth: device-code flow against the well-known Azure CLI public client, so no
app registration is needed. A long-lived refresh token is cached in
~/.claude/.env as MS_REFRESH_TOKEN; each run swaps it for a short-lived access
token. Refresh tokens rotate, so callers should persist the returned one.

CLI:  python3 msgraph.py login     # one-time browser consent → writes .env
      python3 msgraph.py test      # smoke-test the cached token
"""
import os, sys, json, time, urllib.request, urllib.parse, urllib.error

CLIENT_ID = "04b07795-8ddb-461a-bbee-02f9e1bf7b46"  # Azure CLI public client
AUTH = "https://login.microsoftonline.com/organizations/oauth2/v2.0"
GRAPH = "https://graph.microsoft.com/v1.0"
SCOPE = "offline_access Mail.Read Calendars.Read"
ENV = os.path.expanduser("~/.claude/.env")


def _post(url, data):
    body = urllib.parse.urlencode(data).encode()
    req = urllib.request.Request(url, data=body)
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.load(r)


def access_token(refresh_token):
    """refresh_token -> (access_token, possibly-rotated refresh_token)."""
    tok = _post(AUTH + "/token", {
        "client_id": CLIENT_ID, "grant_type": "refresh_token",
        "refresh_token": refresh_token, "scope": SCOPE,
    })
    return tok["access_token"], tok.get("refresh_token", refresh_token)


def get(path, token, **params):
    """GET a Graph v1.0 path (no paging — first page only). Returns 'value' or {}."""
    url = GRAPH + path
    if params:
        url += "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={"Authorization": "Bearer " + token})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.load(r)


def device_login():
    """Interactive device-code consent. Returns the token dict with refresh_token."""
    dc = _post(AUTH + "/devicecode", {"client_id": CLIENT_ID, "scope": SCOPE})
    print("\n" + dc["message"] + "\n", flush=True)
    deadline = time.time() + dc.get("expires_in", 900)
    interval = dc.get("interval", 5)
    while time.time() < deadline:
        time.sleep(interval)
        try:
            return _post(AUTH + "/token", {
                "client_id": CLIENT_ID,
                "grant_type": "urn:ietf:params:oauth:grant-type:device_code",
                "device_code": dc["device_code"],
            })
        except urllib.error.HTTPError as e:
            err = json.load(e).get("error", "")
            if err == "authorization_pending":
                continue
            if err == "slow_down":
                interval += 5
                continue
            raise
    raise TimeoutError("device-code login expired")


def _save_refresh(rt):
    """Upsert MS_REFRESH_TOKEN=<rt> in ~/.claude/.env (chmod 600)."""
    lines, found = [], False
    if os.path.exists(ENV):
        lines = open(ENV).read().splitlines()
    for i, ln in enumerate(lines):
        if ln.startswith("MS_REFRESH_TOKEN="):
            lines[i] = "MS_REFRESH_TOKEN=" + rt
            found = True
            break
    if not found:
        lines.append("MS_REFRESH_TOKEN=" + rt)
    with open(ENV, "w") as f:
        f.write("\n".join(lines) + "\n")
    os.chmod(ENV, 0o600)


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "login"
    if cmd == "login":
        tok = device_login()
        _save_refresh(tok["refresh_token"])
        print(f"saved MS_REFRESH_TOKEN to {ENV}")
    elif cmd == "test":
        rt = os.environ.get("MS_REFRESH_TOKEN")
        assert rt, "MS_REFRESH_TOKEN not set — run: python3 msgraph.py login"
        at, _ = access_token(rt)
        me = get("/me", at)
        print(f"OK: {me.get('displayName')} <{me.get('mail') or me.get('userPrincipalName')}>")
    else:
        sys.exit("usage: msgraph.py login|test")
