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
