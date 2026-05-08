"""GameSnapshot — composed read of game + players + countryStates + map.

The pure rules engine operates on snapshots, never on Firestore directly.
"""
from __future__ import annotations

from pydantic import Field

from .base import CamelModel
from .country_state import CountryState
from .game import Game
from .map import Map
from .player import Player


class GameSnapshot(CamelModel):
    game: Game
    map: Map
    players: dict[str, Player]
    country_states: dict[str, CountryState] = Field(default_factory=dict)

    def player_by_seat(self, seat: int) -> Player:
        for p in self.players.values():
            if p.seat_order == seat:
                return p
        raise KeyError(f"no player at seat {seat}")

    def active_player(self) -> Player | None:
        if self.game.turn.active_player_id is None:
            return None
        return self.players.get(self.game.turn.active_player_id)

    def non_eliminated_players(self) -> list[Player]:
        return sorted(
            (p for p in self.players.values() if not p.eliminated),
            key=lambda p: p.seat_order,
        )

    def countries_owned_by(self, player_id: str) -> list[str]:
        return [
            c.country_id
            for c in self.country_states.values()
            if c.owner_player_id == player_id
        ]
