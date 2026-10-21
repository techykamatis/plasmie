"""Where things live, for tests. Tests import from here instead of working out paths.

ROOT    the repo checkout
ENGINE  engine/, the scripts that ship as Plasmie.app/Contents/Resources/backend
APP     app/, the macOS app and its build scripts
"""
import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ENGINE = ROOT / "engine"
APP = ROOT / "app"


def load_script(fname, name, register=False):
    """Import an engine script whose file name isn't a valid module name (plasmie-graph.py).

    register=True also puts it in sys.modules, for scripts that other modules import by name.
    """
    spec = importlib.util.spec_from_file_location(name, ENGINE / fname)
    mod = importlib.util.module_from_spec(spec)
    if register:
        sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod
