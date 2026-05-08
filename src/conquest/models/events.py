"""Append-only event log."""
from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

EventType = Literal[
    "place_troop",
    "place_researcher",
    "place_capital",
    "seed_disease",
    "place_reinforcements",
    "move_researcher_adjacent",
    "airdrop_researcher",
    "cure",
    "create_vaccine",
    "attack",
    "move_troops",
    "round_end_virus",
    "outbreak",
    "player_eliminated",
    "capital_conquered",
    "game_started",
    "game_ended",
    "turn_started",
    "turn_ended",
]


class GameEvent(BaseModel):
    eventId: str
    sequence: int
    type: EventType
    actorPlayerId: str | None = None
    payload: dict[str, Any] = Field(default_factory=dict)
    createdAt: datetime
