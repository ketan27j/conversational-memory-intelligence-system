"""Minimal signed-token auth.

Per threat_model.md T7 ("pretending to be someone else"): the tenant id used
by every downstream query must come from a verified token, never from a
request body or header the caller fully controls. This module is the only
place allowed to produce a tenant_id from a request.

This is a stand-in for a real IdP (Auth0/Cognito/etc.) integration — the
verification shape (reject on bad signature, reject on missing token) is
what matters for M0, not the token format. Swapping to real JWT/IdP
verification later does not change any caller of `verify_token`.
"""
import hashlib
import hmac
import os
import time
from base64 import urlsafe_b64decode, urlsafe_b64encode

from fastapi import Header, HTTPException

SECRET = os.environ.get("CMIS_TOKEN_SECRET", "dev-only-secret-do-not-use-in-prod").encode()
TOKEN_TTL_SECONDS = 3600


def _sign(payload: bytes) -> str:
    sig = hmac.new(SECRET, payload, hashlib.sha256).digest()
    return urlsafe_b64encode(sig).decode().rstrip("=")


def mint_token(tenant_id: str) -> str:
    """Test/dev helper — a real deployment mints tokens at the IdP, not here."""
    payload = f"{tenant_id}:{int(time.time()) + TOKEN_TTL_SECONDS}".encode()
    body = urlsafe_b64encode(payload).decode().rstrip("=")
    return f"{body}.{_sign(payload)}"


def verify_token(authorization: str = Header(default=None)) -> str:
    """FastAPI dependency: returns the verified tenant_id, or raises 401."""
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="missing bearer token")

    token = authorization.removeprefix("Bearer ")
    try:
        body_b64, sig = token.split(".", 1)
        payload = urlsafe_b64decode(body_b64 + "=" * (-len(body_b64) % 4))
        expected_sig = _sign(payload)
        if not hmac.compare_digest(sig, expected_sig):
            raise HTTPException(status_code=401, detail="invalid token signature")
        tenant_id, expiry = payload.decode().split(":")
        if int(expiry) < time.time():
            raise HTTPException(status_code=401, detail="token expired")
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(status_code=401, detail="malformed token")

    return tenant_id
