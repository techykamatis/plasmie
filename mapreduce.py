#!/usr/bin/env python3
"""Fit long inputs to the on-device context window by map-reduce, never truncation.

Apple's on-device model has a small window (documented 4096 tokens; macOS 27
reports 8192 — always read live via fm.context_size()). A day of raw activity
is 30-100k tokens, so promote and the hourly digest can't send it in one call.
Instead (ADR 0002):

  chunk   split labelled sections ("===== slack 2026-10-02 =====") at line
          boundaries into pieces that fit the live budget; every piece keeps
          its section header, so whatever the model extracts can cite a source.
  map     one short, structured call per chunk.
  reduce  merge the per-chunk outputs in further calls; when they don't fit
          one call, reduce in batches and repeat (bounded depth).

A chunk the model reports as over budget is split in half and retried, so a
bad estimate costs a round trip, never a dropped slice. "busy" and
"unavailable" abort the whole run (raised as Abort): a background job must not
half-finish on a machine that just got busy.

`call(prompt) -> dict` is fm.respond's result shape ({"text"} or {"error"}),
injected so tests run without a model.
"""
import re
import time
from dataclasses import dataclass
from typing import Callable, Optional

import fm

TEMPLATE_TOKENS = 200        # chat-template/system overhead not counted in our text
MIN_CHUNK_CHARS = 1500
SPLIT_ON = ("over_budget", "context_exceeded")
ABORT_ON = ("busy", "unavailable")
MAX_REDUCE_DEPTH = 3

Call = Callable[[str], dict]


class Abort(Exception):
    """The run must stop: machine busy (background guard) or model unavailable."""

    def __init__(self, code: str, reason: str = ""):
        super().__init__(f"{code}: {reason}")
        self.code = code
        self.reason = reason


@dataclass(frozen=True)
class Section:
    label: str
    text: str

    def header(self) -> str:
        return f"===== {self.label} =====\n"


@dataclass(frozen=True)
class MapResult:
    outputs: tuple            # (chunk_index, text) per chunk that answered
    failed: tuple             # (chunk_index, error code) per chunk that didn't
    chunks: int


def fair_shares(lengths: list[int], total: int) -> list[int]:
    """Split `total` chars across items by water-filling: short items keep all of
    their text and the slack goes to the long ones — nobody is dropped."""
    shares = [0] * len(lengths)
    todo = sorted(range(len(lengths)), key=lambda i: lengths[i])
    left = max(0, total)
    for k, i in enumerate(todo):
        share = left // (len(todo) - k)
        shares[i] = min(lengths[i], share)
        left -= shares[i]
    return shares


def cap_sections(sections: list[Section], total: int) -> list[Section]:
    """Bound a run's total input with a fair share per section (newest tail kept).
    A safety bound on run time, not the fitting mechanism — chunking is."""
    if sum(len(s.text) for s in sections) <= total:
        return list(sections)
    caps = fair_shares([len(s.text) for s in sections], total)
    return [Section(s.label, s.text[len(s.text) - c:] if c else "")
            for s, c in zip(sections, caps)]


def chunk_chars(overhead: str, max_tokens: int, ctx: Optional[int],
                ceiling: Optional[int] = None) -> int:
    """Chars of input one call can carry: live window minus the answer reserve,
    template overhead and the fixed instructions, at a conservative chars/token."""
    tokens = (ctx or 4096) - max_tokens - TEMPLATE_TOKENS - fm.estimate_tokens(overhead)
    room = max(MIN_CHUNK_CHARS, int(tokens * fm.CHARS_PER_TOKEN))
    return min(room, ceiling) if ceiling else room


def split_text(text: str, limit: int) -> list[str]:
    """Split at line boundaries into pieces <= limit; an overlong line is hard-cut."""
    limit = max(1, limit)
    pieces, cur = [], ""
    for line in text.splitlines(keepends=True):
        while len(line) > limit:
            if cur:
                pieces.append(cur)
                cur = ""
            pieces.append(line[:limit])
            line = line[limit:]
        if len(cur) + len(line) > limit and cur:
            pieces.append(cur)
            cur = ""
        cur += line
    if cur.strip():
        pieces.append(cur)
    return [p for p in pieces if p.strip()]


def chunk(sections: list[Section], limit: int) -> list[str]:
    """Pack labelled sections into chunks <= limit chars. Large sections are split
    and every piece repeats its header; small ones share a chunk."""
    pieces = []
    for s in sections:
        if not s.text.strip():
            continue
        h = s.header()
        pieces += [h + p.rstrip("\n") for p in split_text(s.text, max(200, limit - len(h)))]
    chunks, cur = [], ""
    for p in pieces:
        if cur and len(cur) + 2 + len(p) > limit:
            chunks.append(cur)
            cur = ""
        cur = f"{cur}\n\n{p}" if cur else p
    if cur:
        chunks.append(cur)
    return chunks


def halve(text: str) -> tuple[str, str]:
    """Split a chunk near its middle line, keeping the section header on both halves."""
    lines = text.splitlines()
    mid = max(1, len(lines) // 2)
    head = next((ln for ln in reversed(lines[:mid]) if ln.startswith("===== ")), "")
    a, b = "\n".join(lines[:mid]), "\n".join(lines[mid:])
    if head and not b.startswith("===== "):
        b = f"{head}\n{b}"
    return a, b


def _ask(call: Call, prompt: str) -> dict:
    res = call(prompt)
    if res.get("error") in ABORT_ON:
        raise Abort(res["error"], str(res.get("reason", "")))
    return res


def run_map(chunks: list[str], make_prompt: Callable[[str], str], call: Call,
            deadline: Optional[float] = None,
            progress: Optional[Callable[[int, int], None]] = None) -> MapResult:
    """One call per chunk; over-budget chunks are halved and retried (depth 2)."""
    outputs, failed = [], []

    def one(i: int, text: str, depth: int) -> None:
        res = _ask(call, make_prompt(text))
        if "error" not in res:
            outputs.append((i, res.get("text", "")))
        elif res["error"] in SPLIT_ON and depth < 2 and len(text) > MIN_CHUNK_CHARS:
            for half in halve(text):
                one(i, half, depth + 1)
        else:
            failed.append((i, res["error"]))

    for i, c in enumerate(chunks):
        if deadline is not None and time.monotonic() > deadline:
            failed.extend((j, "deadline") for j in range(i, len(chunks)))
            break
        if progress:
            progress(i + 1, len(chunks))
        one(i, c, 0)
    return MapResult(tuple(outputs), tuple(failed), len(chunks))


def batches(parts: list[str], limit: int) -> list[list[str]]:
    """Group parts into batches whose joined length fits `limit` (>= 1 part each)."""
    out, cur, size = [], [], 0
    for p in parts:
        if cur and size + len(p) + 2 > limit:
            out.append(cur)
            cur, size = [], 0
        cur.append(p)
        size += len(p) + 2
    if cur:
        out.append(cur)
    return out


def reduce_parts(parts: list[str], make_prompt: Callable[[str], str], call: Call,
                 limit: int, depth: int = 0) -> Optional[str]:
    """Merge parts into one output. Fits -> one call; else reduce batches and
    recurse. None when a merge call fails (the caller falls back deterministically)."""
    parts = [p for p in parts if p.strip()]
    if not parts:
        return ""
    joined = "\n\n".join(parts)
    if len(joined) <= limit or depth >= MAX_REDUCE_DEPTH or len(parts) == 1:
        res = _ask(call, make_prompt(joined))
        return None if "error" in res else res.get("text", "")
    merged = []
    for b in batches(parts, limit):
        out = reduce_parts(b, make_prompt, call, limit, depth + 1)
        if out is None:
            return None
        merged.append(out)
    if len(merged) == len(parts):          # batching made no progress; one last try
        merged = ["\n\n".join(merged)]
    return reduce_parts(merged, make_prompt, call, limit, depth + 1)


def split_labelled(text: str) -> list[Section]:
    """Inverse of Section.header(): '===== label =====' blocks -> Sections."""
    parts = re.split(r"(?m)^===== (.+?) =====\s*$", text)
    out = [Section("input", parts[0])] if parts[0].strip() else []
    for i in range(1, len(parts) - 1, 2):
        out.append(Section(parts[i].strip(), parts[i + 1].strip("\n")))
    return out
