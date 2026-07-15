"""M1 demo test. Success criteria (PLAN.md / sprint_plan.md):
  - secrets findable: zero, down from 1.00 baseline — hard gate
  - secrets tests pass in both directions: real keys blocked, innocent
    phrases ("my key learnings from the project") not blocked
  - every write-gate decision (keep/reject) is logged to audit_log

Note: sprint_plan.md's "relevant results > 0.6" is a retrieval-quality
metric that needs hybrid search (M2) to be measurable — deferred to M5's
full benchmark rerun (see checkpoints/M1.md).
"""
import uuid

from secrets_filter import detector
from api.auth import mint_token
from api.main import app
from write_gate.pipeline import get_extractor, get_judge
from write_gate.judge import Decision
from tests.conftest import FakeExtractor, FakeJudge


# ── secrets_filter unit tests: both directions (threat_model.md T2) ─────────

def test_real_aws_key_is_blocked():
    findings = detector.scan("here's my key: AKIAABCDEFGHIJKLMNOP use it in prod")
    assert any(f.kind == "aws_access_key" for f in findings)


def test_real_private_key_block_is_blocked():
    text = "-----BEGIN RSA PRIVATE KEY-----\nMIIEpAIBAAKCAQEA...\n-----END RSA PRIVATE KEY-----"
    findings = detector.scan(text)
    assert any(f.kind == "private_key" for f in findings)


def test_valid_card_number_is_blocked():
    # 4111111111111111 is a standard Luhn-valid test Visa number
    findings = detector.scan("my card is 4111 1111 1111 1111")
    assert any(f.kind == "card_number" for f in findings)


def test_assigned_secret_is_blocked():
    findings = detector.scan("api_key: sk-abcdefghijklmnopqrstuvwxyz123456")
    assert len(findings) > 0


def test_ssn_is_blocked():
    """threat_model.md names national ID numbers explicitly in scope."""
    findings = detector.scan("my social is 123-45-6789, can you help me file this form")
    assert any(f.kind == "national_id" for f in findings)


def test_jwt_is_blocked():
    findings = detector.scan(
        "here's the token: eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.dQw4w9WgXcQ_abcdefgh"
    )
    assert any(f.kind == "jwt" for f in findings)


def test_bare_mixed_case_high_entropy_token_is_blocked():
    """A provider secret with no recognizable prefix — 'random-looking
    strings that smell like credentials' per threat_model.md."""
    findings = detector.scan("use this to auth: aB3xK9mQz2LpR7vN4tYs8Wc1Ef6Hd0")
    assert any(f.kind == "bare_high_entropy_token" for f in findings)


def test_bare_hex_token_is_blocked():
    findings = detector.scan("session id 9f8e7d6c5b4a3f2e1d0c9b8a7f6e5d4c3b2a1f0e9d8c7b6a")
    assert any(f.kind == "bare_hex_token" for f in findings)


def test_stripe_and_github_prefixes_are_blocked():
    # Built at runtime (not as contiguous literals) so this fixture doesn't
    # look like a real credential to secret scanners such as GitHub push
    # protection, while still exercising the same detector regex.
    fake_stripe_key = "sk_" + "live_" + "51H8xJ2eZvKYlo2C0abcdefgh"
    fake_github_pat = "github_pat_" + "11ABCDEFG0abcdefghijklmnopqrstuvwxyz"
    assert any(f.kind == "api_token" for f in detector.scan(f"key: {fake_stripe_key}"))
    assert any(f.kind == "api_token" for f in detector.scan(f"token {fake_github_pat}"))


def test_innocent_phrase_mentioning_key_is_not_blocked():
    """The exact T2 example: must NOT be blocked."""
    findings = detector.scan("my key learnings from the project this week")
    assert findings == [], f"false positive: {findings!r}"


def test_innocent_phrase_mentioning_secret_is_not_blocked():
    findings = detector.scan("I keep my plans secret until launch day")
    assert findings == []


def test_normal_url_is_not_blocked():
    """All-lowercase URLs are a plausible false-positive risk for the bare
    high-entropy heuristic (it allows '/','.','-' in the contiguous run) —
    confirm the mixed-case requirement keeps ordinary lowercase URLs safe."""
    findings = detector.scan("check the repo at github.com/anthropics/claude-code/issues/12345")
    assert not any(f.kind == "bare_high_entropy_token" for f in findings)


def test_invalid_looking_card_number_not_blocked():
    """16 digits that fail the Luhn check must not be flagged as a card."""
    findings = detector.scan("random number 1234567812345678 not a real card")
    assert not any(f.kind == "card_number" for f in findings)


def test_redact_replaces_only_the_secret_span():
    text = "before AKIAABCDEFGHIJKLMNOP after"
    findings = detector.scan(text)
    redacted = detector.redact(text, findings)
    assert "AKIAABCDEFGHIJKLMNOP" not in redacted
    assert redacted.startswith("before ")
    assert redacted.endswith(" after")
    assert "[REDACTED:aws_access_key]" in redacted


# ── API-level: secrets check happens synchronously, before queueing ────────

def test_message_that_is_entirely_a_secret_is_rejected_422(client, admin_conn, two_tenants):
    token = mint_token(two_tenants["a"])
    resp = client.post(
        "/v1/memories:ingest",
        json={
            "session_id": str(uuid.uuid4()),
            "role": "user",
            "text": "AKIAABCDEFGHIJKLMNOP",
        },
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 422
    assert resp.json()["detail"] == "pii_rejected"

    with admin_conn.cursor() as cur:
        cur.execute(
            "SELECT count(*) FROM conversation_turn WHERE tenant_id = %s", (two_tenants["a"],)
        )
        assert cur.fetchone()[0] == 0, "a fully-secret message must never be stored"


def test_message_with_partial_secret_is_redacted_and_flagged(client, admin_conn, two_tenants):
    token = mint_token(two_tenants["a"])
    resp = client.post(
        "/v1/memories:ingest",
        json={
            "session_id": str(uuid.uuid4()),
            "role": "user",
            "text": "quick question, my key is AKIAABCDEFGHIJKLMNOP, is that a problem?",
        },
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 201
    assert resp.json()["pii_blocked"] is True

    with admin_conn.cursor() as cur:
        cur.execute(
            "SELECT text FROM conversation_turn WHERE tenant_id = %s", (two_tenants["a"],)
        )
        stored_text = cur.fetchone()[0]
    assert "AKIAABCDEFGHIJKLMNOP" not in stored_text
    assert "[REDACTED:aws_access_key]" in stored_text

    with admin_conn.cursor() as cur:
        cur.execute(
            "SELECT count(*) FROM audit_log WHERE tenant_id = %s AND action = 'blocked_secret'",
            (two_tenants["a"],),
        )
        assert cur.fetchone()[0] == 1


def test_clean_message_is_not_flagged(client, admin_conn, two_tenants):
    token = mint_token(two_tenants["a"])
    resp = client.post(
        "/v1/memories:ingest",
        json={
            "session_id": str(uuid.uuid4()),
            "role": "user",
            "text": "my key learnings from the project this week",
        },
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 201
    assert resp.json()["pii_blocked"] is False


# ── write gate: every decision is logged (first_principles.md C3) ─────────

def test_kept_candidate_is_stored_and_logged(client, admin_conn, two_tenants):
    app.dependency_overrides[get_extractor] = lambda: FakeExtractor(["uses PostgreSQL"])
    app.dependency_overrides[get_judge] = lambda: FakeJudge(
        lambda c: Decision(keep=True, importance=6, confidence=0.9, reason="stable tech fact")
    )
    token = mint_token(two_tenants["a"])
    resp = client.post(
        "/v1/memories:ingest",
        json={"session_id": str(uuid.uuid4()), "role": "user", "text": "I use PostgreSQL"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 201

    with admin_conn.cursor() as cur:
        cur.execute(
            "SELECT content, importance, confidence FROM memory WHERE tenant_id = %s",
            (two_tenants["a"],),
        )
        row = cur.fetchone()
    assert row == ("uses PostgreSQL", 6, 0.9)

    with admin_conn.cursor() as cur:
        cur.execute(
            "SELECT count(*) FROM audit_log WHERE tenant_id = %s AND action = 'stored'",
            (two_tenants["a"],),
        )
        assert cur.fetchone()[0] == 1


def test_rejected_candidate_is_not_stored_but_is_logged(client, admin_conn, two_tenants):
    app.dependency_overrides[get_extractor] = lambda: FakeExtractor(["I had dosa today"])
    app.dependency_overrides[get_judge] = lambda: FakeJudge(
        lambda c: Decision(keep=False, importance=1, confidence=0.9, reason="not useful long-term")
    )
    token = mint_token(two_tenants["a"])
    resp = client.post(
        "/v1/memories:ingest",
        json={"session_id": str(uuid.uuid4()), "role": "user", "text": "I had dosa today"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 201

    with admin_conn.cursor() as cur:
        cur.execute("SELECT count(*) FROM memory WHERE tenant_id = %s", (two_tenants["a"],))
        assert cur.fetchone()[0] == 0, "a rejected candidate must never be stored"

    with admin_conn.cursor() as cur:
        cur.execute(
            "SELECT count(*) FROM audit_log WHERE tenant_id = %s AND action = 'rejected'",
            (two_tenants["a"],),
        )
        assert cur.fetchone()[0] == 1
