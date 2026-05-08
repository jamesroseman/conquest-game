"""4-phase setup state machine."""
from __future__ import annotations

from conquest.game import setup as setup_engine
from conquest.game.rng import SeededRNG
from conquest.models.action import PlaceCapital, PlaceResearcher, PlaceTroop
from conquest.services.game_service import GameService


def _two_player_game(svc: GameService):  # type: ignore[no-untyped-def]
    g = svc.create_game(owner_user_id="u1", owner_display_name="A", seed=1)
    svc.add_ai_seat(game_id=g.gameId, owner_user_id="u1", archetype="aggressor")
    snap = svc.start_game(game_id=g.gameId, owner_user_id="u1")
    return snap


def test_first_country_claim_changes_owner(game_service: GameService) -> None:
    snap = _two_player_game(game_service)
    seat0 = next(p for p in snap.players.values() if p.seatOrder == 0)
    target = next(iter(snap.map.countries))
    setup_engine.place_troop(snap, seat0.playerId, PlaceTroop(countryId=target))
    assert snap.countryStates[target].ownerPlayerId == seat0.playerId
    assert snap.countryStates[target].armies == 1


def test_setup_advances_through_all_phases(game_service: GameService) -> None:
    snap = _two_player_game(game_service)
    rng = SeededRNG(snap.game.rngSeed)
    countries = list(snap.map.countries.keys())

    seat0 = next(p for p in snap.players.values() if p.seatOrder == 0)
    seat1 = next(p for p in snap.players.values() if p.seatOrder == 1)
    players = [seat0, seat1]

    # Phase 1: troops. Each places `starting_troops_per_player` (default 30) troops, alternating.
    n_per = snap.game.config.starting_troops_per_player
    total = n_per * 2
    # Round-robin: until all countries claimed at least once we must go to fresh countries.
    n_countries = len(countries)
    placed = 0
    seat = 0
    while snap.game.setup.phase == "troops":
        actor = players[seat]
        if placed < n_countries:
            target = countries[placed]
        else:
            # After all countries claimed, place on a country owned by `actor`.
            owned = [
                cid for cid, s in snap.countryStates.items() if s.ownerPlayerId == actor.playerId
            ]
            target = owned[0]
        setup_engine.place_troop(snap, actor.playerId, PlaceTroop(countryId=target))
        placed += 1
        seat = snap.game.setup.activeSeatOrder

    assert snap.game.setup.phase == "disease_seed"
    assert sum(p.troopsRemainingToPlace for p in snap.players.values()) == 0
    assert sum(s.armies for s in snap.countryStates.values()) == total

    # Phase 2: server-driven seeding.
    seeded = setup_engine.seed_disease(snap, rng)
    cfg = snap.game.config
    assert len(seeded) == cfg.setup_disease_2cube_count + cfg.setup_disease_1cube_count
    assert sum(s.diseaseCubes for s in snap.countryStates.values()) == (
        cfg.setup_disease_2cube_count * 2 + cfg.setup_disease_1cube_count * 1
    )
    assert snap.game.setup.phase == "researchers"

    # Phase 3: researchers — each on a country they own.
    for seat_i in (0, 1):
        actor = players[seat_i]
        owned = next(
            cid
            for cid, s in snap.countryStates.items()
            if s.ownerPlayerId == actor.playerId
        )
        setup_engine.place_researcher(snap, actor.playerId, PlaceResearcher(countryId=owned))
    assert snap.game.setup.phase == "capitals"

    # Phase 4: capitals.
    for seat_i in (0, 1):
        actor = players[seat_i]
        owned = next(
            cid
            for cid, s in snap.countryStates.items()
            if s.ownerPlayerId == actor.playerId
        )
        setup_engine.place_capital(snap, actor.playerId, PlaceCapital(countryId=owned))
    assert snap.game.setup.phase == "done"
    # Each player has researcher and capital.
    for p in snap.players.values():
        assert p.researcherCountryId is not None
        assert p.capitalCountryId is not None
