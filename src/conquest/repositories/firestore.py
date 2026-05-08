"""Firestore-backed repository.

Mirrors the document layout from CLAUDE.md § Firestore data model:

    users/{user_id}                         (camelCase fields on the wire)
    maps/{map_id}
    games/{game_id}
    games/{game_id}/players/{player_id}
    games/{game_id}/countryStates/{country_id}
    games/{game_id}/events/{event_id}

Pydantic CamelModel handles the snake_case ↔ camelCase translation automatically: we write
`model.model_dump(by_alias=True)` and read with `Model.model_validate(doc.to_dict())`.

Snapshot loads use a single transaction; snapshot saves diff and write only changed
sub-collection docs (v0.1: writes everything for simplicity — Firestore handles 500 writes
per transaction and a 6-player game stays well under that). The `google-cloud-firestore`
package is an optional dependency: importing this module at module top would force every
test environment to install it, so we lazy-import inside `__init__`.
"""
from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from conquest.models.country_state import CountryState
from conquest.models.events import GameEvent
from conquest.models.game import Game
from conquest.models.map import Map
from conquest.models.player import Player
from conquest.models.snapshot import GameSnapshot
from conquest.models.user import User


class FirestoreRepository:
    """Firestore-backed implementation of the `Repository` protocol.

    Construct with `client` (a `google.cloud.firestore.Client`) — typically:

        from google.cloud import firestore
        repo = FirestoreRepository(firestore.Client())

    Pointing at the local emulator:

        export FIRESTORE_EMULATOR_HOST=localhost:8080
    """

    def __init__(self, client: Any) -> None:  # google.cloud.firestore.Client
        self._db = client

    # --- helpers -----------------------------------------------------------

    @staticmethod
    def _dump(model: Any) -> dict[str, Any]:
        """Pydantic v2 serialization with camelCase aliases — matches the JSON wire format."""
        return model.model_dump(by_alias=True, mode="json")

    @staticmethod
    def _load(model_cls: type, data: dict[str, Any]) -> Any:
        return model_cls.model_validate(data)

    def _users(self) -> Any:
        return self._db.collection("users")

    def _maps(self) -> Any:
        return self._db.collection("maps")

    def _games(self) -> Any:
        return self._db.collection("games")

    def _game_doc(self, game_id: str) -> Any:
        return self._games().document(game_id)

    # --- users -------------------------------------------------------------

    def get_user(self, user_id: str) -> User | None:
        snap = self._users().document(user_id).get()
        if not snap.exists:
            return None
        return self._load(User, snap.to_dict())

    def get_user_by_email(self, email: str) -> User | None:
        q = self._users().where("email", "==", email.lower()).limit(1).stream()
        for doc in q:
            return self._load(User, doc.to_dict())
        return None

    def upsert_user(self, user: User) -> None:
        self._users().document(user.user_id).set(self._dump(user))

    # --- maps --------------------------------------------------------------

    def get_map(self, map_id: str) -> Map | None:
        snap = self._maps().document(map_id).get()
        if not snap.exists:
            return None
        return self._load(Map, snap.to_dict())

    def put_map(self, m: Map) -> None:
        # Maps are content-addressed and immutable; idempotent set.
        self._maps().document(m.map_id).set(self._dump(m))

    # --- games -------------------------------------------------------------

    def get_game(self, game_id: str) -> Game | None:
        snap = self._game_doc(game_id).get()
        if not snap.exists:
            return None
        return self._load(Game, snap.to_dict())

    def put_game(self, game: Game) -> None:
        self._game_doc(game.game_id).set(self._dump(game))

    def list_games(self) -> Iterable[Game]:
        for doc in self._games().stream():
            yield self._load(Game, doc.to_dict())

    def get_game_by_invite_code(self, code: str) -> Game | None:
        q = self._games().where("inviteCode", "==", code).limit(1).stream()
        for doc in q:
            return self._load(Game, doc.to_dict())
        return None

    # --- players -----------------------------------------------------------

    def get_players(self, game_id: str) -> dict[str, Player]:
        out: dict[str, Player] = {}
        for doc in self._game_doc(game_id).collection("players").stream():
            p = self._load(Player, doc.to_dict())
            out[p.player_id] = p
        return out

    def put_player(self, game_id: str, player: Player) -> None:
        self._game_doc(game_id).collection("players").document(player.player_id).set(
            self._dump(player)
        )

    def delete_player(self, game_id: str, player_id: str) -> None:
        self._game_doc(game_id).collection("players").document(player_id).delete()

    # --- country states ----------------------------------------------------

    def get_country_states(self, game_id: str) -> dict[str, CountryState]:
        out: dict[str, CountryState] = {}
        for doc in self._game_doc(game_id).collection("countryStates").stream():
            s = self._load(CountryState, doc.to_dict())
            out[s.country_id] = s
        return out

    def put_country_state(self, game_id: str, state: CountryState) -> None:
        self._game_doc(game_id).collection("countryStates").document(state.country_id).set(
            self._dump(state)
        )

    def put_country_states(
        self, game_id: str, states: dict[str, CountryState]
    ) -> None:
        # Batched write — Firestore allows up to 500 ops per batch; map sizes are well below.
        batch = self._db.batch()
        col = self._game_doc(game_id).collection("countryStates")
        for state in states.values():
            batch.set(col.document(state.country_id), self._dump(state))
        batch.commit()

    # --- events ------------------------------------------------------------

    def append_event(self, game_id: str, event: GameEvent) -> None:
        self._game_doc(game_id).collection("events").document(event.event_id).set(
            self._dump(event)
        )

    def list_events(self, game_id: str) -> list[GameEvent]:
        col = self._game_doc(game_id).collection("events")
        return [
            self._load(GameEvent, doc.to_dict())
            for doc in col.order_by("sequence").stream()
        ]

    # --- composite ---------------------------------------------------------

    def load_snapshot(self, game_id: str) -> GameSnapshot | None:
        # Single read fan-out. v0.1: not transactional. The service layer reads, applies pure
        # rules, and writes back — Firestore transactions can be added once we want strict
        # multi-actor concurrent-write safety (next milestone).
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
        # Batched write across game root + players + country states.
        batch = self._db.batch()
        batch.set(self._game_doc(snapshot.game.game_id), self._dump(snapshot.game))
        batch.set(self._maps().document(snapshot.map.map_id), self._dump(snapshot.map))
        gid = snapshot.game.game_id
        players_col = self._game_doc(gid).collection("players")
        for p in snapshot.players.values():
            batch.set(players_col.document(p.player_id), self._dump(p))
        states_col = self._game_doc(gid).collection("countryStates")
        for s in snapshot.country_states.values():
            batch.set(states_col.document(s.country_id), self._dump(s))
        batch.commit()
