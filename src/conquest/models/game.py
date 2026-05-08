"""Game root metadata. See CLAUDE.md § Firestore data model."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import Field

from .base import CamelModel
from .game_config import GameConfig

GameStatus = Literal[
    "lobby",
    "placing_troops",
    "seeding_disease",
    "placing_researchers",
    "placing_capitals",
    "in_progress",
    "ended",
]
SetupPhase = Literal["troops", "disease_seed", "researchers", "capitals", "done"]
TurnPhase = Literal["reinforcements", "actions", "virus"]


class SetupState(CamelModel):
    phase: SetupPhase = "troops"
    active_seat_order: int = 0


class TurnState(CamelModel):
    active_player_id: str | None = None
    actions_remaining: int = 0
    reinforcements_to_place: int = 0
    turn_number: int = 0
    round_number: int = 0
    phase: TurnPhase = "reinforcements"


class OutbreakHistoryEntry(CamelModel):
    round_number: int
    origin_country_id: str
    chained_country_ids: list[str]


class Outbreaks(CamelModel):
    count: int = 0
    history: list[OutbreakHistoryEntry] = Field(default_factory=list)


class Game(CamelModel):
    game_id: str
    map_id: str | None = None
    name: str
    config: GameConfig
    status: GameStatus = "lobby"
    created_at: datetime
    updated_at: datetime
    rng_seed: int
    rng_cursor: int = 0
    owner_user_id: str
    min_players: int = 2
    max_players: int = 6
    is_public: bool = False
    invite_code: str | None = None
    player_ids: list[str] = Field(default_factory=list)
    active_player_order: list[str] = Field(default_factory=list)
    player_count: int = 0
    setup: SetupState = Field(default_factory=SetupState)
    turn: TurnState = Field(default_factory=TurnState)
    outbreaks: Outbreaks = Field(default_factory=Outbreaks)
    winner_player_id: str | None = None
    ended_reason: Literal["outbreak_limit", "victory", None] = None

    @property
    def is_joinable(self) -> bool:
        """Game accepts new players iff it's still in the lobby with seats open."""
        return self.status == "lobby" and self.player_count < self.max_players
