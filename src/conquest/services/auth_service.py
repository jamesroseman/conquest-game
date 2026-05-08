"""Auth service. Verifies Google ID tokens, upserts users, mints Conquest JWTs."""
from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

from conquest.auth.google import verify_google_id_token
from conquest.auth.jwt import mint_jwt, verify_jwt
from conquest.config import AppConfig
from conquest.models.user import User
from conquest.repositories import Repository


@dataclass
class AuthResult:
    user: User
    token: str


class AuthService:
    def __init__(self, repo: Repository, config: AppConfig) -> None:
        self._repo = repo
        self._config = config

    def authenticate_google(self, id_token: str) -> AuthResult:
        """Verify a Google ID token, upsert a User row, mint a Conquest JWT."""
        claims = verify_google_id_token(id_token)
        google_sub = str(claims["sub"])
        email = claims.get("email")
        name = claims.get("name") or claims.get("email") or "Player"
        return self._upsert_and_mint(user_id=f"g_{google_sub}", email=email, display_name=name)

    def dev_login(self, *, display_name: str, email: str | None = None) -> AuthResult:
        """Dev-only: mint a JWT for an arbitrary identity. Disable in production."""
        slug = display_name.lower().replace(" ", "-") or "anon"
        return self._upsert_and_mint(
            user_id=f"d_{slug}_{uuid.uuid4().hex[:6]}",
            email=email,
            display_name=display_name,
        )

    def _upsert_and_mint(
        self, *, user_id: str, email: str | None, display_name: str
    ) -> AuthResult:
        existing = (
            self._repo.get_user_by_email(email)
            if email
            else self._repo.get_user(user_id)
        )
        now = datetime.now(UTC)
        if existing:
            existing.last_login_at = now
            existing.display_name = display_name
            self._repo.upsert_user(existing)
            user = existing
        else:
            user = User(
                user_id=user_id,
                email=email,
                display_name=display_name,
                created_at=now,
                last_login_at=now,
            )
            self._repo.upsert_user(user)
        token = mint_jwt(
            config=self._config, user_id=user.user_id, display_name=user.display_name
        )
        return AuthResult(user=user, token=token)

    def user_from_token(self, token: str) -> User | None:
        try:
            claims = verify_jwt(config=self._config, token=token)
        except Exception:  # noqa: BLE001
            return None
        return self._repo.get_user(str(claims["sub"]))
