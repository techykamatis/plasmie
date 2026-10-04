#!/usr/bin/env python3
"""iCloud sync: mirror the vault to iCloud Drive so it reads in Obsidian on iPhone, iPad
and other Macs. The vault on this Mac stays the source of truth.

  plasmie-icloud.py sync --user-enabled [--dest DIR]   mirror now (only the app passes the flag,
                                    when the user's iCloud switch is on)
  plasmie-icloud.py status                JSON: last sync, files, edits kept

Why not keep the vault IN iCloud Drive: background jobs can't read it (TCC), files
iCloud offloads read as empty stubs, and git repos inside it corrupt. So the vault stays
local and this mirrors it. The APP runs the mirror (its iCloud Drive permission covers
child processes); launchd jobs can't.

Safety rules:
- One way, Mac -> iCloud. Never writes into the vault.
- An edit made in the iCloud copy is never lost: if a mirrored file changed since we
  wrote it, it is kept as "<name> (edited in iCloud <date>).md" next to the fresh copy,
  and reported, so you can bring the change into the vault yourself.
- A file deleted from the vault is removed from the mirror only if nobody edited the
  mirror copy since we wrote it.
- Change detection uses size + mtime only (never reads mirror contents), so files
  iCloud has offloaded are never forced to download.
"""
import json
import os
import shutil
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import paths  # noqa: E402
from scrub import redact  # noqa: E402

ICLOUD = Path.home() / "Library/Mobile Documents/com~apple~CloudDocs"
MANIFEST = Path(paths.DATA_DIR) / "icloud-manifest.json"
# What leaves the Mac is an allowlist of what's worth reading on a phone: the curated wiki,
# the archive, daily digests, the index and log, and Obsidian's display settings. Never
# raw/ (unredacted captures: Slack messages, sessions), the rest of meta/ (Ask queries,
# drafts), plugin data (plugins keep API keys in data.json), or git internals.
MIRROR = ("wiki/", "archive/", "meta/digests/", "index.md", "log.md", ".obsidian/")
NEVER = (".obsidian/plugins/", ".obsidian/workspace")
SKIP_FILES = {".DS_Store"}
TEXT = {".md", ".json", ".css", ".txt", ".canvas"}


def default_dest(vault: Path) -> Path:
    return ICLOUD / "Plasmie" / vault.name


def adopt_plasmie_mirror(icloud: Path = ICLOUD) -> bool:
    """Plasmie -> Plasmie (0027): rename iCloud Drive/Plasmie to iCloud Drive/Plasmie, so the
    mirror (and any edit kept in it) carries over instead of being copied anew. Only when
    the new folder doesn't exist yet; never merges. True when it moved."""
    old, new = icloud / "Plasmie", icloud / "Plasmie"
    if not old.is_dir() or new.exists():
        return False
    old.rename(new)
    return True


def _sig(p: Path) -> list:
    st = p.stat()
    return [st.st_size, st.st_mtime_ns]


def mirrored(rel: str) -> bool:
    return rel.startswith(MIRROR) and not rel.startswith(NEVER)


def looks_secret(p: Path) -> bool:
    """A text file the redactor would change holds something that looks like a secret."""
    if p.suffix not in TEXT:
        return False
    try:
        text = p.read_text(errors="replace")
    except OSError:
        return True
    return redact(text) != text


def _files(vault: Path):
    for root, dirs, files in os.walk(vault):
        rel_root = Path(root).relative_to(vault).as_posix()
        dirs[:] = [d for d in dirs if d != ".git" and (rel_root != "." or any(m.startswith(d) for m in MIRROR))]
        for f in files:
            rel = (Path(root) / f).relative_to(vault).as_posix()
            if f not in SKIP_FILES and mirrored(rel):
                yield rel, Path(root) / f


def _keep_edit(dst: Path) -> Path:
    stamp = datetime.now().strftime("%Y-%m-%d %H%M")
    kept = dst.with_name(f"{dst.stem} (edited in iCloud {stamp}){dst.suffix}")
    dst.rename(kept)
    return kept


def sync(vault: Path, dest: Path, manifest_path: Path = MANIFEST) -> dict:
    vault, dest = vault.expanduser(), dest.expanduser()
    if not vault.is_dir():
        return {"ok": False, "error": f"vault missing: {vault}"}
    try:
        old = json.loads(manifest_path.read_text())
    except (OSError, ValueError):
        old = {}
    files = old.get("files", {})          # rel -> {"src": sig of source copied, "dst": sig we left}
    copied, kept, removed, held = 0, [], 0, []
    seen = set()
    for rel, src in _files(vault):
        dst = dest / rel
        rec = files.get(rel)
        src_sig = _sig(src)
        if rec and rec["src"] == src_sig and dst.exists():
            seen.add(rel)
            continue                                             # unchanged since last sync
        if looks_secret(src):
            held.append(rel)                                     # never upload what looks like a secret
            continue
        seen.add(rel)
        if dst.exists() and (not rec or _sig(dst) != rec["dst"]):
            kept.append(str(_keep_edit(dst).relative_to(dest)))  # edited in iCloud (or unknown): keep it
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)
        files[rel] = {"src": src_sig, "dst": _sig(dst)}
        copied += 1
    for rel in [r for r in files if r not in seen]:              # deleted from the vault
        dst = dest / rel
        if dst.exists() and _sig(dst) == files[rel]["dst"]:
            dst.unlink()
            removed += 1
        elif dst.exists():
            kept.append(rel)                                     # edited there: leave it
        del files[rel]
    result = {"ok": True, "dest": str(dest), "copied": copied, "removed": removed,
              "kept_edits": kept, "held_back": held, "files": len(files), "at": datetime.now().isoformat(timespec="seconds")}
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(json.dumps({"files": files, "last": result}))
    return result


def status(manifest_path: Path = MANIFEST) -> dict:
    try:
        return json.loads(manifest_path.read_text()).get("last", {})
    except (OSError, ValueError):
        return {"ok": None, "never": True}


def main(argv: list[str]) -> int:
    cmd = argv[0] if argv else "status"
    if cmd == "sync":
        # Uploading the vault is the user's decision: only the app, when its iCloud switch
        # is on, passes --user-enabled. A hand or script run must never upload by accident.
        if "--user-enabled" not in argv:
            print(json.dumps({"ok": False, "error": f"iCloud sync is off. Turn it on in the {paths.APP_NAME} window."}))
            return 1
        vault = Path(paths.vault())
        if "--dest" not in argv:
            try:
                adopt_plasmie_mirror()
            except OSError:
                pass                             # no permission yet: the sync below reports it
        dest = Path(argv[argv.index("--dest") + 1]) if "--dest" in argv else default_dest(vault)
        if not dest.is_relative_to(ICLOUD) and "--dest" not in argv:
            print(json.dumps({"ok": False, "error": "iCloud Drive not found"}))
            return 1
        if not ICLOUD.exists() and "--dest" not in argv:
            print(json.dumps({"ok": False, "error": "iCloud Drive is off. Turn it on in System Settings › Apple Account › iCloud."}))
            return 1
        try:
            r = sync(vault, dest)
        except OSError as e:                     # no iCloud Drive permission yet, disk full, …
            r = {"ok": False, "error": f"{type(e).__name__}: {e.strerror or e}"}
        print(json.dumps(r))
        return 0 if r["ok"] else 1
    print(json.dumps(status()))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
