"""Capital-conquest cascade."""

from __future__ import annotations

from datetime import UTC, datetime

from conquest.game.elimination import check_win_condition, eliminate_player
from conquest.models.country_state import CountryState
from conquest.models.game import Game
from conquest.models.game_config import GameConfig
from conquest.models.map import Continent, Country, Map, MapGenParams
from conquest.models.player import Player
from conquest.models.snapshot import GameSnapshot


def _three_player_snapshot() -> GameSnapshot:
    countries = {
        f"c{i}": Country(
            country_id=f"c{i}", name=f"C{i}", continent_id="x", tiles=[(i, 0)], centroid=(i, 0)
        )
        for i in range(3)
    }
    cont = Continent(
        continent_id="x",
        name="X",
        is_island=False,
        country_ids=list(countries.keys()),
        tile_count=3,
        bonus_armies=3,
    )
    m = Map(
        map_id="m",
        params=MapGenParams(seed=1),
        width=3,
        height=1,
        tiles=[],
        countries=countries,
        continents={"x": cont},
        paths={},
    )
    now = datetime.now(UTC)
    game = Game(
        game_id="g",
        map_id="m",
        name="t",
        config=GameConfig(),
        created_at=now,
        updated_at=now,
        rng_seed=1,
        owner_user_id="u1",
    )
    players = {
        f"p{i}": Player(
            player_id=f"p{i}",
            seat_order=i,
            color="#000",
            kind="human",
            user_id=f"u{i}",
            capital_country_id=f"c{i}",
            researcher_country_id=f"c{i}",
        )
        for i in range(3)
    }
    states = {
        f"c{i}": CountryState(
            country_id=f"c{i}",
            owner_player_id=f"p{i}",
            armies=5,
            is_capital_of=f"p{i}",
            has_researcher=f"p{i}",
        )
        for i in range(3)
    }
    return GameSnapshot(game=game, map=m, players=players, country_states=states)


def test_eliminate_transfers_countries_and_clears_researcher() -> None:
    snap = _three_player_snapshot()
    eliminate_player(snap, eliminated_id="p1", conqueror_id="p0", round_number=2)
    assert snap.players["p1"].eliminated
    # All p1 countries now owned by p0.
    assert all(
        s.owner_player_id == "p0" for s in snap.country_states.values() if s.country_id == "c1"
    )
    assert snap.country_states["c1"].is_capital_of is None
    assert snap.country_states["c1"].has_researcher is None
    assert snap.players["p1"].researcher_country_id is None
    assert snap.players["p1"].capital_country_id is None
    # p0 retains its capital.
    assert snap.country_states["c0"].is_capital_of == "p0"


def test_win_condition_last_competitor() -> None:
    snap = _three_player_snapshot()
    eliminate_player(snap, eliminated_id="p1", conqueror_id="p0", round_number=1)
    assert check_win_condition(snap) is None
    eliminate_player(snap, eliminated_id="p2", conqueror_id="p0", round_number=1)
    assert check_win_condition(snap) == "p0"
