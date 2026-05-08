"""Google ID-token verification.

Production path uses Google's JWKS:
    1. Fetch https://www.googleapis.com/oauth2/v3/certs (JWKS), cache it in process with TTL.
    2. On a token, decode the unverified header to get the `kid`. If we don't have the key,
       refresh the JWKS once (handles rotation) and retry.
    3. Verify RS256 signature against the matching JWK; require `iss in {accounts.google.com,
       https://accounts.google.com}` and `aud == client_id` (when configured).
    4. Return the verified claims.

When `CONQUEST_DEV_LOGIN=1` (default in v0.1) we skip signature verification so local
development doesn't need a Google client ID. Production deployments set
`CONQUEST_DEV_LOGIN=0` and `CONQUEST_GOOGLE_CLIENT_ID=...` via Secret Manager.
"""

from __future__ import annotations

import os
import threading
import time
from typing import Any

import httpx
import jwt as pyjwt
from jwt.algorithms import RSAAlgorithm

GOOGLE_JWKS_URL = "https://www.googleapis.com/oauth2/v3/certs"
ALLOWED_ISSUERS = ("accounts.google.com", "https://accounts.google.com")
JWKS_TTL_SECONDS = 60 * 60  # 1 hour


class GoogleVerificationError(Exception):
    pass


class _JwksCache:
    """Thread-safe in-process JWKS cache with TTL + on-miss refresh."""

    def __init__(self, ttl_seconds: int = JWKS_TTL_SECONDS) -> None:
        self._ttl = ttl_seconds
        self._lock = threading.Lock()
        self._keys: dict[str, Any] = {}
        self._fetched_at: float = 0.0

    def get_key(self, kid: str) -> Any | None:
        with self._lock:
            if not self._is_fresh():
                self._refresh_locked()
            key = self._keys.get(kid)
            if key is None:
                # Possible rotation — force one refresh.
                self._refresh_locked(force=True)
                key = self._keys.get(kid)
            return key

    def _is_fresh(self) -> bool:
        return self._keys and (time.time() - self._fetched_at) < self._ttl

    def _refresh_locked(self, *, force: bool = False) -> None:
        if not force and self._is_fresh():
            return
        try:
            resp = httpx.get(GOOGLE_JWKS_URL, timeout=5.0)
            resp.raise_for_status()
        except Exception as e:  # noqa: BLE001
            raise GoogleVerificationError(f"could not fetch Google JWKS: {e}") from e
        jwks = resp.json()
        new_keys: dict[str, Any] = {}
        for jwk in jwks.get("keys", []):
            kid = jwk.get("kid")
            if not kid:
                continue
            new_keys[kid] = RSAAlgorithm.from_jwk(jwk)
        self._keys = new_keys
        self._fetched_at = time.time()


_jwks_cache: _JwksCache | None = None


def _cache() -> _JwksCache:
    global _jwks_cache
    if _jwks_cache is None:
        _jwks_cache = _JwksCache()
    return _jwks_cache


def verify_google_id_token(token: str, *, expected_audience: str | None = None) -> dict[str, Any]:
    """Verify a Google ID token and return the decoded claims.

    Set `CONQUEST_DEV_LOGIN=1` for unsigned dev tokens (default in v0.1).
    Set `CONQUEST_GOOGLE_CLIENT_ID=<oauth-client-id>` in production to enforce `aud`.
    """
    if os.environ.get("CONQUEST_DEV_LOGIN", "1") == "1":
        return _verify_dev(token)

    audience = expected_audience or os.environ.get("CONQUEST_GOOGLE_CLIENT_ID")
    if audience is None:
        raise GoogleVerificationError(
            "CONQUEST_GOOGLE_CLIENT_ID must be set to verify production tokens"
        )

    try:
        unverified_header = pyjwt.get_unverified_header(token)
    except Exception as e:  # noqa: BLE001
        raise GoogleVerificationError(f"invalid JWT header: {e}") from e

    kid = unverified_header.get("kid")
    if not kid:
        raise GoogleVerificationError("token header missing `kid`")

    key = _cache().get_key(kid)
    if key is None:
        raise GoogleVerificationError(f"no JWK matches kid={kid}")

    try:
        claims = pyjwt.decode(
            token,
            key=key,
            algorithms=["RS256"],
            audience=audience,
            options={"require": ["sub", "iss", "aud", "exp"]},
        )
    except pyjwt.PyJWTError as e:
        raise GoogleVerificationError(f"signature/claims invalid: {e}") from e

    if claims.get("iss") not in ALLOWED_ISSUERS:
        raise GoogleVerificationError(f"unexpected issuer: {claims.get('iss')!r}")
    return claims


def _verify_dev(token: str) -> dict[str, Any]:
    try:
        claims = pyjwt.decode(token, options={"verify_signature": False})
    except Exception as e:  # noqa: BLE001
        raise GoogleVerificationError(f"could not decode dev token: {e}") from e
    if "sub" not in claims:
        raise GoogleVerificationError("token missing `sub`")
    return claims


def reset_jwks_cache_for_testing() -> None:
    """Clear the in-process JWKS cache. Tests only."""
    global _jwks_cache
    _jwks_cache = None
