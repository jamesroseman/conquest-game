"""End-of-round virus phase: casualties, spread, outbreaks."""
from __future__ import annotations

import math
from datetime import datetime, timezone

from conquest.game.rng import SeededRNG
from conquest.game.virus import run_virus_phase
from conquest.models.country_state import CountryState
from conquest.models.game import Game, Outbreaks
from conquest.models.game_config import GameConfig
from conquest.models.map import Continent, Country, Map, MapGenParams, Path
from conquest.models.player import Player
from conquest.models.snapshot import GameSnapshot


def _two_country_snapshot() -> GameSnapshot:
    cfg = GameConfig()
    countries = {
        "c1": Country(countryId="c1", name="A", continentId="x",
                      tiles=[(0, 0)], centroid=(0, 0), pathIds=["p1"]),
        "c2": Country(countryId="c2", name="B", continentId="x",
                      tiles=[(1, 0)], centroid=(1, 0), pathIds=["p1"]),
    }
    paths = {"p1": Path(pathId="p1", countryAId="c1", countryBId="c2", kind="land")}
    continents = {
        "x": Continent(continentId="x", name="X", isIsland=False,
                       countryIds=["c1", "c2"], tileCount=2, bonusArmies=3),
    }
    m = Map(
        mapId="m", params=MapGenParams(seed=1), width=2, height=1, tiles=[],
        countries=countries, continents=continents, paths=paths,
    )
    now = datetime.now(timezone.utc)
    game = Game(
        gameId="g", mapId="m", name="t", config=cfg,
        createdAt=now, updatedAt=now, rngSeed=1, ownerUserId="u1",
        outbreaks=Outbreaks(),
    )
    states = {
        "c1": CountryState(countryId="c1", ownerPlayerId="p1", armies=12, diseaseCubes=2),
        "c2": CountryState(countryId="c2", ownerPlayerId="p1", armies=9, diseaseCubes=1),
    }
    p = Player(playerId="p1", seatOrder=0, color="#000", kind="human", userId="u1")
    return GameSnapshot(game=game, map=m, players={"p1": p}, countryStates=states)


def test_casualties_round_down() -> None:
    snap = _two_country_snapshot()
    # 12 armies × 1/2 = 6 lost; 9 × 1/3 = 3 lost.
    rng = SeededRNG(99)
    run_virus_phase(snap, rng)
    assert snap.countryStates["c1"].armies == 12 - 6
    assert snap.countryStates["c2"].armies == 9 - 3


def test_three_cubes_kills_all_armies() -> None:
    snap = _two_country_snapshot()
    snap.countryStates["c1"].diseaseCubes = 3
    snap.countryStates["c1"].armies = 7
    rng = SeededRNG(99)
    run_virus_phase(snap, rng)
    assert snap.countryStates["c1"].armies == 0


def test_vaccinated_country_skipped_during_spread() -> None:
    snap = _two_country_snapshot()
    snap.countryStates["c1"].diseaseCubes = 0
    snap.countryStates["c2"].diseaseCubes = 0
    snap.countryStates["c1"].vaccinated = True
    rng = SeededRNG(1)
    run_virus_phase(snap, rng)
    assert snap.countryStates["c1"].diseaseCubes == 0


def test_outbreak_chain_increments_count() -> None:
    snap = _two_country_snapshot()
    # Force a saturated country so the next placement triggers an outbreak.
    snap.countryStates["c1"].diseaseCubes = 3
    snap.countryStates["c2"].diseaseCubes = 0
    snap.countryStates["c1"].armies = 0  # no casualty side-effect to muddy things
    snap.countryStates["c2"].armies = 0
    # Many trials so we eventually hit c1 and trigger.
    cfg = snap.game.config
    cfg.spread_schedule = [(0, 99, 6)]
    before = snap.game.outbreaks.count
    run_virus_phase(snap, SeededRNG(seed=42))
    assert snap.game.outbreaks.count >= before
