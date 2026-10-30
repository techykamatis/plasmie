"""app-setup.sh's search-engine step: npm runs sealed off from the user's own npm setup
(a root-owned ~/.npm cache or a ~/.npmrc naming a work registry broke first-run setup
with "check the internet connection" while the internet was fine), and npm's output is
kept in setup.log so a failure can be explained."""
import os
import subprocess
from pathlib import Path

import pytest
from support import ENGINE, ROOT

APP = ROOT / "app/build/Plasmie.app"
pytestmark = pytest.mark.skipif(not (APP / "Contents/MacOS/plasmie-fm").exists(),
                                reason="needs a built app (app/make-app.sh) for the Apple Intelligence check")

# Stands in for the bundled npm: records the npm settings it was given, then installs a
# fake qmd or fails the way real npm does.
FAKE_NPM = r"""#!/bin/bash
env | grep '^npm_config_' | sort > "$FAKE_NPM_ENV"
prefix=""; while [ $# -gt 0 ]; do [ "$1" = --prefix ] && prefix="$2"; shift; done
if [ "$FAKE_NPM_MODE" = ok ]; then
  mkdir -p "$prefix/bin"
  printf '#!/bin/bash\necho "qmd 2.5.3"\n' > "$prefix/bin/qmd"; chmod +x "$prefix/bin/qmd"
  echo "added 267 packages"; exit 0
fi
echo "npm error code $FAKE_NPM_MODE" >&2
echo "npm error errno $FAKE_NPM_MODE" >&2
exit 1
"""


def setup_until_search(tmp_path, mode):
    res = tmp_path / "Resources"
    (res / "node" / "bin").mkdir(parents=True)
    (res / "backend").symlink_to(ENGINE)
    (res / "python").symlink_to(APP / "Contents/Resources/python")
    for name, body in (("npm", FAKE_NPM), ("node", "#!/bin/bash\necho v22.0.0\n")):
        f = res / "node" / "bin" / name
        f.write_text(body)
        f.chmod(0o755)
    home = tmp_path / "user"
    (home / ".npm").mkdir(parents=True)
    (home / ".npmrc").write_text("registry=https://npm.work.invalid/\n")   # must be ignored
    env = {**os.environ, "HOME": str(home), "PLASMIE_HOME": str(tmp_path / "home"),
           "PLASMIE_LOGS": str(tmp_path / "logs"), "PLASMIE_SETUP_UNTIL": "search",
           "PLASMIE_OLD_HOME": str(tmp_path / "no-old"),
           "PLASMIE_FM_BIN": str(APP / "Contents/MacOS/plasmie-fm"),
           "FAKE_NPM_MODE": mode, "FAKE_NPM_ENV": str(tmp_path / "npm-env")}
    r = subprocess.run(["bash", str(ENGINE / "app-setup.sh"), str(res), str(tmp_path / "vault")],
                       env=env, capture_output=True, text=True, timeout=300, check=False)
    npm_env = dict(ln.split("=", 1) for ln in (tmp_path / "npm-env").read_text().splitlines())
    return r, npm_env


def test_npm_ignores_the_users_own_npm_setup(tmp_path):
    r, npm_env = setup_until_search(tmp_path, "ok")
    assert r.returncode == 0 and "DONE" in r.stdout, r.stdout + r.stderr
    home = str(tmp_path / "home")
    assert npm_env["npm_config_cache"].startswith(home)          # not ~/.npm
    assert npm_env["npm_config_userconfig"].startswith(home)     # not ~/.npmrc
    assert npm_env["npm_config_registry"] == "https://registry.npmjs.org/"
    assert "added 267 packages" in (tmp_path / "logs" / "setup.log").read_text()


def test_unreachable_registry_says_so(tmp_path):
    r, _ = setup_until_search(tmp_path, "ENOTFOUND")
    assert r.returncode == 1
    assert "ERROR:couldn't reach registry.npmjs.org" in r.stdout, r.stdout


def test_other_npm_failure_names_the_code_and_the_log(tmp_path):
    r, _ = setup_until_search(tmp_path, "EACCES")
    assert r.returncode == 1
    err = next(ln for ln in r.stdout.splitlines() if ln.startswith("ERROR:"))
    assert "(EACCES)" in err and "setup.log" in err, err
    assert "npm error code EACCES" in Path(tmp_path / "logs" / "setup.log").read_text()
