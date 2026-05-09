"""4-phase setup state machine. See CLAUDE.md § Setup phase.

Phases (in order):
    1. troops          — players take turns placing one troop at a time.
    2. disease_seed    — server seeds disease automatically (one shot).
    3. researchers     — each player places researcher on a country they own.
    4. capitals        — each player places capital on a country they own.

When `capitals` finishes, the active player flips to seat 0 and the turn state machine takes
over with `phase="reinforcements"`.
"""

from __future__ import annotations

from conquest.game.errors import (
    CountryNotUnclaimed,
    InvalidAction,
    NotYourCountry,
    NotYourTurn,
    WrongPhase,
)
from conquest.game.rng import SeededRNG
from conquest.models.action import (
    PlaceCapital,
    PlaceResearcher,
    PlaceTroop,
)
from conquest.models.country_state import CountryState
from conquest.models.snapshot import GameSnapshot


def initialize_country_states(snapshot: GameSnapshot) -> None:
    """Seed `country_states` with one entry per country, all unowned."""
    for cid in snapshot.map.countries:
        snapshot.country_states[cid] = CountryState(country_id=cid)


# Number of troops added per setup placement. The setup phase is hand-paced
# by the player, so a 1-troop click on a 60-troop budget feels glacial. Two
# at a time keeps placement engaging without changing the strategic depth.
TROOPS_PER_PLACEMENT = 2


def place_troop(snapshot: GameSnapshot, actor_id: str, action: PlaceTroop) -> None:
    """Place TROOPS_PER_PLACEMENT troops at once (clamped to remaining).

    Risk-style claim rule applies until every country has an owner."""
    _require_setup_phase(snapshot, "troops")
    _require_active_seat(snapshot, actor_id)
    state = _country_state(snapshot, action.country_id)
    actor = snapshot.players[actor_id]

    all_claimed = all(s.owner_player_id is not None for s in snapshot.country_states.values())
    if not all_claimed:
        if state.owner_player_id is not None:
            # Must place on an unclaimed country first.
            raise CountryNotUnclaimed("must place on an unclaimed country until all are claimed")
    else:
        if state.owner_player_id != actor_id:
            raise NotYourCountry("can only reinforce countries you own")

    count = max(1, min(TROOPS_PER_PLACEMENT, actor.troops_remaining_to_place))
    if state.owner_player_id is None:
        state.owner_player_id = actor_id
    state.armies += count
    actor.troops_remaining_to_place -= count
    actor.stats.total_armies += count

    _advance_setup_seat_after_troop(snapshot)


def _advance_setup_seat_after_troop(snapshot: GameSnapshot) -> None:
    """Move to the next non-eliminated player; if all have placed all troops, advance phase."""
    players = sorted(snapshot.players.values(), key=lambda p: p.seat_order)
    n = len(players)
    if all(p.troops_remaining_to_place == 0 for p in players):
        snapshot.game.setup.phase = "disease_seed"
        snapshot.game.setup.active_seat_order = 0
        return
    seat = snapshot.game.setup.active_seat_order
    for _ in range(n):
        seat = (seat + 1) % n
        if players[seat].troops_remaining_to_place > 0:
            snapshot.game.setup.active_seat_order = seat
            return
    snapshot.game.setup.phase = "disease_seed"
    snapshot.game.setup.active_seat_order = 0


def seed_disease(snapshot: GameSnapshot, rng: SeededRNG) -> list[str]:
    """Server-driven: seeds 3 countries with 2 cubes, then 7 disjoint countries with 1 cube.

    Returns the list of country IDs that were seeded, in order (2-cube first, then 1-cube).
    """
    _require_setup_phase(snapshot, "disease_seed")
    cfg = snapshot.game.config
    pool = list(snapshot.map.countries.keys())
    rng.shuffle(pool)
    seeded: list[str] = []
    two_cube = pool[: cfg.setup_disease_2cube_count]
    one_cube = pool[
        cfg.setup_disease_2cube_count : cfg.setup_disease_2cube_count
        + cfg.setup_disease_1cube_count
    ]
    for cid in two_cube:
        s = snapshot.country_states[cid]
        s.disease_cubes = 2
        seeded.append(cid)
    for cid in one_cube:
        s = snapshot.country_states[cid]
        s.disease_cubes = 1
        seeded.append(cid)
    snapshot.game.setup.phase = "researchers"
    snapshot.game.setup.active_seat_order = 0
    return seeded


def place_researcher(snapshot: GameSnapshot, actor_id: str, action: PlaceResearcher) -> None:
    _require_setup_phase(snapshot, "researchers")
    _require_active_seat(snapshot, actor_id)
    actor = snapshot.players[actor_id]
    if actor.researcher_country_id is not None:
        raise InvalidAction("researcher already placed")
    state = _country_state(snapshot, action.country_id)
    if state.owner_player_id != actor_id:
        raise NotYourCountry("researcher must be placed on a country you own")
    actor.researcher_country_id = action.country_id
    state.has_researcher = actor_id
    _advance_setup_seat_after_unique(snapshot, attr="researcher_country_id", next_phase="capitals")


def place_capital(snapshot: GameSnapshot, actor_id: str, action: PlaceCapital) -> None:
    _require_setup_phase(snapshot, "capitals")
    _require_active_seat(snapshot, actor_id)
    actor = snapshot.players[actor_id]
    if actor.capital_country_id is not None:
        raise InvalidAction("capital already placed")
    state = _country_state(snapshot, action.country_id)
    if state.owner_player_id != actor_id:
        raise NotYourCountry("capital must be on a country you own")
    actor.capital_country_id = action.country_id
    state.is_capital_of = actor_id
    _advance_setup_seat_after_unique(snapshot, attr="capital_country_id", next_phase="done")


def _advance_setup_seat_after_unique(snapshot: GameSnapshot, *, attr: str, next_phase: str) -> None:
    players = sorted(snapshot.players.values(), key=lambda p: p.seat_order)
    seat = snapshot.game.setup.active_seat_order
    for _ in range(len(players)):
        seat = (seat + 1) % len(players)
        if getattr(players[seat], attr) is None:
            snapshot.game.setup.active_seat_order = seat
            return
    # Everybody placed.
    snapshot.game.setup.phase = next_phase  # type: ignore[assignment]
    snapshot.game.setup.active_seat_order = 0


def _require_setup_phase(snapshot: GameSnapshot, phase: str) -> None:
    if snapshot.game.setup.phase != phase:
        raise WrongPhase(f"expected setup phase {phase}, got {snapshot.game.setup.phase}")


def _require_active_seat(snapshot: GameSnapshot, actor_id: str) -> None:
    actor = snapshot.players[actor_id]
    if actor.seat_order != snapshot.game.setup.active_seat_order:
        raise NotYourTurn("not your turn in setup")


def _country_state(snapshot: GameSnapshot, country_id: str) -> CountryState:
    if country_id not in snapshot.country_states:
        raise InvalidAction(f"unknown country {country_id}")
    return snapshot.country_states[country_id]
