"""Per-game state attached to each country."""
from __future__ import annotations

from pydantic import BaseModel


class CountryState(BaseModel):
    countryId: str
    ownerPlayerId: str | None = None
    armies: int = 0
    diseaseCubes: int = 0
    vaccinated: bool = False
    isCapitalOf: str | None = None
    hasResearcher: str | None = None
