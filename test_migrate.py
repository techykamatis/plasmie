"""plasmie-migrate: each step once, in order; a failure is retried next time."""
import importlib.util
from pathlib import Path

HERE = Path(__file__).resolve().parent


def load(monkeypatch, tmp_path):
    monkeypatch.setenv("PLASMIE_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("PLASMIE_LOGS", str(tmp_path / "logs"))
    spec = importlib.util.spec_from_file_location("plasmie_migrate", HERE / "plasmie-migrate.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_steps_run_once_in_order(monkeypatch, tmp_path):
    km = load(monkeypatch, tmp_path)
    ran = []
    steps = [(1, "a", lambda: ran.append(1)), (2, "b", lambda: ran.append(2))]
    vf = tmp_path / "v"
    assert km.migrate(steps, vf) == {"ok": True, "version": 2, "latest": 2, "applied": ["a", "b"]}
    assert km.migrate(steps, vf)["applied"] == [] and ran == [1, 2]


def test_a_failed_step_stops_and_is_retried(monkeypatch, tmp_path):
    km = load(monkeypatch, tmp_path)
    calls = {"n": 0}

    def flaky():
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("disk busy")

    ran = []
    steps = [(1, "a", lambda: None), (2, "flaky", flaky), (3, "c", lambda: ran.append(3))]
    vf = tmp_path / "v"
    r = km.migrate(steps, vf)
    assert not r["ok"] and r["version"] == 1 and r["failed"] == 2 and ran == []
    r = km.migrate(steps, vf)
    assert r["ok"] and r["version"] == 3 and r["applied"] == ["flaky", "c"]


def test_registry_is_numbered_without_gaps():
    import ast
    tree = ast.parse((HERE / "plasmie-migrate.py").read_text())
    steps = next(n for n in ast.walk(tree) if isinstance(n, ast.Assign) and getattr(n.targets[0], "id", "") == "STEPS")
    nums = [e.elts[0].value for e in steps.value.elts]
    assert nums == list(range(1, len(nums) + 1))
