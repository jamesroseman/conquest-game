"""Action intents. See CLAUDE.md § Player turn — N actions."""
from __future__ import annotations

from typing import Literal

from .base import CamelModel

ActionType = Literal[
    "place_troop",
    "place_researcher",
    "place_capital",
    "place_reinforcements",
    "move_researcher_adjacent",
    "airdrop_researcher",
    "cure",
    "create_vaccine",
    "attack",
    "move_troops",
]


class PlaceTroop(CamelModel):
    type: Literal["place_troop"] = "place_troop"
    country_id: str


class PlaceResearcher(CamelModel):
    type: Literal["place_researcher"] = "place_researcher"
    country_id: str


class PlaceCapital(CamelModel):
    type: Literal["place_capital"] = "place_capital"
    country_id: str


class PlaceReinforcements(CamelModel):
    type: Literal["place_reinforcements"] = "place_reinforcements"
    placements: list[tuple[str, int]]  # (country_id, count) pairs


class MoveResearcherAdjacent(CamelModel):
    type: Literal["move_researcher_adjacent"] = "move_researcher_adjacent"
    to_country_id: str


class AirdropResearcher(CamelModel):
    type: Literal["airdrop_researcher"] = "airdrop_researcher"
    to_country_id: str


class Cure(CamelModel):
    type: Literal["cure"] = "cure"


class CreateVaccine(CamelModel):
    type: Literal["create_vaccine"] = "create_vaccine"


class Attack(CamelModel):
    type: Literal["attack"] = "attack"
    from_country_id: str
    to_country_id: str
    armies: int


class MoveTroops(CamelModel):
    type: Literal["move_troops"] = "move_troops"
    from_country_id: str
    to_country_id: str
    armies: int


Action = (
    PlaceTroop
    | PlaceResearcher
    | PlaceCapital
    | PlaceReinforcements
    | MoveResearcherAdjacent
    | AirdropResearcher
    | Cure
    | CreateVaccine
    | Attack
    | MoveTroops
)
