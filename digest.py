#!/usr/bin/env python3
"""The hourly digest's generation step: raw activity on stdin -> 4-8 bullets on stdout.

summarize.sh gathers today's raw activity ("===== <source> =====" blocks, each
source's newest tail) and pipes it here. When the prompt fits the LIVE context
window it is one call with the measured prompt (faithfulness rules cut
unsupported claims from 14/15 to 3/15 digests, docs/fm-baseline.md). When it
doesn't — always on a 4096-token Mac — it map-reduces (ADR 0025): each chunk
condenses to a few bullets, then the bullet lists merge into the digest.

Exit codes: 0 bullets printed, 3 machine busy (background guard), 4 Apple
Intelligence unavailable (reason + hint on stderr), 5 generation failed.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import fm  # noqa: E402
import mapreduce as mr  # noqa: E402

MAX_TOKENS = 800          # the digest
MAP_TOKENS = 400          # bullets per chunk
TIMEOUT = 90

RULES = """Rules:
- State only what the log explicitly says. Never upgrade a status: write merged, deployed, live, fixed or confirmed only if the log says exactly that. A request, plan or attempt stays a request, plan or attempt.
- Copy names, PR numbers and identifiers exactly as written. Never invent people, teams, milestones or follow-up work.
- If unsure, leave it out: fewer accurate bullets beat more guessed ones.
No preamble, no headings, bullets only."""

HEAD = ("Condense this raw activity log into 4-8 terse markdown bullets: real decisions, "
        f"blockers, and who/what changed.\n{RULES}")
MAP_HEAD = ("Condense this slice of today's raw activity log into at most 5 terse markdown "
            f"bullets: real decisions, blockers, and who/what changed.\n{RULES}")
REDUCE_HEAD = ("These bullet lists each condense one slice of the same day's raw activity log. "
               "Merge them into 4-8 terse markdown bullets: real decisions, blockers, and "
               "who/what changed. Merge duplicates and keep the most important.\n"
               + RULES.replace("the log", "the bullets"))

EXIT = {"busy": 3, "unavailable": 4}


def _call(head: str, max_tokens: int, guard: bool) -> mr.Call:
    return lambda body: fm.respond(f"{head}\n\n{body}", timeout=TIMEOUT, max_tokens=max_tokens,
                                   guard=guard, permissive=True)


def digest(text: str, guard: bool = True) -> tuple[int, str]:
    """-> (exit code, bullets)."""
    ctx = fm.context_size()
    if not ctx:
        p = fm.probe()
        return 4, f"{p.get('detail', '')} {p.get('hint', '')}".strip()
    prompt_tokens = fm.estimate_tokens(f"{HEAD}\n\n{text}") + mr.TEMPLATE_TOKENS
    if prompt_tokens + MAX_TOKENS <= ctx:
        res = _call(HEAD, MAX_TOKENS, guard)(text)
        if "error" not in res:
            return 0, res["text"]
        if res["error"] not in mr.SPLIT_ON:
            return EXIT.get(res["error"], 5), str(res.get("reason", ""))
    try:
        chunks = mr.chunk(mr.split_labelled(text), mr.chunk_chars(MAP_HEAD, MAP_TOKENS, ctx))
        mapped = mr.run_map(chunks, lambda c: c, _call(MAP_HEAD, MAP_TOKENS, guard))
        if not mapped.outputs:
            return 5, f"every chunk failed: {mapped.failed}"
        parts = [t for _, t in mapped.outputs]
        out = mr.reduce_parts(parts, lambda t: t, _call(REDUCE_HEAD, MAX_TOKENS, guard),
                              mr.chunk_chars(REDUCE_HEAD, MAX_TOKENS, ctx))
    except mr.Abort as a:
        return EXIT.get(a.code, 5), a.reason
    return (0, out) if out else (5, "merge failed")


def main() -> int:
    code, out = digest(sys.stdin.read())
    if code == 0:
        print(out, end="")
    else:
        print(out, file=sys.stderr)
    return code


if __name__ == "__main__":
    sys.exit(main())
