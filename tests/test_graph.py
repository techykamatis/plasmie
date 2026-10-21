#!/usr/bin/env python3
"""Plasmie's map engine: frontmatter, wikilink resolution, hubs and scrubbed excerpts.

Usage:  pytest tests/test_graph.py
"""
import json
import subprocess
import sys
from support import ENGINE, load_script

G = load_script("plasmie-graph.py", "plasmie_graph")


def _note(v, rel, front, body=""):
    p = v / "wiki" / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(f"---\n{front}\n---\n{body}\n")


def _ids(g):
    return {n["id"]: i for i, n in enumerate(g["nodes"])}


def _linked(g, a, b):
    ix = _ids(g)
    return sorted([ix[f"wiki/{a}.md"], ix[f"wiki/{b}.md"]]) in g["edges"]


def test_frontmatter_inline_and_block_lists(tmp_path):
    _note(tmp_path, "a.md", 'type: gotcha\ntitle: "RDS only grows"\ntags: [aws, rds]\ntimestamp: 2026-07-03T00:00:00Z')
    _note(tmp_path, "b.md", "type: Decision\ntags:\n  - one\n  - 'two'\ndate: 2026-01-02")
    n = {x["id"]: x for x in G.graph(tmp_path)["nodes"]}
    a, b = n["wiki/a.md"], n["wiki/b.md"]
    assert (a["title"], a["type"], a["tags"], a["date"]) == ("RDS only grows", "gotcha", ["aws", "rds"], "2026-07-03")
    assert (b["type"], b["tags"], b["date"]) == ("decision", ["one", "two"], "2026-01-02")


def test_title_falls_back_to_heading_then_filename(tmp_path):
    _note(tmp_path, "h.md", "type: note", "# The Heading\nbody")
    (tmp_path / "wiki" / "bare.md").write_text("no frontmatter at all\n")
    n = {x["id"]: x for x in G.graph(tmp_path)["nodes"]}
    assert n["wiki/h.md"]["title"] == "The Heading"
    assert n["wiki/bare.md"]["title"] == "bare" and n["wiki/bare.md"]["type"] == "note"


def test_wikilinks_alias_heading_block_folder_and_title(tmp_path):
    _note(tmp_path, "hub.md", "type: note",
          "See [[Alpha|the alpha]], [[beta#Setup]], [[sub/gamma^abc]], [[Delta Title]] and [[alpha]] again.")
    _note(tmp_path, "alpha.md", "type: note")
    _note(tmp_path, "beta.md", "type: note")
    _note(tmp_path, "sub/gamma.md", "type: note")
    _note(tmp_path, "delta.md", 'type: note\ntitle: "Delta Title"')
    g = G.graph(tmp_path)
    for t in ("alpha", "beta", "sub/gamma", "delta"):
        assert _linked(g, "hub", t), t
    hub = next(x for x in g["nodes"] if x["id"] == "wiki/hub.md")
    assert hub["links"] == 4                        # distinct neighbours: the repeat counts once
    assert len(g["edges"]) == 4


def test_missing_targets_self_links_and_attachments_ignored(tmp_path):
    _note(tmp_path, "a.md", "type: note", "[[nowhere]] [[a]] ![[pic.png]] [[b]]")
    _note(tmp_path, "b.md", "type: note", "[[a]]")              # back-link: still one edge
    (tmp_path / "wiki" / "attachments").mkdir()
    (tmp_path / "wiki" / "attachments" / "x.md").write_text("[[a]]")
    g = G.graph(tmp_path)
    assert len(g["nodes"]) == 2 and g["edges"] == [[0, 1]]


def test_hubs_by_type_and_folder(tmp_path):
    _note(tmp_path, "mocs/ai.md", "type: note", "* [[x]]")
    _note(tmp_path, "index.md", "type: index")
    _note(tmp_path, "m.md", "type: moc")
    _note(tmp_path, "x.md", "type: note")
    n = {x["id"]: x for x in G.graph(tmp_path)["nodes"]}
    assert n["wiki/mocs/ai.md"]["hub"] and n["wiki/index.md"]["hub"] and n["wiki/m.md"]["hub"]
    assert not n["wiki/x.md"]["hub"]


def test_excerpt_skips_headings_and_is_redacted(tmp_path):
    _note(tmp_path, "s.md", "type: note",
          "# Title\n<!-- related:start -->\n- [[x]]\n\n---\nThe key is AKIAABCDEFGHIJKLMNOP for **dev**.\n## Sub\nMail ana@example.com via [[b|Bob]].\nThird line.")
    ex = G.graph(tmp_path)["nodes"][0]["excerpt"]
    assert ex.splitlines() == ["The key is «redacted:aws-key» for dev.", "Mail «redacted:email» via Bob."]


def test_no_wiki_is_an_empty_graph_and_cli_prints_json(tmp_path, monkeypatch):
    assert G.graph(tmp_path) == {"nodes": [], "edges": [], "suggested": []}
    _note(tmp_path, "a.md", "type: note")
    monkeypatch.setenv("PLASMIE_VAULT", str(tmp_path))
    out = subprocess.run([sys.executable, str(ENGINE / "plasmie-graph.py")], capture_output=True, text=True, check=True)
    assert json.loads(out.stdout)["nodes"][0]["id"] == "wiki/a.md"


def test_title_tags_and_type_are_redacted(tmp_path):
    _note(tmp_path, "t.md", 'type: note\ntitle: "Key AKIAABCDEFGHIJKLMNOP for bob@example.com"\n'
          'tags: [ghp_abcdefghijklmnopqrstuvwxyz0123, ok]\nsecret_field: hunter2')
    n = G.graph(tmp_path)["nodes"][0]
    assert n["title"] == "Key «redacted:aws-key» for «redacted:email»"
    assert n["tags"] == ["«redacted:gh-token»", "ok"]
    assert "hunter2" not in json.dumps(n) and set(n) == {"id", "title", "type", "tags", "date", "links", "hub", "excerpt"}


def test_secret_split_across_excerpt_lines_is_redacted(tmp_path):
    # the label is on line 1, the credential on line 2: redacting per line would miss it
    _note(tmp_path, "s.md", "type: note", "The staging password is\nZx9vQ2mLp7Rt for now.")
    ex = G.graph(tmp_path)["nodes"][0]["excerpt"]
    assert "Zx9vQ2mLp7Rt" not in ex and "«redacted:credential»" in ex


def test_truncation_happens_after_redaction(tmp_path):
    pad = "x " * ((G.EXCERPT_CHARS - 12) // 2)
    _note(tmp_path, "u.md", "type: note", pad + "ghp_abcdefghijklmnopqrstuvwxyz0123456789 tail")
    ex = G.graph(tmp_path)["nodes"][0]["excerpt"]
    assert len(ex) <= G.EXCERPT_CHARS and "ghp_" not in ex and "abcdefgh" not in ex


def test_map_follows_the_vaults_own_folders_but_never_private_ones(tmp_path):
    _note(tmp_path, "a.md", "type: note", "[[Plan]]")
    for rel in ("01 Projects/Plan.md", "archive/old.md", "top.md",
                "raw/slack/x.md", "meta/q.md", ".obsidian/s.md", ".git/h.md",
                ".trash/t.md", "02 Areas/attachments/pdf.md"):
        p = tmp_path / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("# " + p.stem + "\n")
    g = G.graph(tmp_path)
    assert set(_ids(g)) == {"wiki/a.md", "01 Projects/Plan.md", "archive/old.md", "top.md"}
    ix = _ids(g)
    assert sorted([ix["wiki/a.md"], ix["01 Projects/Plan.md"]]) in g["edges"]


def test_markdown_links_resolve_relative_to_the_note(tmp_path):
    for rel, body in {"01 Projects/hub.md": "[a](sib.md) [b](../03%20Resources/x.md#h) [w](https://e.com/r.md) [out](../../etc.md)",
                      "01 Projects/sib.md": "", "03 Resources/x.md": ""}.items():
        p = tmp_path / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(body + "\n")
    g = G.graph(tmp_path)
    ix = _ids(g)
    h = ix["01 Projects/hub.md"]
    assert sorted(g["edges"]) == sorted([sorted([h, ix["01 Projects/sib.md"]]), sorted([h, ix["03 Resources/x.md"]])])
