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

ARCHIVE = "archive"
META = "meta"
DRAFTS = "meta/promotion-drafts"
TEMPLATES = "meta/templates"
GAPS = "meta/coverage-gaps.md"
IMPROVE_LOG = "meta/improvement-loop.md"

INDEX = "index.md"
LOG = "log.md"

# wiki categories to catalog, in display order: (relpath, human label)
WIKI_CATEGORIES = [
    (CONCEPTS, "Concepts"),
    (PEOPLE, "People"),
    (PROJECTS, "Projects"),
    (TECH, "Tech"),
    (CLIPPINGS, "Clippings"),
    (AREAS, "Areas"),
]

# dirs the Q&A corpus / catalog skips (scaffolding, not knowledge)
SKIP_DIRS = {"meta", "archive", "raw", ".git", ".obsidian", ".ruff_cache", ".claude"}

# raw activity dumps that the maintenance loop prunes on a retention window.
# raw/confluence is a live mirror (rebuilt by the backfill) and raw/journal is
# legacy history — neither is a dated dump, so neither is pruned here.
RAW_ACTIVITY = [RAW_SLACK, RAW_CLAUDE, RAW_OUTLOOK]
RAW_RETENTION_DAYS = int(os.environ.get("PLASMIE_RAW_RETENTION_DAYS", "14"))

_LOG_HEADER = (
    "# Log\n\nComprehensive, append-only audit of the vault — every ingest, promotion, "
    "and prune. `raw/` is transient staging that gets cleaned on a retention window; "
    "this log is the durable record. Grep it: `grep '^## \\[' log.md | tail`.\n")


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
