#!/usr/bin/env python3
"""Draft promotions from recent raw activity on the on-device model (map-reduce).

promote.sh's planner. Reads every enabled source's raw/<dir>/<day>.md for the
given days plus raw/inbox drops (scrubbed), and prints the draft body that
dedupe.py and promote-apply.py consume — one item per '## ' heading:

    ## <title>
    Target: <kind hint (ADR 0005): gotcha, decision, pattern, how-to, concept,
             person, project, tech, security or clipping>
    Description: <one self-contained sentence>
    <2-3 line summary>
    Source: <section label, e.g. "slack 2026-10-02", or raw/inbox/<file>>

or exactly "Nothing to promote." A day is 30-100k tokens and the window 4-8k,
so (ADR 0021):

  map     each chunk (sized to the LIVE context window) -> at most 3 candidates;
          a candidate whose numbers/identifiers aren't in its chunk is dropped
          (ADR 0006), and its Source must be a label of that chunk.
  reduce  the model picks the strongest candidates by number (no rewriting);
          near-duplicates fold together in code. See promote_items.py.

Never writes to the vault. Exit codes: 0 draft printed (may be "Nothing to
promote."), 3 machine busy (background guard), 4 Apple Intelligence
unavailable, 5 every chunk failed, 6 no input.

  promote_plan.py [--vault V] [--dates D1,D2] [--out FILE] [--status-file F] [--no-guard]
"""
import argparse
import datetime
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import fm  # noqa: E402
import mapreduce as mr  # noqa: E402
import paths  # noqa: E402
import promote_items as pi  # noqa: E402
from scrub import redact  # noqa: E402

MAX_ITEMS = int(os.environ.get("PLASMIE_PROMOTE_MAX_ITEMS", "8"))
MAX_INPUT_CHARS = int(os.environ.get("PLASMIE_PROMOTE_MAX_CHARS", "200000"))
CHUNK_CEILING = int(os.environ.get("PLASMIE_PROMOTE_CHUNK_CHARS", "12000"))
RUN_SECONDS = int(os.environ.get("PLASMIE_PROMOTE_RUN_SECS", "1500"))
MAP_TOKENS, PICK_TOKENS, POLISH_TOKENS = 700, 60, 160
MAP_TIMEOUT, PICK_TIMEOUT, POLISH_TIMEOUT = 120, 60, 45
INBOX_CHARS = 4000

# The few-shot example. It cut kind-word headings ("## gotcha") from about half
# of all items to about 1 in 10 on real days, but a small model sometimes copies
# it verbatim, so tidy() drops any candidate that matches it. (Moving it above
# the rules copied less and broke the headings again: 23 of 65.)
EXAMPLE = pi.Item("RDS storage cannot shrink in place", "gotcha",
                  "RDS allocated storage only grows, so shrinking a database means "
                  "restoring a snapshot into a smaller instance.",
                  "Lowering allocated storage on the staging database was refused; a "
                  "snapshot restored into a new, smaller instance worked.",
                  "slack 2026-09-30")

RULES = """Rules:
- State only what the text explicitly says. Never upgrade a status: write merged, deployed, live, fixed or confirmed only if the text says exactly that. A plan, request or attempt stays a plan, request or attempt.
- Copy names, numbers and identifiers exactly as written. Never invent people, teams, numbers or follow-up work."""

MAP_INSTRUCTIONS = f"""You maintain a personal knowledge wiki. You read one slice of a person's raw work activity and pick out durable, reusable knowledge worth its own wiki note: decisions and their reasons, gotchas (a trap and how to escape it), how-tos, recurring patterns, project status changes, facts about people and systems. Ignore chatter, greetings, tool output and one-off noise. Every file listed under raw/inbox needs an item proposing its target.
{RULES}
- Each item is about ONE subject from the activity you are given. At most 3 items. If nothing qualifies, output exactly: {pi.NOTHING}
- Description is ONE sentence of at most 30 words.
Output ONLY markdown in exactly this shape (the ## heading names the subject; Target is one kind word from: {", ".join(pi.KINDS)}; this example's topic is not in your activity, so never repeat it):

{EXAMPLE.render().strip()}"""

PICK_INSTRUCTIONS = f"""You curate a personal knowledge wiki. Below are numbered candidate notes drawn from one stretch of a person's work activity. Choose the ones most worth keeping as wiki notes. Prefer knowledge someone could reuse months later: a gotcha and how to escape it, a decision and its reason, a how-to, a recurring pattern, a security finding. Keep a status update only when it records a real milestone. Skip vague, trivial or one-off items. When several cover the same subject, choose only the best one.
Reply with ONLY the numbers of the chosen notes, best first, comma-separated: between 4 and {MAX_ITEMS} numbers. Example: 4, 1, 12, 7"""

POLISH_INSTRUCTIONS = f"""You tidy one candidate note for a personal knowledge wiki. Write:
- Title: a specific name for its subject, at most 10 words.
- Description: ONE sentence of at most 30 words stating the durable takeaway someone could reuse later.
{RULES}
- Use only facts in the note.
Output exactly two lines and nothing else:
Title: <title>
Description: <sentence>"""

MAP_TASK = "=== END OF ACTIVITY ===\nOutput the items now."
PICK_TASK = "=== TASK ===\nThe numbers of the notes to keep, best first:"


def gather(vault: Path, dates: list[str]) -> list[mr.Section]:
    """Raw activity per enabled source and day, then raw/inbox drops (scrubbed:
    hand-dropped files never pass through ingest's redaction, and this text reaches
    the model AND the transcript log)."""
    secs = [mr.Section(f"{d.split('/')[-1]} {day}", f.read_text(errors="replace"))
            for day in dates for d in paths.activity_dirs()
            if (f := vault / "raw" / d / f"{day}.md").is_file()]
    secs = mr.cap_sections(secs, MAX_INPUT_CHARS)
    inbox = vault / paths.RAW_INBOX
    drops = []
    for f in sorted(inbox.iterdir()) if inbox.is_dir() else []:
        if not f.is_file() or f.name == ".gitkeep":
            continue
        if f.suffix in (".md", ".txt", ".markdown"):
            body = redact(f.read_text(errors="replace")[:INBOX_CHARS])
            drops.append(f"--- raw/inbox/{f.name} ---\n{body}")
        else:
            drops.append(f"--- raw/inbox/{f.name} (binary/unreadable — classify from the filename) ---")
    if drops:
        secs.append(mr.Section("raw/inbox (untriaged manual drops — propose a target for each)",
                               "\n\n".join(drops)))
    return [s for s in secs if s.text.strip()]


def extract(chunks: list[str], call: mr.Call, deadline: float, progress=None):
    """Map: candidates per chunk, each repaired and checked against its own chunk."""
    res = mr.run_map(chunks, lambda c: f"{c}\n\n{MAP_TASK}", call, deadline, progress)
    cands, dropped = [], 0
    for i, text in res.outputs:
        for raw in pi.parse_items(text):
            it = pi.tidy(raw, chunks[i], EXAMPLE)
            if it is None or pi.unsupported(it.claims(), chunks[i]):
                dropped += 1
                continue
            cands.append(it)
    return cands, dropped, res


def plan(vault: Path, dates: list[str], guard: bool = True, status=None):
    """-> (exit_code, draft_body, stats). Reads the vault, never writes it."""
    secs = gather(vault, dates)
    if not secs:
        return 6, "", {"chunks": 0}
    ctx = fm.context_size()
    if not ctx:
        p = fm.probe()
        return 4, "", {"reason": p.get("reason"), "hint": p.get("hint")}

    def caller(instructions: str, max_tokens: int, timeout: int) -> mr.Call:
        return lambda prompt: fm.respond(prompt, timeout=timeout, max_tokens=max_tokens,
                                         guard=guard, instructions=instructions, permissive=True)

    chunks = mr.chunk(secs, mr.chunk_chars(MAP_INSTRUCTIONS + MAP_TASK, MAP_TOKENS, ctx,
                                           CHUNK_CEILING))
    deadline = time.monotonic() + RUN_SECONDS
    say = (lambda i, n: status(f"Drafting on-device — part {i} of {n}…")) if status else None
    try:
        cands, dropped, res = extract(chunks, caller(MAP_INSTRUCTIONS, MAP_TOKENS, MAP_TIMEOUT),
                                      deadline, say)
        if not res.outputs:
            return 5, "", {"chunks": len(chunks), "failed": len(res.failed)}
        if status:
            status(f"Choosing from {len(cands)} candidates…")
        pick = caller(PICK_INSTRUCTIONS, PICK_TOKENS, PICK_TIMEOUT)
        limit = mr.chunk_chars(PICK_INSTRUCTIONS + PICK_TASK, PICK_TOKENS, ctx)
        items, how = pi.choose(cands, lambda m: pick(f"{m}\n\n{PICK_TASK}"), limit, MAX_ITEMS)
        if status:
            status(f"Tidying {len(items)} notes…")
        polish = caller(POLISH_INSTRUCTIONS, POLISH_TOKENS, POLISH_TIMEOUT)
        items = [pi.polish(i, polish) for i in items]
    except mr.Abort as a:
        return (3 if a.code == "busy" else 4), "", {"reason": a.reason}
    stats = {"chunks": len(chunks), "failed": len(res.failed), "candidates": len(cands),
             "dropped": dropped, "items": len(items), "reduce": how, "context": ctx,
             "input_chars": sum(len(s.text) for s in secs)}
    return 0, ("\n".join(i.render() for i in items) if items else pi.NOTHING), stats


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    today = datetime.date.today()
    ap.add_argument("--vault", default=paths.vault())
    ap.add_argument("--dates", default=f"{today - datetime.timedelta(days=1)},{today}")
    ap.add_argument("--out")
    ap.add_argument("--status-file")
    ap.add_argument("--no-guard", action="store_true", help="skip the busy guard (manual runs)")
    a = ap.parse_args()

    def status(msg: str) -> None:
        if a.status_file:
            try:
                Path(a.status_file).write_text(f"{int(time.time())}|{msg}")
            except OSError:
                pass
    code, body, stats = plan(Path(a.vault).expanduser(), [d for d in a.dates.split(",") if d],
                             guard=not a.no_guard, status=status)
    print("PLAN: " + " ".join(f"{k}={v}" for k, v in stats.items()), file=sys.stderr)
    if code == 0:
        if a.out:
            Path(a.out).write_text(body + "\n")
        else:
            print(body)
    return code


if __name__ == "__main__":
    sys.exit(main())
