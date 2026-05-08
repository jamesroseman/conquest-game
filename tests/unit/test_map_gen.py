"""Map generation invariants. See CLAUDE.md § Map generation."""

from __future__ import annotations

import pytest

from conquest.game.map_gen import generate_map
from conquest.models.map import MapGenParams


def _land_tile_count(m) -> int:  # type: ignore[no-untyped-def]
    return sum(1 for t in m.tiles if t.terrain == "land")


def test_generate_is_deterministic() -> None:
    p = MapGenParams(seed=42)
    a = generate_map(p)
    b = generate_map(p)
    assert a.model_dump() == b.model_dump()


@pytest.mark.parametrize("seed", [1, 7, 13, 42, 100, 999, 31337, 99991])
def test_invariants_across_seeds(seed: int) -> None:
    p = MapGenParams(seed=seed)
    m = generate_map(p)
    # Exactly 4 continents.
    assert len(m.continents) == 4
    # Exactly 1 island.
    islands = [c for c in m.continents.values() if c.is_island]
    assert len(islands) == 1
    # All land tiles assigned.
    for tile in m.tiles:
        if tile.terrain == "land":
            assert tile.country_id is not None
        else:
            assert tile.country_id is None
    # Country tile counts sum to land tile count.
    assert sum(len(c.tiles) for c in m.countries.values()) == _land_tile_count(m)
    # Continents reference real countries.
    for cont in m.continents.values():
        for cid in cont.country_ids:
            assert cid in m.countries
            assert m.countries[cid].continent_id == cont.continent_id
    # ≥ 2 sea paths to the island.
    island_id = islands[0].continent_id
    sea_to_island = [
        p
        for p in m.paths.values()
        if p.kind == "sea"
        and (
            m.countries[p.country_a_id].continent_id == island_id
            or m.countries[p.country_b_id].continent_id == island_id
        )
    ]
    assert len(sea_to_island) >= 2


def test_continent_bonus_is_proportional() -> None:
    m = generate_map(MapGenParams(seed=7))
    total_bonus = sum(c.bonus_armies for c in m.continents.values())
    # Bonuses are clamped (min 1 per continent) so the total can exceed the pool by at most
    # `continent_count` (one extra per continent).
    pool = 12
    assert pool <= total_bonus <= pool + len(m.continents)


def test_map_size_scales_with_players() -> None:
    small = MapGenParams.for_player_count(seed=1, player_count=2)
    big = MapGenParams.for_player_count(seed=1, player_count=6)
    assert small.target_country_count < big.target_country_count
    assert small.width * small.height < big.width * big.height


def test_map_size_rejects_invalid_player_count() -> None:
    with pytest.raises(ValueError):
        MapGenParams.for_player_count(seed=1, player_count=1)
    with pytest.raises(ValueError):
        MapGenParams.for_player_count(seed=1, player_count=7)


def test_map_size_validator_rejects_oversized_grid() -> None:
    with pytest.raises(ValueError):
        MapGenParams(seed=1, width=200, height=200)
    with pytest.raises(ValueError):
        MapGenParams(seed=1, width=8, height=8)
