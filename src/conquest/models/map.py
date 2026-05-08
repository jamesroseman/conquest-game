"""Map data structures. Maps are immutable once generated. See CLAUDE.md § Map generation."""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class MapGenParams(BaseModel):
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

    @classmethod
    def for_player_count(cls, *, seed: int, player_count: int) -> "MapGenParams":
        """Pick a map size and country count appropriate for a given player count.

        We aim for roughly 7 countries per player (Risk's 42-territory map across 6 players hits
        this), with a soft floor and ceiling, and grow the grid proportionally so countries stay
        in the same tile-size band.
        """
        if not 2 <= player_count <= 6:
            raise ValueError("player_count must be between 2 and 6")
        target_country_count = max(28, min(56, player_count * 7))
        # Tile budget: each country wants ~ (min+max)/2 tiles → ~15. Add ~55% ocean.
        avg_country_tiles = 15
        land_tiles = target_country_count * avg_country_tiles
        total_tiles = int(land_tiles / 0.45)
        # Slightly wider than tall for nicer rendering.
        width = int((total_tiles * 1.6) ** 0.5)
        height = int(total_tiles / width)
        return cls(
            seed=seed,
            width=max(36, width),
            height=max(24, height),
            target_country_count=target_country_count,
        )


Terrain = Literal["land", "ocean"]
PathKind = Literal["land", "sea"]


class Tile(BaseModel):
    x: int
    y: int
    terrain: Terrain
    countryId: str | None = None


class Path(BaseModel):
    pathId: str
    countryAId: str
    countryBId: str
    kind: PathKind


class Country(BaseModel):
    countryId: str
    name: str
    continentId: str
    tiles: list[tuple[int, int]]
    centroid: tuple[float, float]
    pathIds: list[str] = Field(default_factory=list)


class Continent(BaseModel):
    continentId: str
    name: str
    isIsland: bool
    countryIds: list[str]
    tileCount: int
    bonusArmies: int


class Map(BaseModel):
    mapId: str
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
        for path_id in country.pathIds:
            path = self.paths[path_id]
            other = path.countryBId if path.countryAId == country_id else path.countryAId
            out.append(other)
        return out
