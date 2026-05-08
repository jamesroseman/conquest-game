"""Auth: dev login, JWT round-trip, token-derived user."""
from __future__ import annotations

from conquest.auth.jwt import mint_jwt, verify_jwt
from conquest.config import AppConfig
from conquest.repositories import InMemoryRepository
from conquest.services.auth_service import AuthService


def test_jwt_round_trip() -> None:
    cfg = AppConfig(jwt_secret="test-secret")
    token = mint_jwt(config=cfg, user_id="u1", display_name="Alice")
    claims = verify_jwt(config=cfg, token=token)
    assert claims["sub"] == "u1"
    assert claims["name"] == "Alice"


def test_dev_login_creates_user_and_token() -> None:
    cfg = AppConfig(jwt_secret="test-secret")
    repo = InMemoryRepository()
    auth = AuthService(repo, cfg)
    result = auth.dev_login(display_name="Alice")
    assert result.user.displayName == "Alice"
    user = auth.user_from_token(result.token)
    assert user is not None
    assert user.userId == result.user.userId
