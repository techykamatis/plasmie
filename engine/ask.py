#!/usr/bin/env python3
"""Ask anything in the vault — local-only RAG over your notes.

Retrieve the most relevant notes with **qmd** (vector search — measured best on
this vault; see eval.py), then answer using ONLY those notes. Synthesis runs
on Apple's on-device Foundation Model via fm.py (no model load, streams
immediately; the only backend, ADR 0002). The prompt is budgeted to the
live context window, question last. If the model can't answer — Apple
Intelligence off, still downloading, or a failure before any text — it says why
and shows the matching notes, so you still get an answer.

The model is never asked to cite: the UI shows the real retrieved Sources list
(printed from retrieval, not from model output), and a model-written citation
was the one thing FM fabricated in the A/B (ADR 0002).

qmd owns retrieval (see the vault's CLAUDE.md); ask.py owns the private
synthesis and the promote/improve loops that depend on it. Retrieval
is over the **wiki** collection (Plasmie's curated notes) and the **vault** collection
(the user's own notes, in whatever folders they keep) — raw/ is immutable source
material, not an answer source. If vector search can't run yet (models still downloading), it
falls back to BM25 `qmd search`.

Summary questions ("any decisions lately?", "what's blocking me?", a time window) take
their own path (ADR 0007): filed notes of the asked-for kind first, day logs to fill gaps
(the only time raw/ is read), a draft, a plain-English rewording pass and plain.cleanup().
They print in one piece instead of streaming. Direct lookups are untouched by any of it.

Two output channels so a UI can show live progress:
  stdout = the answer text (streamed), then a "Sources:" list
  stderr = staged status ("Searching your notes…", "Answering on-device…")

Usage:
  ask.py "how do I shrink RDS storage?" [VAULT]
  ask.py --selfcheck
"""
import datetime
import hashlib
import json
import re
import subprocess
import sys
import time
from pathlib import Path

import fm
import paths
import plain
from mapreduce import fair_shares  # noqa: F401  (re-exported; tests use ask.fair_shares)

TOP_K = 4             # notes fed as context
PER_NOTE = 4000       # ceiling on chars of one note (the real share is budget-driven)
JOURNAL_CHARS = 6000  # ceiling on chars of one daily log in a recap prompt
NUM_PREDICT = 600     # cap answer length so a runaway model can't hang the ask
FM_TIMEOUT = 60       # seconds for the on-device model (a person is waiting)
# Conservative: markdown, identifiers and paths tokenize worse than prose. Overshoot
# makes fm.generate return None (no answer); undershoot just trims a little more.
CHARS_PER_TOKEN = 3.0
TEMPLATE_TOKENS = 200  # chat-template/system overhead not counted in our text
DEFAULT_CONTEXT = 4096  # when fm can't report one: Apple's documented minimum
DIGESTS = f"{paths.META}/digests"   # meta/digests/YYYY-MM-DD.md — short on-device rollups
RECAP_TOKENS = 320    # 8 short bullets; a recap ran 26 bullets / 25s on the shared 600 cap
RECAP_CHARS = 12000   # recap prompts stay well under the window: prefill time scales with it
LONG_WINDOW_DAYS = 2  # recaps spanning more days read digests, not raw logs
# Summary questions ("any decisions lately?", "what's blocking me?") — ADR 0007
SUMMARY_NOTES = 5         # filed notes of the asked-for kind in one summary prompt
NOTE_CHARS = 1500         # ceiling on one filed note there (notes are read before logs)
FILED_LOOKBACK_DAYS = 30  # "lately" for filed notes: promoted nightly, so a week is thin
GAP_FILL_BELOW = 3        # fewer filed notes than this: fill in from the day logs
REPHRASE_TOKENS = 220     # 5 one-sentence bullets
REPHRASE_TIMEOUT = 20     # the plain-words pass; on timeout the cleaned draft is shown
LAST_TIMING = {}          # the last summary answer's timings (eval and diagnostics)

QMD = paths.qmd_bin()   # Plasmie's own qmd first, then any installed one
QMD_TIMEOUT = 60
# raw per-source dirs a temporal recap reads (+ the legacy combined journal)
RECAP_DIRS = [paths.RAW_SLACK, paths.RAW_CLAUDE, paths.RAW_OUTLOOK, paths.RAW_GITHUB, paths.RAW_GIT,
              paths.RAW_JOURNAL]
# Coverage: qmd's top score below this means nothing in the vault really answers
# the question — answer tentatively and log a gap. ponytail: tune against eval.py.
COVERAGE_MIN = 0.35
GAPS = paths.GAPS
USAGE = "meta/usage.tsv"


def _say(msg):
    """Emit a status line to stderr (the UI streams these as live progress)."""
    print(msg, file=sys.stderr, flush=True)


def _qmd_env():
    """qmd's bin dir and Plasmie's bundled Node on PATH (the app and launchd give a bare PATH)."""
    return paths.qmd_env(QMD)


def _run_qmd(args):
    return subprocess.run([QMD, *args], capture_output=True, text=True,
                          timeout=QMD_TIMEOUT, env=_qmd_env())


# qmd collection -> its folder in the vault (app-setup.sh registers them; "vault" is the
# root, minus raw/ wiki/ meta/). qmd hands back paths "handelized" (spaces -> dashes,
# e.g. qmd://vault/02-Areas/...), so a path that isn't on disk is matched back to the
# real file by its normalized form.
COLLECTION_DIRS = {"wiki": "wiki", "raw": "raw", "vault": ""}
_real_paths = {}


def _norm(rel):
    return re.sub(r"[^a-z0-9]+", "-", rel.lower()).strip("-")


def real_path(vp, qmd_file):
    """qmd://<collection>/<path> -> the vault-relative path of the real file."""
    coll, _, rest = qmd_file.replace("qmd://", "").partition("/")
    base = COLLECTION_DIRS.get(coll, coll)
    rel = f"{base}/{rest}" if base else rest
    if (vp / rel).exists():
        return rel
    key = str(vp)
    if key not in _real_paths:
        _real_paths[key] = {_norm(p.relative_to(vp).as_posix()): p.relative_to(vp).as_posix()
                            for p in vp.rglob("*.md")
                            if not any(part.startswith(".") for part in p.relative_to(vp).parts)}
    return _real_paths[key].get(_norm(rel), rel)


def qmd_hits(question, vault, k=TOP_K, collection=None):
    """Ranked notes from qmd -> [(score, {path, title, text}), ...].

    Tries vector search (vsearch); if that fails — e.g. the embedding model is
    still downloading — falls back to BM25 `search`. Full note text is read from
    disk (qmd's snippet is only a diff excerpt).
    """
    vp = Path(vault).expanduser()

    def parse(stdout):
        hits = []
        for r in json.loads(stdout or "[]"):
            rel = real_path(vp, r.get("file") or "") if r.get("file") else ""
            # skip generated navigation: an index or a map of content is a list of
            # titles, so as a "source" it hands the model headings instead of facts.
            if not rel or Path(rel).name == "index.md" or paths.MOCS in rel:
                continue
            fp = vp / rel
            text = fp.read_text(errors="replace") if fp.exists() else (r.get("snippet") or "")
            hits.append((round(float(r.get("score", 0.0)), 3),
                         {"path": rel, "title": r.get("title") or Path(rel).stem, "text": text}))
        return hits

    colls = [collection] if isinstance(collection, str) else list(collection or [])
    base = ["-n", str(k), "--json"] + [a for c in colls for a in ("-c", c)]
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


def log_usage(vault, question, hits):
    """Append which notes actually answered something, to meta/usage.tsv.

    log_gap() records what the vault COULDN'T answer; this is the other half —
    what it did, and with which notes. Without it nothing distinguishes a note
    that carries the vault from one nobody has opened since it was promoted, so
    retirement has to guess from link count alone. Append-only TSV: date, query
    hash (dedup without storing the question), rank, score, path.
    """
    path = Path(vault).expanduser() / USAGE
    qh = hashlib.sha1(" ".join(question.split()).lower().encode()).hexdigest()[:8]
    today = datetime.date.today().isoformat()
    rows = "".join(f"{today}\t{qh}\t{i}\t{'' if score is None else score}\t{doc['path']}\n"
                   for i, (score, doc) in enumerate(hits, 1))
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        new = not path.exists()
        with path.open("a") as fh:
            if new:
                fh.write("# date\tquery\trank\tscore\tpath\n")
            fh.write(rows)
    except OSError:
        pass          # usage stats are never worth failing an answer over


RULES = """Rules:
- State only what the notes explicitly say. Never upgrade a status: write merged, deployed, live, fixed or confirmed only if the notes say exactly that. A plan, request or attempt stays a plan, request or attempt.
- Copy names, numbers and identifiers exactly as written. Never invent people, teams, links, file names, dates or follow-up work.
- If the notes don't cover the question, say so plainly in one sentence instead of guessing. If they cover it only partly, answer that part and say what is missing.
- Don't mention note numbers, file names or sources; the reader already sees them separately.
- Answer the question directly in 2-4 sentences, with the specific facts from the notes (what, when, who, numbers). For an open question like "what happened", summarize the events the notes record, in order.
- Never answer by repeating a note's opening description."""


def prompt_char_budget(max_tokens=NUM_PREDICT, ctx=None):
    """Chars available for the whole prompt: live context window minus the answer
    reserve and template overhead, at a conservative chars/token."""
    ctx = ctx or fm.context_size() or DEFAULT_CONTEXT
    return max(1000, int((ctx - max_tokens - TEMPLATE_TOKENS) * CHARS_PER_TOKEN))


def build_prompt(question, hits, weak=False, budget_chars=None):
    """Notes first, QUESTION LAST (fm.generate refuses to trim the tail), with the
    notes trimmed fairly so the whole prompt fits `budget_chars`."""
    warn = ("These notes are only weakly related to the question — they may not "
            "answer it. If they don't, say the vault doesn't cover this yet rather "
            "than forcing an answer.\n\n") if weak else ""
    head = ("Answer the question using ONLY the notes below.\n"
            f"{RULES}\n\n{warn}")
    tail = f"\n\n=== QUESTION ===\n{question}\n\n=== ANSWER ===\n"
    budget = prompt_char_budget() if budget_chars is None else budget_chars
    labels = [f"--- NOTE {i}: {doc['title']} ---\n" for i, (_, doc) in enumerate(hits, 1)]
    seps = 2 * max(0, len(hits) - 1)
    room = budget - len(head) - len(tail) - sum(map(len, labels)) - seps
    # frontmatter is metadata, not content: dropped, it stops the model echoing it and
    # leaves the budget to the notes' facts (the title is already in each label)
    texts = [re.sub(r"\A---\n.*?\n---\n", "", doc["text"], flags=re.S) for _, doc in hits]
    caps = fair_shares([min(len(t), PER_NOTE) for t in texts], room)
    ctx = "\n\n".join(lab + t[:c] for lab, t, c in zip(labels, texts, caps))
    return f"{head}{ctx}{tail}"


def fm_answer(prompt, on_chunk, max_tokens=NUM_PREDICT):
    """Stream the on-device answer. Returns the text, or None if FM produced nothing.

    Once any text has streamed the user has seen it, so a late failure (timeout,
    refusal) keeps what streamed and says it was cut short.
    """
    streamed = []

    def tap(t):
        streamed.append(t)
        on_chunk(t)

    _say("Answering on-device…")
    out = fm.generate(prompt, max_tokens=max_tokens, on_chunk=tap,
                      timeout=FM_TIMEOUT, guard=False)
    if out is not None:
        return out
    partial = "".join(streamed).strip()
    if not partial:
        return None
    notice = "\n\n(The on-device answer was cut short.)"
    on_chunk(notice)
    return partial + notice


def unavailable_notice():
    """Why there is no generated answer, in words a person can act on."""
    p = fm.probe()
    if p.get("available") is True:
        return "(couldn't generate an answer — showing the most relevant notes below)"
    return (f"(Apple Intelligence isn't available, so no answer was written — showing the "
            f"most relevant notes below. {p.get('hint') or ''})").replace(" )", ")")


def synthesize(prompt, on_chunk, max_tokens=NUM_PREDICT):
    """The on-device answer, or "" when the model produced nothing."""
    out = fm_answer(prompt, on_chunk, max_tokens)
    if out is None:
        _say("On-device model unavailable.")
        return ""
    return out


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
    # "what's new / any new changes / latest updates / what changed" -> a recent
    # window. Not when a topic follows ("what changed in the RDS upgrade") — that
    # is a retrieval question, and hijacking it to the logs would be worse.
    nt = r"(?![\w\s]*\b(?:in|to|on|for|about|with|of|from|regarding|around)\b)"
    if (re.search(r"\b(?:any|anything|something)\s+(?:new|recent)\b" + nt, q)
            or re.search(r"\bwhat(?:'s|s| is| has| have)?\s+(?:new|changed|been going on)\b" + nt, q)
            or re.search(r"\b(?:new|latest|recent)\s+(?:changes|updates|activity|news|developments)\b" + nt, q)
            or re.search(r"\bcatch me up\b", q)):
        return "the last two days", span(today - day, today)
    return None


def recap_files(vault, dates):
    """Files a recap reads. Short windows: raw per-source logs (falling back to that
    day's digest if there are none). Long windows: the daily digests — already short
    on-device rollups, where raw logs would be ~100 KB/day — with raw only for days
    that have no digest yet."""
    vp = Path(vault).expanduser()
    long_window = len(dates) > LONG_WINDOW_DAYS
    files = []
    for d in dates:
        raw = [f for sub in RECAP_DIRS if (f := vp / sub / f"{d}.md").exists()]
        dig = vp / DIGESTS / f"{d}.md"
        if long_window:
            files += [dig] if dig.exists() else raw
        else:
            files += raw or ([dig] if dig.exists() else [])
    return files


def log_docs(vault, files):
    """Day logs/digests as answer docs: (None, {path, title, text}) — no qmd score."""
    vp = Path(vault).expanduser()
    return [(None, {"path": str(f.relative_to(vp)), "title": f"{f.parent.name}/{f.stem}",
                    "text": f.read_text(errors="replace")}) for f in files]


# ---- summary questions (ADR 0007) -------------------------------------------
# "Any major decisions lately?" wants a few plain sentences, not the logs' commit IDs
# and test names. Such a question gets its own sources (filed notes of the asked-for
# kind first, day logs to fill gaps), a draft under tighter rules, a rewording-only
# plain-English pass, and a deterministic cleanup (plain.py). Direct lookups ("what's
# the datadog api host?") never come here: they keep the precise, streamed answer.

_INTENTS = (
    ("blockers", r"\bblockers?\b|\bwhat(?:'s|s| is| are)?\s+(?:blocking|holding\s+up|holding)\s+"
                 r"(?:me|us)\b|\b(?:am i|are we|i'm|im|we're)\s+(?:blocked|stuck)\b|"
                 r"\bwhat(?:'s|s| is)\s+stuck\b|\banything\s+(?:blocking|stuck)\b|\bblocked on\b"),
    ("decisions", r"\bdecisions?\b|\bdecided\b|\bwhat did (?:i|we) (?:decide|choose|pick)\b"),
    ("gotchas", r"\bgotchas?\b|\bpitfalls?\b|\blessons? learn(?:ed|t)\b"),
    ("howtos", r"\bhow-?tos\b|\brunbooks\b"),
    ("recap", r"\bwhat (?:did|have|has) (?:i|we) (?:do|done|work(?:ed)? on|get done|got done|"
              r"ship(?:ped)?|been (?:doing|working on|up to))\b|\bwhat (?:was|were) (?:i|we) "
              r"(?:doing|working on)\b|\b(?:summar(?:y|ise|ize)|recap|overview|highlights)\b|"
              r"\bcatch me up\b|\bwhat happened\b"),
    ("changes", r"\bwhat(?:'s|s| has| have)?\s+changed\b|\b(?:recent|latest|new)\s+changes\b"),
)
# Words that say what KIND of answer is wanted, never what it is about. Whatever is
# left after removing them is the question's topic ("the release process").
_NOT_TOPIC = set("""
a an the i we me us my our you your it its this that these those what what's whats which
who when where why how any anything something some all major big key important main
notable significant recent recently lately latest new past few last week weeks month
months today yesterday day days so far been be is are was were am do does did done doing
have has had made make making get got go going decision decisions decided decide choose
chose chosen pick picked blocker blockers blocking blocked block holding stuck gotcha
gotchas pitfall pitfalls lesson lessons learned learnt how-to how-tos howto howtos runbook
runbooks changed change changes happen happened happening summary summarise summarize
recap overview highlights catch up work worked working on ship shipped to of in for with
about there there's please tell show give list still now currently right just been
""".split())
_KIND_TYPES = {"decisions": "decision", "gotchas": "gotcha", "howtos": "how-to"}
_TASK = {
    "decisions": "List the decisions I made: what I chose and why. Skip routine work that wasn't a choice.",
    "blockers": "List what is still blocked or failing, and why, going by the latest entries. Skip anything that got fixed.",
    "gotchas": "List the traps I ran into and how to avoid each.",
    "howtos": "List the procedures I wrote down and what each one is for.",
    "changes": "Summarise what changed and why.",
    "recap": "Summarise what I worked on and what happened, most important first.",
}
SUMMARY_RULES = """Rules:
- State only what the notes and logs say. Never upgrade a status: a plan, request or attempt stays one.
- Never invent people, dates, numbers, reasons or follow-up work.
- At most 5 bullets starting with "- ", one sentence each, most important first. Merge entries about the same thing.
- Write for a reader who doesn't code: say what changed and why, addressing me as "you". Keep real names as written. Never write commit IDs, file names, test names, branch names or backticks.
- No headings or labels; don't repeat these instructions.
- If nothing fits the question, say so in one sentence."""


def _topic(q):
    words = re.findall(r"[a-z0-9][a-z0-9'-]*", q.lower())
    return " ".join(w for w in words if w not in _NOT_TOPIC)


def classify(question, today=None):
    """A summary-style question -> {kind, window, topic, summary}; None for a direct lookup.

    summary=False only for a topical gotcha/how-to ("the how-to for releases"): that
    answer IS the steps or the fix, so it keeps the precise path, retrieved by kind.
    """
    q = question.lower()
    window = detect_window(question, today)
    kind = next((k for k, rx in _INTENTS if re.search(rx, q)), None)
    if kind is None and window is None:
        return None
    kind = kind or "recap"
    topic = _topic(q)
    return {"kind": kind, "window": window, "topic": topic,
            "summary": not (topic and kind in ("gotchas", "howtos"))}


def _frontmatter(text):
    m = re.match(r"\A---\n(.*?)\n---\n", text, re.S)
    if not m:
        return {}
    out = {}
    for line in m.group(1).splitlines():
        k, sep, v = line.partition(":")
        if sep and not k.startswith((" ", "\t", "-")):
            out[k.strip().lower()] = v.strip().strip("'\"")
    return out


def _is_kind(meta, want):
    tags = re.findall(r"[\w-]+", meta.get("tags", "").lower())
    return meta.get("type", "").lower() == want or want in tags


def _note_day(meta, text, p):
    """A filed note's latest day: its timestamp/date, or a later promote merge, else mtime."""
    days = [m for k in ("timestamp", "updated", "date", "created")
            if (m := re.match(r"\d{4}-\d\d-\d\d", meta.get(k, "")))]
    days = [d.group(0) for d in days] + re.findall(r"^- \*\*(\d{4}-\d\d-\d\d) \(", text, re.M)
    if days:
        return max(days)
    return datetime.date.fromtimestamp(p.stat().st_mtime).isoformat()


def filed_notes(vault, want, since, until):
    """Notes whose frontmatter says `type: <want>` (or carry the tag), dated in
    [since, until], newest first. Skips raw/, meta/, archive/ and generated maps."""
    vp = Path(vault).expanduser()
    skip = {paths.RAW, paths.META, paths.ARCHIVE}
    found = []
    for p in vp.rglob("*.md"):
        rel = p.relative_to(vp)
        if (rel.parts[0] in skip or any(x.startswith(".") for x in rel.parts)
                or rel.name == paths.INDEX or rel.as_posix().startswith(paths.MOCS + "/")):
            continue
        try:
            with p.open(errors="replace") as fh:
                head = fh.read(2048)
        except OSError:
            continue
        meta = _frontmatter(head)
        if not _is_kind(meta, want):
            continue
        text = p.read_text(errors="replace")
        day = _note_day(meta, text, p)
        if since <= day <= until:
            found.append((day, {"path": rel.as_posix(), "title": meta.get("title") or p.stem,
                                "text": text}))
    found.sort(key=lambda x: x[0], reverse=True)
    return [(None, doc) for _, doc in found]


def _is_log(rel):
    return rel.startswith((paths.RAW + "/", DIGESTS + "/"))


def _span(today, days):
    return [(today - datetime.timedelta(days=i)).isoformat() for i in range(days - 1, -1, -1)]


def gather(question, vault, intent, today=None):
    """Sources for a summary question -> (label, docs). docs may be empty."""
    today = today or datetime.date.today()
    kind, window, topic = intent["kind"], intent["window"], intent["topic"]
    want = _KIND_TYPES.get(kind)
    if topic:       # about something: retrieve it, notes of the asked-for kind first
        hits = qmd_hits(question, vault, k=TOP_K * 2 if want else TOP_K,
                        collection=["wiki", "vault"])
        if want:
            hits = sorted(hits, key=lambda h: not _is_kind(_frontmatter(h[1]["text"]), want))
        return "your notes", hits[:TOP_K]
    label, log_days = window or ("the past week", _span(today, 7))
    docs = []
    if want:
        # an explicit window is honoured; "lately" means the past month for filed notes
        explicit = window and window[0] in ("today", "yesterday", "this week", "last week")
        days = window[1] if explicit else _span(today, FILED_LOOKBACK_DAYS)
        docs = filed_notes(vault, want, days[0], days[-1])[:SUMMARY_NOTES]
        if not explicit:
            label = "the past month"
    if not want or len(docs) < GAP_FILL_BELOW:
        docs += log_docs(vault, recap_files(vault, log_days))
    return label, docs


def build_summary_prompt(question, kind, label, docs, budget_chars=None):
    """Filed notes first, each up to NOTE_CHARS; day logs share what is left."""
    head = (f"Below are my notes and work logs for {label}. {_TASK[kind]}\n"
            f"{SUMMARY_RULES}\n\n")
    tail = f"\n\n=== QUESTION ===\n{question}\n\n=== SUMMARY ===\n"
    budget = min(prompt_char_budget(), RECAP_CHARS) if budget_chars is None else budget_chars
    is_log = [_is_log(d["path"]) for _, d in docs]
    labels = [f"--- {d['title']} ---\n" if log else f"--- NOTE: {d['title']} ---\n"
              for (_, d), log in zip(docs, is_log)]
    texts = [re.sub(r"\A---\n.*?\n---\n", "", d["text"], flags=re.S) for _, d in docs]
    room = budget - len(head) - len(tail) - sum(map(len, labels)) - 2 * len(docs)
    notes = [i for i, log in enumerate(is_log) if not log]
    logs = [i for i, log in enumerate(is_log) if log]
    caps = [0] * len(docs)
    for i, c in zip(notes, fair_shares([min(len(texts[i]), NOTE_CHARS) for i in notes], room)):
        caps[i] = c
    left = room - sum(caps)
    for i, c in zip(logs, fair_shares([min(len(texts[i]), JOURNAL_CHARS) for i in logs], left)):
        caps[i] = c
    ctx = "\n\n".join(lab + t[:c] for lab, t, c in zip(labels, texts, caps))
    return f"{head}{ctx}{tail}"


def build_recap_prompt(question, label, files, budget_chars=None):
    """A time-window recap over day logs (kept for callers that have files, not docs)."""
    docs = [(None, {"path": f"{paths.RAW}/{f.parent.name}/{f.name}",
                    "title": f"{f.parent.name}/{f.stem}",
                    "text": f.read_text(errors="replace")}) for f in files]
    return build_summary_prompt(question, "recap", label, docs, budget_chars)


def plain_answer(question, prompt, docs):
    """Draft, then plain words. Returns the answer, or None if the model gave nothing.

    The draft is not streamed: it is about to be reworded, and a person shouldn't
    watch commit IDs appear and then vanish. Pass 2 is skipped when the draft is
    already short and plain, and its output is only used when it adds no number or
    name the draft and sources lack (ADR 0006); otherwise the cleaned draft is shown.
    """
    t0 = time.monotonic()
    _say("Answering on-device…")
    draft = fm.generate(prompt, max_tokens=RECAP_TOKENS, timeout=FM_TIMEOUT, guard=False)
    timing = {"draft_s": round(time.monotonic() - t0, 2), "rephrase_s": None}
    LAST_TIMING.update(timing, path="none")
    if not draft:
        return None
    cleaned = plain.cleanup(draft)
    path, final = "draft-plain", cleaned
    if not plain.is_plain(draft):
        _say("Putting it in plain words…")
        t1 = time.monotonic()
        out = fm.generate(plain.rephrase_prompt(cleaned or draft), max_tokens=REPHRASE_TOKENS,
                          timeout=REPHRASE_TIMEOUT, guard=False)
        timing["rephrase_s"] = round(time.monotonic() - t1, 2)
        rc = plain.trim_nothing(plain.cleanup(out or ""))
        bad = plain.introduced(rc, draft, question, *(d.get("text", "") for _, d in docs))
        if not rc:
            path = "fallback:no-rewrite"
        elif bad:
            path = f"fallback:added {', '.join(bad[:5])}"
        elif plain.says_nothing(rc) and len(plain.bullets(cleaned)) >= 2:
            path = "fallback:dropped-everything"
        else:
            path, final = "rephrased", rc
    final = final or "Nothing major in your notes for that stretch."
    LAST_TIMING.update(timing, path=path, draft=draft)
    return final


def summary_answer(question, vault, intent, on_chunk, done, unavailable, today=None):
    """Answer a summary question. None when there are no sources (let retrieval try)."""
    label, docs = gather(question, vault, intent, today)
    if not docs:
        return None
    notes = [h for h in docs if not _is_log(h[1]["path"])]
    n_notes, n_logs = len(notes), len(docs) - len(notes)
    parts = ([f"{n_notes} note{'s' if n_notes != 1 else ''}"] if n_notes else []) + \
            ([f"{n_logs} log{'s' if n_logs != 1 else ''}"] if n_logs else [])
    _say(f"Reading {' and '.join(parts)} — {label}…")
    if notes:
        log_usage(vault, question, notes)
    prompt = build_summary_prompt(question, intent["kind"], label, docs)
    answer = plain_answer(question, prompt, docs)
    if not answer:
        return done(unavailable() if callable(unavailable) else unavailable, docs)
    on_chunk(answer)
    return answer, docs


def recap_journal(question, vault, window, on_chunk, done, unavailable):
    """Answer a temporal question from the logs/digests. None if none in range."""
    intent = {"kind": "recap", "window": window, "topic": "", "summary": True}
    return summary_answer(question, vault, intent, on_chunk, done, unavailable)


def ask(question, vault=None, on_chunk=None):
    """Retrieve, then stream an answer. on_chunk(text) receives answer tokens live."""
    vault = vault or paths.vault()
    on_chunk = on_chunk or (lambda _t: None)
    def done(msg, hits):     # every answer path must emit the text, not just the stream
        on_chunk(msg)
        return msg, hits

    LAST_TIMING.clear()
    intent = classify(question)
    if intent and intent["summary"]:
        # summary question → its own sources, a draft, then plain words (ADR 0007)
        result = summary_answer(question, vault, intent, on_chunk, done, unavailable_notice)
        if result is not None:
            return result    # else nothing to read — fall through to retrieval

    _say("Searching your notes…")
    # Answer from notes: Plasmie's curated wiki/ and the user's own notes (the "vault"
    # collection, their folders as they keep them). Never raw/: it is immutable source
    # material to be synthesized INTO wiki (via promote), and can contradict curated
    # guidance. A weak/empty result is a coverage GAP to fill, not a reason to read raw.
    hits = qmd_hits(question, vault, collection=["wiki", "vault"])
    want = _KIND_TYPES.get(intent["kind"]) if intent else None
    if want:                 # "the how-to for releases": that kind of note first
        hits = sorted(hits, key=lambda h: not _is_kind(_frontmatter(h[1]["text"]), want))
    if not hits:
        if log_gap(vault, question, 0.0, "(none)"):
            _say("Nothing in your notes covers this — logged a coverage gap.")
        return done("Nothing in your notes covers this yet — I'll learn more as I gather and file your work.", [])
    # qmd's top score gauges coverage — a low one means nothing really matches (gap).
    top = max(hits, key=lambda h: h[0])
    weak = top[0] < COVERAGE_MIN
    if weak and log_gap(vault, question, top[0], top[1]["path"]):
        _say("No strong match — answering tentatively and logging a coverage gap.")
    log_usage(vault, question, hits)
    titles = ", ".join(doc["title"] for _, doc in hits[:3])
    _say(f"Found {len(hits)} relevant notes: {titles}")
    answer = synthesize(build_prompt(question, hits, weak=weak), on_chunk)
    if not answer:  # the model couldn't answer — fall back to the retrieved notes
        return done(unavailable_notice(), hits)
    return answer, hits


def selfcheck():
    orig_gen = fm.generate

    def fake(prompt, on_chunk=None, **_k):  # selfcheck never touches the real model
        for part in ("Snap", "shot."):
            if on_chunk:
                on_chunk(part)
        return "Snapshot."
    fm.generate = fake
    try:
        _selfcheck()
    finally:
        fm.generate = orig_gen
    print("ask selfcheck OK")


def _selfcheck():
    import tempfile
    with tempfile.TemporaryDirectory() as d:
        v = Path(d)
        (v / paths.WIKI / "concepts").mkdir(parents=True)
        (v / paths.WIKI / "concepts" / "rds.md").write_text(
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
        assert "NOTE 1: t" in build_prompt("q", [(0.5, {"path": "p", "title": "t", "text": "body"})])

        # coverage gap log: writes once, dedups the normalized question, records score+closest
        assert log_gap(str(v), "how do I bake bread?", 0.21, "rds.md") is True
        assert log_gap(str(v), "how do I  bake   bread?", 0.21, "rds.md") is False
        g = (v / GAPS).read_text()
        assert '(0.21) "how do I bake bread?"' in g and "closest: rds.md" in g, g

        # synthesize streams the on-device answer through on_chunk, in order
        seen = []
        assert synthesize("p", seen.append) == "Snapshot." and seen == ["Snap", "shot."], seen

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
        ans, hits = recap_journal("what did we do yesterday", str(v),
                                  ("yesterday", ["2026-06-28"]), lambda _t: None,
                                  lambda m, h: (m, h), "NA")
        assert ans == "Snapshot." and hits[0][1]["path"].endswith("2026-06-28.md"), (ans, hits)
        assert recap_journal("today", str(v), ("today", ["2099-01-01"]),
                             lambda _t: None, lambda m, h: (m, h), "NA") is None


if __name__ == "__main__":
    args = sys.argv[1:]
    if "--selfcheck" in args:
        selfcheck()
        sys.exit(0)
    if not args:
        print('usage: ask.py "your question" [VAULT]', file=sys.stderr)
        sys.exit(2)
    q = args[0]
    vault = args[1] if len(args) > 1 else paths.vault()
    # Stream answer tokens straight to stdout as they arrive.
    answer, hits = ask(q, vault, on_chunk=lambda t: (sys.stdout.write(t), sys.stdout.flush()))
    if not answer.endswith("\n"):
        print()
    if hits:
        print("\nSources:")
        for sc, doc in hits:
            print(f"  · {doc['path']}" + (f" ({sc})" if sc is not None else ""))
