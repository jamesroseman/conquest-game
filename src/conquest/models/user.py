"""User — authenticated identity. Distinct from Player (per-game participant)."""
from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel


class User(BaseModel):
    userId: str
    email: str | None = None
    displayName: str
    createdAt: datetime
    lastLoginAt: datetime
