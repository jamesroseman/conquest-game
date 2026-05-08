"""All-AI simulation harness. Plays a full game from creation to end_state.

Used for balance work: parameter sweeps over `GameConfig`, archetype matchups, sanity bands.

Bypasses the GraphQL/REST layers; talks directly to the rules engine for speed.
"""

from __future__ import annotations

import time
import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime

from conquest.ai.archetypes import policy_for
from conquest.ai.runner import run_ai_setup_step, run_ai_turn
from conquest.game.map_gen import generate_map
from conquest.game.rng import SeededRNG
from conquest.game.setup import initialize_country_states
from conquest.game.turn import begin_first_turn
from conquest.models.game import Game, SetupState, TurnState
from conquest.models.game_config import GameConfig
from conquest.models.map import MapGenParams
from conquest.models.player import AIConfig, Player
from conquest.models.snapshot import GameSnapshot

PLAYER_COLORS = ["#d23", "#39d", "#3a8", "#fb3", "#92c", "#666"]


@dataclass
class GameOutcome:
    seed: int
    archetypes: list[str]
    rounds_played: int
    winner_archetype: str | None
    ended_reason: str | None
    outbreaks: int
    elapsed_ms: float


def build_simulation_snapshot(
    *,
    seed: int,
    archetypes: Sequence[str],
    config: GameConfig | None = None,
) -> GameSnapshot:
    """Build a fully-set-up `GameSnapshot` ready for `run_ai_turn` to take over."""
    if not 2 <= len(archetypes) <= 6:
        raise ValueError("archetypes must contain 2..6 entries")
    cfg = config or GameConfig()
    params = MapGenParams.for_player_count(seed=seed, player_count=len(archetypes))
    m = generate_map(params)
    now = datetime.now(UTC)
    game = Game(
        game_id=f"sim_{uuid.uuid4().hex[:8]}",
        map_id=m.map_id,
        name="sim",
        config=cfg,
        status="placing_troops",
        created_at=now,
        updated_at=now,
        rng_seed=seed,
        owner_user_id="sim",
        setup=SetupState(phase="troops", active_seat_order=0),
        turn=TurnState(),
    )
    players: dict[str, Player] = {}
    for i, archetype in enumerate(archetypes):
        pid = f"p{i}"
        players[pid] = Player(
            player_id=pid,
            seat_order=i,
            color=PLAYER_COLORS[i % len(PLAYER_COLORS)],
            kind="ai",
            ai_config=AIConfig(archetype=archetype, seed=seed + i),  # type: ignore[arg-type]
            troops_remaining_to_place=cfg.starting_troops_per_player,
        )
    game.player_ids = list(players.keys())
    game.player_count = len(players)
    snapshot = GameSnapshot(game=game, map=m, players=players)
    initialize_country_states(snapshot)
    return snapshot


def run_simulation(
    *,
    seed: int,
    archetypes: Sequence[str],
    config: GameConfig | None = None,
    max_rounds: int = 200,
) -> GameOutcome:
    """Play one all-AI game to completion. Returns a structured outcome row."""
    t0 = time.perf_counter()
    try:
        snap = build_simulation_snapshot(seed=seed, archetypes=archetypes, config=config)
    except RuntimeError:
        # Map-gen exhausted its retry budget for this seed/params combo; surface as a
        # known terminal outcome rather than letting the harness crash.
        return GameOutcome(
            seed=seed,
            archetypes=list(archetypes),
            rounds_played=0,
            winner_archetype=None,
            ended_reason="map_gen_failed",
            outbreaks=0,
            elapsed_ms=(time.perf_counter() - t0) * 1000,
        )
    rng = SeededRNG(seed)

    # Drive setup to completion via the same setup hooks used in production.
    # Keep stepping until phase=="done"; each step performs one AI placement and may
    # auto-advance the phase (e.g., disease seeding is server-driven inside place_troop's
    # phase transition, but we run it explicitly here).
    from conquest.game import setup as setup_engine

    for _ in range(snap.game.config.starting_troops_per_player * len(archetypes) * 2 + 200):
        if snap.game.setup.phase == "done":
            break
        if snap.game.setup.phase == "disease_seed":
            setup_engine.seed_disease(snap, rng)
            continue
        moved = run_ai_setup_step(snap, rng)
        if not moved:
            # All-AI setup means every seat is AI; if we can't step, we're stuck.
            break

    if snap.game.setup.phase != "done":
        # Couldn't finish setup deterministically; bail.
        return GameOutcome(
            seed=seed,
            archetypes=list(archetypes),
            rounds_played=0,
            winner_archetype=None,
            ended_reason="setup_failed",
            outbreaks=snap.game.outbreaks.count,
            elapsed_ms=(time.perf_counter() - t0) * 1000,
        )

    begin_first_turn(snap)

    # Now play AI turns until the game ends.
    rounds_played = 0
    while snap.game.status == "in_progress" and rounds_played < max_rounds:
        run_ai_turn(snap, rng)
        rounds_played = snap.game.turn.round_number
        if snap.game.status == "ended":
            break

    winner_archetype: str | None = None
    if snap.game.winner_player_id is not None:
        wp = snap.players[snap.game.winner_player_id]
        if wp.ai_config is not None:
            winner_archetype = wp.ai_config.archetype

    return GameOutcome(
        seed=seed,
        archetypes=list(archetypes),
        rounds_played=rounds_played,
        winner_archetype=winner_archetype,
        ended_reason=snap.game.ended_reason
        or ("max_rounds" if rounds_played >= max_rounds else None),
        outbreaks=snap.game.outbreaks.count,
        elapsed_ms=(time.perf_counter() - t0) * 1000,
    )


def _policy_archetype(archetype: str) -> str:
    """Force a `KeyError` early if the caller passed an unknown archetype."""
    policy_for(archetype)
    return archetype
