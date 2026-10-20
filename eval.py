#!/usr/bin/env python3
"""Q&A retrieval eval — hit-rate@k + MRR over a grounded gold set.

Questions are paraphrased the way a user would actually ask (NOT echoing the
note title), each mapped to the concept note that answers it. Runs each qmd
search mode (BM25 `search`, `vsearch`, hybrid `query`) over the whole vault —
the same way ask.py retrieves — and prints a comparison table.

  python3 eval.py                # all three modes, k=4
  python3 eval.py --k 6          # different cutoff
  python3 eval.py --only query   # one mode

ponytail: gold set is a plain TSV of (question, expected-basename) kept in
the data folder (see GOLD_FILE) — no fixtures, no framework. Match by
path.endswith(expected). Add cases by appending lines.
"""
import json
import os
import shutil
import subprocess
import sys
import time
from statistics import mean

import paths

VAULT = paths.vault()
QMD = os.environ.get("PLASMIE_QMD") or shutil.which("qmd") or "qmd"


def qmd_retriever(verb):
    """f(question, k) -> [vault-relative path, ...] via `qmd <verb> --json`."""
    def f(q, k):
        try:
            r = subprocess.run([QMD, verb, q, "--json", "-n", str(k), "-c", "wiki"],
                               capture_output=True, text=True, timeout=60)
            return [(x.get("file") or "").replace("qmd://", "")
                    for x in json.loads(r.stdout or "[]")]
        except (subprocess.SubprocessError, OSError, json.JSONDecodeError, ValueError):
            return []
    return f

# (question a user would type, the concept note that answers it). The gold set is
# about YOUR vault, so it lives with your data, not in the repo: one case per line,
# "question<TAB>expected-basename.md", '#' comments allowed. PLASMIE_EVAL_GOLD overrides
# the path. The two examples below only show the shape; they match nothing.
GOLD_FILE = os.path.expanduser(os.environ.get("PLASMIE_EVAL_GOLD")
                               or os.path.join(paths.DATA_DIR, "eval-gold.tsv"))
EXAMPLE = [
    ("why can't I shrink my database disk?", "db-cannot-shrink-storage-in-place.md"),
    ("which hostname do I use for the metrics API?", "metrics-api-host-not-app-host.md"),
]


def load_gold(path=GOLD_FILE):
    """[(question, expected-basename)] from a TSV file; [] when it doesn't exist."""
    try:
        lines = open(path, encoding="utf-8").read().splitlines()
    except OSError:
        return []
    out = []
    for ln in lines:
        if not ln.strip() or ln.lstrip().startswith("#") or "\t" not in ln:
            continue
        q, want = ln.split("\t", 1)
        out.append((q.strip(), want.strip()))
    return out


GOLD = load_gold()


def score(retriever, k):
    ranks = []
    for q, want in GOLD:
        hits = retriever(q, k)
        rank = next((i + 1 for i, p in enumerate(hits) if p.endswith(want)), 0)
        ranks.append(rank)
    hit = mean(1 if r else 0 for r in ranks)
    mrr = mean(1 / r if r else 0 for r in ranks)
    return hit, mrr, ranks


def run(name, retriever, k):
    t = time.time()
    hit, mrr, ranks = score(retriever, k)
    q_s = (time.time() - t) / len(GOLD)
    misses = [GOLD[i][1] for i, r in enumerate(ranks) if not r]
    print(f"{name:8s} hit@{k}={hit:.2f}  MRR={mrr:.3f}  q={q_s*1000:.0f}ms")
    if misses:
        print(f"         misses: {', '.join(m[:34] for m in misses)}")
    return hit, mrr


if __name__ == "__main__":
    k = 4
    only = None
    a = sys.argv
    if "--k" in a:
        k = int(a[a.index("--k") + 1])
    if "--only" in a:
        only = a[a.index("--only") + 1]

    if not GOLD:
        print(f"no gold set at {GOLD_FILE}. Write one line per case:\n"
              + "\n".join(f"  {q}\t{w}" for q, w in EXAMPLE), file=sys.stderr)
        sys.exit(2)
    print(f"gold cases: {len(GOLD)}  k={k}\n")
    for name in ("search", "vsearch", "query"):
        if only and name != only:
            continue
        run(name, qmd_retriever(name), k)
