"""paths.native_tool: on Apple silicon Plasmie never runs an Intel (x86_64) copy of a tool,
even when an old Intel Homebrew in /usr/local shadows the native one on PATH."""
import struct
from pathlib import Path

import paths


def _thin(path, cpu):
    path.write_bytes(b"\xcf\xfa\xed\xfe" + struct.pack("<i", cpu) + b"\0" * 32)
    path.chmod(0o755)
    return path


def _fat(path, *cpus):
    body = b"\xca\xfe\xba\xbe" + struct.pack(">I", len(cpus))
    body += b"".join(struct.pack(">iiIII", c, 0, 0, 0, 0) for c in cpus)
    path.write_bytes(body)
    path.chmod(0o755)
    return path


ARM, X86 = paths._CPU["arm64"], paths._CPU["x86_64"]


def test_arch_is_read_from_the_binary_not_the_location(tmp_path):
    assert paths.runs_natively(_thin(tmp_path / "a", ARM), "arm64")
    assert not paths.runs_natively(_thin(tmp_path / "i", X86), "arm64")
    assert paths.runs_natively(_fat(tmp_path / "u", X86, ARM), "arm64")       # universal
    assert not paths.runs_natively(_fat(tmp_path / "f", X86), "arm64")
    (tmp_path / "s").write_text("#!/bin/sh\necho hi\n")
    assert paths.runs_natively(tmp_path / "s", "arm64")                       # scripts run anywhere
    (tmp_path / "junk").write_bytes(b"\x00\x01\x02\x03")
    assert not paths.runs_natively(tmp_path / "junk", "arm64")
    assert not paths.runs_natively(tmp_path / "missing", "arm64")


def test_an_intel_copy_first_on_path_is_skipped(tmp_path, monkeypatch):
    monkeypatch.setattr(paths, "NATIVE_DIRS", ())
    monkeypatch.setattr(paths, "runs_natively", lambda p, m=None: Path(p).read_bytes()[:4] != b"INTL")
    intel, native = tmp_path / "usr-local", tmp_path / "homebrew"
    for d, magic in ((intel, b"INTL"), (native, b"#!sh")):
        d.mkdir()
        (d / "git").write_bytes(magic)
        (d / "git").chmod(0o755)
    env = {"PATH": f"{intel}:{native}"}
    assert paths.native_tool("git", env) == str(native / "git")
    assert paths.native_tool("git", {"PATH": str(intel)}) == ""               # Intel only: none
    assert paths.native_tool("git", {"PATH": str(intel), "PLASMIE_GIT_BIN": str(native / "git")}) == str(native / "git")
    assert paths.native_tool("git", {"PATH": str(native), "PLASMIE_GIT_BIN": str(intel / "git")}) == str(native / "git")
