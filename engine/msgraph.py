#!/usr/bin/env python3
"""Minimal Microsoft Graph client (stdlib only).

Auth: device-code flow against the well-known Azure CLI public client, so no
app registration is needed. A long-lived refresh token is kept in the login
Keychain as MS_REFRESH_TOKEN (keychain.py); each run swaps it for a short-lived
access token. Refresh tokens rotate, so callers should persist the returned one.

CLI:  python3 msgraph.py login     # one-time browser consent → stores the token
      python3 msgraph.py test      # smoke-test the stored token
"""
import os, sys, json, time, urllib.request, urllib.parse, urllib.error

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import keychain  # noqa: E402

# Your own Entra app (recommended — locked-down tenants block borrowing Microsoft's
# first-party Azure CLI client, AADSTS65002). Set MS_CLIENT_ID + MS_TENANT in
# config.env after registering an app; falls back to the Azure CLI id. Read at call
# time, so a caller's paths.load_env() takes effect even after this module loaded.
GRAPH = "https://graph.microsoft.com/v1.0"
SCOPE = "offline_access Mail.Read Calendars.Read"


def _client():
    return os.environ.get("MS_CLIENT_ID") or "04b07795-8ddb-461a-bbee-02f9e1bf7b46"


def _auth():
    tenant = os.environ.get("MS_TENANT") or "organizations"   # tenant id, or "organizations"/"common"
    return f"https://login.microsoftonline.com/{tenant}/oauth2/v2.0"


def _post(url, data):
    body = urllib.parse.urlencode(data).encode()
    req = urllib.request.Request(url, data=body)
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.load(r)


def access_token(refresh_token):
    """refresh_token -> (access_token, possibly-rotated refresh_token)."""
    tok = _post(_auth() + "/token", {
        "client_id": _client(), "grant_type": "refresh_token",
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
    dc = _post(_auth() + "/devicecode", {"client_id": _client(), "scope": SCOPE})
    print("\n" + dc["message"] + "\n", flush=True)
    deadline = time.time() + dc.get("expires_in", 900)
    interval = dc.get("interval", 5)
    while time.time() < deadline:
        time.sleep(interval)
        try:
            return _post(_auth() + "/token", {
                "client_id": _client(),
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
    """Store the (possibly rotated) refresh token in the login Keychain."""
    keychain.put("MS_REFRESH_TOKEN", rt)


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "login"
    import paths
    paths.load_env()
    if cmd == "login":
        tok = device_login()
        _save_refresh(tok["refresh_token"])
        print("saved MS_REFRESH_TOKEN to the Keychain")
    elif cmd == "test":
        rt = os.environ.get("MS_REFRESH_TOKEN")
        assert rt, "MS_REFRESH_TOKEN not set — run: python3 msgraph.py login"
        at, _ = access_token(rt)
        me = get("/me", at)
        print(f"OK: {me.get('displayName')} <{me.get('mail') or me.get('userPrincipalName')}>")
    else:
        sys.exit("usage: msgraph.py login|test")
