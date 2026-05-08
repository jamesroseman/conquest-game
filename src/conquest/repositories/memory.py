"""In-memory repository. Single-process; not safe for production.

Mirrors the Firestore document model: top-level `users`, `maps`, `games`, plus per-game
`players`, `country_states`, and `events` collections. The Firestore implementation will
implement the same `Repository` protocol.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Protocol

from conquest.models.country_state import CountryState
from conquest.models.events import GameEvent
from conquest.models.game import Game
from conquest.models.map import Map
from conquest.models.player import Player
from conquest.models.snapshot import GameSnapshot
from conquest.models.user import User


class Repository(Protocol):
    # users
    def get_user(self, user_id: str) -> User | None: ...
    def get_user_by_email(self, email: str) -> User | None: ...
    def upsert_user(self, user: User) -> None: ...

    # maps
    def get_map(self, map_id: str) -> Map | None: ...
    def put_map(self, m: Map) -> None: ...

    # games
    def get_game(self, game_id: str) -> Game | None: ...
    def put_game(self, game: Game) -> None: ...
    def list_games(self) -> Iterable[Game]: ...
    def get_game_by_invite_code(self, code: str) -> Game | None: ...

    # players
    def get_players(self, game_id: str) -> dict[str, Player]: ...
    def put_player(self, game_id: str, player: Player) -> None: ...
    def delete_player(self, game_id: str, player_id: str) -> None: ...

    # country states
    def get_country_states(self, game_id: str) -> dict[str, CountryState]: ...
    def put_country_state(self, game_id: str, state: CountryState) -> None: ...
    def put_country_states(self, game_id: str, states: dict[str, CountryState]) -> None: ...

    # events
    def append_event(self, game_id: str, event: GameEvent) -> None: ...
    def list_events(self, game_id: str) -> list[GameEvent]: ...

    # composite
    def load_snapshot(self, game_id: str) -> GameSnapshot | None: ...
    def save_snapshot(self, snapshot: GameSnapshot) -> None: ...


class InMemoryRepository:
    def __init__(self) -> None:
        self._users: dict[str, User] = {}
        self._users_by_email: dict[str, str] = {}
        self._maps: dict[str, Map] = {}
        self._games: dict[str, Game] = {}
        self._players: dict[str, dict[str, Player]] = {}
        self._states: dict[str, dict[str, CountryState]] = {}
        self._events: dict[str, list[GameEvent]] = {}
        self._invite_index: dict[str, str] = {}

    # users -----------------------------------------------------------------
    def get_user(self, user_id: str) -> User | None:
        return self._users.get(user_id)

    def get_user_by_email(self, email: str) -> User | None:
        uid = self._users_by_email.get(email.lower())
        return self._users.get(uid) if uid else None

    def upsert_user(self, user: User) -> None:
        self._users[user.user_id] = user
        if user.email:
            self._users_by_email[user.email.lower()] = user.user_id

    # maps ------------------------------------------------------------------
    def get_map(self, map_id: str) -> Map | None:
        return self._maps.get(map_id)

    def put_map(self, m: Map) -> None:
        self._maps[m.map_id] = m

    # games -----------------------------------------------------------------
    def get_game(self, game_id: str) -> Game | None:
        return self._games.get(game_id)

    def put_game(self, game: Game) -> None:
        self._games[game.game_id] = game
        if game.invite_code:
            self._invite_index[game.invite_code] = game.game_id

    def list_games(self) -> Iterable[Game]:
        return list(self._games.values())

    def get_game_by_invite_code(self, code: str) -> Game | None:
        gid = self._invite_index.get(code)
        return self._games.get(gid) if gid else None

    # players ---------------------------------------------------------------
    def get_players(self, game_id: str) -> dict[str, Player]:
        return dict(self._players.get(game_id, {}))

    def put_player(self, game_id: str, player: Player) -> None:
        self._players.setdefault(game_id, {})[player.player_id] = player

    def delete_player(self, game_id: str, player_id: str) -> None:
        self._players.get(game_id, {}).pop(player_id, None)

    # country states --------------------------------------------------------
    def get_country_states(self, game_id: str) -> dict[str, CountryState]:
        return dict(self._states.get(game_id, {}))

    def put_country_state(self, game_id: str, state: CountryState) -> None:
        self._states.setdefault(game_id, {})[state.country_id] = state

    def put_country_states(self, game_id: str, states: dict[str, CountryState]) -> None:
        self._states[game_id] = dict(states)

    # events ----------------------------------------------------------------
    def append_event(self, game_id: str, event: GameEvent) -> None:
        self._events.setdefault(game_id, []).append(event)

    def list_events(self, game_id: str) -> list[GameEvent]:
        return list(self._events.get(game_id, []))

    # composite -------------------------------------------------------------
    def load_snapshot(self, game_id: str) -> GameSnapshot | None:
        game = self.get_game(game_id)
        if game is None or game.map_id is None:
            return None
        m = self.get_map(game.map_id)
        if m is None:
            return None
        players = self.get_players(game_id)
        states = self.get_country_states(game_id)
        return GameSnapshot(game=game, map=m, players=players, country_states=states)

    def save_snapshot(self, snapshot: GameSnapshot) -> None:
        self.put_game(snapshot.game)
        self.put_map(snapshot.map)
        gid = snapshot.game.game_id
        self._players[gid] = dict(snapshot.players)
        self._states[gid] = dict(snapshot.country_states)
