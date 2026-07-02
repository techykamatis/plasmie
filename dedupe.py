#!/usr/bin/env python3
"""Enrich a promotion draft with local dedupe — no model, no deps, no server.

For each `## item` in the draft, find the nearest existing notes by TF-IDF cosine
over their title+description, then inject a suggested Action so the draft is
apply-ready for promote-apply.py:

  - nearest score >= MERGE_AT  -> Action: merge   (Merge-into: <that note>)
  - source is 00 Inbox/<file>  -> Action: move     (File + Target)
  - otherwise                  -> Action: create   (Target from the proposer)

A `Near:` line records the top matches + scores so a human can override. These
are SUGGESTIONS — promote-apply.py is dry-run by default and you still skim first.

ponytail: TF-IDF over short keyword-dense notes catches lexical dups (shared
identifiers/proper nouns). Swap nearest() for a local embed model only if it
starts missing semantic matches that use different words for the same thing.

Usage:
  dedupe.py DRAFT [VAULT] [--write]   # default prints; --write overwrites DRAFT
  dedupe.py --selfcheck
"""
import math
import re
import sys
from collections import Counter
from pathlib import Path

import paths

MERGE_AT = 0.30  # cosine >= this -> suggest merging into the nearest note
STOP = set("the a an of to in on for and or is are was be it this that with as by from at into not no".split())
CORPUS_DIRS = [paths.CONCEPTS, paths.PEOPLE, paths.PROJECTS]


def tokens(text):
    return [t for t in re.findall(r"[a-z0-9_]+", text.lower()) if len(t) > 1 and t not in STOP]


def frontmatter(text):
    if not text.startswith("---"):
        return {}
    end = text.find("\n---", 3)
    if end == -1:
        return {}
    fm = {}
    for line in text[3:end].splitlines():
        m = re.match(r"^([A-Za-z_]+):\s*(.*)$", line)
        if m:
            fm[m.group(1)] = m.group(2).strip().strip('"').strip("'")
    return fm


def build_corpus(vault):
    """[{path, title, vec}]  — path is relative to vault, vec is a normalized tf-idf dict."""
    vault = Path(vault).expanduser()
    docs = []
    for d in CORPUS_DIRS:
        for p in sorted((vault / d).glob("*.md")):
            if p.name == "index.md":
                continue
            fm = frontmatter(p.read_text(errors="replace"))
            text = f"{fm.get('title', p.stem)} {fm.get('description', '')}"
            docs.append({"path": str(p.relative_to(vault)), "title": fm.get("title", p.stem), "toks": tokens(text)})
    n = len(docs)
    df = Counter(t for doc in docs for t in set(doc["toks"]))
    idf = {t: math.log((1 + n) / (1 + c)) + 1 for t, c in df.items()}
    for doc in docs:
        doc["vec"] = _vec(doc["toks"], idf)
    return docs, idf


def _vec(toks, idf):
    tf = Counter(toks)
    v = {t: c * idf.get(t, 0.0) for t, c in tf.items()}
    norm = math.sqrt(sum(x * x for x in v.values())) or 1.0
    return {t: x / norm for t, x in v.items()}


def nearest(query, corpus, idf, k=3):
    q = _vec(tokens(query), idf)
    scored = []
    for doc in corpus:
        # cosine = dot of two already-normalized vectors; iterate the smaller dict
        small, big = (q, doc["vec"]) if len(q) < len(doc["vec"]) else (doc["vec"], q)
        dot = sum(val * big.get(t, 0.0) for t, val in small.items())
        if dot > 0:
            scored.append((dot, doc))
    scored.sort(key=lambda s: -s[0])
    return [(round(sc, 3), doc) for sc, doc in scored[:k]]


def _split_items(text):
    return [("## " + c) for c in re.split(r"^## ", text, flags=re.M)[1:]]


def enrich(draft_text, corpus, idf):
    head = re.split(r"^## ", draft_text, flags=re.M)[0]
    out = [head.rstrip(), ""] if head.strip() else []
    for block in _split_items(draft_text):
        lines = block.splitlines()
        title = lines[0][3:].strip()
        fields, body = {}, []
        for ln in lines[1:]:
            m = re.match(r"^(Action|Target|Merge-into|File|Source|Near):\s*(.*)$", ln)
            if m:
                if m.group(1) not in ("Near", "Action", "Merge-into", "File"):  # keep Target/Source; drop stale suggestions
                    fields[m.group(1)] = m.group(2).strip()
            else:
                body.append(ln)
        body_text = "\n".join(body).strip()

        near = nearest(f"{title} {body_text}", corpus, idf, k=3)
        src = fields.get("Source", "")
        m_inbox = re.search(rf"{paths.RAW_INBOX}/(.+)$", src)

        sugg = {}
        if near and near[0][0] >= MERGE_AT:
            sugg["Action"], sugg["Merge-into"] = "merge", near[0][1]["path"]
        elif m_inbox:
            sugg["Action"], sugg["File"] = "move", f"{paths.RAW_INBOX}/{m_inbox.group(1)}"
            sugg["Target"] = fields.get("Target", paths.WIKI)
        else:
            sugg["Action"], sugg["Target"] = "create", fields.get("Target", paths.CONCEPTS)

        near_str = " · ".join(f"{d['path']} ({sc})" for sc, d in near) or "(none)"
        rebuilt = [f"## {title}", f"Action: {sugg['Action']}"]
        for kf in ("Merge-into", "Target", "File"):
            if kf in sugg:
                rebuilt.append(f"{kf}: {sugg[kf]}")
        rebuilt.append(f"Near: {near_str}")
        if body_text:
            rebuilt.append(body_text)
        if "Source" in fields:
            rebuilt.append(f"Source: {fields['Source']}")
        out.append("\n".join(rebuilt))
    return "\n\n".join(out) + "\n"


def selfcheck():
    import tempfile
    with tempfile.TemporaryDirectory() as d:
        v = Path(d)
        c = v / paths.CONCEPTS
        c.mkdir(parents=True)
        (v / paths.PEOPLE).mkdir(parents=True)
        (v / paths.PROJECTS).mkdir(parents=True)
        (c / "rds-cannot-shrink-storage-in-place.md").write_text(
            '---\ntitle: "RDS can\'t shrink allocated storage in place"\ndescription: "storage only grows; reduce via snapshot/dump-restore to a smaller instance"\n---\n')
        (c / "slack-bot-mpdm.md").write_text(
            '---\ntitle: "Slack bot tokens can\'t post to mpdm channels"\ndescription: "route bot posts to a real channel"\n---\n')
        corpus, idf = build_corpus(v)
        assert len(corpus) == 2

        hit = nearest("RDS storage cannot be shrunk in place needs rebuild", corpus, idf)
        assert "rds-cannot-shrink" in hit[0][1]["path"], hit
        assert hit[0][0] >= MERGE_AT, f"expected a confident dup match, got {hit[0][0]}"

        miss = nearest("penguins migrating across antarctica", corpus, idf)
        assert not miss or miss[0][0] < MERGE_AT, miss

        draft = ("# Promotion draft\n\n"
                 f"## RDS storage can't be shrunk in place\nTarget: {paths.WIKI}\nFound that RDS storage only grows.\nSource: journal 2026-06-25\n\n"
                 f"## A brand new unrelated idea about penguins\nTarget: {paths.CONCEPTS}\nNothing like it exists.\nSource: journal 2026-06-25\n\n"
                 f"## An inbox file\nTarget: {paths.WIKI}\nSome doc.\nSource: {paths.RAW_INBOX}/foo.pdf\n")
        e = enrich(draft, corpus, idf)
        assert "Action: merge" in e and f"Merge-into: {paths.CONCEPTS}/rds-cannot-shrink-storage-in-place.md" in e, e
        assert "## A brand new unrelated idea about penguins\nAction: create" in e, e
        assert "Action: move" in e and f"File: {paths.RAW_INBOX}/foo.pdf" in e, e
    print("selfcheck OK")


if __name__ == "__main__":
    args = sys.argv[1:]
    if "--selfcheck" in args:
        selfcheck()
    else:
        write = "--write" in args
        rest = [a for a in args if a != "--write"]
        draft = Path(rest[0]).expanduser()
        vault = rest[1] if len(rest) > 1 else "~/knowledge"
        corpus, idf = build_corpus(vault)
        result = enrich(draft.read_text(errors="replace"), corpus, idf)
        if write:
            draft.write_text(result)
            print(f"enriched {draft} against {len(corpus)} notes")
        else:
            sys.stdout.write(result)
