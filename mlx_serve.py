#!/usr/bin/env python
"""Serve Gemma-4 E-series via mlx-vlm's native (Anthropic-compatible) server, with
byte-exact wire logging for audit.

- Non-strict weight load kept as a harmless belt-and-suspenders (the E-series config
  is remapped to gemma4_unified, which already handles its shared-KV weights).
- WireLog middleware tees the EXACT /v1/messages request (incl. Claude Code's full
  system prompt + tool defs) and response to a daily 0600 log, so you can audit
  precisely what context crossed into the local model.
"""
import os
import json
import datetime
import mlx.nn as nn

_orig_load = nn.Module.load_weights
nn.Module.load_weights = lambda self, weights, strict=False, **kw: _orig_load(
    self, weights, strict=False, **kw
)

LOGDIR = os.path.expanduser(os.environ.get("PLASMIE_LOGS") or "~/Library/Logs/Plasmie")
RETAIN_DAYS = 30


def _prune():
    try:
        cutoff = datetime.date.today() - datetime.timedelta(days=RETAIN_DAYS)
        for fn in os.listdir(LOGDIR):
            if fn.startswith("wire-") and fn.endswith(".log"):
                try:
                    d = datetime.date.fromisoformat(fn[5:15])
                    if d < cutoff:
                        os.remove(os.path.join(LOGDIR, fn))
                except Exception:
                    pass
    except Exception:
        pass


class WireLog:
    """Raw ASGI middleware: log exact request + response bytes for /v1/messages."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope.get("type") != "http" or "messages" not in scope.get("path", ""):
            return await self.app(scope, receive, send)
        req_body, resp_body = [], []

        async def rcv():
            m = await receive()
            if m.get("type") == "http.request":
                req_body.append(m.get("body", b""))
            return m

        async def snd(m):
            if m.get("type") == "http.response.body":
                resp_body.append(m.get("body", b""))
            await send(m)

        try:
            await self.app(scope, rcv, snd)
        finally:
            self._write(scope, b"".join(req_body), b"".join(resp_body))

    def _write(self, scope, body, out):
        try:
            os.makedirs(LOGDIR, exist_ok=True)
            path = os.path.join(LOGDIR, "wire-%s.log" % datetime.date.today().isoformat())
            fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
            with os.fdopen(fd, "a") as f:
                ts = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                f.write("\n========== %s  %s %s ==========\n"
                        % (ts, scope.get("method"), scope.get("path")))
                f.write("----- REQUEST (exact bytes from Claude Code) -----\n")
                try:
                    f.write(json.dumps(json.loads(body or b"{}"), indent=2, ensure_ascii=False) + "\n")
                except Exception:
                    f.write((body or b"").decode("utf-8", "replace") + "\n")
                f.write("----- RESPONSE -----\n")
                f.write((out or b"").decode("utf-8", "replace") + "\n")
        except Exception:
            pass


_prune()
import mlx_vlm.server as _srv  # noqa: E402
_srv.app.add_middleware(WireLog)

from mlx_vlm.server import main  # noqa: E402

if __name__ == "__main__":
    main()
