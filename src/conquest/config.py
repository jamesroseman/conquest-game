"""Application config (env vars). Distinct from `GameConfig` (gameplay tuning)."""

from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class AppConfig:
    jwt_secret: str
    jwt_issuer: str = "conquest"
    jwt_audience: str = "conquest"
    jwt_ttl_seconds: int = 60 * 60 * 24 * 7

    @classmethod
    def from_env(cls) -> AppConfig:
        return cls(
            jwt_secret=os.environ.get("CONQUEST_JWT_SECRET", "dev-secret-change-me"),
        )
