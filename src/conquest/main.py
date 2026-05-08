"""FastAPI application: REST auth endpoints + GraphQL mount.

REST surface (kept small — these are auth + identity only):
    POST /auth/google     {idToken}                → {token, user}
    POST /auth/dev-login  {display_name, email?}    → {token, user}        (dev only)
    GET  /auth/me                                  → {user}                (Bearer)

Everything else lives in GraphQL at `/graphql`.
"""
from __future__ import annotations

import os

from fastapi import Depends, FastAPI, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from strawberry.fastapi import GraphQLRouter

from conquest.api.context import ConquestContext
from conquest.api.schema import schema
from conquest.config import AppConfig
from conquest.models.base import CamelModel
from conquest.repositories import InMemoryRepository
from conquest.services.auth_service import AuthService
from conquest.services.game_service import GameService


class GoogleAuthBody(CamelModel):
    id_token: str


class DevLoginBody(CamelModel):
    display_name: str
    email: str | None = None


class AuthResponse(CamelModel):
    token: str
    user_id: str
    display_name: str
    email: str | None = None


def create_app(*, repo: InMemoryRepository | None = None, config: AppConfig | None = None) -> FastAPI:
    config = config or AppConfig.from_env()
    repo = repo or InMemoryRepository()
    auth = AuthService(repo, config)
    games = GameService(repo)

    app = FastAPI(title="Conquest API", version="0.1.0")
    bearer = HTTPBearer(auto_error=False)

    def _to_response(token: str, user) -> AuthResponse:  # type: ignore[no-untyped-def]
        return AuthResponse(
            token=token, user_id=user.user_id, display_name=user.display_name, email=user.email
        )

    @app.post("/auth/google", response_model=AuthResponse)
    def auth_google(body: GoogleAuthBody) -> AuthResponse:
        result = auth.authenticate_google(body.id_token)
        return _to_response(result.token, result.user)

    @app.post("/auth/dev-login", response_model=AuthResponse)
    def auth_dev_login(body: DevLoginBody) -> AuthResponse:
        if os.environ.get("CONQUEST_DEV_LOGIN", "1") != "1":
            raise HTTPException(status_code=403, detail="dev login disabled")
        result = auth.dev_login(display_name=body.display_name, email=body.email)
        return _to_response(result.token, result.user)

    @app.get("/auth/me", response_model=AuthResponse)
    def auth_me(creds: HTTPAuthorizationCredentials | None = Depends(bearer)) -> AuthResponse:  # noqa: B008
        if creds is None:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="missing token")
        user = auth.user_from_token(creds.credentials)
        if user is None:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid token")
        return AuthResponse(token=creds.credentials, user_id=user.user_id,
                            display_name=user.display_name, email=user.email)

    # --- GraphQL -----------------------------------------------------------

    async def context_getter(request: Request) -> ConquestContext:
        ctx = ConquestContext(repo=repo, config=config, auth=auth, games=games)
        header = request.headers.get("authorization")
        if header and header.lower().startswith("bearer "):
            token = header.split(" ", 1)[1]
            ctx.user = auth.user_from_token(token)
        return ctx

    graphql_app: GraphQLRouter = GraphQLRouter(schema, context_getter=context_getter)
    app.include_router(graphql_app, prefix="/graphql")

    @app.get("/healthz")
    def healthz() -> dict[str, str]:
        return {"status": "ok"}

    return app


app = create_app()
