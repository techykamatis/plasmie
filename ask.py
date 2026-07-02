#!/usr/bin/env python3
"""Ask anything in the vault — local-only RAG over your notes.

Retrieve the most relevant notes with **qmd** (vector search — measured best on
this vault; see eval.py), then ask the local Gemma to answer using ONLY those
notes and cite them. Streams
straight from the mlx Gemma server (the same model summarize/promote use) over
its OpenAI-compatible endpoint, token by token — no cloud, no new deps beyond the
qmd CLI. If the server is down it's kicked up on demand; if it can't load, falls
back to showing the matching notes so you still get an answer.

qmd owns retrieval (see the vault's CLAUDE.md); ask.py owns the private
local-Gemma synthesis and the promote/improve loops that depend on it. If qmd's
hybrid `query` can't run yet (models still downloading), it falls back to BM25
`qmd search`, then to nothing.

Two output channels so a UI can show live progress:
  stdout = the answer text (streamed), then a "Sources:" list
  stderr = staged status ("Searching your notes…", "Asking Gemma…")

Usage:
  ask.py "how do I shrink RDS storage?" [VAULT]
  ask.py --selfcheck
"""
import datetime
import json
import os
import re
import shutil
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path

import paths

SELF = Path(__file__).resolve().parent
ENDPOINT = os.environ.get("PLASMIE_ENDPOINT", "http://127.0.0.1:8080")   # mlx Gemma server
MODEL = os.environ.get("GEMMA_MODEL", str(SELF / "models/gemma-4-e4b"))
TIMEOUT = 90          # seconds for the local model
TOP_K = 4             # notes fed as context
PER_NOTE = 2000       # chars of each note in the prompt
JOURNAL_CHARS = 3000  # chars of each daily log in a recap prompt
NUM_PREDICT = 600     # cap answer length so a runaway model can't hang the ask

def _find_qmd():
    """Resolve the qmd binary even under launchd's bare PATH (node lives in nvm)."""
    import glob
    return (os.environ.get("PLASMIE_QMD") or shutil.which("qmd")
            or next(iter(sorted(glob.glob(os.path.expanduser(
                "~/.nvm/versions/node/*/bin/qmd")), reverse=True)), None)
            or "qmd")


QMD = _find_qmd()
QMD_TIMEOUT = 60
# raw per-source dirs a temporal recap reads (+ the legacy combined journal)
RECAP_DIRS = [paths.RAW_SLACK, paths.RAW_CLAUDE, paths.RAW_OUTLOOK, paths.RAW_JOURNAL]
# Coverage: qmd's top score below this means nothing in the vault really answers
# the question — answer tentatively and log a gap. ponytail: tune against eval.py.
COVERAGE_MIN = 0.35
GAPS = paths.GAPS


def _say(msg):
    """Emit a status line to stderr (the UI streams these as live progress)."""
    print(msg, file=sys.stderr, flush=True)


def _qmd_env():
    """Put qmd's own bin dir on PATH so a launchd-spawned ask can still find node."""
    env = dict(os.environ)
    qbin = os.path.dirname(QMD) if os.sep in QMD else ""
    if qbin and qbin not in env.get("PATH", ""):
        env["PATH"] = qbin + os.pathsep + env.get("PATH", "")
    return env


def _run_qmd(args):
    return subprocess.run([QMD, *args], capture_output=True, text=True,
                          timeout=QMD_TIMEOUT, env=_qmd_env())


def qmd_hits(question, vault, k=TOP_K, collection=None):
    """Ranked notes from qmd -> [(score, {path, title, text}), ...].

    Tries the hybrid `query` (expansion + vector + rerank); if that fails —
    e.g. the local models are still downloading — falls back to BM25 `search`.
    Full note text is read from disk (qmd's snippet is only a diff excerpt).
    """
    vp = Path(vault).expanduser()

    def parse(stdout):
        hits = []
        for r in json.loads(stdout or "[]"):
            rel = (r.get("file") or "").replace("qmd://", "")
            if not rel or Path(rel).name == "index.md":   # skip generated sub-indexes
                continue
            fp = vp / rel
            text = fp.read_text(errors="replace") if fp.exists() else (r.get("snippet") or "")
            hits.append((round(float(r.get("score", 0.0)), 3),
                         {"path": rel, "title": r.get("title") or Path(rel).stem, "text": text}))
        return hits

    base = ["-n", str(k), "--json"] + (["-c", collection] if collection else [])
    # vsearch (pure vector) measured best on this vault: hit@4 1.00 / MRR 0.96 vs
    # hybrid `query` 0.74 — paraphrased questions over short curated notes don't
    # benefit from BM25 fusion + rerank. BM25 `search` is the offline fallback
    # for when embeddings aren't ready. Re-measure with eval.py if the corpus shifts.
    for verb in ("vsearch", "search"):
        try:
            res = _run_qmd([verb, question, *base])
            if res.returncode == 0 and res.stdout.strip():
                hits = parse(res.stdout)
                if hits:
                    return hits
        except (subprocess.SubprocessError, OSError, json.JSONDecodeError, ValueError):
            continue
    return []


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
    keyword-retrieved — it's a date range over the daily logs. Recognise the
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
    """Answer a temporal question from the raw per-source logs. None if none in range."""
    label, dates = window
    vp = Path(vault).expanduser()
    files = []
    for d in dates:
        for sub in RECAP_DIRS:
            f = vp / sub / f"{d}.md"
            if f.exists():
                files.append(f)
    if not files:
        return None                                  # nothing logged → let retrieval try
    n = len(files)
    _say(f"Reading raw logs — {label} ({n} file{'s' if n != 1 else ''})…")
    ctx = "\n\n".join(f"--- {f.parent.name}/{f.stem} ---\n{f.read_text(errors='replace')[:JOURNAL_CHARS]}"
                      for f in files)
    prompt = (
        f"These are my raw work logs for {label}. Summarise concisely what I worked on "
        "and what happened — group by theme, skip empty/no-activity sections, don't "
        "invent anything not in the notes.\n\n"
        f"{ctx}\n\n=== QUESTION ===\n{question}\n\n=== SUMMARY ===\n")
    hits = [(None, {"path": str(f.relative_to(vp)), "title": f"{f.parent.name}/{f.stem}"})
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
    if window:               # temporal question → read the raw logs, not retrieval
        result = recap_journal(question, vault, window, on_chunk, done, unavailable)
        if result is not None:
            return result    # else nothing in range — fall through to retrieval

    _say("Searching your notes…")
    # Durable answers live in wiki/; query it first so raw/ (thousands of source
    # pages) can't drown the curated notes. Widen to raw only when the wiki falls
    # short — that's when source-diving is actually what you want.
    hits = qmd_hits(question, vault, collection="wiki")
    if not hits or hits[0][0] < COVERAGE_MIN:
        wide = qmd_hits(question, vault)
        if wide and (not hits or wide[0][0] > hits[0][0]):
            hits = wide
    if not hits:
        return done("No matching notes found in the vault.", [])
    # qmd's top score gauges coverage — a low one means nothing really matches (gap).
    weak = hits[0][0] < COVERAGE_MIN
    if weak and log_gap(vault, question, hits[0][0], hits[0][1]["path"]):
        _say("No strong match — answering tentatively and logging a coverage gap.")
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
        (v / paths.CONCEPTS).mkdir(parents=True)
        (v / paths.CONCEPTS / "rds.md").write_text(
            '---\ntitle: "RDS storage only grows"\n---\n'
            "RDS allocated storage cannot shrink in place; snapshot and restore smaller.")

        # qmd_hits parses qmd's JSON, maps qmd://<coll>/<rel> -> vault-relative path,
        # and reads FULL text from disk (not the diff snippet). Mock the subprocess.
        payload = json.dumps([{"docid": "#1", "score": 0.87,
                               "file": "qmd://wiki/concepts/rds.md",
                               "title": "RDS storage only grows", "snippet": "@@ diff @@"}])

        def _fake(args, _out):
            return type("R", (), {"returncode": 0, "stdout": _out, "stderr": ""})()
        orig = globals()["_run_qmd"]
        globals()["_run_qmd"] = lambda args: _fake(args, payload)
        try:
            hits = qmd_hits("shrink rds", str(v))
            assert hits and hits[0][1]["path"] == "wiki/concepts/rds.md", hits
            assert hits[0][0] == 0.87, hits
            assert "cannot shrink in place" in hits[0][1]["text"], hits   # read from disk
        finally:
            globals()["_run_qmd"] = orig
        # both verbs return empty -> no hits (no crash)
        globals()["_run_qmd"] = lambda args: _fake(args, "[]")
        try:
            assert qmd_hits("nothing here", str(v)) == []
        finally:
            globals()["_run_qmd"] = orig

        assert "QUESTION" in build_prompt("q", [(0.5, {"path": "p", "title": "t", "text": "body"})])
        assert "NOTE: p" in build_prompt("q", [(0.5, {"path": "p", "title": "t", "text": "body"})])

        # coverage gap log: writes once, dedups the normalized question, records score+closest
        assert log_gap(str(v), "how do I bake bread?", 0.21, "rds.md") is True
        assert log_gap(str(v), "how do I  bake   bread?", 0.21, "rds.md") is False
        g = (v / GAPS).read_text()
        assert '(0.21) "how do I bake bread?"' in g and "closest: rds.md" in g, g

        # stream_model parses SSE, assembles chunks in order, fires on_chunk live
        def _sse(c):
            return b'data: {"choices":[{"delta":{"content":"%s"}}]}' % c

        class _Fake:
            _lines = [_sse(b"Snap"), _sse(b"shot."), b"", b"data: [DONE]"]
            def read(self, *a):
                return b"{}"
            def __enter__(self):
                return iter(self._lines)
            def __exit__(self, *a):
                return False
        origu = urllib.request.urlopen
        urllib.request.urlopen = lambda *a, **k: _Fake()
        try:
            seen = []
            full = stream_model("p", seen.append)
            assert full == "Snapshot." and seen == ["Snap", "shot."], (full, seen)
        finally:
            urllib.request.urlopen = origu

        # detect_window date math, relative to a fixed Monday (2026-06-29)
        mon = datetime.date(2026, 6, 29)
        assert detect_window("notes on rds", mon) is None
        assert detect_window("what did we do today", mon) == ("today", ["2026-06-29"])
        assert detect_window("anything yesterday?", mon) == ("yesterday", ["2026-06-28"])
        lw = detect_window("what did we do last week", mon)
        assert lw[0] == "last week" and len(lw[1]) == 7, lw
        assert detect_window("this week", mon) == ("this week", ["2026-06-29"])
        assert len(detect_window("anything lately?", mon)[1]) == 7

        # recap reads raw per-source files in the window; falls through (None) when empty
        (v / paths.RAW_CLAUDE).mkdir(parents=True)
        (v / paths.RAW_CLAUDE / "2026-06-28.md").write_text("# Claude\nShipped the ask overlay.")
        urllib.request.urlopen = lambda *a, **k: _Fake()
        try:
            ans, hits = recap_journal("what did we do yesterday", str(v),
                                      ("yesterday", ["2026-06-28"]), lambda _t: None,
                                      lambda m, h: (m, h), "NA")
            assert ans == "Snapshot." and hits[0][1]["path"].endswith("2026-06-28.md"), (ans, hits)
            assert recap_journal("today", str(v), ("today", ["2099-01-01"]),
                                 lambda _t: None, lambda m, h: (m, h), "NA") is None
        finally:
            urllib.request.urlopen = origu
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
