#!/usr/bin/env python3
"""Connector tokens in the macOS login Keychain — the one Python reader and writer.

Each credential is a generic password: service "Plasmie", account = its env var name
(SLACK_USER_TOKEN, ...). Non-secret connector settings (site URL, orgs, folders)
live in config.env instead.

Every read AND write goes through /usr/bin/security, never Security.framework, so
every item's access list names one stable binary. An item made by the app itself
would trust only that build of the app (ad-hoc signed: a new identity per build),
and the hourly launchd jobs reading it through `security` would raise an "allow
access?" prompt on every run. An item that `security` creates trusts exactly that
tool to decrypt it, pinned by Apple's code requirement (identifier
"com.apple.security" and anchor apple), so it also survives OS updates. The Swift app
writes through the same tool. No `-T` flag: with an explicit -T list every later
`-U` update raises a prompt (tested).

Writes pipe the command into `security -i` on stdin, so the token never appears in
a process's arguments (visible to `ps`). `security -i` reads lines of at most 4096
bytes; a longer token falls back to `-w <token>` on the command line for the few
milliseconds the call takes. That exposes it only to processes of the same user
(macOS hides other users' arguments), which can already read the item by running
`security` themselves, so the fallback adds no reader that didn't exist.

PLASMIE_KEYCHAIN=<path> points every call at another keychain file (tests use a
throwaway one); unset means the login keychain. A path that doesn't exist is refused:
`security` would silently fall back to the login keychain.

CLI:  keychain.py migrate        one-time copy from ~/.claude/.env (idempotent)
      keychain.py set NAME       store the value read from stdin
"""
import datetime
import os
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import paths  # noqa: E402

SERVICE = "Plasmie"
SECURITY = "/usr/bin/security"
# Tokens: the Keychain only. Mirrored by PLASMIE_SECRETS in plasmie-env.sh and
# Keychain.secrets in app/Sources/Keychain.swift (a test keeps the three equal).
# The Atlassian email is half of a Basic-auth credential, so it counts as one.
SECRETS = ("SLACK_USER_TOKEN", "JIRA_API_TOKEN", "CONFLUENCE_API_TOKEN", "MS_REFRESH_TOKEN",
           "JIRA_EMAIL", "CONFLUENCE_EMAIL")
# Plasmie's non-secret keys that used to share ~/.claude/.env; they move to config.env.
SETTINGS = ("JIRA_BASE_URL", "CONFLUENCE_BASE_URL", "PLASMIE_GITHUB_ORGS", "PLASMIE_GIT_ROOTS",
            "MS_CLIENT_ID", "MS_TENANT")
MAX_LINE = 4000          # security -i drops lines over 4096 bytes; keep a margin
TIMEOUT = 15


class KeychainError(RuntimeError):
    pass


def _keychain():
    p = os.environ.get("PLASMIE_KEYCHAIN")
    if p and not os.path.isfile(p):
        raise KeychainError(f"PLASMIE_KEYCHAIN={p} does not exist")
    return [p] if p else []


def _quote(s):
    return '"' + s.replace("\\", "\\\\").replace('"', '\\"') + '"'


def _check(name, value):
    if name not in SECRETS:
        raise KeychainError(f"not a Plasmie secret: {name}")
    if not value or any(ord(c) < 32 or ord(c) == 127 for c in value):
        raise KeychainError(f"{name}: empty, or contains control characters")


def get(name):
    """The stored value, or None when absent (or the keychain can't be read)."""
    try:
        r = subprocess.run([SECURITY, "find-generic-password", "-s", SERVICE, "-a", name, "-w",
                            *_keychain()], capture_output=True, text=True, timeout=TIMEOUT)
    except (OSError, subprocess.TimeoutExpired, KeychainError):
        return None
    v = r.stdout.rstrip("\n")
    return v if r.returncode == 0 and v else None


def put(name, value):
    """Create or replace NAME. Raises KeychainError unless it reads back identical."""
    _check(name, value)
    kc = _keychain()
    line = " ".join(["add-generic-password", "-U", "-s", SERVICE, "-a", name,
                     "-w", _quote(value), *map(_quote, kc)])
    try:
        if len(line.encode()) <= MAX_LINE:     # token on stdin: invisible to ps
            subprocess.run([SECURITY, "-i"], input=line + "\n", capture_output=True,
                           text=True, timeout=TIMEOUT)
        else:                                  # too long for -i; see module docstring
            subprocess.run([SECURITY, "add-generic-password", "-U", "-s", SERVICE, "-a", name,
                            "-w", value, *kc], capture_output=True, timeout=TIMEOUT)
    except (OSError, subprocess.TimeoutExpired) as e:
        raise KeychainError(f"{name}: {e}") from None
    if get(name) != value:                     # `security -i` exits 0 even on failure
        raise KeychainError(f"{name}: the Keychain did not keep it (locked, or access denied?)")


def delete(name):
    """Remove NAME; True if something was removed."""
    try:
        r = subprocess.run([SECURITY, "delete-generic-password", "-s", SERVICE, "-a", name,
                            *_keychain()], capture_output=True, timeout=TIMEOUT)
    except (OSError, subprocess.TimeoutExpired, KeychainError):
        return False
    return r.returncode == 0


def load(environ=None, names=SECRETS):
    """Export each stored token into `environ` unless it is already set there."""
    environ = os.environ if environ is None else environ
    for n in names:
        if not environ.get(n):
            v = get(n)
            if v:
                environ[n] = v


# --- one-time migration from ~/.claude/.env ---------------------------------
def legacy_env():
    return os.path.expanduser(os.environ.get("PLASMIE_LEGACY_ENV") or "~/.claude/.env")


def marker(data_dir=None):
    return os.path.join(data_dir or paths.DATA_DIR, ".secrets-migrated")


def needs_migration(data_dir=None):
    """An install that predates the Keychain (it has run before) and hasn't migrated.
    A fresh install never imports: migrate-home.sh marks it done, so Plasmie doesn't
    help itself to tokens another tool left in ~/.claude/.env."""
    d = data_dir or paths.DATA_DIR
    return (not os.path.exists(marker(d)) and os.path.exists(os.path.join(d, ".loop-state.json"))
            and os.path.isfile(legacy_env()))


def migrate(data_dir=None, config=None):
    """Copy Plasmie's keys out of ~/.claude/.env: tokens to the Keychain, settings to
    config.env. Never edits or deletes ~/.claude/.env (other tools share it) and never
    overwrites: a value already in the Keychain or config.env wins (a rotated Outlook
    token must not be rolled back). Marks itself done only when every token landed.
    Returns (tokens copied, settings copied, errors)."""
    d = data_dir or paths.DATA_DIR
    config = config or os.path.join(d, "config.env")
    src = paths.read_config(legacy_env())
    tokens, errors = [], []
    for n in SECRETS:
        if src.get(n) and get(n) is None:
            try:
                put(n, src[n])
                tokens.append(n)
            except KeychainError as e:
                errors.append(str(e))
    have = paths.read_config(config)
    settings = {k: src[k] for k in SETTINGS if src.get(k) and k not in have}
    unsafe = [k for k, v in settings.items() if any(c in v for c in '"$`\\\n')]
    errors += [f"{k}: not copied (characters config.env can't hold safely)" for k in unsafe]
    settings = {k: v for k, v in settings.items() if k not in unsafe}
    if settings:
        with open(config, "a", encoding="utf-8") as fh:
            fh.write("".join(f'{k}="{v}"\n' for k, v in settings.items()))
    if not any(e for e in errors if "not copied" not in e):
        with open(marker(d), "w") as fh:
            fh.write(f"{datetime.datetime.now().isoformat(timespec='seconds')} "
                     f"tokens={','.join(tokens) or '-'} settings={','.join(settings) or '-'}\n")
    return tokens, list(settings), errors


def migrate_if_needed(data_dir=None):
    if needs_migration(data_dir):
        return migrate(data_dir)
    return None


if __name__ == "__main__":
    cmd = sys.argv[1:2]
    if cmd == ["migrate"]:
        res = migrate_if_needed()
        if res is None:
            print("secrets: nothing to migrate")
        else:
            tokens, settings, errors = res
            print(f"secrets: {len(tokens)} token(s) to the Keychain, {len(settings)} setting(s) to config.env")
            for e in errors:
                print("secrets: " + e, file=sys.stderr)
            sys.exit(1 if errors else 0)
    elif cmd == ["set"] and len(sys.argv) == 3:
        try:
            put(sys.argv[2], sys.stdin.readline().strip())
        except KeychainError as e:
            sys.exit(f"keychain: {e}")
    else:
        sys.exit("usage: keychain.py migrate | set NAME  (value on stdin)")
