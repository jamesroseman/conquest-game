"""Conquest JWT mint + verify. HS256 with a server-side secret for v0.1.

A production deployment swaps the secret for a Secret Manager–backed key and rotates it.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

import jwt as pyjwt

from conquest.config import AppConfig


def mint_jwt(*, config: AppConfig, user_id: str, display_name: str) -> str:
    now = datetime.now(timezone.utc)
    payload = {
        "iss": config.jwt_issuer,
        "aud": config.jwt_audience,
        "sub": user_id,
        "name": display_name,
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(seconds=config.jwt_ttl_seconds)).timestamp()),
    }
    return pyjwt.encode(payload, config.jwt_secret, algorithm="HS256")


def verify_jwt(*, config: AppConfig, token: str) -> dict[str, Any]:
    return pyjwt.decode(
        token,
        config.jwt_secret,
        algorithms=["HS256"],
        audience=config.jwt_audience,
        issuer=config.jwt_issuer,
    )
