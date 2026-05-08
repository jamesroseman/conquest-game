"""GraphQL execution context — wires up the request, the auth user, and the services."""
from __future__ import annotations

from typing import TYPE_CHECKING

from strawberry.fastapi import BaseContext

from conquest.config import AppConfig
from conquest.repositories import Repository
from conquest.services.auth_service import AuthService
from conquest.services.game_service import GameService

if TYPE_CHECKING:
    from conquest.models.user import User


class ConquestContext(BaseContext):
    def __init__(
        self,
        *,
        repo: Repository,
        config: AppConfig,
        auth: AuthService,
        games: GameService,
        user: "User | None" = None,
    ) -> None:
        super().__init__()
        self.repo = repo
        self.config = config
        self.auth = auth
        self.games = games
        self.user = user

    def require_user(self) -> "User":
        if self.user is None:
            raise PermissionError("authentication required")
        return self.user
