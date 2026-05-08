"""Per-game state attached to each country."""
from __future__ import annotations

from .base import CamelModel


class CountryState(CamelModel):
    country_id: str
    owner_player_id: str | None = None
    armies: int = 0
    disease_cubes: int = 0
    vaccinated: bool = False
    is_capital_of: str | None = None
    has_researcher: str | None = None
