#!/usr/bin/env python3
"""Helper for the /release skill. Read-only except `verify` (mounts and detaches a DMG).

It never builds, tags, pushes or touches GitHub releases: those steps stay as explicit
commands in SKILL.md so each external action is visible and gated on a yes.

  release.py preflight [--allow-dirty]       checks before a build; exit 1 on any failure
  release.py changes [--since REF]           raw material for the notes (commits + docs)
  release.py dry-run [--since REF]           preflight (dirty tree warns) + changes
  release.py check-notes FILE [--sha HEX]    plain-English / no-personal-data lint
  release.py verify                          DMG mounts, codesign, version, .sha256
  release.py state [--tag vX.Y.Z]            what exists now: tag local/remote, release, push
  release.py site-version [VER] [--check]    rewrite (or check) the website's version spans
  release.py repo                            print the GitHub repo releases go to
"""
import argparse
import difflib
import importlib.util
import json
import os
import re
import subprocess
import sys
import tempfile

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..", ".."))
APP_NAME = "Plasmie"
BUILD = os.path.join(ROOT, "app", "build")
# The one place that names where releases go. Switch it to a separate public repo (for
# example "techykamatis/plasmie-releases") to make downloads public; SKILL.md reads it
# with `release.py repo`. Tags still live in this repo's origin.
RELEASE_REPO = "techykamatis/plasmie"
# The website (GitHub Pages). Its version number lives in <span data-plasmie-version>.
SITE_DIR = os.path.join(os.path.dirname(ROOT), "plasmie-site")
SITE_FILES = ("index.html", "404.html")
SITE_SPAN = re.compile(r"(<span data-plasmie-version>)([^<]*)(</span>)")
# Download buttons: <a href=".../releases/download/v<ver>/Plasmie-<ver>.dmg" data-plasmie-download>
GITHUB = "https://github.com/"
SITE_DL = re.compile(r'(href=")' + re.escape(GITHUB)
                     + r'[^"]+/releases/download/v([0-9.]+)/Plasmie-([0-9.]+)\.dmg(" data-plasmie-download)')


def download_url(ver):
    return f"{GITHUB}{RELEASE_REPO}/releases/download/v{ver}/Plasmie-{ver}.dmg"


def run(*cmd, check=False):
    p = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True)
    if check and p.returncode:
        raise SystemExit(f"failed: {' '.join(cmd)}\n{p.stderr.strip()}")
    return p


def out(*cmd):
    return run(*cmd).stdout.strip()


def version():
    with open(os.path.join(ROOT, "VERSION"), encoding="utf-8") as f:
        return f.read().strip()


def default_branch():
    ref = out("git", "symbolic-ref", "--short", "refs/remotes/origin/HEAD")
    if ref:
        return ref.split("/", 1)[1]
    p = run("gh", "repo", "view", "--json", "defaultBranchRef", "-q", ".defaultBranchRef.name")
    return p.stdout.strip() or "main"


def previous_tag():
    """Newest v* tag reachable from HEAD's parent, or None (first release)."""
    p = run("git", "describe", "--tags", "--abbrev=0", "--match", "v[0-9]*", "HEAD^")
    return p.stdout.strip() if p.returncode == 0 else None


def previous_release_commit(ver):
    """The newest `chore: release X.Y.Z` commit for an older version: a narrower range
    to suggest when there is no tag yet."""
    for line in out("git", "log", "--format=%H %s", "--grep=^chore: release ").splitlines():
        sha, subject = line.split(" ", 1)
        m = re.match(r"chore: release (\d+\.\d+\.\d+)", subject)
        if m and m.group(1) != ver:
            return sha, m.group(1)
    return None


# ---------------------------------------------------------------- preflight
def preflight(allow_dirty=False):
    ok, report = True, []

    def item(status, msg):
        nonlocal ok
        if status == "FAIL":
            ok = False
        report.append(f"[{status}] {msg}")

    ver = version()
    tag = f"v{ver}"
    if re.fullmatch(r"\d+\.\d+\.\d+", ver):
        item("ok", f"VERSION is {ver} (tag would be {tag})")
    else:
        item("FAIL", f"VERSION {ver!r} is not X.Y.Z")

    branch, default = out("git", "branch", "--show-current"), default_branch()
    item("ok" if branch == default else "FAIL",
         f"on branch {branch!r} (default branch is {default!r})")

    dirty = run("git", "status", "--porcelain").stdout.rstrip("\n")
    if not dirty:
        item("ok", "working tree is clean")
    else:
        lines = dirty.splitlines()
        shown = "\n        ".join(lines[:40]) + (f"\n        ... and {len(lines) - 40} more"
                                                 if len(lines) > 40 else "")
        # Untracked files count: make-app.sh compiles app/Sources/*.swift from the tree,
        # so an untracked source file would ship in a build that no commit describes.
        item("WARN" if allow_dirty else "FAIL",
             f"working tree is not clean ({len(lines)} paths; the build would not match any "
             f"commit):\n        {shown}")
        if allow_dirty:
            report.append("       continuing anyway: --allow-dirty is for a notes preview only, "
                          "never for a real build")

    head_subject = out("git", "log", "-1", "--format=%s")
    if head_subject.startswith(f"chore: release {ver}"):
        item("ok", f"HEAD is the release commit: {head_subject[:80]}")
    else:
        item("WARN", f"HEAD is not a `chore: release {ver}` commit (HEAD: {head_subject[:70]})")

    run("git", "fetch", "--quiet", "origin", default)
    counts = out("git", "rev-list", "--left-right", "--count", f"origin/{default}...HEAD").split()
    if len(counts) == 2:
        behind, ahead = map(int, counts)
        if behind:
            item("FAIL", f"{default} is {behind} commit(s) behind origin/{default}: pull first")
        else:
            item("ok", f"{default} is {ahead} commit(s) ahead of origin" if ahead
                 else f"{default} matches origin/{default}")

    for t in (tag, ver):
        if run("git", "rev-parse", "-q", "--verify", f"refs/tags/{t}").returncode == 0:
            item("FAIL", f"tag {t} already exists locally")
    remote_tags = out("git", "ls-remote", "--tags", "origin", tag, ver)
    item("FAIL" if remote_tags else "ok",
         f"tag {tag} already exists on GitHub" if remote_tags else f"tag {tag} is free on GitHub")
    if run("gh", "release", "view", tag, "-R", RELEASE_REPO).returncode == 0:
        item("FAIL", f"a GitHub release for {tag} already exists in {RELEASE_REPO}")

    auth = run("gh", "auth", "status")
    item("ok" if auth.returncode == 0 else "FAIL",
         "gh auth status ok" if auth.returncode == 0 else f"gh auth status failed: {auth.stderr.strip()[:200]}")
    vis = out("gh", "repo", "view", RELEASE_REPO, "--json", "visibility", "-q", ".visibility")
    if vis == "PRIVATE":
        item("WARN", f"release repo {RELEASE_REPO} is PRIVATE: release downloads only work "
                     "for people with repo access")
    elif vis:
        item("ok", f"repo visibility {vis}")

    venv = os.path.join(ROOT, ".venv", "bin", "python3")
    item("ok" if os.access(venv, os.X_OK) else "FAIL",
         ".venv/bin/python3 present (make-release.sh runs the tests with it)"
         if os.access(venv, os.X_OK) else
         ".venv/bin/python3 missing: make-release.sh's test gate needs it (run ./install.sh "
         "or `python3 -m venv .venv && .venv/bin/pip install pytest`)")

    site_ver, problems = site_versions()
    if problems:
        item("WARN", "website: " + "; ".join(problems))
    elif site_ver != {ver}:
        item("WARN", f"website shows {', '.join(sorted(site_ver))}, not {ver} (expected until "
                     "this release is published; /release updates it after that)")
    else:
        item("ok", f"website version spans show {ver}")

    if os.path.isdir(BUILD) and os.listdir(BUILD):
        item("WARN", f"app/build is not empty ({', '.join(sorted(os.listdir(BUILD)))}); "
                     "make-app.sh wipes it")
    return ok, report


# ---------------------------------------------------------------- changes
def changes(since=None):
    ver = version()
    base = since or previous_tag()
    rng = f"{base}..HEAD" if base else "HEAD"
    lines = [f"# Raw material for the {APP_NAME} {ver} notes",
             f"range: {rng}" + ("" if base else "  (no previous tag: all history)")]
    if not base:
        prev = previous_release_commit(ver)
        if prev:
            lines.append(f"hint: the last release commit before this one is {prev[0][:9]} "
                         f"({prev[1]}); pass --since {prev[0][:9]} for notes covering only "
                         f"what changed since {prev[1]}")
    log = out("git", "log", "--no-merges", "--format=%x1e%s%x1f%b", rng)
    commits = [c for c in log.split("\x1e") if c.strip()]
    lines.append(f"commits: {len(commits)}\n")
    for c in commits:
        subject, _, body = c.partition("\x1f")
        if subject.startswith("chore: release"):
            continue
        lines.append(f"- {subject.strip()}")
        para = body.strip().split("\n\n")[0].strip()
        if para:
            lines += ["    " + ln for ln in para.splitlines()[:6]]
    docs = out("git", "log", "--no-merges", "--format=%s", rng, "--", "docs", "README.md")
    lines.append("\n# Commits that touched user docs (docs/, README.md)")
    lines += [f"- {s}" for s in docs.splitlines()] or ["(none)"]
    diffstat = out("git", "diff", "--stat", f"{base}..HEAD" if base else
                   out("git", "rev-list", "--max-parents=0", "HEAD").splitlines()[0],
                   "--", "docs", "README.md")
    if diffstat:
        lines += ["", diffstat]
    return "\n".join(lines)


# ---------------------------------------------------------------- check-notes
SLOP = [r"\bunlock", r"\bseamless", r"\beffortless", r"\belevat", r"\bempower", r"\bsupercharg",
        r"game.?changer", r"\brevolution", r"\bdelve", r"\bleverag", r"\brobust", r"\bstreamlin",
        r"cutting.?edge", r"next.?level", r"\blevel up", r"\bjourney\b", r"say goodbye",
        r"say hello to", r"\bexcited\b", r"\bthrilled\b", r"\bmagic", r"\bblazing",
        r"\bnot (just|only)\b", r"\bisn't just\b", r"\bmore than just\b", r"\bboasts?\b"]
JARGON = [r"\bADR\b", r"\blaunchd\b", r"\bqmd\b", r"\bruff\b", r"\bpytest\b", r"\brefactor",
          r"\bCI\b", r"\bAPI\b", r"\bSDK\b", r"\bJSON\b", r"\bYAML\b", r"\bfrontmatter\b",
          r"\bMOC\b", r"map.?reduce", r"\bsanitiz", r"\bstdlib\b", r"\bcommits?\b", r"\brepo\b",
          r"\bPR\b", r"\bregex", r"\bsubprocess\b", r"\bmigrations?\b", r"\bplasmie-fm\b",
          r"\bplasmie-", r"\bbackfill", r"\bdedupe\b", r"\bheartbeat\b", r"\bcodesign", r"\bad-hoc\b",
          r"\bSwiftUI\b", r"\bfeat\b", r"\bfix\(", r"\bchore\b"]
FILE_RE = r"\b[\w./-]+\.(py|sh|swift|md|json|ya?ml|plist|tsv|log|env|txt)\b"
HEADINGS = ["New", "Better", "Fixed", "Install"]


def deny_terms():
    """The owner terms test_no_personal.py reads from .personal-deny.txt, its generic terms, and every commit author name and email."""
    spec = importlib.util.spec_from_file_location("tnp", os.path.join(ROOT, "test_no_personal.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    found = mod._deny_terms() if hasattr(mod, "_deny_terms") else (list(getattr(mod, "DENY", [])), [])
    terms = list(found[0]) if found else []          # the git-ignored .personal-deny.txt terms
    terms += [t for t in getattr(mod, "GENERIC", []) if t not in terms]
    for line in out("git", "log", "--format=%an%n%ae").splitlines():
        if line and line not in terms:
            terms.append(line)
            terms.append(line.split("@")[0])
    owner = out("gh", "repo", "view", RELEASE_REPO, "--json", "owner", "-q", ".owner.login")
    if owner:
        terms.append(owner)
    return sorted({t for t in terms if len(t) >= 3}, key=str.lower)


def check_notes(path, sha=None):
    text = open(path, encoding="utf-8").read()
    low = text.lower()
    problems = []
    for t in deny_terms():
        if t.lower() in low:
            problems.append(f"personal/owner name or address: {t!r}")
    for pat in SLOP:
        for m in re.finditer(pat, text, re.I):
            problems.append(f"marketing phrasing: {m.group(0)!r}")
    for pat in JARGON:
        for m in re.finditer(pat, text):
            problems.append(f"developer word or internal name: {m.group(0)!r}")
    for m in re.finditer(FILE_RE, text):
        if not m.group(0).lower().endswith(".dmg"):
            problems.append(f"file name: {m.group(0)!r}")
    body = re.sub(r"\b[0-9a-f]{64}\b", "", text)          # the SHA-256 line itself is fine
    for m in re.finditer(r"\b[0-9a-f]{7,40}\b", body):
        if re.search(r"\d", m.group(0)) and re.search(r"[a-f]", m.group(0)):
            problems.append(f"looks like a commit hash: {m.group(0)!r}")
    if "—" in text or "–" in text or " -- " in text:
        problems.append("em/en dash or ' -- ': use a full stop, comma or parentheses")
    if "?" in text:
        problems.append("question mark: no rhetorical questions")
    if "!" in text:
        problems.append("exclamation mark: keep it calm")

    heads = re.findall(r"^#{1,6}\s*(.+?)\s*$", text, re.M)
    for h in heads:
        if h not in HEADINGS:
            problems.append(f"heading {h!r}: only {', '.join(HEADINGS)} are allowed")
    if heads[-1:] != ["Install"]:
        problems.append("the notes must end with an Install section")
    sections = re.split(r"^#{1,6}\s*", text, flags=re.M)
    for s in sections[1:]:
        name, _, rest = s.partition("\n")
        if name.strip() in HEADINGS[:3] and not re.search(r"^\s*[-*] \S", rest, re.M):
            problems.append(f"empty group {name.strip()!r}: drop it")
    for name, _, rest in (s.partition("\n") for s in sections[1:]):
        if name.strip() in HEADINGS[:3]:
            for ln in re.findall(r"^\s*[-*] (.+)$", rest, re.M):
                if len(ln) > 140:
                    problems.append(f"long line ({len(ln)} chars), keep to one short line: {ln[:50]!r}...")

    inst = text.split("Install", 1)[-1]
    for step, need in (("Step 1", "Applications"), ("Step 2", "Done"),
                       ("Step 3", "Open Anyway")):
        if step not in inst or need not in inst:
            problems.append(f"Install section is missing {step} ({need})")
    if "App Store" not in inst:
        problems.append("Install Step 2 should say it warns because Plasmie isn't from the App Store")
    m = re.search(r"SHA-256[^\n]*", inst)
    if not m:
        problems.append("Install section has no SHA-256 line")
    elif sha and sha not in m.group(0):
        problems.append(f"SHA-256 line does not match the built DMG ({sha[:12]}...)")
    elif not sha and not re.search(r"\b[0-9a-f]{64}\b", m.group(0)):
        print("note: SHA-256 is still a placeholder (fine for a dry run; fill it after the build)")
    return problems


# ---------------------------------------------------------------- verify
def verify():
    ver = version()
    dmg = os.path.join(BUILD, f"{APP_NAME}-{ver}.dmg")
    shaf = dmg + ".sha256"
    fails = []
    for f in (dmg, shaf):
        if not os.path.isfile(f):
            raise SystemExit(f"missing {f}")
    p = subprocess.run(["shasum", "-a", "256", "-c", os.path.basename(shaf)], cwd=BUILD,
                       capture_output=True, text=True)
    print(("ok  " if p.returncode == 0 else "FAIL") + f" .sha256 matches: {p.stdout.strip()}")
    if p.returncode:
        fails.append("sha256")
    mnt = tempfile.mkdtemp(prefix="plasmie-dmg-")
    p = run("hdiutil", "attach", "-nobrowse", "-readonly", "-noautoopen", "-mountpoint", mnt, dmg)
    if p.returncode:
        print(f"FAIL DMG mounts: {p.stderr.strip()}")
        return ["mount"]
    try:
        print("ok   DMG mounts")
        app = os.path.join(mnt, f"{APP_NAME}.app")
        if not os.path.isdir(app):
            fails.append("app")
            print(f"FAIL {APP_NAME}.app is in the DMG")
        else:
            c = run("codesign", "--verify", "--deep", "--strict", app)
            print(("ok  " if c.returncode == 0 else "FAIL") + " codesign --verify --deep --strict"
                  + ("" if c.returncode == 0 else f": {c.stderr.strip()}"))
            if c.returncode:
                fails.append("codesign")
            v = out("plutil", "-extract", "CFBundleShortVersionString", "raw",
                    os.path.join(app, "Contents", "Info.plist"))
            print(("ok  " if v == ver else "FAIL") + f" CFBundleShortVersionString {v!r} == VERSION {ver!r}")
            if v != ver:
                fails.append("version")
        if not os.path.islink(os.path.join(mnt, "Applications")):
            print("WARN no Applications link in the DMG")
    finally:
        run("hdiutil", "detach", mnt, "-quiet")
        try:
            os.rmdir(mnt)
        except OSError:
            pass
    return fails


# ---------------------------------------------------------------- site-version
def site_versions():
    """({versions shown on the site}, [problems]). Only index.html must have spans."""
    found, problems = set(), []
    if not os.path.isdir(SITE_DIR):
        return found, [f"{SITE_DIR} not found"]
    for name in SITE_FILES:
        path = os.path.join(SITE_DIR, name)
        if not os.path.isfile(path):
            continue
        spans = SITE_SPAN.findall(open(path, encoding="utf-8").read())
        if not spans and name == "index.html":
            problems.append("index.html has no <span data-plasmie-version> (the version is unmarked)")
        found |= {v.strip() for _, v, _ in spans}
        for m in SITE_DL.finditer(open(path, encoding="utf-8").read()):
            found |= {m.group(2), m.group(3)}
    return found, problems


def site_version(ver, check):
    if not re.fullmatch(r"\d+\.\d+\.\d+", ver):
        raise SystemExit(f"{ver!r} is not X.Y.Z")
    shown, problems = site_versions()
    if problems:
        print("\n".join(f"FAIL {p}" for p in problems))
        return 1
    if check:
        ok = shown == {ver}
        print(("ok   website shows " if ok else "FAIL website shows ")
              + ", ".join(sorted(shown)) + ("" if ok else f", expected {ver}"))
        return 0 if ok else 1
    changed = False
    for name in SITE_FILES:
        path = os.path.join(SITE_DIR, name)
        if not os.path.isfile(path):
            continue
        old = open(path, encoding="utf-8").read()
        new = SITE_SPAN.sub(lambda m: m.group(1) + ver + m.group(3), old)
        new = SITE_DL.sub(lambda m: m.group(1) + download_url(ver) + m.group(4), new)
        if new != old:
            changed = True
            with open(path, "w", encoding="utf-8") as f:
                f.write(new)
            sys.stdout.writelines(difflib.unified_diff(
                old.splitlines(True), new.splitlines(True), f"a/{name}", f"b/{name}"))
    print(f"website now shows {ver}" + ("" if changed else " (already did; nothing changed)"))
    return 0


# ---------------------------------------------------------------- state
def state(tag):
    tag = tag or f"v{version()}"
    branch = default_branch()
    s = {"tag": tag}
    loc = run("git", "rev-parse", "-q", "--verify", f"refs/tags/{tag}^{{commit}}")
    s["tag_local"] = loc.stdout.strip()[:9] if loc.returncode == 0 else None
    rem = out("git", "ls-remote", "--tags", "origin", f"refs/tags/{tag}")
    s["tag_on_github"] = bool(rem)
    run("git", "fetch", "--quiet", "origin", branch)
    s["branch_ahead_of_origin"] = int(out("git", "rev-list", "--count", f"origin/{branch}..{branch}") or 0)
    r = run("gh", "release", "view", tag, "-R", RELEASE_REPO, "--json", "isDraft,url,assets")
    if r.returncode == 0:
        info = json.loads(r.stdout)
        s["release"] = {"draft": info["isDraft"], "url": info["url"],
                        "assets": [a["name"] for a in info.get("assets", [])]}
    else:
        s["release"] = None
    print(json.dumps(s, indent=2))
    undo = []
    if s["release"]:
        undo.append(f"gh release delete {tag} -R {RELEASE_REPO} --yes   # removes the release (draft or not), keeps the tag")
    if s["tag_on_github"]:
        undo.append(f"git push origin :refs/tags/{tag}          # removes the tag from GitHub")
    if s["tag_local"]:
        undo.append(f"git tag -d {tag}                          # removes the local tag")
    if undo:
        print("\nto undo, newest first:\n  " + "\n  ".join(undo))


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("preflight"); p.add_argument("--allow-dirty", action="store_true")
    p = sub.add_parser("changes"); p.add_argument("--since")
    p = sub.add_parser("dry-run"); p.add_argument("--since")
    p = sub.add_parser("check-notes"); p.add_argument("file"); p.add_argument("--sha")
    sub.add_parser("verify")
    p = sub.add_parser("state"); p.add_argument("--tag")
    p = sub.add_parser("site-version"); p.add_argument("version", nargs="?")
    p.add_argument("--check", action="store_true")
    sub.add_parser("repo")
    a = ap.parse_args()

    if a.cmd in ("preflight", "dry-run"):
        dry = a.cmd == "dry-run"
        # A dry run reports the real verdict (a dirty tree still FAILs) and then carries on
        # to the notes material anyway, so the notes can be previewed mid-development.
        ok, report = preflight(allow_dirty=a.allow_dirty if not dry else False)
        print(f"== {APP_NAME} {version()}: pre-flight" + (" (dry run: no build, no push)" if dry else "") + " ==")
        print("\n".join(report))
        print(f"\npre-flight: {'PASS' if ok else 'FAIL'}")
        if dry:
            if not ok:
                print("WARNING: a real /release would stop here. Dry run: continuing to the notes "
                      "preview only. Nothing is built, tagged or pushed.")
            print("\n" + changes(a.since))
        sys.exit(0 if ok or dry else 1)
    if a.cmd == "changes":
        print(changes(a.since))
    elif a.cmd == "check-notes":
        problems = check_notes(a.file, a.sha)
        print("\n".join(f"- {p}" for p in problems) or "notes ok")
        sys.exit(1 if problems else 0)
    elif a.cmd == "verify":
        fails = verify()
        print("verify: " + ("PASS" if not fails else f"FAIL ({', '.join(fails)})"))
        sys.exit(1 if fails else 0)
    elif a.cmd == "state":
        state(a.tag)
    elif a.cmd == "site-version":
        sys.exit(site_version(a.version or version(), a.check))
    elif a.cmd == "repo":
        print(RELEASE_REPO)


if __name__ == "__main__":
    main()
