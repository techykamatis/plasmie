"""reindex.py --check must lint: dead [[wikilinks]] and post-2026-09-17 notes with no provenance."""
import importlib.util
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("reindex", HERE / "reindex.py")
RI = importlib.util.module_from_spec(spec)
spec.loader.exec_module(RI)


def _note(d, name, body, ts="2026-09-20T00:00:00Z", extra=""):
    (d / f"{name}.md").write_text(f'---\ntitle: "{name}"\ntimestamp: {ts}\n{extra}---\n{body}\n')


def _vault(tmp_path):
    w = tmp_path / "wiki"
    (w / "mocs").mkdir(parents=True)
    return w


def test_dead_wikilinks_flagged_with_alias_anchor_and_fence_rules(tmp_path):
    w = _vault(tmp_path)
    _note(w, "a", "[[B]] [[b#sec]] [[b|alias]] [[gone]] [[gone2#x|y]]\n```\n[[infence]]\n```\n", extra="source: x\n")
    _note(w, "b", "body", extra="source: x\n")
    dead, _ = RI.lint(tmp_path)
    assert sorted(t for _, t in dead) == ["gone", "gone2"], dead


def test_missing_provenance_only_after_cutoff_and_not_mocs(tmp_path):
    w = _vault(tmp_path)
    _note(w, "old", "x", ts="2026-06-01T00:00:00Z")
    _note(w, "new-bad", "x")
    _note(w, "new-fm", "x", extra="source: slack\n")
    _note(w, "new-line", "x\n\nSource: slack thread")
    _note(w, "boundary", "x", ts="2026-09-17T00:00:00Z")
    _note(w / "mocs", "map", "x")
    _, noprov = RI.lint(tmp_path)
    assert sorted(noprov) == ["wiki/boundary.md", "wiki/new-bad.md"], noprov


def test_check_exits_nonzero_on_findings_clean_exits_zero(tmp_path):
    w = _vault(tmp_path)
    _note(w, "a", "[[gone]]", extra="source: x\n")
    r = subprocess.run([sys.executable, str(HERE / "reindex.py"), "--check", str(tmp_path)],
                       capture_output=True, text=True)
    assert r.returncode == 1 and "gone" in r.stdout
    assert not (tmp_path / "index.md").exists()
    _note(w, "a", "fine", extra="source: x\n")
    r = subprocess.run([sys.executable, str(HERE / "reindex.py"), "--check", str(tmp_path)],
                       capture_output=True, text=True)
    assert r.returncode == 0, r.stdout


def test_catalog_header_has_no_categories_wording(tmp_path):
    w = _vault(tmp_path)
    _note(w, "a", "x", extra="source: x\n")
    RI.catalog(tmp_path, write=True, maps={})
    assert "categories" not in (tmp_path / "index.md").read_text()


def test_standalone_catalog_still_counts_maps(tmp_path):
    """CLI `reindex.py` and promote-apply call catalog() without maps; the header
    must not regress to '0 maps' while wiki/mocs is full."""
    w = _vault(tmp_path)
    for i in range(RI.MOC_MIN):
        _note(w, f"n{i}", "x", extra="source: x\ntags: [shared]\n")
    RI.catalog(tmp_path, write=True)
    assert "· 1 maps" in (tmp_path / "index.md").read_text()
