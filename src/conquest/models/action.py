"""Action intents. See CLAUDE.md § Player turn — N actions."""
from __future__ import annotations

from typing import Literal, Union

from pydantic import BaseModel

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


class PlaceTroop(BaseModel):
    type: Literal["place_troop"] = "place_troop"
    countryId: str


class PlaceResearcher(BaseModel):
    type: Literal["place_researcher"] = "place_researcher"
    countryId: str


class PlaceCapital(BaseModel):
    type: Literal["place_capital"] = "place_capital"
    countryId: str


class PlaceReinforcements(BaseModel):
    type: Literal["place_reinforcements"] = "place_reinforcements"
    placements: list[tuple[str, int]]  # (countryId, count) pairs


class MoveResearcherAdjacent(BaseModel):
    type: Literal["move_researcher_adjacent"] = "move_researcher_adjacent"
    toCountryId: str


class AirdropResearcher(BaseModel):
    type: Literal["airdrop_researcher"] = "airdrop_researcher"
    toCountryId: str


class Cure(BaseModel):
    type: Literal["cure"] = "cure"


class CreateVaccine(BaseModel):
    type: Literal["create_vaccine"] = "create_vaccine"


class Attack(BaseModel):
    type: Literal["attack"] = "attack"
    fromCountryId: str
    toCountryId: str
    armies: int


class MoveTroops(BaseModel):
    type: Literal["move_troops"] = "move_troops"
    fromCountryId: str
    toCountryId: str
    armies: int


Action = Union[
    PlaceTroop,
    PlaceResearcher,
    PlaceCapital,
    PlaceReinforcements,
    MoveResearcherAdjacent,
    AirdropResearcher,
    Cure,
    CreateVaccine,
    Attack,
    MoveTroops,
]
