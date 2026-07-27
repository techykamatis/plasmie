#!/usr/bin/env python3
"""Tests for the hourly improvement pass — heartbeat and gap-closing.

Both regressions here are the same shape as everything else the 2026-07-27 audit
found: a stage that looks fine because nothing contradicts it. improve wrote no
timestamped line at all, and coverage gaps were re-reported identically for three
weeks because nothing could ever close one.

Usage:  pytest test_improve.py
"""
import importlib.util
import sys
from datetime import date
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))


def _load(name, fname):
    spec = importlib.util.spec_from_file_location(name, HERE / fname)
    m = importlib.util.module_from_spec(spec)
    sys.modules[name] = m
    spec.loader.exec_module(m)
    return m


KI = _load("plasmie_improve", "plasmie-improve.py")
import paths  # noqa: E402


GAPS_DOC = """# Coverage gaps

intro prose that is not a gap

- 2026-07-02 · (0.34) "answerable question?" — closest: wiki/concepts/x.md
- 2026-07-02 · (0.00) "how do I bake sourdough bread?" — closest: (none)

## Dismissed

- 2026-07-01 · (0.00) "old junk" — closest: (none)
"""


def test_only_open_gaps_are_counted(tmp_path):
    """Dismissed entries must stop counting, or the backlog never shrinks."""
    (tmp_path / paths.GAPS).parent.mkdir(parents=True, exist_ok=True)
    (tmp_path / paths.GAPS).write_text(GAPS_DOC)
    assert KI.count_gaps(tmp_path) == 2, "dismissed gap still counted"


def test_split_gaps_separates_sections(tmp_path):
    pre, open_lines, closed, dismissed = KI._split_gaps(GAPS_DOC)
    assert len(open_lines) == 2
    assert len(dismissed) == 1
    assert closed == []
    assert "intro prose" in pre


def test_closed_gaps_do_not_reappear_as_open():
    doc = GAPS_DOC + "\n## Closed\n\n- 2026-07-27 · closed (0.88) \"resolved one\" — answered by wiki/x.md\n"
    _, open_lines, closed, _ = KI._split_gaps(doc)
    assert len(closed) == 1
    assert not any("resolved one" in ln for ln in open_lines), "closed gap leaked back into open"


def test_resolve_gaps_is_a_noop_without_retrieval(tmp_path, monkeypatch):
    """No qmd/node available must leave the backlog untouched, not wipe it."""
    (tmp_path / paths.GAPS).parent.mkdir(parents=True, exist_ok=True)
    (tmp_path / paths.GAPS).write_text(GAPS_DOC)
    monkeypatch.setattr(KI, "_load_ask", lambda: (_ for _ in ()).throw(RuntimeError("no node")))
    assert KI.resolve_gaps(tmp_path, write=True) == []
    assert (tmp_path / paths.GAPS).read_text() == GAPS_DOC, "backlog mutated on retrieval failure"


def test_run_writes_a_timestamped_heartbeat(tmp_path, monkeypatch):
    """A no-op pass must still prove it ran — that was the observability hole."""
    logs = HERE / "logs"
    audit = logs / f"audit-{date.today():%Y-%m-%d}.log"
    before = audit.read_text() if audit.exists() else ""

    (tmp_path / paths.CONCEPTS).mkdir(parents=True, exist_ok=True)
    (tmp_path / paths.CONCEPTS / "a.md").write_text('---\ntitle: "A"\n---\nbody')
    monkeypatch.setattr(KI, "resolve_gaps", lambda *a, **k: [])  # no network

    KI.run(str(tmp_path), write=True)

    after = audit.read_text() if audit.exists() else ""
    new = after[len(before):]
    assert "| improve |" in new, "improve pass left no timestamped audit line"
    assert "wiki notes" in new

    if before:                      # restore: don't pollute the real audit log
        audit.write_text(before)
    elif audit.exists():
        audit.unlink()


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))
