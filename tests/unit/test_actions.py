"""In-game action validation + dispatch."""

from __future__ import annotations

from datetime import UTC, datetime

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
        "c1": Country(
            country_id="c1",
            name="A",
            continent_id="x",
            tiles=[(0, 0)],
            centroid=(0, 0),
            path_ids=["p1"],
        ),
        "c2": Country(
            country_id="c2",
            name="B",
            continent_id="x",
            tiles=[(1, 0)],
            centroid=(1, 0),
            path_ids=["p1"],
        ),
    }
    paths = {"p1": Path(path_id="p1", country_a_id="c1", country_b_id="c2", kind="land")}
    cont = Continent(
        continent_id="x",
        name="X",
        is_island=False,
        country_ids=["c1", "c2"],
        tile_count=2,
        bonus_armies=3,
    )
    m = Map(
        map_id="m",
        params=MapGenParams(seed=1),
        width=2,
        height=1,
        tiles=[],
        countries=countries,
        continents={"x": cont},
        paths=paths,
    )
    now = datetime.now(UTC)
    game = Game(
        game_id="g",
        map_id="m",
        name="t",
        config=cfg,
        created_at=now,
        updated_at=now,
        rng_seed=1,
        owner_user_id="u1",
        status="in_progress",
        turn=TurnState(
            active_player_id="p1",
            actions_remaining=cfg.actions_per_turn,
            reinforcements_to_place=0,
            turn_number=1,
            round_number=1,
            phase="actions",
        ),
    )
    p1 = Player(
        player_id="p1",
        seat_order=0,
        color="#000",
        kind="human",
        user_id="u1",
        researcher_country_id="c1",
        capital_country_id="c1",
    )
    p2 = Player(
        player_id="p2",
        seat_order=1,
        color="#fff",
        kind="human",
        user_id="u2",
        researcher_country_id="c2",
        capital_country_id="c2",
    )
    states = {
        "c1": CountryState(
            country_id="c1",
            owner_player_id="p1",
            armies=5,
            has_researcher="p1",
            is_capital_of="p1",
            disease_cubes=2,
        ),
        "c2": CountryState(
            country_id="c2", owner_player_id="p2", armies=3, has_researcher="p2", is_capital_of="p2"
        ),
    }
    return GameSnapshot(game=game, map=m, players={"p1": p1, "p2": p2}, country_states=states)


def test_not_your_turn() -> None:
    snap = _two_country_in_progress()
    with pytest.raises(NotYourTurn):
        apply_action(snap, "p2", Cure(), SeededRNG(1))


def test_cure_clears_cubes_and_costs_one_action() -> None:
    snap = _two_country_in_progress()
    apply_action(snap, "p1", Cure(), SeededRNG(1))
    assert snap.country_states["c1"].disease_cubes == 0
    assert snap.game.turn.actions_remaining == snap.game.config.actions_per_turn - 1


def test_move_troops_requires_owned_endpoints() -> None:
    snap = _two_country_in_progress()
    with pytest.raises(NotYourCountry):
        apply_action(
            snap,
            "p1",
            MoveTroops(from_country_id="c1", to_country_id="c2", armies=1),
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
    snap.game.turn.reinforcements_to_place = 3
    with pytest.raises(ReinforcementsNotPlaced):
        apply_action(snap, "p1", Cure(), SeededRNG(1))


def test_place_reinforcements_consumes_pool() -> None:
    snap = _two_country_in_progress()
    snap.game.turn.phase = "reinforcements"
    snap.game.turn.reinforcements_to_place = 4
    apply_action(
        snap,
        "p1",
        PlaceReinforcements(placements=[("c1", 4)]),
        SeededRNG(1),
    )
    assert snap.game.turn.reinforcements_to_place == 0
    assert snap.game.turn.phase == "actions"
    assert snap.country_states["c1"].armies == 9


def test_attack_costs_action_and_runs() -> None:
    from conquest.models.action import Attack

    snap = _two_country_in_progress()
    snap.country_states["c1"].armies = 10
    apply_action(
        snap, "p1", Attack(from_country_id="c1", to_country_id="c2", armies=5), SeededRNG(123)
    )
    assert snap.game.turn.actions_remaining == snap.game.config.actions_per_turn - 1


def test_actions_run_out() -> None:
    snap = _two_country_in_progress()
    snap.game.turn.actions_remaining = 0
    with pytest.raises(NotEnoughActions):
        apply_action(snap, "p1", Cure(), SeededRNG(1))
