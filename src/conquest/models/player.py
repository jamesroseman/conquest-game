"""Player — per-game participant. See CLAUDE.md § User vs Player."""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

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


class AIConfig(BaseModel):
    archetype: ArchetypeId
    difficulty: Difficulty = "medium"
    seed: int


class PlayerStats(BaseModel):
    countriesOwned: int = 0
    totalArmies: int = 0


class Player(BaseModel):
    playerId: str
    seatOrder: int
    color: str
    kind: Literal["human", "ai"]
    userId: str | None = None
    aiConfig: AIConfig | None = None
    troopsRemainingToPlace: int = 0
    researcherCountryId: str | None = None
    capitalCountryId: str | None = None
    eliminated: bool = False
    eliminatedByPlayerId: str | None = None
    eliminatedAtRound: int | None = None
    stats: PlayerStats = Field(default_factory=PlayerStats)
