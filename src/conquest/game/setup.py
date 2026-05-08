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
    """Seed `countryStates` with one entry per country, all unowned."""
    for cid in snapshot.map.countries:
        snapshot.countryStates[cid] = CountryState(countryId=cid)


def place_troop(snapshot: GameSnapshot, actor_id: str, action: PlaceTroop) -> None:
    """Place one troop. Risk-style claim rule applies until every country has an owner."""
    _require_setup_phase(snapshot, "troops")
    _require_active_seat(snapshot, actor_id)
    state = _country_state(snapshot, action.countryId)
    actor = snapshot.players[actor_id]

    all_claimed = all(s.ownerPlayerId is not None for s in snapshot.countryStates.values())
    if not all_claimed:
        if state.ownerPlayerId is not None:
            # Must place on an unclaimed country first.
            raise CountryNotUnclaimed("must place on an unclaimed country until all are claimed")
    else:
        if state.ownerPlayerId != actor_id:
            raise NotYourCountry("can only reinforce countries you own")

    if state.ownerPlayerId is None:
        state.ownerPlayerId = actor_id
    state.armies += 1
    actor.troopsRemainingToPlace -= 1
    actor.stats.totalArmies += 1
    if state.ownerPlayerId == actor_id:
        # Recount once at the end of placement; here just bump.
        pass

    _advance_setup_seat_after_troop(snapshot)


def _advance_setup_seat_after_troop(snapshot: GameSnapshot) -> None:
    """Move to the next non-eliminated player; if all have placed all troops, advance phase."""
    players = sorted(snapshot.players.values(), key=lambda p: p.seatOrder)
    n = len(players)
    if all(p.troopsRemainingToPlace == 0 for p in players):
        snapshot.game.setup.phase = "disease_seed"
        snapshot.game.setup.activeSeatOrder = 0
        return
    seat = snapshot.game.setup.activeSeatOrder
    for _ in range(n):
        seat = (seat + 1) % n
        if players[seat].troopsRemainingToPlace > 0:
            snapshot.game.setup.activeSeatOrder = seat
            return
    snapshot.game.setup.phase = "disease_seed"
    snapshot.game.setup.activeSeatOrder = 0


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
        cfg.setup_disease_2cube_count : cfg.setup_disease_2cube_count + cfg.setup_disease_1cube_count
    ]
    for cid in two_cube:
        s = snapshot.countryStates[cid]
        s.diseaseCubes = 2
        seeded.append(cid)
    for cid in one_cube:
        s = snapshot.countryStates[cid]
        s.diseaseCubes = 1
        seeded.append(cid)
    snapshot.game.setup.phase = "researchers"
    snapshot.game.setup.activeSeatOrder = 0
    return seeded


def place_researcher(
    snapshot: GameSnapshot, actor_id: str, action: PlaceResearcher
) -> None:
    _require_setup_phase(snapshot, "researchers")
    _require_active_seat(snapshot, actor_id)
    actor = snapshot.players[actor_id]
    if actor.researcherCountryId is not None:
        raise InvalidAction("researcher already placed")
    state = _country_state(snapshot, action.countryId)
    if state.ownerPlayerId != actor_id:
        raise NotYourCountry("researcher must be placed on a country you own")
    actor.researcherCountryId = action.countryId
    state.hasResearcher = actor_id
    _advance_setup_seat_after_unique(snapshot, attr="researcherCountryId", next_phase="capitals")


def place_capital(snapshot: GameSnapshot, actor_id: str, action: PlaceCapital) -> None:
    _require_setup_phase(snapshot, "capitals")
    _require_active_seat(snapshot, actor_id)
    actor = snapshot.players[actor_id]
    if actor.capitalCountryId is not None:
        raise InvalidAction("capital already placed")
    state = _country_state(snapshot, action.countryId)
    if state.ownerPlayerId != actor_id:
        raise NotYourCountry("capital must be on a country you own")
    actor.capitalCountryId = action.countryId
    state.isCapitalOf = actor_id
    _advance_setup_seat_after_unique(snapshot, attr="capitalCountryId", next_phase="done")


def _advance_setup_seat_after_unique(
    snapshot: GameSnapshot, *, attr: str, next_phase: str
) -> None:
    players = sorted(snapshot.players.values(), key=lambda p: p.seatOrder)
    seat = snapshot.game.setup.activeSeatOrder
    for _ in range(len(players)):
        seat = (seat + 1) % len(players)
        if getattr(players[seat], attr) is None:
            snapshot.game.setup.activeSeatOrder = seat
            return
    # Everybody placed.
    snapshot.game.setup.phase = next_phase  # type: ignore[assignment]
    snapshot.game.setup.activeSeatOrder = 0


def _require_setup_phase(snapshot: GameSnapshot, phase: str) -> None:
    if snapshot.game.setup.phase != phase:
        raise WrongPhase(f"expected setup phase {phase}, got {snapshot.game.setup.phase}")


def _require_active_seat(snapshot: GameSnapshot, actor_id: str) -> None:
    actor = snapshot.players[actor_id]
    if actor.seatOrder != snapshot.game.setup.activeSeatOrder:
        raise NotYourTurn("not your turn in setup")


def _country_state(snapshot: GameSnapshot, country_id: str) -> CountryState:
    if country_id not in snapshot.countryStates:
        raise InvalidAction(f"unknown country {country_id}")
    return snapshot.countryStates[country_id]
