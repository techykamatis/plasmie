"""Vault layout — single source of truth for on-disk structure.

All paths are RELATIVE to the vault root (PLASMIE_VAULT or ~/knowledge); scripts join
them with their own resolved vault dir. Reshape the vault by editing here, not by
grepping ten files.

Layout (llm-wiki):
  raw/      immutable source material, one subdir per source — the loop appends,
            never rewrites. qmd collection "raw".
  wiki/     LLM-owned synthesized pages, FLAT. Structure is tags + generated
            maps of content in wiki/mocs/. qmd collection "wiki".
  archive/  done / dead.
  meta/     templates, promotion drafts, loop bookkeeping.
"""
import datetime
import os
import sys

# --- where things live: engine (code) vs data vs logs --------------------------
# The engine is wherever these scripts are: the dev checkout, or inside Plasmie.app for
# an installed copy (read-only, replaced on update). Everything Plasmie writes lives in
# the per-user data and log folders, macOS-conventionally, never next to the code.
# Shell scripts get the same three from plasmie-env.sh; the app from PlasmiePaths.
# The user-visible name, in one place for the engine (ADR 0014): data/log folders, the
# Keychain service, the iCloud folder, notifications and status copy all read it. Its twins:
# Brand.swift, PLASMIE_APP_NAME in plasmie-env.sh, APP_NAME in app/make-*.sh (test_brand.py).
# Internal names (PLASMIE_* env vars, plasmie-*.py files) follow it too (ADR 0014).
APP_NAME = "Plasmie"
APP_ID = "plasmie"

# --- earlier names: for migrations only (ADR 0023) -----------------------
# Every old name is spelled in parts on purpose: test_old_names.py fails if one is written
# out anywhere in the repo, so these assembled copies are the only ones, and only the code
# that carries an older install over (or still recognises its notes) reads them.
PREVIOUS_NAMES = ("Kl" + "oop", "Blob" + "kin")   # the app's earlier names, oldest first
SKETCH_NAME = "Loo" + "py"                        # the mascot's design-time name ("... noticed")
# Env vars and config.env keys used to start with one of these; now they start PLASMIE_.
OLD_ENV_PREFIXES = ("KL" + "OOP_", "KL" + "_")
ENV_PREFIX = "PLASMIE_"


def renamed_key(key):
    """The PLASMIE_ name for an env var or config.env key spelled the old way, else None."""
    for p in OLD_ENV_PREFIXES:
        if key.startswith(p) and len(key) > len(p):
            return ENV_PREFIX + key[len(p):]
    return None


def with_new_names(cfg):
    """`cfg` with every old-prefixed key under its PLASMIE_ name. A key already present under
    the new name keeps its value (the new name wins); keys that aren't old are kept as is."""
    out = {k: v for k, v in cfg.items() if renamed_key(k) is None}
    for k, v in cfg.items():
        new = renamed_key(k)
        if new and new not in out:
            out[new] = v
    return out


def adopt_old_env(environ):
    """Copy any old-prefixed variable to its PLASMIE_ name unless that is set already: a job
    an older build registered, or a shell profile, may still pass the old one.
    Fallback for one release (ADR 0023); drop it, with the twins in plasmie-env.sh and
    RenameMigration.swift, in the release after."""
    for k in [k for k in environ if renamed_key(k)]:
        environ.setdefault(renamed_key(k), environ[k])


adopt_old_env(os.environ)          # first: DATA_DIR and LOG_DIR below read PLASMIE_HOME/_LOGS
ENGINE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.expanduser(os.environ.get("PLASMIE_HOME") or f"~/Library/Application Support/{APP_NAME}")
LOG_DIR = os.path.expanduser(os.environ.get("PLASMIE_LOGS") or f"~/Library/Logs/{APP_NAME}")
LOOP_DIR = DATA_DIR          # older name for the data folder (state files hang off it)
os.makedirs(DATA_DIR, exist_ok=True)
os.makedirs(LOG_DIR, exist_ok=True)

# --- config.env: the ONE reader (the app writes it; shell scripts source it) ---
CONFIG = os.path.join(DATA_DIR, "config.env")

# Every connector the menu-bar app shows a card (and an On/Off switch) for.
SOURCES = ("slack", "github", "git", "confluence", "outlook", "claude")
# Ids that are no longer connectors (an old config.env may still list them) are
# simply ignored: disabled_sources() intersects with SOURCES.


def read_config(path=CONFIG):
    """KEY=value lines, tolerating `export ` and quotes. Parsed line by line, so
    one malformed line can't truncate everything below it the way `.` does."""
    out = {}
    try:
        with open(path, encoding="utf-8", errors="replace") as fh:
            for raw in fh:
                line = raw.strip()
                if line.startswith("export "):
                    line = line[7:]
                k, eq, v = line.partition("=")
                if not eq or line.startswith("#") or not k.strip().isidentifier():
                    continue
                v = v.strip()
                if len(v) >= 2 and v[0] == v[-1] and v[0] in "\"'":
                    v = v[1:-1]
                    if raw.strip().split("=", 1)[1].strip().startswith("'"):
                        v = v.replace("'\\''", "'")          # shell-escaped apostrophe
                out[k.strip()] = v
    except OSError:
        pass
    # A config.env not yet rewritten by plasmie-migrate.py step 8 still works: old keys are
    # read under their new names. Fallback for one release (ADR 0023).
    return with_new_names(out)


def migrate_config_keys(path=CONFIG):
    """Rewrite old-prefixed keys in config.env to their PLASMIE_ names, in place (ADR 0023).
    Values, quoting, `export `, comments, order and every other key stay as they are. An old
    key whose new name the file already defines loses its line (readers let the new one win,
    so nothing changes). Idempotent. Returns the old keys it rewrote or dropped."""
    import shutil
    import tempfile
    try:
        with open(path, encoding="utf-8", errors="surrogateescape") as fh:
            lines = fh.read().splitlines(keepends=True)
    except FileNotFoundError:
        return []

    def key(line):
        s = line.strip()
        s = s[7:] if s.startswith("export ") else s
        k, eq, _ = s.partition("=")
        k = k.strip()
        return k if eq and not s.startswith("#") and k.isidentifier() else None

    have = {key(ln) for ln in lines} - {None}        # names defined before any rewrite
    out, changed = [], []
    for ln in lines:
        k = key(ln)
        new = renamed_key(k) if k else None
        if new is None:
            out.append(ln)
            continue
        changed.append(k)
        if new not in have:
            out.append(ln.replace(k, new, 1))
    if changed:
        d = os.path.dirname(os.path.abspath(path))
        fd, tmp = tempfile.mkstemp(dir=d, prefix=".config.env.")
        with os.fdopen(fd, "w", encoding="utf-8", errors="surrogateescape") as fh:
            fh.write("".join(out))
        shutil.copymode(path, tmp)
        os.replace(tmp, path)
    return changed


def load_env(environ=None):
    """Settings from config.env, then connector tokens from the Keychain, into the
    environment, without overriding anything already set there (a one-off run's env
    wins). ~/.claude/.env is only migrated, once; until that succeeds (a Keychain that
    refuses writes) its tokens are still used, so an upgrade never cuts a connector off."""
    import keychain   # here, not at the top: keychain imports paths
    environ = os.environ if environ is None else environ
    res = keychain.migrate_if_needed()
    for k, v in read_config(CONFIG).items():
        environ.setdefault(k, v)
    keychain.load(environ)
    if res and res[2] and keychain.needs_migration():
        print("secrets: Keychain migration incomplete (" + "; ".join(res[2]) +
              "); using ~/.claude/.env until it succeeds", file=sys.stderr)
        legacy = read_config(keychain.legacy_env())
        for k in keychain.SECRETS:
            if legacy.get(k):
                environ.setdefault(k, legacy[k])


# --- native tools --------------------------------------------------------------
# Plasmie runs as arm64 on Apple silicon and never uses an Intel (x86_64) copy of a tool:
# without Rosetta it dies with "Bad CPU type in executable", with Rosetta it runs emulated.
# An old Intel Homebrew in /usr/local often shadows the native one on PATH, so tools are
# resolved by what the binary IS, not by where PATH finds it first.
NATIVE_DIRS = ("/opt/homebrew/bin", os.path.expanduser("~/.local/bin"), "/usr/bin", "/bin",
               "/usr/local/bin")
_CPU = {"arm64": 0x0100000C, "x86_64": 0x01000007}


def runs_natively(path, machine=None) -> bool:
    """True when `path` is a script or a Mach-O binary with a slice for this Mac's CPU."""
    import platform
    import struct
    want = _CPU.get(machine or platform.machine())
    try:
        with open(path, "rb") as f:
            head = f.read(4096)
    except OSError:
        return False
    if head[:2] == b"#!" or want is None:
        return True
    magic = head[:4]
    if magic in (b"\xcf\xfa\xed\xfe", b"\xce\xfa\xed\xfe"):          # thin, little-endian
        return struct.unpack("<i", head[4:8])[0] == want
    if magic in (b"\xca\xfe\xba\xbe", b"\xca\xfe\xba\xbf"):          # universal (fat)
        n, size = struct.unpack(">I", head[4:8])[0], 20 if magic[3] == 0xBE else 32
        return any(struct.unpack(">i", head[8 + i * size:12 + i * size])[0] == want
                   for i in range(min(n, (len(head) - 8) // size)))
    return False


def native_tool(name, environ=None):
    """Absolute path of a native `name`: PLASMIE_<NAME>_BIN (written by setup) if it still is,
    else the first native one on PATH or in NATIVE_DIRS; "" when there is none."""
    env = os.environ if environ is None else environ
    dirs = [env.get(f"PLASMIE_{name.upper()}_BIN", "")]
    dirs += [os.path.join(d, name) for d in env.get("PATH", "").split(os.pathsep) + list(NATIVE_DIRS) if d]
    for p in dict.fromkeys(dirs):
        if p and os.path.isfile(p) and os.access(p, os.X_OK) and runs_natively(p):
            return p
    return ""


def qmd_bin():
    """qmd: Plasmie's own copy ($PLASMIE_HOME/qmd), else PLASMIE_QMD, PATH, or an nvm install."""
    import glob
    import shutil
    own = os.path.join(DATA_DIR, "qmd", "bin", "qmd")
    node = os.path.join(ENGINE_DIR, "..", "node", "bin", "node")      # ships inside Plasmie.app
    usable = os.access(own, os.X_OK) and (os.access(node, os.X_OK) or shutil.which("node"))
    return ((own if usable else None) or os.environ.get("PLASMIE_QMD")
            or shutil.which("qmd")
            or next(iter(sorted(glob.glob(os.path.expanduser("~/.nvm/versions/node/*/bin/qmd")), reverse=True)), None)
            or "qmd")


def qmd_env(qmd, environ=None):
    """An env where qmd's `#!/usr/bin/env node` works: qmd's bin dir, plus the Node that
    ships inside Plasmie.app (Resources/node/bin, beside the engine), on PATH."""
    env = dict(os.environ if environ is None else environ)
    dirs = [os.path.normpath(os.path.join(ENGINE_DIR, "..", "node", "bin"))]
    if os.sep in qmd:
        dirs.append(os.path.dirname(qmd))
    for d in dirs:
        if os.path.isdir(d) and d not in env.get("PATH", "").split(os.pathsep):
            env["PATH"] = d + os.pathsep + env.get("PATH", "")
    return env


def csv_setting(name, environ=None):
    """A comma-separated setting (PLASMIE_GITHUB_ORGS, PLASMIE_GIT_ROOTS) as a list; empty if unset."""
    environ = os.environ if environ is None else environ
    return [p.strip() for p in environ.get(name, "").split(",") if p.strip()]


def vault(config=CONFIG):
    """Vault root: PLASMIE_VAULT (launchd wrappers) > VAULT_DIR env > config.env > ~/knowledge."""
    v = (os.environ.get("PLASMIE_VAULT") or os.environ.get("VAULT_DIR")
         or read_config(config).get("VAULT_DIR") or "~/knowledge")
    return os.path.expanduser(v)


def disabled_sources(config=CONFIG):
    """Connectors switched Off in the app (PLASMIE_DISABLED_SOURCES, comma-separated).
    The env var wins when set, even empty, so a test or one-off run can override."""
    raw = os.environ.get("PLASMIE_DISABLED_SOURCES")
    if raw is None:
        raw = read_config(config).get("PLASMIE_DISABLED_SOURCES", "")
    return {s.strip().lower() for s in raw.split(",")} & set(SOURCES)


def source_enabled(name, config=CONFIG):
    return name not in disabled_sources(config)


# connector -> its dated raw/ activity dir (confluence is a mirror, not dated dumps)
_ACTIVITY = (("slack", "slack"), ("claude", "claude"),
             ("outlook", "outlook"), ("github", "github"), ("git", "git"))


def activity_dirs(config=CONFIG):
    """raw/ subdirs summarize + promote read, minus connectors switched Off."""
    off, out = disabled_sources(config), []
    for src, d in _ACTIVITY:
        if src not in off and d not in out:
            out.append(d)
    return out

# --- raw sources (qmd collection "raw") ---
RAW = "raw"
RAW_SLACK = "raw/slack"
RAW_CLAUDE = "raw/claude"
RAW_OUTLOOK = "raw/outlook"
RAW_CONFLUENCE = "raw/confluence"
RAW_GITHUB = "raw/github"
RAW_GIT = "raw/git"
RAW_INBOX = "raw/inbox"
RAW_JOURNAL = "raw/journal"      # legacy combined digests (pre-refactor, read-only)

# --- wiki (qmd collection "wiki") ---
# FLAT since 2026-09-17: notes live directly in wiki/, and the taxonomy is tags +
# generated maps of content (wiki/mocs/). Folders were a second, redundant axis —
# every note now carries its old folder as a tag, so nothing was lost.
WIKI = "wiki"
MOCS = "wiki/mocs"              # generated per-tag maps; not hand-authored notes
ATTACHMENTS = "wiki/attachments"  # pdfs/html/svg that notes refer to

ARCHIVE = "archive"
META = "meta"
DRAFTS = "meta/promotion-drafts"
TEMPLATES = "meta/templates"
GAPS = "meta/coverage-gaps.md"
IMPROVE_LOG = "meta/improvement-loop.md"
USAGE = "meta/usage.tsv"

INDEX = "index.md"
LOG = "log.md"

# A promotion draft is LLM-written, so `Target:` is untrusted input — a local
# model reliably invents names ("03 Resources", "Technical") and used to create
# directories OUTSIDE wiki/, invisible to the qmd collection and therefore
# unanswerable by ask.py. With a flat wiki there is exactly one legal
# destination, which removes that whole class: Target can no longer name a place,
# only a tag. resolve_target stays as the single chokepoint.
TARGET_TAGS = {
    "concept": "concept", "concepts": "concept", "note": "concept", "notes": "concept",
    "person": "person", "people": "person",
    "project": "project", "projects": "project",
    "tech": "tech", "technical": "tech", "technology": "tech", "engineering": "tech",
    "how-to": "how-to", "how-tos": "how-to", "howto": "how-to", "howtos": "how-to",
    "guide": "how-to", "guides": "how-to", "runbook": "how-to", "runbooks": "how-to",
    "security": "security",
    "clipping": "clipping", "clippings": "clipping",
    "area": "area", "areas": "area",
    # the load-bearing kinds the vault contract names; the drafter can now say them
    "gotcha": "gotcha", "gotchas": "gotcha", "trap": "gotcha", "pitfall": "gotcha",
    "decision": "decision", "decisions": "decision",
    "pattern": "pattern", "patterns": "pattern",
}

# Target string -> frontmatter type. Type used to be inferred from the folder a
# note landed in; with one folder it comes from the same hint, defaulting to note.
TARGET_TYPES = {"person": "person", "project": "project", "concept": "reference",
                "tech": "reference", "how-to": "reference", "security": "reference",
                "gotcha": "gotcha", "decision": "decision", "pattern": "pattern"}


def resolve_target(t, default=WIKI):
    """Every promoted note lands in wiki/. Kept as the one place that decides."""
    return WIKI


def target_tag(t):
    """The tag an untrusted `Target:` hint maps to, or None if it means nothing."""
    seg = (t or "").strip().strip("/").split("/")[-1].lower()
    return TARGET_TAGS.get(seg)


# dirs the Q&A corpus / catalog skips (scaffolding, not knowledge)
SKIP_DIRS = {"meta", "archive", "raw", ".git", ".obsidian", ".ruff_cache", ".claude"}

# raw activity dumps that the maintenance loop prunes on a retention window.
# raw/confluence is a live mirror (rebuilt by the backfill) and raw/journal is
# legacy history — neither is a dated dump, so neither is pruned here.
# raw/github holds BOTH: dated incremental dumps (raw/github/YYYY-MM-DD.md, pruned
# by the non-recursive *.md glob) and the backfill mirror in raw/github/<repo>/
# subdirs (untouched — subdir files aren't matched, and _MOC stem isn't a date).
RAW_ACTIVITY = [RAW_SLACK, RAW_CLAUDE, RAW_OUTLOOK, RAW_GITHUB, RAW_GIT]
RAW_RETENTION_DAYS = int(os.environ.get("PLASMIE_RAW_RETENTION_DAYS", "14"))

_LOG_HEADER = (
    "# Log\n\nComprehensive, append-only audit of the vault — every ingest, promotion, "
    "and prune. `raw/` is transient staging that gets cleaned on a retention window; "
    "this log is the durable record. Grep it: `grep '^## \\[' log.md | tail`.\n")


# The Mac had no network (a run that starts before Wi-Fi is back after wake): the source is
# fine, nothing reached it. Timeouts and HTTP errors are NOT here; those can be the source.
_OFFLINE = ("nodename nor servname", "[errno 8]", "network is unreachable", "[errno 51]",
            "[errno 50]", "internet connection appears to be offline",
            "check your internet connection", "error connecting to")


def is_offline(err) -> bool:
    """True when a source's error means "no network", not "this connector is broken"."""
    return bool(err) and any(m in str(err).lower() for m in _OFFLINE)


def ingest_worth_logging(written, conf_count, errors=(), truncated=()):
    """Policy for log_event: is this ingest run an event, or just a quiet hour?

    1,275 of the first 2,319 entries were "0 convo / 0 msg", making the durable
    audit 55% noise and slow to grep. Only a CLEAN, genuinely empty run is
    dropped: any error or truncation still logs, because a silent failure is
    exactly what this record exists to catch. "Creds not set" is a steady state,
    not an error, so it does not keep an empty run alive.
    """
    real = [e for e in errors if e and "not set" not in e]
    return bool(written or conf_count or real or truncated)


def log_event(vault, header, bullets=()):
    """Append a timestamped event to the durable audit log (log.md).

    Creates it with a header on first write. This is the never-pruned record that
    survives raw/ cleanup — every ingest/promote/prune writes one event here.
    """
    p = os.path.join(os.path.expanduser(str(vault)), LOG)
    if not os.path.exists(p):
        with open(p, "w") as fh:
            fh.write(_LOG_HEADER)
    ts = datetime.datetime.now().isoformat(timespec="seconds")
    lines = [f"\n## [{ts}] {header}"] + [f"- {b}" for b in bullets]
    with open(p, "a") as fh:
        fh.write("\n".join(lines) + "\n")
    return ts


if __name__ == "__main__":  # `paths.py activity-dirs` — for the shell jobs
    import sys
    if sys.argv[1:] == ["activity-dirs"]:
        print(" ".join(activity_dirs()))
