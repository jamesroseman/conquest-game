"""Game service — orchestrates the lobby, game start, and in-game actions.

Lobby flow:
    create_game(owner)               → status: lobby                (creator joins seat 0)
    join_game(game, user)             → status: lobby (must be joinable)
    add_ai_seat(game, owner, ...)     → status: lobby (owner only)
    remove_seat(game, owner, ...)     → status: lobby (owner only)
    start_game(game, owner)           → status: placing_troops; map is generated here

In-game flow:
    apply_setup_action(...)           → 4-phase setup
    apply_action(...)                 → 6 in-game action types
    end_turn(...)                     → advances seat; runs virus phase at round-end
"""
from __future__ import annotations

import secrets
import uuid
from collections.abc import Sequence
from datetime import datetime, timezone
from typing import cast

from conquest.game import setup as setup_engine
from conquest.game import turn as turn_engine
from conquest.game.actions import apply_action as apply_in_game_action
from conquest.game.elimination import check_win_condition
from conquest.game.errors import (
    GameNotJoinable,
    GameNotStartable,
    InvalidAction,
    NotInGame,
    RuleError,
)
from conquest.game.map_gen import generate_map
from conquest.game.rng import SeededRNG
from conquest.models.action import (
    Action,
    PlaceCapital,
    PlaceResearcher,
    PlaceTroop,
)
from conquest.models.events import GameEvent
from conquest.models.game import Game, SetupState, TurnState
from conquest.models.game_config import GameConfig
from conquest.models.map import MapGenParams
from conquest.models.player import AIConfig, ArchetypeId, Difficulty, Player
from conquest.models.snapshot import GameSnapshot
from conquest.models.virus import VirusPhaseResult

PLAYER_COLORS = ["#d23", "#39d", "#3a8", "#fb3", "#92c", "#666"]


class GameService:
    def __init__(self, repo) -> None:  # type: ignore[no-untyped-def]
        self._repo = repo

    # --- Lobby ----------------------------------------------------------------

    def create_game(
        self,
        *,
        owner_user_id: str,
        owner_display_name: str,
        name: str | None = None,
        config: GameConfig | None = None,
        max_players: int = 6,
        is_public: bool = False,
        seed: int | None = None,
    ) -> Game:
        if not 2 <= max_players <= 6:
            raise InvalidAction("max_players must be between 2 and 6")
        game_id = f"g_{uuid.uuid4().hex[:10]}"
        now = datetime.now(timezone.utc)
        rng_seed = seed if seed is not None else secrets.randbits(63)
        invite_code = secrets.token_urlsafe(6)
        game = Game(
            gameId=game_id,
            mapId=None,  # generated at start_game once player count is known
            name=name or f"Game {game_id[2:8]}",
            config=config or GameConfig(),
            status="lobby",
            createdAt=now,
            updatedAt=now,
            rngSeed=rng_seed,
            ownerUserId=owner_user_id,
            minPlayers=2,
            maxPlayers=max_players,
            isPublic=is_public,
            inviteCode=invite_code,
        )
        self._repo.put_game(game)
        # Owner auto-joins seat 0.
        self._add_human_player(game, user_id=owner_user_id, display_name=owner_display_name)
        return self._repo.get_game(game_id)  # reload with playerIds set

    def join_game(
        self,
        *,
        game_id: str,
        user_id: str,
        display_name: str,
        invite_code: str | None = None,
    ) -> Game:
        game = self._must_get_game(game_id)
        if invite_code is not None and game.inviteCode != invite_code and not game.isPublic:
            raise GameNotJoinable("invalid invite code")
        if not game.isPublic and invite_code is None:
            raise GameNotJoinable("game requires an invite code")
        if not game.is_joinable:
            raise GameNotJoinable("game is not accepting players")

        # Already joined?
        for p in self._repo.get_players(game_id).values():
            if p.userId == user_id:
                return game
        self._add_human_player(game, user_id=user_id, display_name=display_name)
        return self._must_get_game(game_id)

    def add_ai_seat(
        self,
        *,
        game_id: str,
        owner_user_id: str,
        archetype: ArchetypeId,
        difficulty: Difficulty = "medium",
    ) -> Game:
        game = self._must_get_game(game_id)
        self._require_owner(game, owner_user_id)
        if not game.is_joinable:
            raise GameNotJoinable("cannot add AI: game is not in lobby")
        seat = game.playerCount
        ai_seed = (game.rngSeed ^ (seat + 1) * 1103515245) & 0x7FFFFFFF
        player_id = f"p_{uuid.uuid4().hex[:8]}"
        ai_player = Player(
            playerId=player_id,
            seatOrder=seat,
            color=PLAYER_COLORS[seat % len(PLAYER_COLORS)],
            kind="ai",
            aiConfig=AIConfig(archetype=archetype, difficulty=difficulty, seed=ai_seed),
            troopsRemainingToPlace=game.config.starting_troops_per_player,
        )
        self._repo.put_player(game_id, ai_player)
        game.playerIds = [*game.playerIds, player_id]
        game.playerCount = len(game.playerIds)
        game.updatedAt = datetime.now(timezone.utc)
        self._repo.put_game(game)
        return game

    def remove_seat(
        self, *, game_id: str, owner_user_id: str, target_player_id: str
    ) -> Game:
        game = self._must_get_game(game_id)
        self._require_owner(game, owner_user_id)
        if game.status != "lobby":
            raise GameNotStartable("can only remove seats while in lobby")
        if target_player_id == game.playerIds[0]:
            raise InvalidAction("cannot remove the game owner")
        self._repo.delete_player(game_id, target_player_id)
        game.playerIds = [pid for pid in game.playerIds if pid != target_player_id]
        # Re-pack seat order so seats stay 0..n-1.
        for i, pid in enumerate(game.playerIds):
            p = self._repo.get_players(game_id)[pid]
            p.seatOrder = i
            p.color = PLAYER_COLORS[i % len(PLAYER_COLORS)]
            self._repo.put_player(game_id, p)
        game.playerCount = len(game.playerIds)
        game.updatedAt = datetime.now(timezone.utc)
        self._repo.put_game(game)
        return game

    def start_game(self, *, game_id: str, owner_user_id: str) -> GameSnapshot:
        """Generate the map (sized for player count) and run setup-phase init."""
        game = self._must_get_game(game_id)
        self._require_owner(game, owner_user_id)
        if game.status != "lobby":
            raise GameNotStartable(f"game already {game.status}")
        if game.playerCount < game.minPlayers:
            raise GameNotStartable(
                f"need at least {game.minPlayers} players, have {game.playerCount}"
            )

        # Generate map for the actual player count.
        params = MapGenParams.for_player_count(seed=game.rngSeed, player_count=game.playerCount)
        m = generate_map(params)
        self._repo.put_map(m)
        game.mapId = m.mapId
        game.status = "placing_troops"
        game.setup = SetupState(phase="troops", activeSeatOrder=0)
        game.turn = TurnState()
        game.updatedAt = datetime.now(timezone.utc)
        self._repo.put_game(game)

        snapshot = self._load_snapshot(game_id)
        setup_engine.initialize_country_states(snapshot)
        # Seed troopsRemainingToPlace per the config.
        for p in snapshot.players.values():
            p.troopsRemainingToPlace = snapshot.game.config.starting_troops_per_player
        self._repo.save_snapshot(snapshot)
        self._append_event(game_id, "game_started", actor=owner_user_id, payload={"mapId": m.mapId})
        return snapshot

    # --- Setup actions --------------------------------------------------------

    def apply_setup_action(
        self,
        *,
        game_id: str,
        actor_user_id: str,
        action: Action,
    ) -> GameSnapshot:
        snapshot = self._load_snapshot(game_id)
        actor = self._resolve_player(snapshot, actor_user_id)
        rng = self._rng_for(snapshot)

        # Map game.status → setup phase that's allowed.
        if snapshot.game.setup.phase == "troops" and isinstance(action, PlaceTroop):
            setup_engine.place_troop(snapshot, actor.playerId, action)
            self._append_event(game_id, "place_troop", actor=actor.playerId,
                               payload={"countryId": action.countryId})
        elif snapshot.game.setup.phase == "researchers" and isinstance(action, PlaceResearcher):
            setup_engine.place_researcher(snapshot, actor.playerId, action)
            self._append_event(game_id, "place_researcher", actor=actor.playerId,
                               payload={"countryId": action.countryId})
        elif snapshot.game.setup.phase == "capitals" and isinstance(action, PlaceCapital):
            setup_engine.place_capital(snapshot, actor.playerId, action)
            self._append_event(game_id, "place_capital", actor=actor.playerId,
                               payload={"countryId": action.countryId})
        else:
            raise InvalidAction(
                f"action {type(action).__name__} not allowed in setup phase {snapshot.game.setup.phase}"
            )

        # Auto-progress through disease seeding (server-driven step) and the eventual
        # transition to in-progress.
        self._auto_progress_setup(snapshot, rng)
        snapshot.game.updatedAt = datetime.now(timezone.utc)
        snapshot.game.rngCursor = rng.cursor
        self._repo.save_snapshot(snapshot)
        return snapshot

    def _auto_progress_setup(self, snapshot: GameSnapshot, rng: SeededRNG) -> None:
        if snapshot.game.setup.phase == "disease_seed":
            seeded = setup_engine.seed_disease(snapshot, rng)
            self._append_event(
                snapshot.game.gameId, "seed_disease", payload={"countries": seeded}
            )
            snapshot.game.status = "placing_researchers"
        elif snapshot.game.setup.phase == "researchers":
            snapshot.game.status = "placing_researchers"
        elif snapshot.game.setup.phase == "capitals":
            snapshot.game.status = "placing_capitals"
        elif snapshot.game.setup.phase == "done":
            turn_engine.begin_first_turn(snapshot)
            self._append_event(snapshot.game.gameId, "turn_started",
                               actor=snapshot.game.turn.activePlayerId, payload={"round": 1})
        elif snapshot.game.setup.phase == "troops":
            snapshot.game.status = "placing_troops"

    # --- In-game actions ------------------------------------------------------

    def apply_in_game_action(
        self,
        *,
        game_id: str,
        actor_user_id: str,
        action: Action,
    ) -> GameSnapshot:
        snapshot = self._load_snapshot(game_id)
        actor = self._resolve_player(snapshot, actor_user_id)
        rng = self._rng_for(snapshot)
        apply_in_game_action(snapshot, actor.playerId, action, rng)
        winner = check_win_condition(snapshot)
        if winner is not None and snapshot.game.status != "ended":
            snapshot.game.status = "ended"
            snapshot.game.endedReason = "victory"
            snapshot.game.winnerPlayerId = winner
        self._append_event(game_id, cast("str", action.type), actor=actor.playerId,
                           payload=action.model_dump())
        snapshot.game.updatedAt = datetime.now(timezone.utc)
        snapshot.game.rngCursor = rng.cursor
        self._repo.save_snapshot(snapshot)
        return snapshot

    def end_turn(
        self, *, game_id: str, actor_user_id: str
    ) -> tuple[GameSnapshot, VirusPhaseResult | None]:
        snapshot = self._load_snapshot(game_id)
        actor = self._resolve_player(snapshot, actor_user_id)
        rng = self._rng_for(snapshot)
        result = turn_engine.end_turn(snapshot, actor.playerId, rng)
        if result is not None:
            self._append_event(game_id, "round_end_virus", payload=result.model_dump())
        if snapshot.game.status == "ended":
            self._append_event(
                game_id, "game_ended",
                payload={"reason": snapshot.game.endedReason,
                         "winner": snapshot.game.winnerPlayerId},
            )
        else:
            self._append_event(game_id, "turn_started",
                               actor=snapshot.game.turn.activePlayerId,
                               payload={"round": snapshot.game.turn.roundNumber})
        snapshot.game.updatedAt = datetime.now(timezone.utc)
        snapshot.game.rngCursor = rng.cursor
        self._repo.save_snapshot(snapshot)
        return snapshot, result

    # --- helpers --------------------------------------------------------------

    def list_joinable_games(self) -> list[Game]:
        return [g for g in self._repo.list_games() if g.is_joinable and g.isPublic]

    def get_snapshot(self, game_id: str) -> GameSnapshot | None:
        snap = self._repo.load_snapshot(game_id)
        return snap

    def list_events(self, game_id: str) -> list[GameEvent]:
        return self._repo.list_events(game_id)

    def _add_human_player(self, game: Game, *, user_id: str, display_name: str) -> Player:
        seat = game.playerCount
        player_id = f"p_{uuid.uuid4().hex[:8]}"
        player = Player(
            playerId=player_id,
            seatOrder=seat,
            color=PLAYER_COLORS[seat % len(PLAYER_COLORS)],
            kind="human",
            userId=user_id,
            troopsRemainingToPlace=game.config.starting_troops_per_player,
        )
        self._repo.put_player(game.gameId, player)
        game.playerIds = [*game.playerIds, player_id]
        game.playerCount = len(game.playerIds)
        game.updatedAt = datetime.now(timezone.utc)
        self._repo.put_game(game)
        return player

    def _must_get_game(self, game_id: str) -> Game:
        g = self._repo.get_game(game_id)
        if g is None:
            raise InvalidAction(f"unknown game {game_id}")
        return g

    def _require_owner(self, game: Game, user_id: str) -> None:
        if game.ownerUserId != user_id:
            raise RuleError("only the game owner can perform this action")

    def _resolve_player(self, snapshot: GameSnapshot, user_id: str) -> Player:
        for p in snapshot.players.values():
            if p.userId == user_id:
                return p
        raise NotInGame(f"user {user_id} is not a player in this game")

    def _load_snapshot(self, game_id: str) -> GameSnapshot:
        snap = self._repo.load_snapshot(game_id)
        if snap is None:
            raise InvalidAction(f"snapshot for {game_id} not found")
        return snap

    def _rng_for(self, snapshot: GameSnapshot) -> SeededRNG:
        return SeededRNG(snapshot.game.rngSeed, cursor=snapshot.game.rngCursor)

    def _append_event(
        self,
        game_id: str,
        event_type: str,
        *,
        actor: str | None = None,
        payload: dict | None = None,
    ) -> None:
        seq = len(self._repo.list_events(game_id)) + 1
        event = GameEvent(
            eventId=f"e_{game_id}_{seq}",
            sequence=seq,
            type=cast("str", event_type),  # narrowed at type-check; runtime is permissive
            actorPlayerId=actor,
            payload=payload or {},
            createdAt=datetime.now(timezone.utc),
        )
        self._repo.append_event(game_id, event)


__all__ = ["GameService"]
_ = Sequence
