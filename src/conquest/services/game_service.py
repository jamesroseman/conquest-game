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
import time
import uuid
from collections.abc import Sequence
from datetime import UTC, datetime
from typing import cast

from conquest.ai.runner import run_ai_setup_step, run_ai_turn
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
from conquest.models.map import MAX_PLAYERS, MIN_PLAYERS, MapGenParams
from conquest.models.player import AIConfig, ArchetypeId, Difficulty, Player
from conquest.models.snapshot import GameSnapshot
from conquest.models.virus import VirusPhaseResult

PLAYER_COLORS = ["#d23", "#39d", "#3a8", "#fb3", "#92c", "#666"]

# Per-user concurrency cap. The in-memory repository holds full snapshots in process memory
# (a 6-player map has ~5k tiles + ~50 country states); this prevents a single user from
# spawning unbounded games and exhausting RAM. Tune via constructor.
DEFAULT_MAX_ACTIVE_GAMES_PER_USER = 5


class GameService:
    def __init__(
        self,
        repo,  # type: ignore[no-untyped-def]
        *,
        max_active_games_per_user: int = DEFAULT_MAX_ACTIVE_GAMES_PER_USER,
    ) -> None:
        self._repo = repo
        self._max_active_games_per_user = max_active_games_per_user

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
        if not MIN_PLAYERS <= max_players <= MAX_PLAYERS:
            raise InvalidAction(f"max_players must be between {MIN_PLAYERS} and {MAX_PLAYERS}")
        # Enforce per-user concurrent-active-games cap.
        active = self._count_active_games_for_user(owner_user_id)
        if active >= self._max_active_games_per_user:
            raise InvalidAction(
                f"user has reached the active-game cap "
                f"({active}/{self._max_active_games_per_user}); finish or abandon a game first"
            )
        game_id = f"g_{uuid.uuid4().hex[:10]}"
        now = datetime.now(UTC)
        rng_seed = seed if seed is not None else secrets.randbits(63)
        invite_code = secrets.token_urlsafe(6)
        game = Game(
            game_id=game_id,
            map_id=None,  # generated at start_game once player count is known
            name=name or f"Game {game_id[2:8]}",
            # Default live games to a half-second AI pause so bot turns play
            # at a watchable cadence. Tests pass `config` explicitly to keep
            # the model-level default (0) and run instantly.
            config=config or GameConfig(ai_action_delay_ms=500),
            status="lobby",
            created_at=now,
            updated_at=now,
            rng_seed=rng_seed,
            owner_user_id=owner_user_id,
            min_players=2,
            max_players=max_players,
            is_public=is_public,
            invite_code=invite_code,
        )
        self._repo.put_game(game)
        # Owner auto-joins seat 0.
        self._add_human_player(game, user_id=owner_user_id, display_name=owner_display_name)
        return self._repo.get_game(game_id)  # reload with player_ids set

    def join_game(
        self,
        *,
        game_id: str,
        user_id: str,
        display_name: str,
        invite_code: str | None = None,
    ) -> Game:
        game = self._must_get_game(game_id)
        if invite_code is not None and game.invite_code != invite_code and not game.is_public:
            raise GameNotJoinable("invalid invite code")
        if not game.is_public and invite_code is None:
            raise GameNotJoinable("game requires an invite code")
        if not game.is_joinable:
            raise GameNotJoinable("game is not accepting players")

        # Already joined?
        for p in self._repo.get_players(game_id).values():
            if p.user_id == user_id:
                return game
        self._add_human_player(game, user_id=user_id, display_name=display_name)
        return self._must_get_game(game_id)

    def add_ai_seat(
        self,
        *,
        game_id: str,
        owner_user_id: str,
        archetype: ArchetypeId | None = None,
        difficulty: Difficulty | None = None,
    ) -> Game:
        game = self._must_get_game(game_id)
        self._require_owner(game, owner_user_id)
        if not game.is_joinable:
            raise GameNotJoinable("cannot add AI: game is not in lobby")
        seat = game.player_count
        ai_seed = (game.rng_seed ^ (seat + 1) * 1103515245) & 0x7FFFFFFF
        # Archetype and difficulty are intentionally hidden from the UI — pick
        # one at random per seat so each game feels fresh. Tests still pass
        # explicit values when they need a deterministic policy.
        from conquest.ai.archetypes import ARCHETYPES as _ARCHETYPES

        rng_pick = SeededRNG(ai_seed)
        chosen_archetype: ArchetypeId = (
            archetype if archetype is not None else cast("ArchetypeId", rng_pick.choice(list(_ARCHETYPES.keys())))
        )
        chosen_difficulty: Difficulty = (
            difficulty if difficulty is not None else cast("Difficulty", rng_pick.choice(["easy", "medium", "hard", "brutal"]))
        )
        player_id = f"p_{uuid.uuid4().hex[:8]}"
        ai_player = Player(
            player_id=player_id,
            seat_order=seat,
            color=PLAYER_COLORS[seat % len(PLAYER_COLORS)],
            kind="ai",
            ai_config=AIConfig(archetype=chosen_archetype, difficulty=chosen_difficulty, seed=ai_seed),
            troops_remaining_to_place=game.config.starting_troops_per_player,
        )
        self._repo.put_player(game_id, ai_player)
        game.player_ids = [*game.player_ids, player_id]
        game.player_count = len(game.player_ids)
        game.updated_at = datetime.now(UTC)
        self._repo.put_game(game)
        return game

    def leave_game(self, *, game_id: str, user_id: str) -> Game:
        """A human player removes themselves from a lobby. Owner cannot leave their own game.

        Once a game has started, players can no longer leave — they must `abandon_game`
        instead, which hands their seat to an AI policy.
        """
        game = self._must_get_game(game_id)
        if game.status != "lobby":
            raise GameNotStartable("game already started; use abandon_game to hand the seat to AI")
        if game.owner_user_id == user_id:
            raise InvalidAction("the game owner cannot leave their own game; remove it instead")
        target = next(
            (p for p in self._repo.get_players(game_id).values() if p.user_id == user_id),
            None,
        )
        if target is None:
            raise NotInGame(f"user {user_id} is not in this game")
        self._repo.delete_player(game_id, target.player_id)
        game.player_ids = [pid for pid in game.player_ids if pid != target.player_id]
        for i, pid in enumerate(game.player_ids):
            p = self._repo.get_players(game_id)[pid]
            p.seat_order = i
            p.color = PLAYER_COLORS[i % len(PLAYER_COLORS)]
            self._repo.put_player(game_id, p)
        game.player_count = len(game.player_ids)
        game.updated_at = datetime.now(UTC)
        self._repo.put_game(game)
        return game

    def abandon_game(
        self,
        *,
        game_id: str,
        user_id: str,
        archetype: ArchetypeId = "chaos",
        difficulty: Difficulty = "medium",
    ) -> GameSnapshot:
        """A human player leaves an in-progress game; their seat becomes an AI player.

        The seat keeps its current ownership of countries, capital, researcher, and stats
        — only the controller flips from human to AI. If it's their turn right now, the AI
        runner takes over for the rest of the turn before this method returns.
        """
        snapshot = self._load_snapshot(game_id)
        target = next(
            (p for p in snapshot.players.values() if p.user_id == user_id),
            None,
        )
        if target is None:
            raise NotInGame(f"user {user_id} is not in this game")
        if target.kind != "human":
            raise InvalidAction("only human players can abandon a game")
        if target.eliminated:
            raise InvalidAction("eliminated players cannot abandon (they're already out)")

        ai_seed = (snapshot.game.rng_seed ^ (target.seat_order + 1) * 2654435761) & 0x7FFFFFFF
        target.kind = "ai"
        target.ai_config = AIConfig(archetype=archetype, difficulty=difficulty, seed=ai_seed)
        # Keep `user_id` intact for audit; the AI runner only checks `kind`.
        rng = self._rng_for(snapshot)
        # If it's their turn right now, drain immediately.
        snapshot.game.updated_at = datetime.now(UTC)
        snapshot.game.rng_cursor = rng.cursor
        self._repo.save_snapshot(snapshot)
        self._append_event(
            game_id,
            "place_reinforcements",  # nearest existing event type for v1; future: dedicated `abandon`
            actor=target.player_id,
            payload={"abandoned_by": user_id, "archetype": archetype},
        )
        if (
            snapshot.game.status == "in_progress"
            and snapshot.game.turn.active_player_id == target.player_id
        ):
            self._pace_ai_turns(snapshot, rng)
        return snapshot

    def remove_seat(self, *, game_id: str, owner_user_id: str, target_player_id: str) -> Game:
        game = self._must_get_game(game_id)
        self._require_owner(game, owner_user_id)
        if game.status != "lobby":
            raise GameNotStartable("can only remove seats while in lobby")
        if target_player_id == game.player_ids[0]:
            raise InvalidAction("cannot remove the game owner")
        self._repo.delete_player(game_id, target_player_id)
        game.player_ids = [pid for pid in game.player_ids if pid != target_player_id]
        # Re-pack seat order so seats stay 0..n-1.
        for i, pid in enumerate(game.player_ids):
            p = self._repo.get_players(game_id)[pid]
            p.seat_order = i
            p.color = PLAYER_COLORS[i % len(PLAYER_COLORS)]
            self._repo.put_player(game_id, p)
        game.player_count = len(game.player_ids)
        game.updated_at = datetime.now(UTC)
        self._repo.put_game(game)
        return game

    def start_game(self, *, game_id: str, owner_user_id: str) -> GameSnapshot:
        """Generate the map (sized for player count) and run setup-phase init."""
        game = self._must_get_game(game_id)
        self._require_owner(game, owner_user_id)
        if game.status != "lobby":
            raise GameNotStartable(f"game already {game.status}")
        if game.player_count < game.min_players:
            raise GameNotStartable(
                f"need at least {game.min_players} players, have {game.player_count}"
            )

        # Generate map for the actual player count.
        params = MapGenParams.for_player_count(seed=game.rng_seed, player_count=game.player_count)
        m = generate_map(params)
        self._repo.put_map(m)
        game.map_id = m.map_id
        game.status = "placing_troops"
        game.setup = SetupState(phase="troops", active_seat_order=0)
        game.turn = TurnState()
        game.updated_at = datetime.now(UTC)
        self._repo.put_game(game)

        snapshot = self._load_snapshot(game_id)
        setup_engine.initialize_country_states(snapshot)
        # Seed troops_remaining_to_place per the config.
        for p in snapshot.players.values():
            p.troops_remaining_to_place = snapshot.game.config.starting_troops_per_player
        self._repo.save_snapshot(snapshot)
        self._append_event(
            game_id, "game_started", actor=owner_user_id, payload={"map_id": m.map_id}
        )
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
            setup_engine.place_troop(snapshot, actor.player_id, action)
            self._append_event(
                game_id,
                "place_troop",
                actor=actor.player_id,
                payload={"country_id": action.country_id},
            )
        elif snapshot.game.setup.phase == "researchers" and isinstance(action, PlaceResearcher):
            setup_engine.place_researcher(snapshot, actor.player_id, action)
            self._append_event(
                game_id,
                "place_researcher",
                actor=actor.player_id,
                payload={"country_id": action.country_id},
            )
        elif snapshot.game.setup.phase == "capitals" and isinstance(action, PlaceCapital):
            setup_engine.place_capital(snapshot, actor.player_id, action)
            self._append_event(
                game_id,
                "place_capital",
                actor=actor.player_id,
                payload={"country_id": action.country_id},
            )
        else:
            raise InvalidAction(
                f"action {type(action).__name__} not allowed in setup phase {snapshot.game.setup.phase}"
            )

        # Auto-progress through disease seeding (server-driven step) and the eventual
        # transition to in-progress.
        self._auto_progress_setup(snapshot, rng)
        # Save the human action snapshot before the AI begins so polling
        # clients can render the human placement immediately.
        snapshot.game.updated_at = datetime.now(UTC)
        snapshot.game.rng_cursor = rng.cursor
        self._repo.save_snapshot(snapshot)
        # Drain any AI seats that should be placing right now (paced by config).
        self._pace_ai_setup(snapshot, rng)
        # If setup just finished and the first turn-active player is AI, run them too.
        if snapshot.game.status == "in_progress":
            self._pace_ai_turns(snapshot, rng)
        snapshot.game.updated_at = datetime.now(UTC)
        snapshot.game.rng_cursor = rng.cursor
        self._repo.save_snapshot(snapshot)
        return snapshot

    def _drain_ai_setup(self, snapshot: GameSnapshot, rng: SeededRNG) -> None:
        """Sync drain (no pacing). Used by tests and the simulation harness."""
        # Bound to avoid runaway in pathological configs (e.g., all-AI).
        for _ in range(
            snapshot.game.player_count * snapshot.game.config.starting_troops_per_player + 50
        ):
            took_step = run_ai_setup_step(snapshot, rng)
            if not took_step:
                break
            self._auto_progress_setup(snapshot, rng)

    def _auto_progress_setup(self, snapshot: GameSnapshot, rng: SeededRNG) -> None:
        if snapshot.game.setup.phase == "disease_seed":
            seeded = setup_engine.seed_disease(snapshot, rng)
            self._append_event(snapshot.game.game_id, "seed_disease", payload={"countries": seeded})
            snapshot.game.status = "placing_researchers"
        elif snapshot.game.setup.phase == "researchers":
            snapshot.game.status = "placing_researchers"
        elif snapshot.game.setup.phase == "capitals":
            snapshot.game.status = "placing_capitals"
        elif snapshot.game.setup.phase == "done":
            turn_engine.begin_first_turn(snapshot)
            self._append_event(
                snapshot.game.game_id,
                "turn_started",
                actor=snapshot.game.turn.active_player_id,
                payload={"round": 1},
            )
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
        apply_in_game_action(snapshot, actor.player_id, action, rng)
        winner = check_win_condition(snapshot)
        if winner is not None and snapshot.game.status != "ended":
            snapshot.game.status = "ended"
            snapshot.game.ended_reason = "victory"
            snapshot.game.winner_player_id = winner
        self._append_event(
            game_id, cast("str", action.type), actor=actor.player_id, payload=action.model_dump()
        )
        # Save the human's action snapshot immediately so the client poll
        # picks it up before the bot turns start playing.
        snapshot.game.updated_at = datetime.now(UTC)
        snapshot.game.rng_cursor = rng.cursor
        self._repo.save_snapshot(snapshot)
        # If a human ended their turn or this action eliminated other players
        # and the next active seat is AI, drain those AI turns paced.
        if snapshot.game.status == "in_progress":
            self._pace_ai_turns(snapshot, rng)
        return snapshot

    def end_turn(
        self, *, game_id: str, actor_user_id: str
    ) -> tuple[GameSnapshot, VirusPhaseResult | None]:
        snapshot = self._load_snapshot(game_id)
        actor = self._resolve_player(snapshot, actor_user_id)
        rng = self._rng_for(snapshot)
        result = turn_engine.end_turn(snapshot, actor.player_id, rng)
        if result is not None:
            self._append_event(game_id, "round_end_virus", payload=result.model_dump())
        if snapshot.game.status == "ended":
            self._append_event(
                game_id,
                "game_ended",
                payload={
                    "reason": snapshot.game.ended_reason,
                    "winner": snapshot.game.winner_player_id,
                },
            )
        else:
            self._append_event(
                game_id,
                "turn_started",
                actor=snapshot.game.turn.active_player_id,
                payload={"round": snapshot.game.turn.round_number},
            )
        # Save the human-ended snapshot first so polling clients see the
        # turn boundary immediately.
        snapshot.game.updated_at = datetime.now(UTC)
        snapshot.game.rng_cursor = rng.cursor
        self._repo.save_snapshot(snapshot)
        # Drain AI seats following the now-ended human turn (paced).
        if snapshot.game.status == "in_progress":
            self._pace_ai_turns(snapshot, rng)
        return snapshot, result

    # --- AI pacing -----------------------------------------------------------
    #
    # The simulation harness drains AI turns synchronously (zero delay) — it
    # cares about throughput, not feel. Live games go through this helper so
    # each AI turn lands in its own snapshot save and the request thread
    # sleeps between turns. Polling clients see the bots "play" one turn at
    # a time; the human's perceived latency before they regain control is
    # `ai_count * ai_action_delay_ms`, which feels deliberate rather than
    # instant. ai_action_delay_ms == 0 retains the old test-fast behaviour.

    def _pace_ai_turns(self, snapshot: GameSnapshot, rng: SeededRNG) -> None:
        delay_s = max(0, snapshot.game.config.ai_action_delay_ms) / 1000.0
        guard = 0
        max_iters = 100
        while guard < max_iters:
            guard += 1
            if snapshot.game.status != "in_progress":
                return
            pid = snapshot.game.turn.active_player_id
            if pid is None:
                return
            if snapshot.players[pid].kind != "ai":
                return
            if delay_s > 0:
                time.sleep(delay_s)
            run_ai_turn(snapshot, rng)
            snapshot.game.updated_at = datetime.now(UTC)
            snapshot.game.rng_cursor = rng.cursor
            self._repo.save_snapshot(snapshot)

    def _pace_ai_setup(self, snapshot: GameSnapshot, rng: SeededRNG) -> None:
        delay_s = max(0, snapshot.game.config.ai_action_delay_ms) / 1000.0
        # Use a short fraction of the per-turn delay for setup placements —
        # placement is one tile per step and would feel sluggish at the full
        # delay across 30+ tiles.
        per_step_s = delay_s / 4
        max_iters = (
            snapshot.game.player_count * snapshot.game.config.starting_troops_per_player + 50
        )
        for _ in range(max_iters):
            took_step = run_ai_setup_step(snapshot, rng)
            if not took_step:
                return
            self._auto_progress_setup(snapshot, rng)
            snapshot.game.updated_at = datetime.now(UTC)
            snapshot.game.rng_cursor = rng.cursor
            self._repo.save_snapshot(snapshot)
            if per_step_s > 0:
                time.sleep(per_step_s)

    # --- helpers --------------------------------------------------------------

    def list_joinable_games(self) -> list[Game]:
        return [g for g in self._repo.list_games() if g.is_joinable and g.is_public]

    def list_games_for_user(self, user_id: str) -> list[Game]:
        """All games where `user_id` owns or plays. Useful for a 'My games' view."""
        out: list[Game] = []
        for g in self._repo.list_games():
            if g.owner_user_id == user_id:
                out.append(g)
                continue
            for p in self._repo.get_players(g.game_id).values():
                if p.user_id == user_id:
                    out.append(g)
                    break
        return out

    def _count_active_games_for_user(self, user_id: str) -> int:
        """Active = not 'ended'. Both ownership and seat membership count."""
        seen: set[str] = set()
        for g in self._repo.list_games():
            if g.status == "ended":
                continue
            if g.owner_user_id == user_id:
                seen.add(g.game_id)
                continue
            for p in self._repo.get_players(g.game_id).values():
                if p.user_id == user_id:
                    seen.add(g.game_id)
                    break
        return len(seen)

    def get_snapshot(self, game_id: str) -> GameSnapshot | None:
        snap = self._repo.load_snapshot(game_id)
        return snap

    def list_events(self, game_id: str) -> list[GameEvent]:
        return self._repo.list_events(game_id)

    def _add_human_player(self, game: Game, *, user_id: str, display_name: str) -> Player:
        seat = game.player_count
        player_id = f"p_{uuid.uuid4().hex[:8]}"
        player = Player(
            player_id=player_id,
            seat_order=seat,
            color=PLAYER_COLORS[seat % len(PLAYER_COLORS)],
            kind="human",
            user_id=user_id,
            troops_remaining_to_place=game.config.starting_troops_per_player,
        )
        self._repo.put_player(game.game_id, player)
        game.player_ids = [*game.player_ids, player_id]
        game.player_count = len(game.player_ids)
        game.updated_at = datetime.now(UTC)
        self._repo.put_game(game)
        return player

    def _must_get_game(self, game_id: str) -> Game:
        g = self._repo.get_game(game_id)
        if g is None:
            raise InvalidAction(f"unknown game {game_id}")
        return g

    def _require_owner(self, game: Game, user_id: str) -> None:
        if game.owner_user_id != user_id:
            raise RuleError("only the game owner can perform this action")

    def _resolve_player(self, snapshot: GameSnapshot, user_id: str) -> Player:
        for p in snapshot.players.values():
            if p.user_id == user_id:
                return p
        raise NotInGame(f"user {user_id} is not a player in this game")

    def _load_snapshot(self, game_id: str) -> GameSnapshot:
        snap = self._repo.load_snapshot(game_id)
        if snap is None:
            raise InvalidAction(f"snapshot for {game_id} not found")
        return snap

    def _rng_for(self, snapshot: GameSnapshot) -> SeededRNG:
        return SeededRNG(snapshot.game.rng_seed, cursor=snapshot.game.rng_cursor)

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
            event_id=f"e_{game_id}_{seq}",
            sequence=seq,
            type=cast("str", event_type),  # narrowed at type-check; runtime is permissive
            actor_player_id=actor,
            payload=payload or {},
            created_at=datetime.now(UTC),
        )
        self._repo.append_event(game_id, event)


__all__ = ["GameService"]
_ = Sequence
