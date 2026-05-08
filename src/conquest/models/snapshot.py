"""GameSnapshot — composed read of game + players + countryStates + map.

The pure rules engine operates on snapshots, never on Firestore directly.
"""
from __future__ import annotations

from pydantic import BaseModel, Field

from .country_state import CountryState
from .game import Game
from .map import Map
from .player import Player


class GameSnapshot(BaseModel):
    game: Game
    map: Map
    players: dict[str, Player]
    countryStates: dict[str, CountryState] = Field(default_factory=dict)

    def player_by_seat(self, seat: int) -> Player:
        for p in self.players.values():
            if p.seatOrder == seat:
                return p
        raise KeyError(f"no player at seat {seat}")

    def active_player(self) -> Player | None:
        if self.game.turn.activePlayerId is None:
            return None
        return self.players.get(self.game.turn.activePlayerId)

    def non_eliminated_players(self) -> list[Player]:
        return sorted(
            (p for p in self.players.values() if not p.eliminated),
            key=lambda p: p.seatOrder,
        )

    def countries_owned_by(self, player_id: str) -> list[str]:
        return [
            c.countryId
            for c in self.countryStates.values()
            if c.ownerPlayerId == player_id
        ]
