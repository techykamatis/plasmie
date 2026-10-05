"""github_api: a Keychain token reaches api.github.com directly (no gh CLI); errors are plain."""
import io
import json
import urllib.error

import pytest

import github_api


class FakeResp(io.BytesIO):
    def __init__(self, body, link=""):
        super().__init__(json.dumps(body).encode())
        self.headers = {"Link": link}

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def test_token_path_follows_link_pagination(monkeypatch):
    monkeypatch.setenv("GITHUB_TOKEN", "t0k")
    seen = []

    def urlopen(req, timeout):
        seen.append((req.full_url, req.get_header("Authorization")))
        if "page=2" in req.full_url:
            return FakeResp({"items": [3]})
        return FakeResp({"items": [1, 2]}, '<https://api.github.com/search/issues?q=x&page=2>; rel="next"')

    monkeypatch.setattr(github_api.urllib.request, "urlopen", urlopen)
    bodies = github_api.pages("search/issues", {"q": "x"})
    assert [it for b in bodies for it in b["items"]] == [1, 2, 3]
    assert all(auth == "Bearer t0k" for _, auth in seen)


def test_rejected_token_is_a_plain_error(monkeypatch):
    monkeypatch.setenv("GITHUB_TOKEN", "bad")

    def urlopen(req, timeout):
        raise urllib.error.HTTPError(req.full_url, 401, "Unauthorized", {}, None)

    monkeypatch.setattr(github_api.urllib.request, "urlopen", urlopen)
    with pytest.raises(github_api.GitHubError, match="token rejected"):
        github_api.login()


def test_no_token_and_no_gh_asks_for_a_token(monkeypatch):
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    monkeypatch.setattr(github_api, "GH_BIN", "")
    assert not github_api.available()
    with pytest.raises(github_api.GitHubError, match="add a GitHub token"):
        github_api.login()


def test_422_carries_githubs_own_reason(monkeypatch):
    """A bare guess ("an org you can't see?") hid the real 422 for days: GitHub had
    started requiring is:issue / is:pull-request on every issue search."""
    monkeypatch.setenv("GITHUB_TOKEN", "t0k")
    why = "Query must include 'is:issue' or 'is:pull-request'"

    def urlopen(req, timeout):
        body = io.BytesIO(json.dumps({"message": why}).encode())
        raise urllib.error.HTTPError(req.full_url, 422, "Unprocessable", {}, body)

    monkeypatch.setattr(github_api.urllib.request, "urlopen", urlopen)
    with pytest.raises(github_api.GitHubError, match=r"is:issue' or 'is:pull-request"):
        github_api.get("search/issues", {"q": "author:me"})


def test_every_issue_search_names_issue_or_pr():
    """loop-ingest's _gh_search must send each query twice, once per kind; a query
    without is:issue / is:pull-request now 422s and marks GitHub "Failed last run"."""
    import pathlib
    import re
    src = (pathlib.Path(__file__).parent / "loop-ingest.py").read_text()
    fn = src[src.index("def _gh_search"):]
    fn = fn[:fn.index("\n\n\n")]
    assert re.search(r'for kind in \("is:issue", "is:pull-request"\)', fn)
    assert 'f"{kind} {q}"' in fn
    doctor = (pathlib.Path(__file__).parent / "plasmie-doctor.py").read_text()
    for q in re.findall(r'"search/issues", \{"q": f"([^"]*)"', doctor):
        assert re.search(r"\bis:(issue|pull-request|pr)\b", q), q
    backfill = (pathlib.Path(__file__).parent / "github-backfill.py").read_text()
    for q in re.findall(r'search\(f"([^"]*)"\)', backfill):
        assert re.search(r"\bis:(issue|pull-request|pr)\b", q), q
