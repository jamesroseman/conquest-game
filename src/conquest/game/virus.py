"""End-of-round virus phase. See CLAUDE.md § End-of-round virus phase.

Two steps in order:
    1. Apply army casualties on every country with cubes (round DOWN; min 0).
    2. Place new cubes on uniformly-random unvaccinated countries, with outbreak chains.
"""
from __future__ import annotations

import math

from conquest.game.rng import SeededRNG
from conquest.models.country_state import CountryState
from conquest.models.snapshot import GameSnapshot
from conquest.models.virus import (
    CasualtyEvent,
    CubePlacement,
    Outbreak,
    VirusPhaseResult,
)


def run_virus_phase(snapshot: GameSnapshot, rng: SeededRNG) -> VirusPhaseResult:
    """Execute the end-of-round virus phase. Mutates snapshot in place."""
    cfg = snapshot.game.config
    result = VirusPhaseResult()

    # Step 1: casualties.
    for cid, state in snapshot.country_states.items():
        if state.disease_cubes <= 0 or state.armies <= 0:
            continue
        if state.disease_cubes == 1:
            frac = cfg.casualty_fraction_one_cube
        elif state.disease_cubes == 2:
            frac = cfg.casualty_fraction_two_cubes
        else:
            frac = cfg.casualty_fraction_three_cubes
        loss = math.floor(state.armies * frac)
        loss = max(0, min(state.armies, loss))
        if loss > 0:
            result.casualties.append(
                CasualtyEvent(
                    country_id=cid,
                    cubes=state.disease_cubes,
                    armies_before=state.armies,
                    armies_lost=loss,
                )
            )
            state.armies -= loss

    # Step 2: place cubes.
    cube_count = cfg.cubes_to_spread(snapshot.game.outbreaks.count)
    eligible = [
        cid for cid, s in snapshot.country_states.items() if not s.vaccinated
    ]
    if not eligible:
        return result

    for _ in range(cube_count):
        target = rng.choice(eligible)
        outbreak_set: set[str] = set()
        _place_or_outbreak(snapshot, target, result, outbreak_set, rng)
        if snapshot.game.outbreaks.count >= cfg.outbreak_loss_threshold:
            result.game_ended = True
            snapshot.game.status = "ended"
            snapshot.game.ended_reason = "outbreak_limit"
            return result
    return result


def _place_or_outbreak(
    snapshot: GameSnapshot,
    target_id: str,
    result: VirusPhaseResult,
    already_outbroken: set[str],
    rng: SeededRNG,
) -> None:
    cfg = snapshot.game.config
    state = snapshot.country_states[target_id]
    if state.vaccinated:
        return
    if state.disease_cubes < cfg.max_cubes_per_country:
        state.disease_cubes += 1
        result.placements.append(CubePlacement(country_id=target_id, triggered_outbreak=False))
        return

    # OUTBREAK: each unvaccinated neighbor gains 1 cube; chain limited to once per country
    # per virus phase.
    if target_id in already_outbroken:
        return
    already_outbroken.add(target_id)
    snapshot.game.outbreaks.count += 1
    chained: list[str] = []
    for nid in snapshot.map.neighbors(target_id):
        nstate = snapshot.country_states[nid]
        if nstate.vaccinated:
            continue
        chained.append(nid)
        if cfg.vaccinated_blocks_outbreak_chain and nstate.vaccinated:
            continue
        if nstate.disease_cubes < cfg.max_cubes_per_country:
            nstate.disease_cubes += 1
            result.placements.append(CubePlacement(country_id=nid, triggered_outbreak=False))
        else:
            # Chained outbreak.
            _place_or_outbreak(snapshot, nid, result, already_outbroken, rng)

    from conquest.models.game import OutbreakHistoryEntry  # local to avoid cycle

    result.outbreaks.append(Outbreak(origin_country_id=target_id, chained_country_ids=chained))
    snapshot.game.outbreaks.history.append(
        OutbreakHistoryEntry(
            round_number=snapshot.game.turn.round_number,
            origin_country_id=target_id,
            chained_country_ids=chained,
        )
    )


def initial_country_state(country_id: str) -> CountryState:
    return CountryState(country_id=country_id)
