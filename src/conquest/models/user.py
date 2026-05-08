"""User — authenticated identity. Distinct from Player (per-game participant)."""
from __future__ import annotations

from datetime import datetime

from .base import CamelModel


class User(CamelModel):
    user_id: str
    email: str | None = None
    display_name: str
    created_at: datetime
    last_login_at: datetime
