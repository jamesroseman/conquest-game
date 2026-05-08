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


def test_google_verification_requires_client_id_in_prod(monkeypatch) -> None:
    from conquest.auth.google import GoogleVerificationError, verify_google_id_token

    monkeypatch.setenv("CONQUEST_DEV_LOGIN", "0")
    monkeypatch.delenv("CONQUEST_GOOGLE_CLIENT_ID", raising=False)
    import pytest as _pt
    with _pt.raises(GoogleVerificationError):
        verify_google_id_token("any.token.value")


def test_dev_login_creates_user_and_token() -> None:
    cfg = AppConfig(jwt_secret="test-secret")
    repo = InMemoryRepository()
    auth = AuthService(repo, cfg)
    result = auth.dev_login(display_name="Alice")
    assert result.user.display_name == "Alice"
    user = auth.user_from_token(result.token)
    assert user is not None
    assert user.user_id == result.user.user_id
