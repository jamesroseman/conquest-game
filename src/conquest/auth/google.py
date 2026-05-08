"""Google ID-token verification via JWKS.

Production path:
    1. Fetch Google's JWKS at https://www.googleapis.com/oauth2/v3/certs (cached, refreshed on
       kid miss).
    2. Decode + verify the ID token (RS256) against the matching JWK; check `iss` is
       `https://accounts.google.com` (or `accounts.google.com`); check `aud` is our client ID.
    3. Return the verified claims (`sub`, `email`, `name`, ...).

For v0.1 we ship a stub that decodes without signature verification when running with
`CONQUEST_DEV_LOGIN=1`. This module exposes the same `verify_google_id_token(token)` signature
either way; production wires in a real verifier.
"""
from __future__ import annotations

import os
from typing import Any

import jwt as pyjwt


class GoogleVerificationError(Exception):
    pass


def verify_google_id_token(token: str, *, expected_audience: str | None = None) -> dict[str, Any]:
    """Verify a Google ID token, returning the decoded claims.

    In dev mode (CONQUEST_DEV_LOGIN=1, default in v0.1), the signature is *not* verified;
    only the structure is parsed. This is suitable for local development against a fake token
    payload. In production this path is replaced with a JWKS-backed verifier.
    """
    if os.environ.get("CONQUEST_DEV_LOGIN", "1") == "1":
        try:
            claims = pyjwt.decode(token, options={"verify_signature": False})
        except Exception as e:  # noqa: BLE001
            raise GoogleVerificationError(f"could not decode dev token: {e}") from e
        if "sub" not in claims:
            raise GoogleVerificationError("token missing `sub`")
        return claims

    raise GoogleVerificationError(
        "production Google ID-token verification is not yet implemented"
    )
