"""Capital-conquest cascade."""
from __future__ import annotations

from datetime import datetime, timezone

from conquest.game.elimination import check_win_condition, eliminate_player
from conquest.models.country_state import CountryState
from conquest.models.game import Game
from conquest.models.game_config import GameConfig
from conquest.models.map import Continent, Country, Map, MapGenParams
from conquest.models.player import Player
from conquest.models.snapshot import GameSnapshot


def _three_player_snapshot() -> GameSnapshot:
    countries = {
        f"c{i}": Country(countryId=f"c{i}", name=f"C{i}", continentId="x",
                         tiles=[(i, 0)], centroid=(i, 0))
        for i in range(3)
    }
    cont = Continent(continentId="x", name="X", isIsland=False,
                     countryIds=list(countries.keys()), tileCount=3, bonusArmies=3)
    m = Map(mapId="m", params=MapGenParams(seed=1), width=3, height=1, tiles=[],
            countries=countries, continents={"x": cont}, paths={})
    now = datetime.now(timezone.utc)
    game = Game(gameId="g", mapId="m", name="t", config=GameConfig(),
                createdAt=now, updatedAt=now, rngSeed=1, ownerUserId="u1")
    players = {
        f"p{i}": Player(playerId=f"p{i}", seatOrder=i, color="#000", kind="human", userId=f"u{i}",
                        capitalCountryId=f"c{i}", researcherCountryId=f"c{i}")
        for i in range(3)
    }
    states = {
        f"c{i}": CountryState(countryId=f"c{i}", ownerPlayerId=f"p{i}", armies=5,
                              isCapitalOf=f"p{i}", hasResearcher=f"p{i}")
        for i in range(3)
    }
    return GameSnapshot(game=game, map=m, players=players, countryStates=states)


def test_eliminate_transfers_countries_and_clears_researcher() -> None:
    snap = _three_player_snapshot()
    eliminate_player(snap, eliminated_id="p1", conqueror_id="p0", round_number=2)
    assert snap.players["p1"].eliminated
    # All p1 countries now owned by p0.
    assert all(
        s.ownerPlayerId == "p0" for s in snap.countryStates.values() if s.countryId == "c1"
    )
    assert snap.countryStates["c1"].isCapitalOf is None
    assert snap.countryStates["c1"].hasResearcher is None
    assert snap.players["p1"].researcherCountryId is None
    assert snap.players["p1"].capitalCountryId is None
    # p0 retains its capital.
    assert snap.countryStates["c0"].isCapitalOf == "p0"


def test_win_condition_last_competitor() -> None:
    snap = _three_player_snapshot()
    eliminate_player(snap, eliminated_id="p1", conqueror_id="p0", round_number=1)
    assert check_win_condition(snap) is None
    eliminate_player(snap, eliminated_id="p2", conqueror_id="p0", round_number=1)
    assert check_win_condition(snap) == "p0"
