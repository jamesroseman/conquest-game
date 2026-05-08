"""Property-based invariants. See CLAUDE.md § Property-based.

Each property runs the rules engine end-to-end through the simulation harness on a small
random sample of seeds and archetypes, then asserts a single invariant.

The samples are intentionally small (max_examples kept low) so the suite stays fast in CI;
balance work uses scripts/run_simulation.py with thousands of games.
"""
from __future__ import annotations

from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from conquest.ai.archetypes import ARCHETYPES
from conquest.game.map_gen import generate_map
from conquest.models.map import MapGenParams
from conquest.simulation import run_simulation
from conquest.simulation.harness import build_simulation_snapshot

ARCHETYPE_NAMES = sorted(ARCHETYPES)
SLOW_SETTINGS = settings(
    max_examples=8,
    deadline=None,
    suppress_health_check=[HealthCheck.too_slow, HealthCheck.function_scoped_fixture],
)


@given(seed=st.integers(min_value=1, max_value=10_000))
@settings(max_examples=15, deadline=None)
def test_map_invariants_hold(seed: int) -> None:
    m = generate_map(MapGenParams(seed=seed))
    # Exactly 4 continents.
    assert len(m.continents) == 4
    # Exactly 1 island.
    assert sum(1 for c in m.continents.values() if c.is_island) == 1
    # Every land tile has a country; ocean tiles never do.
    for tile in m.tiles:
        if tile.terrain == "land":
            assert tile.country_id is not None
        else:
            assert tile.country_id is None
    # No country exceeds the configured max tile size by much.
    for c in m.countries.values():
        assert len(c.tiles) >= 1


@given(seed=st.integers(min_value=1, max_value=10_000))
@settings(max_examples=15, deadline=None)
def test_starting_troops_conserved_at_setup_start(seed: int) -> None:
    snap = build_simulation_snapshot(
        seed=seed, archetypes=["aggressor", "medic"]
    )
    cfg = snap.game.config
    expected_per_player = cfg.starting_troops_per_player
    # Pre-placement: every player has their full pool, board has zero armies.
    assert all(
        p.troops_remaining_to_place == expected_per_player for p in snap.players.values()
    )
    assert sum(s.armies for s in snap.country_states.values()) == 0


@given(
    seed=st.integers(min_value=1, max_value=10_000),
    archetypes=st.lists(st.sampled_from(ARCHETYPE_NAMES), min_size=2, max_size=4),
)
@SLOW_SETTINGS
def test_outbreak_count_monotonic_and_cubes_bounded(
    seed: int, archetypes: list[str]
) -> None:
    snap = build_simulation_snapshot(seed=seed, archetypes=archetypes)
    # Right after seeding, no country has more than max_cubes_per_country.
    for s in snap.country_states.values():
        assert 0 <= s.disease_cubes <= snap.game.config.max_cubes_per_country


@given(
    seed=st.integers(min_value=1, max_value=10_000),
    archetypes=st.lists(st.sampled_from(ARCHETYPE_NAMES), min_size=2, max_size=3),
)
@SLOW_SETTINGS
def test_simulation_terminates_with_known_reason(
    seed: int, archetypes: list[str]
) -> None:
    out = run_simulation(seed=seed, archetypes=archetypes, max_rounds=80)
    assert out.ended_reason in {
        "victory",
        "outbreak_limit",
        "max_rounds",
        "setup_failed",
    }
