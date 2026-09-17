"""Vault layout — single source of truth for on-disk structure.

All paths are RELATIVE to the vault root (PLASMIE_VAULT or ~/knowledge); scripts join
them with their own resolved vault dir. Reshape the vault by editing here, not by
grepping ten files.

Layout (llm-wiki):
  raw/      immutable source material, one subdir per source — the loop appends,
            never rewrites. qmd collection "raw".
  wiki/     LLM-owned synthesized pages (concepts/people/projects/tech/areas).
            qmd collection "wiki".
  archive/  done / dead.
  meta/     templates, promotion drafts, loop bookkeeping.
"""
import datetime
import os

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
WIKI = "wiki"
CONCEPTS = "wiki/concepts"
PEOPLE = "wiki/people"
PROJECTS = "wiki/projects"
TECH = "wiki/tech"
CLIPPINGS = "wiki/clippings"
AREAS = "wiki/areas"
HOWTOS = "wiki/how-tos"
SECURITY = "wiki/security"

ARCHIVE = "archive"
META = "meta"
DRAFTS = "meta/promotion-drafts"
TEMPLATES = "meta/templates"
GAPS = "meta/coverage-gaps.md"
IMPROVE_LOG = "meta/improvement-loop.md"

INDEX = "index.md"
LOG = "log.md"

# wiki categories to catalog, in display order: (relpath, human label).
# This list IS the whitelist of legal promotion targets (see promote-apply.py) —
# a category missing here is invisible to index.md AND unwritable by the loop.
MOCS = "wiki/mocs"          # generated per-tag maps of content; not hand-authored notes

WIKI_CATEGORIES = [
    (CONCEPTS, "Concepts"),
    (PEOPLE, "People"),
    (PROJECTS, "Projects"),
    (TECH, "Tech"),
    (HOWTOS, "How-tos"),
    (SECURITY, "Security"),
    (CLIPPINGS, "Clippings"),
    (AREAS, "Areas"),
]

# Legacy / model-invented target names → the real category. The promotion draft
# is LLM-written, so `Target:` is untrusted input: a local model reliably emits
# capitalised pre-refactor names ("Project", "Technical"), which used to be
# passed through verbatim and created top-level dirs OUTSIDE wiki/ — invisible
# to the "wiki" qmd collection and therefore unanswerable by ask.py.
# Matched on the final path segment, lowercased.
TARGET_ALIASES = {
    "concept": CONCEPTS, "concepts": CONCEPTS, "note": CONCEPTS, "notes": CONCEPTS,
    "person": PEOPLE, "people": PEOPLE,
    "project": PROJECTS, "projects": PROJECTS,
    "tech": TECH, "technical": TECH, "technology": TECH, "engineering": TECH,
    "how-to": HOWTOS, "how-tos": HOWTOS, "howto": HOWTOS, "howtos": HOWTOS,
    "guide": HOWTOS, "guides": HOWTOS, "runbook": HOWTOS, "runbooks": HOWTOS,
    "security": SECURITY,
    "clipping": CLIPPINGS, "clippings": CLIPPINGS,
    "area": AREAS, "areas": AREAS,
}


def resolve_target(t, default=CONCEPTS):
    """Map an untrusted `Target:` string onto a real wiki category.

    Returns a path guaranteed to sit under wiki/. Anything unrecognised falls
    back to `default` rather than being trusted as a path — the promotion path
    must never be able to invent a directory outside the indexed tree.
    """
    seg = (t or "").strip().strip("/").split("/")[-1].lower()
    known = {c for c, _ in WIKI_CATEGORIES}
    if (t or "").strip().strip("/") in known:
        return (t or "").strip().strip("/")
    return TARGET_ALIASES.get(seg, default)

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
