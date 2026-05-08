"""Reinforcement formula. See CLAUDE.md § Reinforcements."""
from __future__ import annotations

from datetime import datetime, timezone

from conquest.game.reinforcements import compute_reinforcements
from conquest.models.country_state import CountryState
from conquest.models.game import Game
from conquest.models.game_config import GameConfig
from conquest.models.map import Continent, Country, Map, MapGenParams
from conquest.models.player import Player
from conquest.models.snapshot import GameSnapshot


def _toy_snapshot() -> GameSnapshot:
    cfg = GameConfig()
    countries = {
        "c1": Country(countryId="c1", name="A", continentId="cont1", tiles=[(0, 0)], centroid=(0, 0)),
        "c2": Country(countryId="c2", name="B", continentId="cont1", tiles=[(0, 1)], centroid=(0, 1)),
        "c3": Country(countryId="c3", name="C", continentId="cont2", tiles=[(0, 2)], centroid=(0, 2)),
    }
    continents = {
        "cont1": Continent(continentId="cont1", name="X", isIsland=False,
                           countryIds=["c1", "c2"], tileCount=2, bonusArmies=3),
        "cont2": Continent(continentId="cont2", name="Y", isIsland=True,
                           countryIds=["c3"], tileCount=1, bonusArmies=2),
    }
    m = Map(
        mapId="m1",
        params=MapGenParams(seed=1),
        width=1, height=3,
        tiles=[],
        countries=countries,
        continents=continents,
        paths={},
    )
    now = datetime.now(timezone.utc)
    game = Game(
        gameId="g1", mapId="m1", name="Test", config=cfg,
        createdAt=now, updatedAt=now, rngSeed=1, ownerUserId="u1",
    )
    p = Player(playerId="p1", seatOrder=0, color="#000", kind="human", userId="u1")
    states = {
        "c1": CountryState(countryId="c1", ownerPlayerId="p1", armies=3),
        "c2": CountryState(countryId="c2", ownerPlayerId="p1", armies=4),
        "c3": CountryState(countryId="c3", ownerPlayerId=None, armies=0),
    }
    return GameSnapshot(game=game, map=m, players={"p1": p}, countryStates=states)


def test_base_plus_per_country_plus_owned_continent() -> None:
    snap = _toy_snapshot()
    # 10 base + 1*2 owned + 3 (full ownership of cont1) = 15
    assert compute_reinforcements(snap, "p1") == 15


def test_no_continent_bonus_when_partial() -> None:
    snap = _toy_snapshot()
    snap.countryStates["c2"].ownerPlayerId = None
    # 10 base + 1*1 owned + 0 = 11
    assert compute_reinforcements(snap, "p1") == 11
