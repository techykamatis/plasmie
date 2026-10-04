"""The name lives in one place per language (ADR 0028), and no user-facing string still says
an earlier name outside the code that migrates from it.

  Swift   app/Sources/Brand.swift          Brand.name / Brand.id
  Python  paths.py                         APP_NAME / APP_ID
  shell   plasmie-env.sh                     PLASMIE_APP_NAME / PLASMIE_APP_ID
  build   app/make-app.sh, make-dmg.sh, make-release.sh   APP_NAME (/ APP_ID)
"""
import io
import re
import tokenize
from pathlib import Path

import pytest

import paths

HERE = Path(__file__).resolve().parent
SOURCES = HERE / "app" / "Sources"
OLD = re.compile(r"\b(?:Plasmie|plasmie|Plasmie)\b")

# Code that has to name an earlier name: it recognises or migrates from it.
COMPAT = {
    "paths.py": "PREVIOUS_NAMES",
    "plasmie-migrate.py": "steps 4-7 retire old jobs and copy old sign-ins",
    "plasmie-diagnostics.py": "lists older job labels",
    "fm.py": "finds the helper in a not-yet-replaced older install",
    "install.sh": "warns about an older app left in /Applications",
    "Brand.swift": "Brand.previous",
}


def _assign(text, name):
    m = re.search(rf'^\s*(?:static let )?{name}\s*=\s*"([^"]+)"', text, re.M)
    assert m, name
    return m.group(1)


def test_every_copy_of_the_name_agrees():
    brand = (SOURCES / "Brand.swift").read_text()
    env = (HERE / "plasmie-env.sh").read_text()
    make = (HERE / "app" / "make-app.sh").read_text()
    names = {
        "Brand.name": _assign(brand, "name"), "paths.APP_NAME": paths.APP_NAME,
        "PLASMIE_APP_NAME": _assign(env, "PLASMIE_APP_NAME"), "make-app APP_NAME": _assign(make, "APP_NAME"),
        "make-dmg APP_NAME": _assign((HERE / "app" / "make-dmg.sh").read_text(), "APP_NAME"),
        "make-release APP_NAME": _assign((HERE / "app" / "make-release.sh").read_text(), "APP_NAME"),
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
    py = [p for p in HERE.glob("*.py") if not p.name.startswith("test_") and p.name != "conftest.py"]
    sh = list(HERE.glob("*.sh")) + list((HERE / "app").glob("*.sh")) + list((HERE / "launchd").glob("*.sh"))
    return py, sh, sorted(SOURCES.glob("*.swift"))


def test_the_name_is_spelled_out_only_where_it_is_defined():
    py, sh, swift = _engine_files()
    hits = []
    for p in swift:
        if p.name != "Brand.swift":
            hits += [f"{p.name}:{i}" for i, c in _swift_code_lines(p.read_text()) if paths.APP_NAME in c]
    for p in py:
        if p.name != "paths.py":
            hits += [f"{p.name}:{i}" for i, s in _python_strings(p) if paths.APP_NAME in s]
    builds = {"plasmie-env.sh", "make-app.sh", "make-dmg.sh", "make-release.sh"}
    for p in sh:
        if p.name not in builds:
            hits += [f"{p.name}:{i}" for i, c in _shell_code_lines(p.read_text()) if paths.APP_NAME in c]
    assert hits == [], "use Brand.name / paths.APP_NAME / $PLASMIE_APP_NAME instead"


def test_no_user_facing_string_still_says_an_earlier_name():
    py, sh, swift = _engine_files()
    hits = []
    for p in swift:
        if p.name not in COMPAT:
            hits += [f"{p.name}:{i}" for i, c in _swift_code_lines(p.read_text()) if OLD.search(c)]
    for p in py:
        if p.name not in COMPAT:
            hits += [f"{p.name}:{i}" for i, s in _python_strings(p) if OLD.search(s)]
    for p in sh:
        if p.name not in COMPAT:
            hits += [f"{p.name}:{i}" for i, c in _shell_code_lines(p.read_text()) if OLD.search(c)]
    assert hits == []


@pytest.mark.parametrize("doc", ["docs/PRIVACY.md", "DESIGN.md", "PRODUCT.md", "app/brand/plasmie-brand.template.html",
                                 "app/make-dmg.sh", "vault-template"])
def test_docs_and_shipped_text_say_plasmie(doc):
    p = HERE / doc
    files = [p] if p.is_file() else [f for f in p.rglob("*") if f.is_file()]
    assert not [f.name for f in files if re.search(r"\bPlasmie\b", f.read_text(errors="replace"))]


@pytest.mark.parametrize("doc", ["README.md", "docs/QUICKSTART.md"])
def test_friend_docs_name_the_old_app_only_to_upgrade_from_it(doc):
    for line in (HERE / doc).read_text().splitlines():
        if "Plasmie" in line:
            assert re.search(r"Upgrading from|Coming from|used to be called", line), line
