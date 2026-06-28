#!/usr/bin/env python3
"""Secret/PII redactor — canonical copy for the promote path (promote-apply.py).

The patterns are duplicated verbatim from loop-ingest.py because that module runs
Slack fetches at import time (no __main__ guard), so it can't be imported safely.
If loop-ingest.py is ever refactored, have it import from here instead. stdlib only.

  redact(text) -> text with gh/AWS/Slack tokens, sk-/Bearer keys, connection-string
  passwords, labelled secrets, and PEM private keys replaced by «redacted:…».
"""
import re

_SECRET_PATTERNS = [
    (re.compile(r'gh[pousr]_[A-Za-z0-9]{20,}'), '«redacted:gh-token»'),
    (re.compile(r'github_pat_[A-Za-z0-9_]{20,}'), '«redacted:gh-pat»'),
    (re.compile(r'xox[baprs]-[A-Za-z0-9-]{10,}'), '«redacted:slack-token»'),
    (re.compile(r'AKIA[0-9A-Z]{16}'), '«redacted:aws-key»'),
    (re.compile(r'sk-[A-Za-z0-9_-]{20,}'), '«redacted:api-key»'),
    (re.compile(r'(Bearer\s+)[A-Za-z0-9._\-]{20,}'), r'\1«redacted»'),
    # creds embedded in connection strings: scheme://user:PASSWORD@host
    (re.compile(r'(\w+(?:\+\w+)?://[^:/\s]+:)[^@/\s]+(@)'), r'\1«redacted»\2'),
    (re.compile(r'(?i)(password|passwd|pwd|passphrase|secret|api[_-]?key|token|ssid|wifi|otp|pin)(["\']?\s*[:=]\s*["\']?)[^\s"\'`]+'),
     r'\1\2«redacted»'),
    (re.compile(r'-----BEGIN [A-Z ]*PRIVATE KEY-----[\s\S]*?-----END [A-Z ]*PRIVATE KEY-----'),
     '«redacted:private-key»'),
    # email — redacted on the PROMOTE path only (durable notes minimise PII). The
    # ingest/journal path keeps its own redact() without this, so attribution
    # ("who said what") survives in the transient journal. Deliberate divergence.
    (re.compile(r'[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}'), '«redacted:email»'),
]
_CRED_LABEL = re.compile(r'(?i)\b(passwords?|passwd|pwd|passphrase|secret|api[_-]?key|token|ssid|wifi|otp|pin|credentials?|login)\b')
_SECRETISH = re.compile(r'(?<![\w@./-])(?=[A-Za-z0-9!@#$%^&*_-]*[A-Za-z])(?=[A-Za-z0-9!@#$%^&*_-]*\d)[A-Za-z0-9!@#$%^&*_-]{8,}(?![\w@./-])')


def redact(s):
    if not s:
        return s
    for pat, repl in _SECRET_PATTERNS:
        s = pat.sub(repl, s)
    if _CRED_LABEL.search(s):
        s = _SECRETISH.sub('«redacted:credential»', s)
    return s


def selfcheck():
    assert redact("key AKIAABCDEFGHIJKLMNOP here") == "key «redacted:aws-key» here"
    assert "«redacted" in redact("Authorization: Bearer abcdefghijklmnopqrstuvwxyz123")
    assert "«redacted" in redact("token sk-abcdefghijklmnopqrstuvwxyz")
    assert "«redacted" in redact("postgres://user:hunter2spelled@db.host/x")
    assert redact("ping me at jane.doe@example.com please") == "ping me at «redacted:email» please"
    assert redact("just a normal sentence about EKS clusters") == "just a normal sentence about EKS clusters"
    print("scrub selfcheck OK")


if __name__ == "__main__":
    selfcheck()
