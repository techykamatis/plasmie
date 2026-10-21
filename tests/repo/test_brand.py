"""The name lives in one place per language (ADR 0014). Older versions' names are checked by
test_old_names.py (ADR 0023): they may not appear written out anywhere.

  Swift   app/Sources/Brand.swift          Brand.name / Brand.id
  Python  paths.py                         APP_NAME / APP_ID
  shell   plasmie-env.sh                   PLASMIE_APP_NAME / PLASMIE_APP_ID
  build   app/make-app.sh, make-dmg.sh, make-release.sh   APP_NAME (/ APP_ID)
"""
import io
import re
import tokenize

import paths
from support import ENGINE, ROOT

SOURCES = ROOT / "app" / "Sources"
# The name as a word: identifiers that merely start with it (PlasmieView, PlasmiePaths: ADR
# 0014) are code, not copy, so they don't count as spelling it out.
NAME = re.compile(rf"\b{re.escape(paths.APP_NAME)}\b")


def _assign(text, name):
    m = re.search(rf'^\s*(?:static let )?{name}\s*=\s*"([^"]+)"', text, re.M)
    assert m, name
    return m.group(1)


def test_every_copy_of_the_name_agrees():
    brand = (SOURCES / "Brand.swift").read_text()
    env = (ENGINE / "plasmie-env.sh").read_text()
    make = (ROOT / "app" / "make-app.sh").read_text()
    names = {
        "Brand.name": _assign(brand, "name"), "paths.APP_NAME": paths.APP_NAME,
        "PLASMIE_APP_NAME": _assign(env, "PLASMIE_APP_NAME"), "make-app APP_NAME": _assign(make, "APP_NAME"),
        "make-dmg APP_NAME": _assign((ROOT / "app" / "make-dmg.sh").read_text(), "APP_NAME"),
        "make-release APP_NAME": _assign((ROOT / "app" / "make-release.sh").read_text(), "APP_NAME"),
    }
    ids = {"Brand.id": _assign(brand, "id"), "paths.APP_ID": paths.APP_ID,
           "PLASMIE_APP_ID": _assign(env, "PLASMIE_APP_ID"), "make-app APP_ID": _assign(make, "APP_ID")}
    assert len(set(names.values())) == 1, names
    assert len(set(ids.values())) == 1, ids
    assert paths.APP_ID == paths.APP_NAME.lower()


def _swift_code_lines(text):
    """(line number, code) with // comments and /// doc comments dropped."""
    for i, line in enumerate(text.splitlines(), 1):
        code = re.sub(r"(^|\s)//.*$", "", line)
        if code.strip():
            yield i, code


def _python_strings(path):
    """(line, text) of every string literal that isn't a docstring or a comment."""
    toks = list(tokenize.generate_tokens(io.StringIO(path.read_text()).readline))
    prev = None
    starts = (tokenize.STRING, getattr(tokenize, "FSTRING_START", -1))
    for t in toks:
        if t.type in starts:
            statement = prev is None or prev.type in (tokenize.NEWLINE, tokenize.NL, tokenize.INDENT,
                                                      tokenize.DEDENT, tokenize.ENCODING)
            if not statement:
                yield t.start[0], t.line
        if t.type not in (tokenize.COMMENT, tokenize.NL):
            prev = t


def _shell_code_lines(text):
    for i, line in enumerate(text.splitlines(), 1):
        code = re.sub(r"(^|\s)#\s.*$", "", line)            # whole-line and trailing comments
        if code.strip() and not code.lstrip().startswith("#"):
            yield i, code


def _engine_files():
    py = list(ENGINE.glob("*.py"))
    sh = list(ENGINE.glob("*.sh")) + list((ROOT / "app").glob("*.sh")) + list((ENGINE / "launchd").glob("*.sh"))
    return py, sh, sorted(SOURCES.glob("*.swift"))


def test_the_name_is_spelled_out_only_where_it_is_defined():
    py, sh, swift = _engine_files()
    hits = []
    for p in swift:
        if p.name != "Brand.swift":
            hits += [f"{p.name}:{i}" for i, c in _swift_code_lines(p.read_text()) if NAME.search(c)]
    for p in py:
        if p.name != "paths.py":
            hits += [f"{p.name}:{i}" for i, s in _python_strings(p) if NAME.search(s)]
    builds = {"plasmie-env.sh", "make-app.sh", "make-dmg.sh", "make-release.sh"}
    for p in sh:
        if p.name not in builds:
            hits += [f"{p.name}:{i}" for i, c in _shell_code_lines(p.read_text()) if NAME.search(c)]
    assert hits == [], "use Brand.name / paths.APP_NAME / $PLASMIE_APP_NAME instead"
