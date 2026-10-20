#!/usr/bin/env python3
"""Build the Plasmie brand sheet: template + shapes + trophy report + theme toggle.

  python3 app/brand/build.py          # sample stats (sample-report.json): safe to commit
  python3 app/brand/build.py --live   # your own stats, for looking at locally; don't commit that output
"""
import json
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
LOOP = HERE.parent.parent


def main():
    t = (HERE / "plasmie-brand.template.html").read_text()
    shapes = json.loads((HERE / "plasmie-shapes.json").read_text())
    py = LOOP / ".venv/bin/python3"
    if "--live" in sys.argv[1:]:
        report = json.loads(subprocess.run([str(py if py.exists() else sys.executable), str(LOOP / "plasmie-achievements.py")],
                                           capture_output=True, text=True, check=True).stdout)
        print("built with your own stats: don't commit plasmie-brand.html", file=sys.stderr)
    else:
        report = json.loads((HERE / "sample-report.json").read_text())
    sys.path.insert(0, str(LOOP))
    import importlib.util
    spec = importlib.util.spec_from_file_location("ach", LOOP / "plasmie-achievements.py")
    ach = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(ach)
    stages = [{"id": s[0], "name": s[1], "accessory": s[2], "days": s[3], "notes": s[4]} for s in ach.STAGES]
    toggle = (Path.home() / ".claude/snippets/theme-toggle.html").read_text()
    out = (t.replace("/*SHAPES_JSON*/", json.dumps(shapes, separators=(",", ":")))
            .replace("/*REPORT_JSON*/", json.dumps(report, separators=(",", ":")))
            .replace("/*STAGES_JSON*/", json.dumps(stages, separators=(",", ":")))
            .replace("<!--THEME_TOGGLE-->", toggle))
    (HERE / "plasmie-brand.html").write_text(out)
    print(f"built plasmie-brand.html ({len(out)} bytes, {report['unlockedCount']}/{report['total']} trophies)")


if __name__ == "__main__":
    main()
