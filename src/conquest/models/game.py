"""Game root metadata. See CLAUDE.md § Firestore data model."""
from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

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


class SetupState(BaseModel):
    phase: SetupPhase = "troops"
    activeSeatOrder: int = 0


class TurnState(BaseModel):
    activePlayerId: str | None = None
    actionsRemaining: int = 0
    reinforcementsToPlace: int = 0
    turnNumber: int = 0
    roundNumber: int = 0
    phase: TurnPhase = "reinforcements"


class OutbreakHistoryEntry(BaseModel):
    roundNumber: int
    originCountryId: str
    chainedCountryIds: list[str]


class Outbreaks(BaseModel):
    count: int = 0
    history: list[OutbreakHistoryEntry] = Field(default_factory=list)


class Game(BaseModel):
    gameId: str
    mapId: str | None = None  # not generated until startGame; map size depends on player count
    name: str
    config: GameConfig
    status: GameStatus = "lobby"
    createdAt: datetime
    updatedAt: datetime
    rngSeed: int
    rngCursor: int = 0
    ownerUserId: str
    minPlayers: int = 2
    maxPlayers: int = 6
    isPublic: bool = False
    inviteCode: str | None = None
    playerIds: list[str] = Field(default_factory=list)
    activePlayerOrder: list[str] = Field(default_factory=list)
    playerCount: int = 0
    setup: SetupState = Field(default_factory=SetupState)
    turn: TurnState = Field(default_factory=TurnState)
    outbreaks: Outbreaks = Field(default_factory=Outbreaks)
    winnerPlayerId: str | None = None
    endedReason: Literal["outbreak_limit", "victory", None] = None

    @property
    def is_joinable(self) -> bool:
        """Game accepts new players iff it's still in the lobby with seats open."""
        return self.status == "lobby" and self.playerCount < self.maxPlayers
