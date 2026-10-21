"""Privacy guard: every host the code can reach is on this list, and docs/PRIVACY.md is
the place that explains each one. A new host fails this test until it's added here AND
described in the privacy note (goal item 8: "the only network calls are the connectors
the user enabled and one-time downloads")."""
import re
import subprocess
from support import ROOT


ALLOWED = {
    # connectors (only when the user switched them on)
    "slack.com", "api.github.com", "github.com", "login.microsoftonline.com",
    "graph.microsoft.com", "your-site.atlassian.net",
    # one-time setup downloads
    "huggingface.co", "nodejs.org",
    # links the user clicks (opened in their browser), never fetched by Plasmie
    "obsidian.md", "claude.com", "brew.sh",
    # local only
    "127.0.0.1",
    # plist DTD identifier (never fetched)
    "www.apple.com",
}


def hosts() -> set[str]:
    files = subprocess.run(["git", "-C", str(ROOT), "ls-files", "*.py", "*.sh", "*.swift"],
                           capture_output=True, text=True).stdout.split()
    found = set()
    for f in files:
        if f.startswith(("tests/", "engine/vault-template/")):
            continue
        text = (ROOT / f).read_text(errors="replace")
        found |= set(re.findall(r"https?://([a-zA-Z0-9.-]+)", text))
    return found


def test_every_host_is_reviewed():
    unknown = hosts() - ALLOWED
    assert not unknown, f"new network host(s) {sorted(unknown)}: add to ALLOWED and explain in docs/PRIVACY.md"
