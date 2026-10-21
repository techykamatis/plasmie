"""Tests for scrub.redact — bare token shapes and per-pattern regressions."""
import pytest

from scrub import redact

B64 = "AbCdEfGh1234567890_-" * 6          # 120 b64url chars
ATL = "ATATT3xFfGF0" + B64[:100] + "=1A2B3C4D"
ATL_C = "ATCTT3xFfGF0" + B64[:100]
JWT = "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.dBjftJeZ4CVPmB92K27uhbUJU1p1r"
XAPP = "xapp-1-A0123456789-1234567890123-abcdef0123456789abcdef"
GLPAT = "glpat-abcdefghij0123456789"
HF = "hf_" + "aBcDeFgHiJ0123456789kLmNoPqRsT"
MS = "0.A" + B64


@pytest.mark.parametrize("tok", [ATL, ATL_C, JWT, XAPP, GLPAT, HF, MS])
def test_new_shapes_bare_and_embedded(tok):
    assert redact(tok) != tok and "«redacted" in redact(tok)
    out = redact(f"see the value {tok} in the logs.")
    assert tok not in out and "«redacted" in out
    assert out.startswith("see the value ") and out.endswith(" in the logs.")


def test_ms_refresh_token_1_prefix():
    assert "«redacted" in redact("1.A" + B64)


@pytest.mark.parametrize("text", [
    "just a normal sentence about EKS clusters",
    "version 1.A of the doc", "upgrade to 1.Alpha release", "0.Alpha",
    "see hf_x for details", "hf_short123",
    "commit 9d77ca9e66f6b4e3c60bb1c2d3e4f5a6b7c8d9e0 landed",
    "id 123e4567-e89b-12d3-a456-426614174000",
    "https://github.com/org/repo/pull/12",
    "the prefix eyJ is base64 for {\"", "eyJ.eyJ.x",
    "def encode_payload_for_transport(): return base64_encoded_value",
    "xapp-style apps", "glpat-short",
])
def test_negatives_untouched(text):
    assert redact(text) == text


@pytest.mark.parametrize("tok", [
    "ghp_" + "a" * 36, "gho_" + "b" * 30, "github_pat_" + "A1_" * 10,
    "xoxb-1234567890-abcdefghij", "AKIAABCDEFGHIJKLMNOP", "sk-" + "a1" * 12,
])
def test_existing_token_regressions(tok):
    out = redact(f"x {tok} y")
    assert tok not in out and "«redacted" in out


def test_bearer_and_pem_regressions():
    assert "abcdefghijklmnopqrstuvwxyz123" not in redact("Authorization: Bearer abcdefghijklmnopqrstuvwxyz123")
    pem = "-----BEGIN RSA PRIVATE KEY-----\nMIIabc\n-----END RSA PRIVATE KEY-----"
    assert redact(f"k\n{pem}\nz") == "k\n«redacted:private-key»\nz"
