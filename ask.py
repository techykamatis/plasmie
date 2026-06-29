#!/usr/bin/env python3
"""Ask anything in the vault — local-only RAG over your notes.

Retrieve the most relevant notes by TF-IDF cosine (reusing dedupe's tokenizer),
then ask the local Gemma to answer using ONLY those notes and cite them. Streams
straight from the mlx Gemma server (the same model summarize/promote use) over
its OpenAI-compatible endpoint, token by token — no network, no new deps, no
spawning the Claude CLI. If the server is down it's kicked up on demand; if it
can't load, falls back to showing the matching notes so you still get an answer.

Two output channels so a UI can show live progress:
  stdout = the answer text (streamed), then a "Sources:" list
  stderr = staged status ("Searching your notes…", "Asking Gemma…")

ponytail: talk to the mlx server's /v1/chat/completions with urllib + SSE
instead of `gen.sh`→`cc-local.sh`→full `claude` CLI. The CLI spawn + the
up/down churn (5GB load+unload per ask) was the slowness; streaming from a
left-warm server is the fix. First ask after idle still pays the one-time weight
load — add an idle-unload timer only if resident RAM becomes a problem.
TF-IDF build is ~0.3s over the vault, so no index cache (YAGNI).

Usage:
  ask.py "how do I shrink RDS storage?" [VAULT]
  ask.py --selfcheck
"""
import datetime
import json
import math
import os
import re
import sys
import urllib.error
import urllib.request
from collections import Counter
from pathlib import Path

from dedupe import _vec, frontmatter, tokens

SELF = Path(__file__).resolve().parent
ENDPOINT = os.environ.get("PLASMIE_ENDPOINT", "http://127.0.0.1:8080")   # mlx Gemma server
MODEL = os.environ.get("GEMMA_MODEL", str(SELF / "models/gemma-4-e4b"))
TIMEOUT = 90          # seconds for the local model
TOP_K = 4             # notes fed as context
PER_NOTE = 2000       # chars of each note in the prompt
JOURNAL_CHARS = 3000  # chars of each daily journal in a recap prompt
NUM_PREDICT = 600     # cap answer length so a runaway model can't hang the ask
JOURNAL = "02 Areas/journal"   # dated daily notes: YYYY-MM-DD.md
# Whole vault except scaffolding/drafts — ask anything that's actually filed.
SKIP_DIRS = {"00 Inbox", "99 Meta", ".git", ".obsidian"}
# Coverage: EmbeddingGemma cosine of the top hit. Measured in-vault hits land
# 0.51–0.72, out-of-vault 0.11–0.35 — 0.40 splits them with margin. Below this,
# nothing in the vault really answers the question: log it as a gap to fill.
COVERAGE_MIN = 0.40
GAPS = "99 Meta/coverage-gaps.md"


def _say(msg):
    """Emit a status line to stderr (the UI streams these as live progress)."""
    print(msg, file=sys.stderr, flush=True)


def build_corpus(vault):
    """[{path, title, text, vec}] over the whole filed vault; full body indexed."""
    vault = Path(vault).expanduser()
    docs = []
    for p in sorted(vault.rglob("*.md")):
        rel = p.relative_to(vault)
        if p.name == "index.md" or any(part in SKIP_DIRS for part in rel.parts):
            continue
        raw = p.read_text(errors="replace")
        fm = frontmatter(raw)
        title = fm.get("title", p.stem)
        docs.append({"path": str(rel), "title": title,
                     "text": raw, "toks": tokens(f"{title} {raw}")})
    n = len(docs)
    df = Counter(t for doc in docs for t in set(doc["toks"]))
    idf = {t: math.log((1 + n) / (1 + c)) + 1 for t, c in df.items()}
    for doc in docs:
        doc["vec"] = _vec(doc["toks"], idf)
    return docs, idf


def nearest(query, corpus, idf, k=TOP_K):
    q = _vec(tokens(query), idf)
    scored = []
    for doc in corpus:
        small, big = (q, doc["vec"]) if len(q) < len(doc["vec"]) else (doc["vec"], q)
        dot = sum(val * big.get(t, 0.0) for t, val in small.items())
        if dot > 0:
            scored.append((dot, doc))
    scored.sort(key=lambda s: -s[0])
    return [(round(sc, 3), doc) for sc, doc in scored[:k]]


def embed_hits(question, corpus, k=TOP_K):
    """EmbeddingGemma semantic ranking (Google on-device, via Ollama).

    Returns [(score, doc), ...] like nearest(), or None if embeddings are
    unavailable (Ollama down) so the caller falls back to lexical TF-IDF.
    Eval: pure embed scores 1.00 hit@1 / MRR 1.0 vs TF-IDF's 0.81 — see eval.py.
    """
    try:
        import retrieve                       # lazy: retrieve imports ask
        vecs = retrieve.embed_corpus(corpus)
        qv = retrieve.embed_query(question)
    except Exception:                          # ollama down / model missing / net
        return None
    scored = sorted(((retrieve._dot(qv, vecs[d["path"]]), d)
                     for d in corpus if d["path"] in vecs), key=lambda s: -s[0])
    return [(round(sc, 3), doc) for sc, doc in scored[:k]]


def expand_links(hits, corpus, cap=2):
    """OKF: append concepts the top hits link to, so Gemma sees the neighborhood.

    Traversable knowledge beats isolated chunks — a hit's curated cross-links
    are exactly the context a person already decided was related.
    """
    import retrieve
    graph = retrieve.link_graph(corpus)
    by_path = {d["path"]: d for d in corpus}
    have = {doc["path"] for _, doc in hits}
    extra = []
    for _, doc in hits:
        for nb in graph.get(doc["path"], ()):
            if nb not in have and len(extra) < cap:
                have.add(nb)
                extra.append((None, by_path[nb]))    # sc=None → not a ranked hit
    return hits + extra


def log_gap(vault, question, score, closest):
    """Record a question the vault couldn't answer well, so coverage can grow.

    Dedup on the question text — asking the same thing twice shouldn't spam the
    log. The file is the backlog: write/promote a note and the gap drops off.
    """
    q = " ".join(question.split())
    path = Path(vault).expanduser() / GAPS
    existing = path.read_text(errors="replace") if path.exists() else ""
    if f'"{q}"' in existing:
        return False
    if not existing:
        path.parent.mkdir(parents=True, exist_ok=True)
        existing = ("# Coverage gaps\n\nQuestions asked that the vault couldn't answer well "
                    "(top similarity below threshold). Fill each by writing or promoting a "
                    "concept note, then it drops off.\n\n")
    line = f'- {datetime.date.today().isoformat()} · ({score:.2f}) "{q}" — closest: {closest}\n'
    path.write_text(existing + line)
    return True


def build_prompt(question, hits, weak=False):
    ctx = "\n\n".join(
        f"--- NOTE: {doc['path']} ---\n{doc['text'][:PER_NOTE]}" for _, doc in hits)
    warn = ("These notes are only weakly related to the question — they may not "
            "answer it. If they don't, say the vault doesn't cover this yet rather "
            "than forcing an answer.\n\n") if weak else ""
    return (
        "Answer the question using ONLY the notes below. Cite the note path(s) you "
        "used. If the notes don't contain the answer, say so plainly — do not guess.\n\n"
        f"{warn}{ctx}\n\n=== QUESTION ===\n{question}\n\n=== ANSWER ===\n")


def ensure_up():
    """Make sure the mlx server is listening; kick it up on demand if not.

    Returns True if the endpoint answers. The first ask after idle pays the
    model weight-load on the first generation request, not here.
    """
    import subprocess
    try:
        urllib.request.urlopen(f"{ENDPOINT}/v1/models", timeout=1.5).read()
        return True
    except (urllib.error.URLError, OSError):
        pass
    _say("Starting the local model…")
    try:
        subprocess.run([str(SELF / "mlx-ctl.sh"), "up"], timeout=TIMEOUT, check=True)
        return True
    except (subprocess.SubprocessError, OSError):
        return False


def stream_model(prompt, on_chunk):
    """Stream Gemma's answer over the OpenAI-compatible SSE endpoint.

    Calls on_chunk(text) per token; returns the full answer, or "" if the
    server is unreachable/empty (caller falls back to the retrieved notes).
    """
    body = json.dumps({
        "model": MODEL, "stream": True, "max_tokens": NUM_PREDICT, "temperature": 0.2,
        "messages": [{"role": "user", "content": prompt}],
    }).encode()
    req = urllib.request.Request(f"{ENDPOINT}/v1/chat/completions", data=body,
                                 headers={"Content-Type": "application/json"})
    parts = []
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
            for line in resp:                     # SSE: "data: {json}" / "data: [DONE]"
                line = line.strip()
                if not line.startswith(b"data:"):
                    continue
                payload = line[5:].strip()
                if payload == b"[DONE]":
                    break
                chunk = json.loads(payload)["choices"][0].get("delta", {}).get("content") or ""
                if chunk:
                    parts.append(chunk)
                    on_chunk(chunk)
    except (urllib.error.URLError, OSError, json.JSONDecodeError, KeyError, IndexError):
        return "".join(parts).strip()
    return "".join(parts).strip()


def detect_window(query, today=None):
    """Map a temporal question to (label, [YYYY-MM-DD,...]); None if not temporal.

    "what did we do last week / yesterday / today / this week / recently" can't be
    keyword-retrieved — it's a date range over the daily journal. Recognise the
    common phrasings and resolve them to dates relative to `today`.
    """
    today = today or datetime.date.today()
    q = query.lower()
    day = datetime.timedelta(days=1)

    def span(a, b):  # inclusive [a, b]
        return [(a + day * i).isoformat() for i in range((b - a).days + 1)]

    mon = today - day * today.weekday()              # Monday of this week
    if re.search(r"\btoday\b", q):
        return "today", [today.isoformat()]
    if re.search(r"\byesterday\b", q):
        return "yesterday", [(today - day).isoformat()]
    if re.search(r"\blast week\b", q):
        return "last week", span(mon - day * 7, mon - day)     # previous Mon–Sun
    if re.search(r"\bthis week\b", q):
        return "this week", span(mon, today)
    if re.search(r"\b(recently|lately|past few days|last few days|past week)\b", q):
        return "the past week", span(today - day * 6, today)
    return None


def recap_journal(question, vault, window, on_chunk, done, unavailable):
    """Answer a temporal question from the daily journal. None if no journal in range."""
    label, dates = window
    jdir = Path(vault).expanduser() / JOURNAL
    files = [jdir / f"{d}.md" for d in dates]
    files = [f for f in files if f.exists()]
    if not files:
        return None                                  # nothing logged → let TF-IDF try
    n = len(files)
    _say(f"Reading journal — {label} ({n} day{'s' if n != 1 else ''})…")
    ctx = "\n\n".join(f"--- {f.stem} ---\n{f.read_text(errors='replace')[:JOURNAL_CHARS]}"
                      for f in files)
    prompt = (
        f"These are my daily work-journal notes for {label}. Summarise concisely what I "
        "worked on and what happened — group by theme, skip empty/no-activity sections, "
        "don't invent anything not in the notes.\n\n"
        f"{ctx}\n\n=== QUESTION ===\n{question}\n\n=== SUMMARY ===\n")
    hits = [(None, {"path": str(f.relative_to(Path(vault).expanduser())), "title": f.stem})
            for f in files]
    if not ensure_up():
        return done(unavailable, hits)
    _say("Asking Gemma…")
    answer = stream_model(prompt, on_chunk)
    if not answer:
        return done(unavailable, hits)
    return answer, hits


def ask(question, vault="~/knowledge", on_chunk=None):
    """Retrieve, then stream an answer. on_chunk(text) receives answer tokens live."""
    on_chunk = on_chunk or (lambda _t: None)
    unavailable = "(local model unavailable — showing the most relevant notes below)"

    def done(msg, hits):     # every answer path must emit the text, not just the stream
        on_chunk(msg)
        return msg, hits

    window = detect_window(question)
    if window:               # temporal question → read the journal, not TF-IDF
        result = recap_journal(question, vault, window, on_chunk, done, unavailable)
        if result is not None:
            return result    # else no journal in range — fall through to retrieval

    _say("Searching your notes…")
    corpus, idf = build_corpus(vault)
    if not corpus:
        return done("Vault is empty — nothing to search yet.", [])
    embedded = embed_hits(question, corpus)
    hits = embedded or nearest(question, corpus, idf)
    if not hits:
        return done("No matching notes found in the vault.", [])
    # Coverage: a low top cosine means nothing really matches (gap). Only the
    # embed path gives a query-comparable score; skip the check on TF-IDF fallback.
    weak = bool(embedded) and embedded[0][0] < COVERAGE_MIN
    if weak and log_gap(vault, question, embedded[0][0], embedded[0][1]["path"]):
        _say("No strong match — answering tentatively and logging a coverage gap.")
    hits = expand_links(hits, corpus)        # OKF: pull in linked neighbors
    titles = ", ".join(doc["title"] for _, doc in hits[:3])
    _say(f"Found {len(hits)} relevant notes: {titles}")
    if not ensure_up():
        return done(unavailable, hits)
    _say("Asking Gemma…")
    answer = stream_model(build_prompt(question, hits, weak=weak), on_chunk)
    if not answer:  # model off/unreachable/timed out — fall back to the retrieved notes
        return done(unavailable, hits)
    return answer, hits


def selfcheck():
    import tempfile
    with tempfile.TemporaryDirectory() as d:
        v = Path(d)
        c = v / "03 Resources/concepts"
        c.mkdir(parents=True)
        (v / "00 Inbox").mkdir()
        (c / "index.md").write_text("# index\n")  # must be skipped
        (v / "00 Inbox/raw.md").write_text("RDS storage secret stuff")  # skipped dir
        (c / "rds.md").write_text(
            '---\ntitle: "RDS storage only grows"\n---\n'
            "RDS allocated storage cannot shrink in place; snapshot and restore smaller.")
        (c / "slack.md").write_text(
            '---\ntitle: "Slack bot mpdm"\n---\nBot tokens cannot post to mpdm channels.\n')
        corpus, idf = build_corpus(v)
        assert len(corpus) == 2, [d_["path"] for d_ in corpus]  # index + inbox excluded
        hits = nearest("how do I shrink RDS storage", corpus, idf)
        assert hits and hits[0][1]["path"].endswith("rds.md"), hits
        assert "QUESTION" in build_prompt("q", hits) and "NOTE:" in build_prompt("q", hits)

        # OKF expansion: a [[wikilink]] from a hit pulls its neighbor in (offline)
        (c / "rds.md").write_text(
            '---\ntitle: "RDS storage only grows"\n---\nshrink RDS; see [[slack]]')
        corpus2, idf2 = build_corpus(v)
        h2 = nearest("how do I shrink RDS storage", corpus2, idf2, k=1)
        exp = expand_links(h2, corpus2)
        assert len(exp) == 2 and any(d["path"].endswith("slack.md") for _, d in exp), exp

        # coverage gap log: writes once, dedups the same question, records score+closest
        assert log_gap(v, "how do I bake bread?", 0.21, "rds.md") is True
        assert log_gap(v, "how do I  bake   bread?", 0.21, "rds.md") is False  # normalized dup
        g = (v / GAPS).read_text()
        assert '(0.21) "how do I bake bread?"' in g and "closest: rds.md" in g, g

        # stream_model parses SSE, assembles chunks in order, fires on_chunk live
        def _sse(c): return b'data: {"choices":[{"delta":{"content":"%s"}}]}' % c
        class _Fake:
            _lines = [_sse(b"Snap"), _sse(b"shot."), b"", b"data: [DONE]"]
            def read(self, *a): return b"{}"          # for ensure_up's /v1/models probe
            def __enter__(self): return iter(self._lines)
            def __exit__(self, *a): return False
        import urllib.request as _u
        orig = _u.urlopen
        _u.urlopen = lambda *a, **k: _Fake()
        try:
            seen = []
            full = stream_model("p", seen.append)
            assert full == "Snapshot." and seen == ["Snap", "shot."], (full, seen)
        finally:
            _u.urlopen = orig

        # detect_window date math, relative to a fixed Monday (2026-06-29)
        mon = datetime.date(2026, 6, 29)
        assert detect_window("notes on rds", mon) is None
        assert detect_window("what did we do today", mon) == ("today", ["2026-06-29"])
        assert detect_window("anything yesterday?", mon) == ("yesterday", ["2026-06-28"])
        lw = detect_window("what did we do last week", mon)
        assert lw == ("last week", ["2026-06-22", "2026-06-23", "2026-06-24", "2026-06-25",
                                    "2026-06-26", "2026-06-27", "2026-06-28"]), lw
        assert detect_window("this week", mon) == ("this week", ["2026-06-29"]), detect_window("this week", mon)
        assert len(detect_window("anything lately?", mon)[1]) == 7

        # recap_journal reads the journal window and falls through (None) when empty
        (v / JOURNAL).mkdir(parents=True)
        (v / JOURNAL / "2026-06-28.md").write_text("# 2026-06-28\nShipped the ask overlay.")
        _u.urlopen = lambda *a, **k: _Fake()
        try:
            ans, hits = recap_journal("what did we do yesterday", str(v),
                                      ("yesterday", ["2026-06-28"]), lambda _t: None,
                                      lambda m, h: (m, h), "NA")
            assert ans == "Snapshot." and hits[0][1]["path"].endswith("2026-06-28.md"), (ans, hits)
            assert recap_journal("today", str(v), ("today", ["2099-01-01"]),
                                 lambda _t: None, lambda m, h: (m, h), "NA") is None
        finally:
            _u.urlopen = orig
    print("ask selfcheck OK")


if __name__ == "__main__":
    args = sys.argv[1:]
    if "--selfcheck" in args:
        selfcheck()
        sys.exit(0)
    if not args:
        print('usage: ask.py "your question" [VAULT]', file=sys.stderr)
        sys.exit(2)
    q = args[0]
    vault = args[1] if len(args) > 1 else "~/knowledge"
    # Stream answer tokens straight to stdout as they arrive.
    answer, hits = ask(q, vault, on_chunk=lambda t: (sys.stdout.write(t), sys.stdout.flush()))
    if not answer.endswith("\n"):
        print()
    if hits:
        print("\nSources:")
        for sc, doc in hits:
            print(f"  · {doc['path']}" + (f" ({sc})" if sc is not None else ""))
