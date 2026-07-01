#!/usr/bin/env python3
"""Retrieval strategies for vault Q&A — pluggable, measured by eval.py.

  tfidf   — lexical baseline (ask.build_corpus / ask.nearest)
  embed   — EmbeddingGemma semantic (Google on-device, in-process MLX), cosine
  hybrid  — blend of min-max-normalized tfidf + embed scores (alpha = embed weight)

Plus link_graph(): OKF cross-links (markdown links + [[wikilinks]]) → adjacency,
so ask.py can expand a hit to its directly-connected concepts ("traversable
knowledge" — the OKF idea that beats isolated chunks).

A retriever is build_X(vault) -> f(question, k) -> [relpath, ...] best-first.

ponytail: embeddings cached to disk keyed by (path, content-hash); only changed
notes re-embed. Vectors normalized so cosine == dot — a few hundred 768-float
lists is a sub-millisecond pure-Python dot, no numpy, no vector DB.
"""
import hashlib
import json
import math
import os
import re
from pathlib import Path

import ask

# EmbeddingGemma on MLX — same model the rest of the stack uses, no extra runtime
# (we already bundle Python+MLX for generation, so Ollama is no longer needed).
EMBED_MODEL = os.environ.get("PLASMIE_EMBED_MODEL", "mlx-community/embeddinggemma-300m-bf16")
CACHE = ask.SELF / ".embed-cache.json"
DOC_CHARS = 1500       # EmbeddingGemma context is ~2k tokens; title+this stays under
BATCH = 16
_EMBEDDER = None       # (model, tokenizer), loaded once per process (~2s cold)


def _embedder():
    global _EMBEDDER
    if _EMBEDDER is None:
        from mlx_embeddings.utils import load
        _EMBEDDER = load(EMBED_MODEL)
    return _EMBEDDER


def _embed(inputs):
    # Call the model directly (mlx_embeddings.generate passes input_ids= but the
    # gemma3 embedding class wants a positional arg — calling it ourselves is robust).
    import mlx.core as mx
    model, tok = _embedder()
    enc = tok.batch_encode_plus(list(inputs), return_tensors="mlx", padding=True)
    out = model(enc["input_ids"], attention_mask=enc.get("attention_mask"))
    mx.eval(out.text_embeds)
    return [[float(x) for x in row] for row in out.text_embeds]


def _norm(v):
    n = math.sqrt(sum(x * x for x in v)) or 1.0
    return [x / n for x in v]


def _dot(a, b):
    return sum(x * y for x, y in zip(a, b))


def embed_query(q):
    # EmbeddingGemma's required query task-prefix — consistency with docs matters.
    return _norm(_embed([f"task: search result | query: {q}"])[0])


def _doc_text(doc):
    # Document prefix; title is curated OKF frontmatter — high signal, embed it.
    return f"title: {doc['title']} | text: {doc['text'][:DOC_CHARS]}"


def embed_corpus(corpus):
    """{path: normalized-vec} for the corpus, re-embedding only changed notes."""
    cache = json.loads(CACHE.read_text()) if CACHE.exists() else {}
    out, pending, meta = {}, [], []
    for doc in corpus:
        h = hashlib.sha1(_doc_text(doc).encode()).hexdigest()
        c = cache.get(doc["path"])
        if c and c["hash"] == h:
            out[doc["path"]] = c["vec"]
        else:
            pending.append(_doc_text(doc))
            meta.append((doc["path"], h))
    for i in range(0, len(pending), BATCH):
        for (path, h), v in zip(meta[i:i + BATCH], _embed(pending[i:i + BATCH])):
            nv = _norm(v)
            out[path] = nv
            cache[path] = {"hash": h, "vec": nv}
    if pending:
        CACHE.write_text(json.dumps(cache))
    return out


def _tfidf_scores(q, corpus, idf):
    qv = ask._vec(ask.tokens(q), idf)
    scores = {}
    for d in corpus:
        small, big = (qv, d["vec"]) if len(qv) < len(d["vec"]) else (d["vec"], qv)
        scores[d["path"]] = sum(v * big.get(t, 0.0) for t, v in small.items())
    return scores


def _minmax(d):
    lo, hi = min(d.values()), max(d.values())
    rng = (hi - lo) or 1.0
    return {k: (v - lo) / rng for k, v in d.items()}


def build_tfidf(vault):
    corpus, idf = ask.build_corpus(vault)
    return lambda q, k: [d["path"] for _, d in ask.nearest(q, corpus, idf, k)]


def build_embed(vault):
    corpus, _ = ask.build_corpus(vault)
    vecs = embed_corpus(corpus)
    paths = list(vecs)

    def f(q, k):
        qv = embed_query(q)
        return [p for _, p in sorted(((_dot(qv, vecs[p]), p) for p in paths),
                                     key=lambda s: -s[0])[:k]]
    return f


def build_hybrid(vault, alpha=0.5):
    corpus, idf = ask.build_corpus(vault)
    vecs = embed_corpus(corpus)
    paths = list(vecs)

    def f(q, k):
        tf = _minmax(_tfidf_scores(q, corpus, idf))
        qv = embed_query(q)
        em = _minmax({p: _dot(qv, vecs[p]) for p in paths})
        blend = {p: alpha * em[p] + (1 - alpha) * tf.get(p, 0.0) for p in paths}
        return [p for p, _ in sorted(blend.items(), key=lambda s: -s[1])[:k]]
    return f


def link_graph(corpus):
    """OKF cross-links: {path: {linked_path,...}} from [[wikilinks]] and ](rel.md)."""
    by_base = {Path(d["path"]).stem: d["path"] for d in corpus}
    graph = {}
    for d in corpus:
        out = set()
        for m in re.findall(r"\[\[([^\]]+)\]\]", d["text"]):
            base = m.split("|")[0].split("#")[0].strip().removesuffix(".md")
            if base in by_base:
                out.add(by_base[base])
        for m in re.findall(r"\]\(([^)]+\.md)\)", d["text"]):
            base = Path(m.split("#")[0]).stem
            if base in by_base:
                out.add(by_base[base])
        out.discard(d["path"])
        graph[d["path"]] = out
    return graph


def selfcheck():
    import tempfile
    with tempfile.TemporaryDirectory() as d:
        v = Path(d) / "03 Resources/concepts"
        v.mkdir(parents=True)
        (v / "a.md").write_text('---\ntitle: "A"\n---\nlinks [[b]] and [c](c.md)')
        (v / "b.md").write_text('---\ntitle: "B"\n---\nbody')
        (v / "c.md").write_text('---\ntitle: "C"\n---\nbody')
        corpus, _ = ask.build_corpus(str(Path(d)))
        g = link_graph(corpus)
        a = next(p for p in g if p.endswith("a.md"))
        assert {x.split("/")[-1] for x in g[a]} == {"b.md", "c.md"}, g[a]
        assert _minmax({"x": 2, "y": 4}) == {"x": 0.0, "y": 1.0}
        assert abs(_dot(_norm([3, 4]), _norm([3, 4])) - 1.0) < 1e-9
    print("retrieve selfcheck OK")


if __name__ == "__main__":
    import sys
    if "--selfcheck" in sys.argv:
        selfcheck()
