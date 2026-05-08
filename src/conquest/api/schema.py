"""Strawberry GraphQL schema — queries and mutations.

Mutations return a `MutationResult` union of `{Success-payload, GameError}` so callers can
discriminate without try/except. v0.1 unions are intentionally simple; the spec allows a
richer per-mutation error union later.
"""
from __future__ import annotations

import functools
from typing import Annotated, Optional, Union

import strawberry
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


@strawberry.type
class Query:
    @strawberry.field
    def me(self, info: Info) -> Optional[User]:
        ctx = _ctx(info)
        return User.from_model(ctx.user) if ctx.user else None

    @strawberry.field
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
                countryStates=[],
                map=None,
            )
        return GameStateView.from_snapshot(snap)

    @strawberry.field
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

    @strawberry.mutation
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
            owner_user_id=user.userId,
            owner_display_name=user.displayName,
            name=name,
            max_players=max_players,
            is_public=is_public,
            config=config.to_model() if config else None,
            seed=seed,
        )
        return GameResult(game=Game.from_model(game))

    @strawberry.mutation
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
            user_id=user.userId,
            display_name=user.displayName,
            invite_code=invite_code,
        )
        return GameResult(game=Game.from_model(game))

    @strawberry.mutation
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
            owner_user_id=user.userId,
            archetype=archetype,  # type: ignore[arg-type]
            difficulty=difficulty,  # type: ignore[arg-type]
        )
        return GameResult(game=Game.from_model(game))

    @strawberry.mutation
    @_wrap
    def remove_seat(
        self, info: Info, game_id: str, target_player_id: str
    ) -> GameMutationResult:
        ctx = _ctx(info)
        user = ctx.require_user()
        game = ctx.games.remove_seat(
            game_id=game_id,
            owner_user_id=user.userId,
            target_player_id=target_player_id,
        )
        return GameResult(game=Game.from_model(game))

    @strawberry.mutation
    @_wrap
    def start_game(self, info: Info, game_id: str) -> StateMutationResult:
        ctx = _ctx(info)
        user = ctx.require_user()
        snap = ctx.games.start_game(game_id=game_id, owner_user_id=user.userId)
        return GameStateResult(state=GameStateView.from_snapshot(snap))

    # --- Setup actions ---

    @strawberry.mutation
    @_wrap
    def place_setup_troop(
        self, info: Info, game_id: str, country_id: str
    ) -> StateMutationResult:
        return self._setup_action(info, game_id, PlaceTroop(countryId=country_id))

    @strawberry.mutation
    @_wrap
    def place_researcher(
        self, info: Info, game_id: str, country_id: str
    ) -> StateMutationResult:
        return self._setup_action(info, game_id, PlaceResearcher(countryId=country_id))

    @strawberry.mutation
    @_wrap
    def place_capital(
        self, info: Info, game_id: str, country_id: str
    ) -> StateMutationResult:
        return self._setup_action(info, game_id, PlaceCapital(countryId=country_id))

    # --- In-game actions ---

    @strawberry.mutation
    @_wrap
    def place_reinforcements(
        self,
        info: Info,
        game_id: str,
        placements: list[TilePlacementInput],
    ) -> StateMutationResult:
        action = PlaceReinforcements(placements=[(p.countryId, p.count) for p in placements])
        return self._in_game(info, game_id, action)

    @strawberry.mutation
    @_wrap
    def move_researcher(
        self, info: Info, game_id: str, to_country_id: str
    ) -> StateMutationResult:
        return self._in_game(info, game_id, MoveResearcherAdjacent(toCountryId=to_country_id))

    @strawberry.mutation
    @_wrap
    def airdrop_researcher(
        self, info: Info, game_id: str, to_country_id: str
    ) -> StateMutationResult:
        return self._in_game(info, game_id, AirdropResearcher(toCountryId=to_country_id))

    @strawberry.mutation
    @_wrap
    def cure(self, info: Info, game_id: str) -> StateMutationResult:
        return self._in_game(info, game_id, Cure())

    @strawberry.mutation
    @_wrap
    def create_vaccine(self, info: Info, game_id: str) -> StateMutationResult:
        return self._in_game(info, game_id, CreateVaccine())

    @strawberry.mutation
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
            Attack(fromCountryId=from_country_id, toCountryId=to_country_id, armies=armies),
        )

    @strawberry.mutation
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
            MoveTroops(fromCountryId=from_country_id, toCountryId=to_country_id, armies=armies),
        )

    @strawberry.mutation
    @_wrap
    def end_turn(self, info: Info, game_id: str) -> StateMutationResult:
        ctx = _ctx(info)
        user = ctx.require_user()
        snap, _virus = ctx.games.end_turn(game_id=game_id, actor_user_id=user.userId)
        return GameStateResult(state=GameStateView.from_snapshot(snap))

    # --- helpers ---

    def _setup_action(self, info: Info, game_id: str, action) -> StateMutationResult:  # type: ignore[no-untyped-def]
        ctx = _ctx(info)
        user = ctx.require_user()
        snap = ctx.games.apply_setup_action(
            game_id=game_id, actor_user_id=user.userId, action=action
        )
        return GameStateResult(state=GameStateView.from_snapshot(snap))

    def _in_game(self, info: Info, game_id: str, action) -> StateMutationResult:  # type: ignore[no-untyped-def]
        ctx = _ctx(info)
        user = ctx.require_user()
        snap = ctx.games.apply_in_game_action(
            game_id=game_id, actor_user_id=user.userId, action=action
        )
        return GameStateResult(state=GameStateView.from_snapshot(snap))


schema = strawberry.Schema(Query, Mutation)
