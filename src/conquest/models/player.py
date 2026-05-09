"""Player — per-game participant. See CLAUDE.md § User vs Player."""

from __future__ import annotations

from typing import Literal

from pydantic import Field

from .base import CamelModel

ArchetypeId = Literal[
    "aggressor",
    "turtle",
    "medic",
    "opportunist",
    "expansionist",
    "consolidator",
    "saboteur",
    "kingmaker",
    "doomsayer",
    "isolationist",
    "bandwagon",
    "chaos",
]
Difficulty = Literal["easy", "medium", "hard", "brutal"]


class AIConfig(CamelModel):
    archetype: ArchetypeId
    difficulty: Difficulty = "medium"
    seed: int


class PlayerStats(CamelModel):
    countries_owned: int = 0
    total_armies: int = 0
    # Cumulative disease cubes this player has personally cured this game.
    # Surfaces in the Game Overview panel so players can see who's actually
    # dragging the outbreak counter down vs free-riding.
    cubes_cured: int = 0


class Player(CamelModel):
    player_id: str
    seat_order: int
    color: str
    kind: Literal["human", "ai"]
    user_id: str | None = None
    ai_config: AIConfig | None = None
    troops_remaining_to_place: int = 0
    researcher_country_id: str | None = None
    capital_country_id: str | None = None
    eliminated: bool = False
    eliminated_by_player_id: str | None = None
    eliminated_at_round: int | None = None
    stats: PlayerStats = Field(default_factory=PlayerStats)
