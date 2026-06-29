#!/usr/bin/env python3
"""Q&A retrieval eval — hit-rate@k + MRR over a grounded gold set.

Questions are paraphrased the way a user would actually ask (NOT echoing the
note title), each mapped to the concept note that answers it. Runs every
retriever in retrieve.py and prints a comparison table so we can pick the
winner and tune it.

  python3 eval.py                 # all retrievers, k=4
  python3 eval.py --k 6           # different cutoff
  python3 eval.py --only hybrid   # one retriever
  python3 eval.py --alpha 0.3,0.5,0.7   # sweep hybrid blend weights

ponytail: gold set is a plain list of (question, expected-basename) — no
fixtures, no framework. Match by path.endswith(expected). Add cases by
appending tuples.
"""
import sys
import time
from statistics import mean

import ask
import retrieve

VAULT = "~/knowledge"

# (question a user would type, the concept note that answers it)
GOLD = [
    ("why can't I shrink my database disk?", "db-cannot-shrink-storage-in-place.md"),
    ("which hostname do I use for the metrics API?", "metrics-api-host-not-app-host.md"),
]


def score(retriever, k):
    ranks = []
    for q, want in GOLD:
        hits = retriever(q, k)
        rank = next((i + 1 for i, p in enumerate(hits) if p.endswith(want)), 0)
        ranks.append(rank)
    hit = mean(1 if r else 0 for r in ranks)
    mrr = mean(1 / r if r else 0 for r in ranks)
    return hit, mrr, ranks


def run(name, builder, k):
    t = time.time()
    retriever = builder(VAULT)
    build_s = time.time() - t
    t = time.time()
    hit, mrr, ranks = score(retriever, k)
    q_s = (time.time() - t) / len(GOLD)
    misses = [GOLD[i][1] for i, r in enumerate(ranks) if not r]
    print(f"{name:14s} hit@{k}={hit:.2f}  MRR={mrr:.3f}  "
          f"build={build_s:.1f}s  q={q_s*1000:.0f}ms")
    if misses:
        print(f"               misses: {', '.join(m[:34] for m in misses)}")
    return hit, mrr


if __name__ == "__main__":
    k = 4
    only = None
    alphas = None
    a = sys.argv
    if "--k" in a:
        k = int(a[a.index("--k") + 1])
    if "--only" in a:
        only = a[a.index("--only") + 1]
    if "--alpha" in a:
        alphas = [float(x) for x in a[a.index("--alpha") + 1].split(",")]

    print(f"gold cases: {len(GOLD)}  k={k}\n")
    builders = {
        "tfidf": retrieve.build_tfidf,
        "embed": retrieve.build_embed,
        "hybrid": retrieve.build_hybrid,
    }
    if alphas:
        for al in alphas:
            run(f"hybrid α={al}", lambda v, al=al: retrieve.build_hybrid(v, al), k)
    else:
        for name, b in builders.items():
            if only and name != only:
                continue
            run(name, b, k)
