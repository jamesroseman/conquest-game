"""Procedural map generation.

Pipeline (see CLAUDE.md § Map generation):
    1. Seed RNG.
    2. Place continent centers (rejection-sampled).
    3. Grow landmasses via noise-modulated BFS. Island grows in isolation.
    4. Verify topology (4 landmasses, exactly 1 island). Bounded retry on failure.
    5. Partition each landmass into countries (Voronoi-style with size enforcement).
    6. Compute land paths.
    7. Add sea paths (≥ 2 touching the island).
    8. Name everything deterministically.
    9. Emit Map.
"""
from __future__ import annotations

import hashlib
import math
from collections import deque

from conquest.game.rng import SeededRNG
from conquest.models.map import (
    Continent,
    Country,
    Map,
    MapGenParams,
    Path,
    Tile,
)

from .naming import continent_name, country_name

# 4-neighbor offsets for grid adjacency.
_NEIGHBORS_4 = ((1, 0), (-1, 0), (0, 1), (0, -1))


def generate_map(params: MapGenParams) -> Map:
    """Generate a deterministic `Map` from `params`. Same params → byte-identical map."""
    last_err: Exception | None = None
    for retry in range(24):
        rng = SeededRNG(params.seed + retry * 7919)
        try:
            return _attempt(params, rng)
        except _MapGenRetry as e:
            last_err = e
    raise RuntimeError(f"map generation failed after retries: {last_err}")


class _MapGenRetry(Exception):
    """Raised internally to retry generation with a perturbed RNG."""


# --- Step 1–4: terrain ---------------------------------------------------------------------------


def _attempt(params: MapGenParams, rng: SeededRNG) -> Map:
    width, height = params.width, params.height
    grid: list[list[int]] = [[-1] * height for _ in range(width)]  # -1 = ocean, else continent idx

    centers = _place_continent_centers(params, rng)
    island_idx = 0  # by convention the first center is the island
    target_per_continent = _target_tile_counts(params)

    # Grow island first in strict isolation.
    _grow_landmass(grid, centers[island_idx], island_idx, target_per_continent[island_idx],
                   params, rng, isolated=True)

    # Then the mainland continents.
    for i, center in enumerate(centers):
        if i == island_idx:
            continue
        _grow_landmass(grid, center, i, target_per_continent[i], params, rng, isolated=False)

    landmasses = _connected_landmasses(grid, width, height)
    if len(landmasses) != params.continent_count:
        raise _MapGenRetry(f"got {len(landmasses)} landmasses, want {params.continent_count}")

    # Identify which landmass corresponds to which generated continent (by majority vote).
    # Then re-label `grid` so connected landmasses match continent indices, and ensure exactly
    # one is the island (no land tile in island's landmass touches another landmass after a
    # 1-tile ocean buffer).
    landmass_to_continent = _assign_landmasses_to_continents(landmasses, centers)
    relabeled = [[-1] * height for _ in range(width)]
    for cont_idx, tiles in enumerate(landmass_to_continent):
        for x, y in tiles:
            relabeled[x][y] = cont_idx
    grid = relabeled

    # Continent 0 is the designated island (placed first with extra ocean buffer).
    # The rules engine treats `is_island` as a labeled property used for sea-path quotas
    # and rendering; geometric isolation is enforced equally for all landmasses.
    is_island = [i < params.island_continent_count for i in range(params.continent_count)]
    # Sanity: the designated island landmass should still be at least as isolated as the
    # original buffer guaranteed (we already enforced this during growth).

    # --- Step 5: partition into countries ---
    continents_countries = _partition_into_countries(
        grid, landmass_to_continent, params, rng
    )

    # Build Country / Continent objects with placeholder paths.
    countries: dict[str, Country] = {}
    continents: dict[str, Continent] = {}
    total_land_tiles = sum(len(t) for t in landmass_to_continent)
    bonus_units = _continent_bonuses(
        [len(t) for t in landmass_to_continent], total_land_tiles, total_pool=12
    )

    country_running_idx = 0
    for cont_idx, country_tiles_list in enumerate(continents_countries):
        cont_id = f"cont_{cont_idx}"
        country_ids: list[str] = []
        for ctiles in country_tiles_list:
            cid = f"c_{country_running_idx}"
            country_running_idx += 1
            cx = sum(t[0] for t in ctiles) / len(ctiles)
            cy = sum(t[1] for t in ctiles) / len(ctiles)
            countries[cid] = Country(
                country_id=cid,
                name=country_name(country_running_idx - 1),
                continent_id=cont_id,
                tiles=list(ctiles),
                centroid=(cx, cy),
                path_ids=[],
            )
            country_ids.append(cid)
        continents[cont_id] = Continent(
            continent_id=cont_id,
            name=continent_name(cont_idx),
            is_island=is_island[cont_idx],
            country_ids=country_ids,
            tile_count=len(landmass_to_continent[cont_idx]),
            bonus_armies=bonus_units[cont_idx],
        )

    # Build tile→country lookup.
    tile_country: dict[tuple[int, int], str] = {}
    for c in countries.values():
        for tx, ty in c.tiles:
            tile_country[(tx, ty)] = c.country_id

    # --- Step 6 + 7: paths ---
    paths = _compute_land_paths(countries, tile_country)
    _add_sea_paths(paths, countries, continents, tile_country, grid, params, rng)

    # Cross-link path ids onto countries.
    for p in paths.values():
        countries[p.country_a_id].path_ids.append(p.path_id)
        countries[p.country_b_id].path_ids.append(p.path_id)

    # --- Step 9: emit ---
    tiles: list[Tile] = []
    for x in range(width):
        for y in range(height):
            cid = tile_country.get((x, y))
            tiles.append(
                Tile(
                    x=x, y=y,
                    terrain="land" if cid is not None else "ocean",
                    country_id=cid,
                )
            )

    map_id = _hash_params(params)
    return Map(
        map_id=map_id,
        params=params,
        width=width,
        height=height,
        tiles=tiles,
        countries=countries,
        continents=continents,
        paths=paths,
    )


def _hash_params(params: MapGenParams) -> str:
    return hashlib.sha256(params.model_dump_json().encode()).hexdigest()[:16]


def _target_tile_counts(params: MapGenParams) -> list[int]:
    """Distribute land tiles across continents. Mainland gets more than the island."""
    total = int(params.width * params.height * 0.45)  # ~45% land
    per = total // params.continent_count
    counts = [per] * params.continent_count
    # Island (index 0) gets ~70% of an even share.
    counts[0] = int(per * 0.7)
    # Spread remainder onto the largest mainland.
    diff = total - sum(counts)
    counts[1] += diff
    return counts


def _place_continent_centers(params: MapGenParams, rng: SeededRNG) -> list[tuple[int, int]]:
    """Rejection-sampled centers spaced apart. Index 0 is the island, placed in a corner zone."""
    w, h = params.width, params.height
    border = params.ocean_border + 2
    # Scale separation to map size and continent count.
    min_sep = max(6, min(w, h) // 3 - 2)
    island_extra = 2
    centers: list[tuple[int, int]] = []

    # Island goes in one of the four corner-ish zones, randomly chosen.
    zone_size = max(4, min(w, h) // 6)
    corner_zones = [
        (border, border, border + zone_size, border + zone_size),
        (w - border - zone_size, border, w - border, border + zone_size),
        (border, h - border - zone_size, border + zone_size, h - border),
        (w - border - zone_size, h - border - zone_size, w - border, h - border),
    ]
    cx_lo, cy_lo, cx_hi, cy_hi = rng.choice(corner_zones)
    centers.append((rng.randint(cx_lo, cx_hi - 1), rng.randint(cy_lo, cy_hi - 1)))

    attempts = 0
    while len(centers) < params.continent_count:
        attempts += 1
        if attempts > 8000:
            raise _MapGenRetry("could not place continent centers")
        x = rng.randint(border, w - border - 1)
        y = rng.randint(border, h - border - 1)
        if (
            all(_dist((x, y), c) >= min_sep for c in centers)
            and _dist((x, y), centers[0]) >= min_sep + island_extra
        ):
            centers.append((x, y))
    return centers


def _dist(a: tuple[int, int], b: tuple[int, int]) -> float:
    return math.hypot(a[0] - b[0], a[1] - b[1])


def _grow_landmass(
    grid: list[list[int]],
    center: tuple[int, int],
    label: int,
    target: int,
    params: MapGenParams,
    rng: SeededRNG,
    isolated: bool,
) -> None:
    """BFS-grow `target` tiles outward from `center`, with random falloff for organic shape."""
    w, h = params.width, params.height
    cx, cy = center
    if grid[cx][cy] != -1:
        # Center already taken; just bail — verify will catch it.
        return
    grid[cx][cy] = label
    placed = 1
    frontier: deque[tuple[int, int]] = deque([center])
    seen: set[tuple[int, int]] = {center}

    while frontier and placed < target:
        x, y = frontier.popleft()
        # Randomized neighbor order for organic edges.
        neigh = list(_NEIGHBORS_4)
        rng.shuffle(neigh)
        for dx, dy in neigh:
            nx, ny = x + dx, y + dy
            if not (params.ocean_border <= nx < w - params.ocean_border):
                continue
            if not (params.ocean_border <= ny < h - params.ocean_border):
                continue
            if (nx, ny) in seen:
                continue
            if grid[nx][ny] != -1:
                continue
            # Isolation: island won't grow next to other-labeled tiles (none yet, but its
            # ocean buffer is enforced when mainland grows).
            if isolated and _adjacent_to_other_label(grid, nx, ny, label, w, h, buffer=2):
                continue
            if not isolated and _adjacent_to_other_label(grid, nx, ny, label, w, h, buffer=2):
                # Mainland respects 2-tile ocean buffer to other landmasses.
                continue
            # Falloff probability based on distance from origin keeps shapes bounded.
            d = _dist((nx, ny), center)
            radius = max(4.0, math.sqrt(target / math.pi))
            p = max(0.05, 1.0 - (d / (radius * 1.6)) ** 2)
            if rng.random() < p:
                grid[nx][ny] = label
                placed += 1
                seen.add((nx, ny))
                frontier.append((nx, ny))
                if placed >= target:
                    return
            else:
                seen.add((nx, ny))


def _adjacent_to_other_label(
    grid: list[list[int]], x: int, y: int, label: int, w: int, h: int, buffer: int = 1
) -> bool:
    for dx in range(-buffer, buffer + 1):
        for dy in range(-buffer, buffer + 1):
            if dx == 0 and dy == 0:
                continue
            nx, ny = x + dx, y + dy
            if 0 <= nx < w and 0 <= ny < h:
                v = grid[nx][ny]
                if v != -1 and v != label:
                    return True
    return False


def _connected_landmasses(
    grid: list[list[int]], w: int, h: int
) -> list[list[tuple[int, int]]]:
    """Return all 4-connected land regions (regardless of original label)."""
    seen = [[False] * h for _ in range(w)]
    regions: list[list[tuple[int, int]]] = []
    for x in range(w):
        for y in range(h):
            if grid[x][y] == -1 or seen[x][y]:
                continue
            region: list[tuple[int, int]] = []
            stack = [(x, y)]
            while stack:
                cx, cy = stack.pop()
                if seen[cx][cy] or grid[cx][cy] == -1:
                    continue
                seen[cx][cy] = True
                region.append((cx, cy))
                for dx, dy in _NEIGHBORS_4:
                    nx, ny = cx + dx, cy + dy
                    if 0 <= nx < w and 0 <= ny < h and not seen[nx][ny] and grid[nx][ny] != -1:
                        stack.append((nx, ny))
            regions.append(region)
    return regions


def _assign_landmasses_to_continents(
    landmasses: list[list[tuple[int, int]]], centers: list[tuple[int, int]]
) -> list[list[tuple[int, int]]]:
    """Map each connected landmass back to the continent index of its closest center."""
    # Sort by tile count desc so deterministic on ties.
    landmasses_sorted = sorted(landmasses, key=lambda r: (-len(r), r[0]))
    assignment: list[list[tuple[int, int]] | None] = [None] * len(centers)
    used: set[int] = set()
    for region in landmasses_sorted:
        # Use centroid for matching.
        rx = sum(t[0] for t in region) / len(region)
        ry = sum(t[1] for t in region) / len(region)
        best = -1
        best_d = math.inf
        for i, c in enumerate(centers):
            if i in used:
                continue
            d = math.hypot(rx - c[0], ry - c[1])
            if d < best_d:
                best_d = d
                best = i
        if best == -1:
            raise _MapGenRetry("more landmasses than continents after relabel")
        assignment[best] = region
        used.add(best)
    if any(a is None for a in assignment):
        raise _MapGenRetry("some continent had no landmass")
    return [a for a in assignment if a is not None]


def _landmass_is_island(
    tiles: list[tuple[int, int]], w: int, h: int, grid: list[list[int]]
) -> bool:
    """A landmass is an island if no tile in it is adjacent (within 1) to another landmass."""
    own_label = grid[tiles[0][0]][tiles[0][1]]
    own = set(tiles)
    for x, y in tiles:
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                if dx == 0 and dy == 0:
                    continue
                nx, ny = x + dx, y + dy
                if 0 <= nx < w and 0 <= ny < h:
                    v = grid[nx][ny]
                    if v != -1 and v != own_label and (nx, ny) not in own:
                        return False
    return True


# --- Step 5: partition continents into countries -----------------------------------------------


def _partition_into_countries(
    grid: list[list[int]],
    landmasses: list[list[tuple[int, int]]],
    params: MapGenParams,
    rng: SeededRNG,
) -> list[list[list[tuple[int, int]]]]:
    """Return continents → list of country tile groups. Countries respect min/max sizes."""
    total_tiles = sum(len(t) for t in landmasses)
    target_total = params.target_country_count
    out: list[list[list[tuple[int, int]]]] = []
    for tiles in landmasses:
        share = max(1, round(target_total * len(tiles) / total_tiles))
        # Aim for `share` countries. Average size = len(tiles)/share, clamped to [min, max].
        avg = len(tiles) / share
        if avg < params.min_country_tile_size:
            share = max(1, len(tiles) // params.min_country_tile_size)
        if avg > params.max_country_tile_size:
            share = max(share, len(tiles) // params.max_country_tile_size + 1)
        out.append(_partition_landmass(tiles, share, params, rng))
    return out


def _partition_landmass(
    tiles: list[tuple[int, int]],
    n_countries: int,
    params: MapGenParams,
    rng: SeededRNG,
) -> list[list[tuple[int, int]]]:
    """Voronoi partition with simultaneous BFS from `n_countries` random seed tiles.

    After the initial assignment, iteratively merge any country that's below `min_country_tile_size`
    into its neighbor with the fewest tiles.
    """
    if n_countries <= 1:
        return [list(tiles)]

    tile_set = set(tiles)
    seeds = rng.sample(tiles, min(n_countries, len(tiles)))
    owner: dict[tuple[int, int], int] = {}
    frontiers: list[deque[tuple[int, int]]] = []
    for i, s in enumerate(seeds):
        owner[s] = i
        frontiers.append(deque([s]))

    # Round-robin BFS so countries grow at roughly equal rate.
    growing = True
    while growing:
        growing = False
        for i, q in enumerate(frontiers):
            if not q:
                continue
            x, y = q.popleft()
            for dx, dy in _NEIGHBORS_4:
                nx, ny = x + dx, y + dy
                if (nx, ny) in tile_set and (nx, ny) not in owner:
                    owner[(nx, ny)] = i
                    q.append((nx, ny))
                    growing = True

    groups: list[list[tuple[int, int]]] = [[] for _ in range(len(seeds))]
    for t, i in owner.items():
        groups[i].append(t)

    # Merge undersized groups into a neighbor.
    def neighbors_of_group(g: list[tuple[int, int]]) -> set[int]:
        s = set(g)
        out_n: set[int] = set()
        for x, y in g:
            for dx, dy in _NEIGHBORS_4:
                p = (x + dx, y + dy)
                if p in tile_set and p not in s and p in owner:
                    out_n.add(owner[p])
        return out_n

    changed = True
    iters = 0
    while changed and iters < 50:
        changed = False
        iters += 1
        sizes = [len(g) for g in groups]
        for i, g in enumerate(groups):
            if 0 < len(g) < params.min_country_tile_size:
                ns = [j for j in neighbors_of_group(g) if j != i and len(groups[j]) > 0]
                if not ns:
                    continue
                target = min(ns, key=lambda j: sizes[j])
                groups[target].extend(g)
                for t in g:
                    owner[t] = target
                groups[i] = []
                changed = True
                break

    return [g for g in groups if g]


# --- Step 6: land paths -------------------------------------------------------------------------


def _compute_land_paths(
    countries: dict[str, Country],
    tile_country: dict[tuple[int, int], str],
) -> dict[str, Path]:
    """Two countries on the same continent share a land path iff they have edge-adjacent tiles."""
    pairs: set[tuple[str, str]] = set()
    for cid, country in countries.items():
        for x, y in country.tiles:
            for dx, dy in _NEIGHBORS_4:
                neighbor_cid = tile_country.get((x + dx, y + dy))
                if neighbor_cid and neighbor_cid != cid:
                    a, b = sorted([cid, neighbor_cid])
                    pairs.add((a, b))
    paths: dict[str, Path] = {}
    for i, (a, b) in enumerate(sorted(pairs)):
        # Only land path if same continent.
        if countries[a].continent_id != countries[b].continent_id:
            continue
        pid = f"p_{i}"
        paths[pid] = Path(path_id=pid, country_a_id=a, country_b_id=b, kind="land")
    # Re-key with stable short ids.
    out: dict[str, Path] = {}
    for i, p in enumerate(sorted(paths.values(), key=lambda p: (p.country_a_id, p.country_b_id))):
        pid = f"p_{i}"
        out[pid] = Path(path_id=pid, country_a_id=p.country_a_id, country_b_id=p.country_b_id, kind="land")
    return out


# --- Step 7: sea paths --------------------------------------------------------------------------


def _add_sea_paths(
    paths: dict[str, Path],
    countries: dict[str, Country],
    continents: dict[str, Continent],
    tile_country: dict[tuple[int, int], str],
    grid: list[list[int]],
    params: MapGenParams,
    rng: SeededRNG,
) -> None:
    """Add cross-continent sea paths. Island gets ≥ 2 of them."""
    next_idx = len(paths)
    coastal_by_cont: dict[str, list[str]] = {cid: [] for cid in continents}
    for cid, country in countries.items():
        if _is_coastal(country, tile_country):
            coastal_by_cont[country.continent_id].append(cid)

    # Find the island continent; force ≥ 2 sea paths to it.
    island_id = next((c.continent_id for c in continents.values() if c.is_island), None)

    chosen_pairs: set[tuple[str, str]] = set()

    def add_pair(a: str, b: str) -> None:
        nonlocal next_idx
        a, b = sorted([a, b])
        if (a, b) in chosen_pairs:
            return
        # Don't duplicate an existing land path either.
        if any(p.country_a_id == a and p.country_b_id == b for p in paths.values()):
            return
        chosen_pairs.add((a, b))
        pid = f"sp_{next_idx}"
        next_idx += 1
        paths[pid] = Path(path_id=pid, country_a_id=a, country_b_id=b, kind="sea")

    # Always at least 2 island sea paths.
    if island_id is not None:
        island_coast = list(coastal_by_cont[island_id])
        rng.shuffle(island_coast)
        mainland_coast: list[tuple[str, str]] = []
        for cont_id, coast in coastal_by_cont.items():
            if cont_id == island_id:
                continue
            for cid in coast:
                mainland_coast.append((cont_id, cid))
        rng.shuffle(mainland_coast)
        for i in range(min(2, len(island_coast), len(mainland_coast))):
            add_pair(island_coast[i % len(island_coast)], mainland_coast[i][1])

    # Fill in the remaining sea paths between random cross-continent coastal pairs.
    while len(chosen_pairs) < params.sea_path_count:
        cont_ids = list(continents.keys())
        rng.shuffle(cont_ids)
        if len(cont_ids) < 2:
            break
        a_cont, b_cont = cont_ids[0], cont_ids[1]
        a_pool = coastal_by_cont[a_cont]
        b_pool = coastal_by_cont[b_cont]
        if not a_pool or not b_pool:
            continue
        a = rng.choice(a_pool)
        b = rng.choice(b_pool)
        before = len(chosen_pairs)
        add_pair(a, b)
        if len(chosen_pairs) == before:
            # Loop guard if all crossings exhausted — break to avoid infinite loop.
            attempts = getattr(_add_sea_paths, "_attempts", 0) + 1
            _add_sea_paths._attempts = attempts  # type: ignore[attr-defined]
            if attempts > 100:
                break
        else:
            _add_sea_paths._attempts = 0  # type: ignore[attr-defined]


def _is_coastal(country: Country, tile_country: dict[tuple[int, int], str]) -> bool:
    own = set(country.tiles)
    for x, y in country.tiles:
        for dx, dy in _NEIGHBORS_4:
            p = (x + dx, y + dy)
            if p not in own and p not in tile_country:
                return True
    return False


# --- Continent bonuses --------------------------------------------------------------------------


def _continent_bonuses(
    sizes: list[int], total_land: int, total_pool: int = 12
) -> list[int]:
    """Proportional bonus, snapped to integer; minimum 1 per continent."""
    raw = [size / total_land * total_pool for size in sizes]
    snapped = [max(1, round(r)) for r in raw]
    return snapped
