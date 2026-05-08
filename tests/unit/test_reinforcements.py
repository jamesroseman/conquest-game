"""Reinforcement formula. See CLAUDE.md § Reinforcements."""
from __future__ import annotations

from datetime import UTC, datetime

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
        "c1": Country(country_id="c1", name="A", continent_id="cont1", tiles=[(0, 0)], centroid=(0, 0)),
        "c2": Country(country_id="c2", name="B", continent_id="cont1", tiles=[(0, 1)], centroid=(0, 1)),
        "c3": Country(country_id="c3", name="C", continent_id="cont2", tiles=[(0, 2)], centroid=(0, 2)),
    }
    continents = {
        "cont1": Continent(continent_id="cont1", name="X", is_island=False,
                           country_ids=["c1", "c2"], tile_count=2, bonus_armies=3),
        "cont2": Continent(continent_id="cont2", name="Y", is_island=True,
                           country_ids=["c3"], tile_count=1, bonus_armies=2),
    }
    m = Map(
        map_id="m1",
        params=MapGenParams(seed=1),
        width=1, height=3,
        tiles=[],
        countries=countries,
        continents=continents,
        paths={},
    )
    now = datetime.now(UTC)
    game = Game(
        game_id="g1", map_id="m1", name="Test", config=cfg,
        created_at=now, updated_at=now, rng_seed=1, owner_user_id="u1",
    )
    p = Player(player_id="p1", seat_order=0, color="#000", kind="human", user_id="u1")
    states = {
        "c1": CountryState(country_id="c1", owner_player_id="p1", armies=3),
        "c2": CountryState(country_id="c2", owner_player_id="p1", armies=4),
        "c3": CountryState(country_id="c3", owner_player_id=None, armies=0),
    }
    return GameSnapshot(game=game, map=m, players={"p1": p}, country_states=states)


def test_base_plus_per_country_plus_owned_continent() -> None:
    snap = _toy_snapshot()
    # 10 base + 1*2 owned + 3 (full ownership of cont1) = 15
    assert compute_reinforcements(snap, "p1") == 15


def test_no_continent_bonus_when_partial() -> None:
    snap = _toy_snapshot()
    snap.country_states["c2"].owner_player_id = None
    # 10 base + 1*1 owned + 0 = 11
    assert compute_reinforcements(snap, "p1") == 11
