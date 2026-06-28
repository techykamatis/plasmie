#!/usr/bin/env python3
"""Measure dedupe quality: does the TF-IDF merge suggestion fire on real duplicates
and stay quiet on novel items? Labeled set of paraphrased-real-notes (should MERGE)
vs unrelated topics (should NOT). Reports precision/recall at the 0.30 threshold and,
if either < 0.80, sweeps for a better one.

Usage:  eval_dedupe.py [VAULT=~/knowledge]
"""
import importlib.util
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("dedupe", HERE / "dedupe.py")
DD = importlib.util.module_from_spec(spec)
spec.loader.exec_module(DD)

# (query text, is_duplicate_of_an_existing_note)
LABELED = [
    # --- known duplicates: paraphrase of a real concept, different words, same idea ---
    ("Hugging Face downloads hang because the Xet CDN connection dies holding a zero-byte socket", True),
    ("You cannot reduce RDS allocated storage in place; it only grows, so you must rebuild", True),
    ("ElastiCache refuses to drop a replica while automatic failover is enabled", True),
    ("Slack bot tokens are unable to deliver messages into multi-person group DM channels", True),
    ("Datadog API requests must target the api host, not the app web UI host", True),
    ("A date helper returns the UTC date where the local calendar date is intended, an off-by-one", True),
    ("Helm rejects release names with underscores because they must be valid DNS labels", True),
    ("Prefer the gh CLI over the GitHub MCP server because of authenticated rate limits", True),
    ("Never commit environment values like ARNs or account IDs into git", True),
    ("An RDS instance flagged publicly accessible inside private subnets is still unreachable", True),
    # --- known novel: unrelated to anything in this work vault ---
    ("Quarterly OKR planning ritual cadence for the team", False),
    ("Office coffee machine descaling and maintenance schedule", False),
    ("Recipe and feeding schedule for a sourdough bread starter", False),
    ("Setting up the nitrogen cycle in a freshwater home aquarium", False),
    ("Technique for replacing acoustic guitar strings without buzz", False),
    ("Best watering frequency for indoor succulents in low light", False),
    ("Conference travel reimbursement claim policy and per-diem rates", False),
    ("Onboarding checklist for a newly hired marketing coordinator", False),
    ("Choosing between gas and induction stovetops for a kitchen remodel", False),
    ("Stretching routine to relieve lower-back pain from sitting", False),
]


def evaluate(corpus, idf, threshold):
    tp = fp = fn = tn = 0
    rows = []
    for text, is_dup in LABELED:
        near = DD.nearest(text, corpus, idf, k=1)
        score = near[0][0] if near else 0.0
        pred = score >= threshold
        rows.append((is_dup, pred, score, near[0][1]["path"] if near else "-"))
        if is_dup and pred: tp += 1
        elif is_dup and not pred: fn += 1
        elif not is_dup and pred: fp += 1
        else: tn += 1
    prec = tp / (tp + fp) if (tp + fp) else 1.0
    rec = tp / (tp + fn) if (tp + fn) else 1.0
    f1 = 2 * prec * rec / (prec + rec) if (prec + rec) else 0.0
    return prec, rec, f1, rows


def main(vault):
    corpus, idf = DD.build_corpus(vault)
    print(f"corpus: {len(corpus)} notes | threshold MERGE_AT = {DD.MERGE_AT}\n")
    prec, rec, f1, rows = evaluate(corpus, idf, DD.MERGE_AT)
    for is_dup, pred, score, path in rows:
        tag = "OK " if (is_dup == pred) else "MISS"
        print(f"  [{tag}] label={'dup ' if is_dup else 'novel'} pred={'merge' if pred else 'new  '} score={score:.3f}  {path if pred else ''}")
    print(f"\nprecision={prec:.2f}  recall={rec:.2f}  f1={f1:.2f}  (n={len(LABELED)})")

    if prec < 0.8 or rec < 0.8:
        print("\nbelow 0.80 — sweeping threshold:")
        best = max((evaluate(corpus, idf, t / 100)[2], t / 100) for t in range(15, 46, 1))
        bp, br, bf1, _ = evaluate(corpus, idf, best[1])
        print(f"  best threshold = {best[1]:.2f}  (precision={bp:.2f} recall={br:.2f} f1={bf1:.2f})")
        print("  -> update MERGE_AT in dedupe.py to this value")
    else:
        print("PASS: precision and recall both >= 0.80 at the current threshold")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "~/knowledge")
