"""digest.py: the hourly digest on the on-device model — one call when it fits,
map-reduce when it doesn't, and the exit codes summarize.sh acts on."""
import os
import subprocess
from pathlib import Path

import digest
import fm

HERE = Path(__file__).resolve().parent


def fake(sent, reply="- a bullet", errors=None):
    errors = list(errors or [])

    def respond(prompt, **kw):
        sent.append(prompt)
        if errors:
            return {"error": errors.pop(0), "reason": "r"}
        return {"text": reply}
    return respond


def test_a_day_that_fits_is_one_call_with_the_measured_prompt(monkeypatch):
    sent = []
    monkeypatch.setattr(fm, "context_size", lambda: 8192)
    monkeypatch.setattr(fm, "respond", fake(sent))
    code, out = digest.digest("===== slack =====\nshipped the thing\n")
    assert (code, out) == (0, "- a bullet") and len(sent) == 1
    assert sent[0].startswith(digest.HEAD) and "Never upgrade a status" in sent[0]


def test_a_day_that_does_not_fit_is_map_reduced_not_truncated(monkeypatch):
    sent = []
    monkeypatch.setattr(fm, "context_size", lambda: 4096)
    monkeypatch.setattr(fm, "respond", fake(sent))
    day = "".join(f"===== {s} =====\n" + f"{s} line {{}}\n".format(s) * 2000 for s in ("slack", "git"))
    code, out = digest.digest(day)
    assert code == 0 and out == "- a bullet"
    maps = [p for p in sent if p.startswith(digest.MAP_HEAD)]
    assert len(maps) > 2 and sent[-1].startswith(digest.REDUCE_HEAD)
    assert all(len(p) < 4096 * 3 for p in sent)
    assert "slack line" in "".join(maps) and "git line" in "".join(maps)


def test_over_budget_on_the_single_call_falls_into_map_reduce(monkeypatch):
    sent = []
    monkeypatch.setattr(fm, "context_size", lambda: 8192)
    monkeypatch.setattr(fm, "respond", fake(sent, errors=["over_budget"]))
    assert digest.digest("===== slack =====\nx\n") == (0, "- a bullet")
    assert len(sent) == 3            # single (refused) -> one map -> one reduce


def test_exit_codes(monkeypatch):
    monkeypatch.setattr(fm, "context_size", lambda: 8192)
    for err, code in (("busy", 3), ("unavailable", 4), ("guardrail", 5)):
        monkeypatch.setattr(fm, "respond", fake([], errors=[err]))
        assert digest.digest("===== slack =====\nx\n")[0] == code, err
    monkeypatch.setattr(fm, "context_size", lambda: None)
    monkeypatch.setattr(fm, "probe", lambda: {"detail": "off", "hint": "Turn on Apple Intelligence."})
    code, why = digest.digest("x")
    assert code == 4 and "Apple Intelligence" in why


def test_summarize_writes_a_digest_through_the_helper(tmp_path, fake_fm):
    """The real summarize.sh against the fake plasmie-fm: digest file + audit line."""
    import datetime
    day = datetime.date.today().isoformat()
    v = tmp_path / "vault"
    (v / "raw" / "slack").mkdir(parents=True)
    (v / "raw" / "slack" / f"{day}.md").write_text("merged PR #12\n")
    fake_fm.set(reply={"text": "- PR #12 merged"})
    env = {**os.environ, "PLASMIE_HOME": str(tmp_path / "home"), "PLASMIE_LOGS": str(tmp_path / "logs"),
           "VAULT_DIR": str(v), "PLASMIE_FM_BIN": fake_fm.bin, "FAKE_FM_DIR": fake_fm.dir,
           "PLASMIE_FM_GUARD": "off"}
    r = subprocess.run(["bash", str(HERE / "summarize.sh")], capture_output=True, text=True,
                       env=env, timeout=120)
    assert r.returncode == 0, r.stderr
    d = (v / "meta" / "digests" / f"{day}.md").read_text()
    assert "- PR #12 merged" in d and "Apple on-device" in d
    assert "ok: wrote" in (tmp_path / "logs" / f"audit-{day}.log").read_text()


def test_summarize_says_why_when_apple_intelligence_is_off(tmp_path, fake_fm):
    import datetime
    day = datetime.date.today().isoformat()
    v = tmp_path / "vault"
    (v / "raw" / "slack").mkdir(parents=True)
    (v / "raw" / "slack" / f"{day}.md").write_text("x\n")
    fake_fm.set(probe={"status": "appleIntelligenceNotEnabled"})
    env = {**os.environ, "PLASMIE_HOME": str(tmp_path / "home"), "PLASMIE_LOGS": str(tmp_path / "logs"),
           "VAULT_DIR": str(v), "PLASMIE_FM_BIN": fake_fm.bin, "FAKE_FM_DIR": fake_fm.dir,
           "PLASMIE_FM_GUARD": "off"}
    r = subprocess.run(["bash", str(HERE / "summarize.sh")], capture_output=True, text=True,
                       env=env, timeout=120)
    assert r.returncode == 0 and "Apple Intelligence" in r.stdout
    assert not (v / "meta" / "digests" / f"{day}.md").exists()
    assert "System Settings" in (tmp_path / "logs" / f"audit-{day}.log").read_text()
