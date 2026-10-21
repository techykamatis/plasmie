"""related.py: suggested links across the whole vault, computed (never written) unless the
user applies them, and then only into the user's own notes."""
import json

import related
from support import load_script


def _w(root, rel, text):
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text)
    return p


def _vault(tmp_path):
    _w(tmp_path, "01 Projects/resume-metlife.md", "# Resume update for MetLife\nTailor the resume summary and experience bullets for the MetLife role.\n")
    _w(tmp_path, "03 Resources/resume-style.md", "# Resume writing style\nPlain English resume summary, experience bullets with numbers.\n")
    _w(tmp_path, "02 Areas/bungee.md", "# Bungee vet log\nDachshund medication gabapentin neurobion.\n")
    _w(tmp_path, "wiki/rds.md", "# Shrink RDS storage\nSnapshot restore into a smaller instance.\n")
    _w(tmp_path, "raw/slack/2026-10-01.md", "resume resume resume summary experience bullets\n")
    _w(tmp_path, "meta/q.md", "resume summary experience\n")
    return tmp_path


def test_neighbours_pair_related_notes_and_skip_unrelated_and_private(tmp_path):
    rel = related.compute(_vault(tmp_path))
    assert set(rel) == {"01 Projects/resume-metlife.md", "03 Resources/resume-style.md",
                        "02 Areas/bungee.md", "wiki/rds.md"}            # never raw/ or meta/
    assert [n[0] for n in rel["01 Projects/resume-metlife.md"]] == ["03 Resources/resume-style.md"]
    assert rel["02 Areas/bungee.md"] == []                               # nothing clears the floor


def test_cache_is_reused_until_a_note_changes(tmp_path):
    v, cache = _vault(tmp_path / "v"), tmp_path / "related.json"
    a = related.build(v, cache=cache)
    assert related.build(v, cache=cache)["signature"] == a["signature"]
    _w(v, "02 Areas/bungee.md", "# Resume writing style notes\nPlain English resume summary, experience bullets with numbers.\n")
    b = related.build(v, cache=cache)
    assert b["signature"] != a["signature"] and b["related"]["02 Areas/bungee.md"]


def test_apply_writes_only_user_notes_and_remove_restores_them(tmp_path):
    v, cache = _vault(tmp_path / "v"), tmp_path / "related.json"
    wiki_before = (v / "wiki/rds.md").read_text()
    before = (v / "01 Projects/resume-metlife.md").read_text()
    assert related.apply(v, cache=cache) >= 2
    after = (v / "01 Projects/resume-metlife.md").read_text()
    assert "<!-- related:start -->" in after and "- [[resume-style]]" in after
    assert (v / "wiki/rds.md").read_text() == wiki_before                # plasmie-improve owns wiki/
    assert related.apply(v, cache=cache) == 0                            # idempotent
    related.remove(v)
    assert (v / "01 Projects/resume-metlife.md").read_text() == before


def test_the_map_gets_suggested_edges_that_are_not_real_links(tmp_path):
    G = load_script("plasmie-graph.py", "plasmie_graph")
    v = _vault(tmp_path)
    g = G.graph(v)
    ix = {n["id"]: i for i, n in enumerate(g["nodes"])}
    pair = sorted([ix["01 Projects/resume-metlife.md"], ix["03 Resources/resume-style.md"]])
    assert pair in g["suggested"] and pair not in g["edges"]
    assert all(n["links"] == 0 for n in g["nodes"])                      # suggestions aren't links
    json.dumps(g)
