"""Map data structures. Maps are immutable once generated. See CLAUDE.md § Map generation."""
from __future__ import annotations

from typing import Literal

from pydantic import Field, model_validator

from .base import CamelModel

# Hard ceilings — see CLAUDE.md § Map generation. The simulation engine and the in-memory
# repository hold the full map and per-country state in process memory; an unbounded grid
# would let a single game balloon RAM. These caps are well above realistic gameplay needs.
MAX_PLAYERS = 6
MIN_PLAYERS = 2
MAX_MAP_TILES = 96 * 60  # 5760 tiles — comfortably above any 6-player map
MAX_MAP_DIMENSION = 96


class MapGenParams(CamelModel):
    seed: int
    width: int = 64
    height: int = 40
    continent_count: int = 4
    island_continent_count: int = 1
    target_country_count: int = 42
    min_country_tile_size: int = 6
    max_country_tile_size: int = 24
    sea_path_count: int = 6
    ocean_border: int = 2

    @model_validator(mode="after")
    def _validate_size(self) -> "MapGenParams":
        if self.width > MAX_MAP_DIMENSION or self.height > MAX_MAP_DIMENSION:
            raise ValueError(
                f"map dimensions exceed cap: {self.width}x{self.height} (max {MAX_MAP_DIMENSION})"
            )
        if self.width * self.height > MAX_MAP_TILES:
            raise ValueError(
                f"map too large: {self.width * self.height} tiles (max {MAX_MAP_TILES})"
            )
        if self.width < 16 or self.height < 12:
            raise ValueError("map dimensions too small")
        return self

    @classmethod
    def for_player_count(cls, *, seed: int, player_count: int) -> "MapGenParams":
        """Pick a map size and country count appropriate for a given player count.

        Aims for ~7 countries per player (Risk's 42-territory map across 6 players hits this),
        with soft floor and ceiling, and grows the grid proportionally so countries stay in
        the same tile-size band. Hard-capped at `MAX_PLAYERS`.
        """
        if not MIN_PLAYERS <= player_count <= MAX_PLAYERS:
            raise ValueError(
                f"player_count must be between {MIN_PLAYERS} and {MAX_PLAYERS}"
            )
        target_country_count = max(28, min(56, player_count * 7))
        avg_country_tiles = 15
        land_tiles = target_country_count * avg_country_tiles
        total_tiles = int(land_tiles / 0.45)
        width = int((total_tiles * 1.6) ** 0.5)
        height = int(total_tiles / width)
        return cls(
            seed=seed,
            width=max(36, min(MAX_MAP_DIMENSION, width)),
            height=max(24, min(MAX_MAP_DIMENSION, height)),
            target_country_count=target_country_count,
        )


Terrain = Literal["land", "ocean"]
PathKind = Literal["land", "sea"]


class Tile(CamelModel):
    x: int
    y: int
    terrain: Terrain
    country_id: str | None = None


class Path(CamelModel):
    path_id: str
    country_a_id: str
    country_b_id: str
    kind: PathKind


class Country(CamelModel):
    country_id: str
    name: str
    continent_id: str
    tiles: list[tuple[int, int]]
    centroid: tuple[float, float]
    path_ids: list[str] = Field(default_factory=list)


class Continent(CamelModel):
    continent_id: str
    name: str
    is_island: bool
    country_ids: list[str]
    tile_count: int
    bonus_armies: int


class Map(CamelModel):
    map_id: str
    params: MapGenParams
    width: int
    height: int
    tiles: list[Tile]
    countries: dict[str, Country]
    continents: dict[str, Continent]
    paths: dict[str, Path]

    def neighbors(self, country_id: str) -> list[str]:
        out: list[str] = []
        country = self.countries[country_id]
        for path_id in country.path_ids:
            path = self.paths[path_id]
            other = path.country_b_id if path.country_a_id == country_id else path.country_a_id
            out.append(other)
        return out
