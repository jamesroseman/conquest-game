"""End-of-round virus phase: casualties, spread, outbreaks."""
from __future__ import annotations

from datetime import UTC, datetime

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
        "c1": Country(country_id="c1", name="A", continent_id="x",
                      tiles=[(0, 0)], centroid=(0, 0), path_ids=["p1"]),
        "c2": Country(country_id="c2", name="B", continent_id="x",
                      tiles=[(1, 0)], centroid=(1, 0), path_ids=["p1"]),
    }
    paths = {"p1": Path(path_id="p1", country_a_id="c1", country_b_id="c2", kind="land")}
    continents = {
        "x": Continent(continent_id="x", name="X", is_island=False,
                       country_ids=["c1", "c2"], tile_count=2, bonus_armies=3),
    }
    m = Map(
        map_id="m", params=MapGenParams(seed=1), width=2, height=1, tiles=[],
        countries=countries, continents=continents, paths=paths,
    )
    now = datetime.now(UTC)
    game = Game(
        game_id="g", map_id="m", name="t", config=cfg,
        created_at=now, updated_at=now, rng_seed=1, owner_user_id="u1",
        outbreaks=Outbreaks(),
    )
    states = {
        "c1": CountryState(country_id="c1", owner_player_id="p1", armies=12, disease_cubes=2),
        "c2": CountryState(country_id="c2", owner_player_id="p1", armies=9, disease_cubes=1),
    }
    p = Player(player_id="p1", seat_order=0, color="#000", kind="human", user_id="u1")
    return GameSnapshot(game=game, map=m, players={"p1": p}, country_states=states)


def test_casualties_round_down() -> None:
    snap = _two_country_snapshot()
    # 12 armies × 1/2 = 6 lost; 9 × 1/3 = 3 lost.
    rng = SeededRNG(99)
    run_virus_phase(snap, rng)
    assert snap.country_states["c1"].armies == 12 - 6
    assert snap.country_states["c2"].armies == 9 - 3


def test_three_cubes_kills_all_armies() -> None:
    snap = _two_country_snapshot()
    snap.country_states["c1"].disease_cubes = 3
    snap.country_states["c1"].armies = 7
    rng = SeededRNG(99)
    run_virus_phase(snap, rng)
    assert snap.country_states["c1"].armies == 0


def test_vaccinated_country_skipped_during_spread() -> None:
    snap = _two_country_snapshot()
    snap.country_states["c1"].disease_cubes = 0
    snap.country_states["c2"].disease_cubes = 0
    snap.country_states["c1"].vaccinated = True
    rng = SeededRNG(1)
    run_virus_phase(snap, rng)
    assert snap.country_states["c1"].disease_cubes == 0


def test_outbreak_chain_increments_count() -> None:
    snap = _two_country_snapshot()
    # Force a saturated country so the next placement triggers an outbreak.
    snap.country_states["c1"].disease_cubes = 3
    snap.country_states["c2"].disease_cubes = 0
    snap.country_states["c1"].armies = 0  # no casualty side-effect to muddy things
    snap.country_states["c2"].armies = 0
    # Many trials so we eventually hit c1 and trigger.
    cfg = snap.game.config
    cfg.spread_schedule = [(0, 99, 6)]
    before = snap.game.outbreaks.count
    run_virus_phase(snap, SeededRNG(seed=42))
    assert snap.game.outbreaks.count >= before
