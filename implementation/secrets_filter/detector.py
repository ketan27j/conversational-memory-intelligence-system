"""Secrets detection. Runs synchronously, before anything is queued (ADR-005).

Per threat_model.md T2, this must pass in both directions:
  - real secrets (API keys, card numbers, private keys) are blocked
  - innocent phrases that merely mention the word "key"/"secret" are not
    blocked (e.g. "my key learnings from the project")

The distinguishing signal is never the word alone — it's a real credential
shape (high-entropy token, known prefix, Luhn-valid digit sequence, PEM
block), because that's what's actually dangerous to store.
"""
import re
from dataclasses import dataclass


@dataclass(frozen=True)
class Finding:
    kind: str
    start: int
    end: int


_PRIVATE_KEY = re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----.*?-----END [A-Z ]*PRIVATE KEY-----", re.DOTALL)
_AWS_ACCESS_KEY = re.compile(r"\b(AKIA|ASIA)[0-9A-Z]{16}\b")
_KNOWN_PREFIX_TOKEN = re.compile(
    r"\b(sk-[A-Za-z0-9]{20,}|sk_(live|test)_[A-Za-z0-9]{16,}|pk_(live|test)_[A-Za-z0-9]{16,}"
    r"|ghp_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{30,}|glpat-[A-Za-z0-9_-]{16,}"
    r"|xox[abpr]-[A-Za-z0-9-]{10,}|AIza[0-9A-Za-z_-]{30,}|npm_[A-Za-z0-9]{30,})\b"
)
# key/secret/password/token followed by an assignment-like separator and a
# long random-looking value — NOT just the word appearing in prose.
_ASSIGNED_SECRET = re.compile(
    r"\b(api[_-]?key|secret|password|token)\b\s*[:=]\s*['\"]?([A-Za-z0-9\-_./+]{16,})['\"]?",
    re.IGNORECASE,
)
# US Social Security Number — the one national-ID shape threat_model.md
# names explicitly and that's cheaply matchable without a classifier.
_SSN = re.compile(r"\b\d{3}-\d{2}-\d{4}\b")
# JWT: three base64url segments; "eyJ" is base64 of the literal `{"`, which
# every JWT header starts with, so this is precise, not just high-entropy.
_JWT = re.compile(r"\beyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\b")
# Bare (unlabeled) high-entropy tokens — the "random-looking strings that
# smell like credentials" category threat_model.md names as in scope, for
# providers with no recognizable prefix. Two independent heuristics, each
# requiring enough length that natural language/URLs/single-case hashes
# don't trip it:
#   (a) mixed upper+lower+digit run of 24+ chars — natural prose never
#       produces this (no spaces, three character classes simultaneously)
#   (b) bare hex run of 32+ chars — catches raw hex secrets/session tokens.
#       Trade-off: this also matches a 32+ char git commit-ish hex string;
#       accepted, since over-redacting a hash is a low-severity, safe-
#       direction miss compared to under-blocking a real secret.
_BARE_MIXED_TOKEN = re.compile(r"\b(?=[A-Za-z0-9+/_.-]{24,}\b)(?=\w*[a-z])(?=\w*[A-Z])(?=\w*\d)[A-Za-z0-9+/_.-]{24,}\b")
_BARE_HEX_TOKEN = re.compile(r"\b[0-9a-fA-F]{32,}\b")


def _luhn_valid(digits: str) -> bool:
    total = 0
    for i, ch in enumerate(reversed(digits)):
        d = int(ch)
        if i % 2 == 1:
            d *= 2
            if d > 9:
                d -= 9
        total += d
    return total % 10 == 0


_CARD_CANDIDATE = re.compile(r"\b(?:\d[ -]?){13,19}\b")


def _find_card_numbers(text: str) -> list[Finding]:
    findings = []
    for m in _CARD_CANDIDATE.finditer(text):
        digits = re.sub(r"[ -]", "", m.group())
        if 13 <= len(digits) <= 19 and _luhn_valid(digits):
            findings.append(Finding("card_number", m.start(), m.end()))
    return findings


def scan(text: str) -> list[Finding]:
    findings: list[Finding] = []
    for pattern, kind in [
        (_PRIVATE_KEY, "private_key"),
        (_AWS_ACCESS_KEY, "aws_access_key"),
        (_KNOWN_PREFIX_TOKEN, "api_token"),
        (_ASSIGNED_SECRET, "assigned_secret"),
        (_SSN, "national_id"),
        (_JWT, "jwt"),
        (_BARE_MIXED_TOKEN, "bare_high_entropy_token"),
        (_BARE_HEX_TOKEN, "bare_hex_token"),
    ]:
        for m in pattern.finditer(text):
            findings.append(Finding(kind, m.start(), m.end()))
    findings.extend(_find_card_numbers(text))
    return findings


def redact(text: str, findings: list[Finding]) -> str:
    """Replace each finding's span with a placeholder that names the kind
    but never the value, per threat_model.md T2 ("never the secret itself")."""
    if not findings:
        return text
    ordered = sorted(findings, key=lambda f: f.start)
    out = []
    cursor = 0
    for f in ordered:
        if f.start < cursor:
            continue  # overlapping match, already covered
        out.append(text[cursor:f.start])
        out.append(f"[REDACTED:{f.kind}]")
        cursor = f.end
    out.append(text[cursor:])
    return "".join(out)


def is_entirely_secret(text: str, findings: list[Finding]) -> bool:
    """422 pii_rejected case (api_contracts.md): the whole message was a secret."""
    if not findings:
        return False
    covered = sum(f.end - f.start for f in findings)
    return covered >= 0.8 * len(text.strip())
