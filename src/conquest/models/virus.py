"""Virus phase result types."""
from __future__ import annotations

from pydantic import BaseModel, Field


class CasualtyEvent(BaseModel):
    countryId: str
    cubes: int
    armiesBefore: int
    armiesLost: int


class CubePlacement(BaseModel):
    countryId: str
    triggeredOutbreak: bool


class Outbreak(BaseModel):
    originCountryId: str
    chainedCountryIds: list[str]


class VirusPhaseResult(BaseModel):
    casualties: list[CasualtyEvent] = Field(default_factory=list)
    placements: list[CubePlacement] = Field(default_factory=list)
    outbreaks: list[Outbreak] = Field(default_factory=list)
    gameEnded: bool = False
