"""Virus phase result types."""
from __future__ import annotations

from pydantic import Field

from .base import CamelModel


class CasualtyEvent(CamelModel):
    country_id: str
    cubes: int
    armies_before: int
    armies_lost: int


class CubePlacement(CamelModel):
    country_id: str
    triggered_outbreak: bool


class Outbreak(CamelModel):
    origin_country_id: str
    chained_country_ids: list[str]


class VirusPhaseResult(CamelModel):
    casualties: list[CasualtyEvent] = Field(default_factory=list)
    placements: list[CubePlacement] = Field(default_factory=list)
    outbreaks: list[Outbreak] = Field(default_factory=list)
    game_ended: bool = False
