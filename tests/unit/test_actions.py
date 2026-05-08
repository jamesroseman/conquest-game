"""In-game action validation + dispatch."""
from __future__ import annotations

from datetime import datetime, timezone

import pytest

from conquest.game.actions import apply_action
from conquest.game.errors import (
    NotAllResearchersPresent,
    NotEnoughActions,
    NotYourCountry,
    NotYourTurn,
    ReinforcementsNotPlaced,
)
from conquest.game.rng import SeededRNG
from conquest.models.action import (
    Cure,
    MoveTroops,
    PlaceReinforcements,
)
from conquest.models.country_state import CountryState
from conquest.models.game import Game, TurnState
from conquest.models.game_config import GameConfig
from conquest.models.map import Continent, Country, Map, MapGenParams, Path
from conquest.models.player import Player
from conquest.models.snapshot import GameSnapshot


def _two_country_in_progress() -> GameSnapshot:
    cfg = GameConfig()
    countries = {
        "c1": Country(countryId="c1", name="A", continentId="x",
                      tiles=[(0, 0)], centroid=(0, 0), pathIds=["p1"]),
        "c2": Country(countryId="c2", name="B", continentId="x",
                      tiles=[(1, 0)], centroid=(1, 0), pathIds=["p1"]),
    }
    paths = {"p1": Path(pathId="p1", countryAId="c1", countryBId="c2", kind="land")}
    cont = Continent(continentId="x", name="X", isIsland=False,
                     countryIds=["c1", "c2"], tileCount=2, bonusArmies=3)
    m = Map(mapId="m", params=MapGenParams(seed=1), width=2, height=1, tiles=[],
            countries=countries, continents={"x": cont}, paths=paths)
    now = datetime.now(timezone.utc)
    game = Game(
        gameId="g", mapId="m", name="t", config=cfg,
        createdAt=now, updatedAt=now, rngSeed=1, ownerUserId="u1",
        status="in_progress",
        turn=TurnState(
            activePlayerId="p1",
            actionsRemaining=cfg.actions_per_turn,
            reinforcementsToPlace=0,
            turnNumber=1,
            roundNumber=1,
            phase="actions",
        ),
    )
    p1 = Player(playerId="p1", seatOrder=0, color="#000", kind="human", userId="u1",
                researcherCountryId="c1", capitalCountryId="c1")
    p2 = Player(playerId="p2", seatOrder=1, color="#fff", kind="human", userId="u2",
                researcherCountryId="c2", capitalCountryId="c2")
    states = {
        "c1": CountryState(countryId="c1", ownerPlayerId="p1", armies=5,
                           hasResearcher="p1", isCapitalOf="p1", diseaseCubes=2),
        "c2": CountryState(countryId="c2", ownerPlayerId="p2", armies=3,
                           hasResearcher="p2", isCapitalOf="p2"),
    }
    return GameSnapshot(game=game, map=m, players={"p1": p1, "p2": p2}, countryStates=states)


def test_not_your_turn() -> None:
    snap = _two_country_in_progress()
    with pytest.raises(NotYourTurn):
        apply_action(snap, "p2", Cure(), SeededRNG(1))


def test_cure_clears_cubes_and_costs_one_action() -> None:
    snap = _two_country_in_progress()
    apply_action(snap, "p1", Cure(), SeededRNG(1))
    assert snap.countryStates["c1"].diseaseCubes == 0
    assert snap.game.turn.actionsRemaining == snap.game.config.actions_per_turn - 1


def test_move_troops_requires_owned_endpoints() -> None:
    snap = _two_country_in_progress()
    with pytest.raises(NotYourCountry):
        apply_action(
            snap, "p1",
            MoveTroops(fromCountryId="c1", toCountryId="c2", armies=1),
            SeededRNG(1),
        )


def test_vaccine_requires_all_researchers_present() -> None:
    from conquest.models.action import CreateVaccine
    snap = _two_country_in_progress()
    with pytest.raises(NotAllResearchersPresent):
        apply_action(snap, "p1", CreateVaccine(), SeededRNG(1))


def test_reinforcements_must_be_placed_first() -> None:
    snap = _two_country_in_progress()
    snap.game.turn.phase = "reinforcements"
    snap.game.turn.reinforcementsToPlace = 3
    with pytest.raises(ReinforcementsNotPlaced):
        apply_action(snap, "p1", Cure(), SeededRNG(1))


def test_place_reinforcements_consumes_pool() -> None:
    snap = _two_country_in_progress()
    snap.game.turn.phase = "reinforcements"
    snap.game.turn.reinforcementsToPlace = 4
    apply_action(
        snap, "p1",
        PlaceReinforcements(placements=[("c1", 4)]),
        SeededRNG(1),
    )
    assert snap.game.turn.reinforcementsToPlace == 0
    assert snap.game.turn.phase == "actions"
    assert snap.countryStates["c1"].armies == 9


def test_attack_costs_action_and_runs() -> None:
    from conquest.models.action import Attack
    snap = _two_country_in_progress()
    snap.countryStates["c1"].armies = 10
    apply_action(snap, "p1", Attack(fromCountryId="c1", toCountryId="c2", armies=5),
                 SeededRNG(123))
    assert snap.game.turn.actionsRemaining == snap.game.config.actions_per_turn - 1


def test_actions_run_out() -> None:
    snap = _two_country_in_progress()
    snap.game.turn.actionsRemaining = 0
    with pytest.raises(NotEnoughActions):
        apply_action(snap, "p1", Cure(), SeededRNG(1))
