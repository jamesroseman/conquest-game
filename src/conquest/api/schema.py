"""Strawberry GraphQL schema — queries and mutations.

Mutations return a `MutationResult` union of `{Success-payload, GameError}` so callers can
discriminate without try/except. v0.1 unions are intentionally simple; the spec allows a
richer per-mutation error union later.
"""
from __future__ import annotations

import functools
from typing import Annotated, Any, Optional, Union

import strawberry
from strawberry.permission import BasePermission
from strawberry.types import Info

from conquest.api.context import ConquestContext
from conquest.api.types import (
    Game,
    GameConfigInput,
    GameError,
    GameStateView,
    Player,
    TilePlacementInput,
    User,
)
from conquest.game.errors import RuleError
from conquest.models.action import (
    AirdropResearcher,
    Attack,
    CreateVaccine,
    Cure,
    MoveResearcherAdjacent,
    MoveTroops,
    PlaceCapital,
    PlaceReinforcements,
    PlaceResearcher,
    PlaceTroop,
)


def _ctx(info: Info) -> ConquestContext:
    return info.context  # type: ignore[no-any-return]


class IsAuthenticated(BasePermission):
    """Reject the operation if the request did not present a valid Conquest JWT.

    Applied to every Query/Mutation field. Authentication itself happens out of band via
    REST (`/auth/google`, `/auth/dev-login`) so `IsAuthenticated` does not gate the JWT
    minting flow — only the GraphQL surface.
    """

    message = "authentication required"
    error_extensions = {"code": "UNAUTHORIZED"}

    def has_permission(self, source: Any, info: Info, **kwargs: Any) -> bool:
        return _ctx(info).user is not None


def _wrap(fn):  # type: ignore[no-untyped-def]
    """Convert RuleError → GameError union member.

    Preserves the original signature so Strawberry can introspect resolver arguments.
    """

    @functools.wraps(fn)
    def wrapped(*args, **kwargs):  # type: ignore[no-untyped-def]
        try:
            return fn(*args, **kwargs)
        except RuleError as e:
            return GameError(code=e.code, message=str(e))
        except PermissionError as e:
            return GameError(code="UNAUTHORIZED", message=str(e))

    return wrapped


# --- Query ----------------------------------------------------------------------------------


_AUTH = [IsAuthenticated]


@strawberry.type
class Query:
    @strawberry.field(permission_classes=_AUTH)
    def me(self, info: Info) -> Optional[User]:
        ctx = _ctx(info)
        return User.from_model(ctx.user) if ctx.user else None

    @strawberry.field(permission_classes=_AUTH)
    def game(self, info: Info, game_id: str) -> Optional[GameStateView]:
        snap = _ctx(info).games.get_snapshot(game_id)
        if snap is None:
            game = _ctx(info).repo.get_game(game_id)
            if game is None:
                return None
            # Lobby game without a map yet.
            return GameStateView(
                game=Game.from_model(game),
                players=[
                    Player.from_model(p)
                    for p in _ctx(info).repo.get_players(game_id).values()
                ],
                country_states=[],
                map=None,
            )
        return GameStateView.from_snapshot(snap)

    @strawberry.field(permission_classes=_AUTH)
    def joinable_games(self, info: Info) -> list[Game]:
        return [Game.from_model(g) for g in _ctx(info).games.list_joinable_games()]


# --- Mutation results ------------------------------------------------------------------------


@strawberry.type
class GameResult:
    game: Game


@strawberry.type
class GameStateResult:
    state: GameStateView


CreateGameResult = Annotated[
    Union[GameResult, GameError], strawberry.union("CreateGameResult")
]
GameMutationResult = Annotated[
    Union[GameResult, GameError], strawberry.union("GameMutationResult")
]
StateMutationResult = Annotated[
    Union[GameStateResult, GameError], strawberry.union("StateMutationResult")
]


# --- Mutation -------------------------------------------------------------------------------


@strawberry.type
class Mutation:
    # --- Lobby ---

    @strawberry.mutation(permission_classes=_AUTH)
    @_wrap
    def create_game(
        self,
        info: Info,
        name: Optional[str] = None,
        max_players: int = 6,
        is_public: bool = False,
        config: Optional[GameConfigInput] = None,
        seed: Optional[int] = None,
    ) -> CreateGameResult:
        ctx = _ctx(info)
        user = ctx.require_user()
        game = ctx.games.create_game(
            owner_user_id=user.user_id,
            owner_display_name=user.display_name,
            name=name,
            max_players=max_players,
            is_public=is_public,
            config=config.to_model() if config else None,
            seed=seed,
        )
        return GameResult(game=Game.from_model(game))

    @strawberry.mutation(permission_classes=_AUTH)
    @_wrap
    def join_game(
        self,
        info: Info,
        game_id: str,
        invite_code: Optional[str] = None,
    ) -> GameMutationResult:
        ctx = _ctx(info)
        user = ctx.require_user()
        game = ctx.games.join_game(
            game_id=game_id,
            user_id=user.user_id,
            display_name=user.display_name,
            invite_code=invite_code,
        )
        return GameResult(game=Game.from_model(game))

    @strawberry.mutation(permission_classes=_AUTH)
    @_wrap
    def add_ai_seat(
        self,
        info: Info,
        game_id: str,
        archetype: str,
        difficulty: str = "medium",
    ) -> GameMutationResult:
        ctx = _ctx(info)
        user = ctx.require_user()
        game = ctx.games.add_ai_seat(
            game_id=game_id,
            owner_user_id=user.user_id,
            archetype=archetype,  # type: ignore[arg-type]
            difficulty=difficulty,  # type: ignore[arg-type]
        )
        return GameResult(game=Game.from_model(game))

    @strawberry.mutation(permission_classes=_AUTH)
    @_wrap
    def remove_seat(
        self, info: Info, game_id: str, target_player_id: str
    ) -> GameMutationResult:
        ctx = _ctx(info)
        user = ctx.require_user()
        game = ctx.games.remove_seat(
            game_id=game_id,
            owner_user_id=user.user_id,
            target_player_id=target_player_id,
        )
        return GameResult(game=Game.from_model(game))

    @strawberry.mutation(permission_classes=_AUTH)
    @_wrap
    def leave_game(self, info: Info, game_id: str) -> GameMutationResult:
        """Self-service: a player leaves a lobby. Owner cannot leave their own game."""
        ctx = _ctx(info)
        user = ctx.require_user()
        game = ctx.games.leave_game(game_id=game_id, user_id=user.user_id)
        return GameResult(game=Game.from_model(game))

    @strawberry.mutation(permission_classes=_AUTH)
    @_wrap
    def abandon_game(
        self, info: Info, game_id: str, archetype: str = "chaos"
    ) -> StateMutationResult:
        """Self-service: an active player drops out of an in-progress game; AI takes over."""
        ctx = _ctx(info)
        user = ctx.require_user()
        snap = ctx.games.abandon_game(
            game_id=game_id, user_id=user.user_id, archetype=archetype  # type: ignore[arg-type]
        )
        return GameStateResult(state=GameStateView.from_snapshot(snap))

    @strawberry.mutation(permission_classes=_AUTH)
    @_wrap
    def start_game(self, info: Info, game_id: str) -> StateMutationResult:
        ctx = _ctx(info)
        user = ctx.require_user()
        snap = ctx.games.start_game(game_id=game_id, owner_user_id=user.user_id)
        return GameStateResult(state=GameStateView.from_snapshot(snap))

    # --- Setup actions ---

    @strawberry.mutation(permission_classes=_AUTH)
    @_wrap
    def place_setup_troop(
        self, info: Info, game_id: str, country_id: str
    ) -> StateMutationResult:
        return self._setup_action(info, game_id, PlaceTroop(country_id=country_id))

    @strawberry.mutation(permission_classes=_AUTH)
    @_wrap
    def place_researcher(
        self, info: Info, game_id: str, country_id: str
    ) -> StateMutationResult:
        return self._setup_action(info, game_id, PlaceResearcher(country_id=country_id))

    @strawberry.mutation(permission_classes=_AUTH)
    @_wrap
    def place_capital(
        self, info: Info, game_id: str, country_id: str
    ) -> StateMutationResult:
        return self._setup_action(info, game_id, PlaceCapital(country_id=country_id))

    # --- In-game actions ---

    @strawberry.mutation(permission_classes=_AUTH)
    @_wrap
    def place_reinforcements(
        self,
        info: Info,
        game_id: str,
        placements: list[TilePlacementInput],
    ) -> StateMutationResult:
        action = PlaceReinforcements(placements=[(p.countryId, p.count) for p in placements])
        return self._in_game(info, game_id, action)

    @strawberry.mutation(permission_classes=_AUTH)
    @_wrap
    def move_researcher(
        self, info: Info, game_id: str, to_country_id: str
    ) -> StateMutationResult:
        return self._in_game(info, game_id, MoveResearcherAdjacent(to_country_id=to_country_id))

    @strawberry.mutation(permission_classes=_AUTH)
    @_wrap
    def airdrop_researcher(
        self, info: Info, game_id: str, to_country_id: str
    ) -> StateMutationResult:
        return self._in_game(info, game_id, AirdropResearcher(to_country_id=to_country_id))

    @strawberry.mutation(permission_classes=_AUTH)
    @_wrap
    def cure(self, info: Info, game_id: str) -> StateMutationResult:
        return self._in_game(info, game_id, Cure())

    @strawberry.mutation(permission_classes=_AUTH)
    @_wrap
    def create_vaccine(self, info: Info, game_id: str) -> StateMutationResult:
        return self._in_game(info, game_id, CreateVaccine())

    @strawberry.mutation(permission_classes=_AUTH)
    @_wrap
    def attack(
        self,
        info: Info,
        game_id: str,
        from_country_id: str,
        to_country_id: str,
        armies: int,
    ) -> StateMutationResult:
        return self._in_game(
            info,
            game_id,
            Attack(from_country_id=from_country_id, to_country_id=to_country_id, armies=armies),
        )

    @strawberry.mutation(permission_classes=_AUTH)
    @_wrap
    def move_troops(
        self,
        info: Info,
        game_id: str,
        from_country_id: str,
        to_country_id: str,
        armies: int,
    ) -> StateMutationResult:
        return self._in_game(
            info,
            game_id,
            MoveTroops(from_country_id=from_country_id, to_country_id=to_country_id, armies=armies),
        )

    @strawberry.mutation(permission_classes=_AUTH)
    @_wrap
    def end_turn(self, info: Info, game_id: str) -> StateMutationResult:
        ctx = _ctx(info)
        user = ctx.require_user()
        snap, _virus = ctx.games.end_turn(game_id=game_id, actor_user_id=user.user_id)
        return GameStateResult(state=GameStateView.from_snapshot(snap))

    # --- helpers ---

    def _setup_action(self, info: Info, game_id: str, action) -> StateMutationResult:  # type: ignore[no-untyped-def]
        ctx = _ctx(info)
        user = ctx.require_user()
        snap = ctx.games.apply_setup_action(
            game_id=game_id, actor_user_id=user.user_id, action=action
        )
        return GameStateResult(state=GameStateView.from_snapshot(snap))

    def _in_game(self, info: Info, game_id: str, action) -> StateMutationResult:  # type: ignore[no-untyped-def]
        ctx = _ctx(info)
        user = ctx.require_user()
        snap = ctx.games.apply_in_game_action(
            game_id=game_id, actor_user_id=user.user_id, action=action
        )
        return GameStateResult(state=GameStateView.from_snapshot(snap))


schema = strawberry.Schema(Query, Mutation)
