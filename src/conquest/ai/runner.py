"""AI runner. Drives a single AI through whatever step is currently theirs.

The runner is invoked by the service layer when the active player is AI. It's also used by
the simulation harness to play full games without any HTTP layer.

Three modes (see CLAUDE.md § AI runner):
    - `run_ai_setup_step` — handles the four-phase setup until that AI's seat is no longer
      the active setup seat.
    - `run_ai_turn` — handles one AI turn: place reinforcements, take actions, end turn.
    - `run_ai_until_human` — convenience that keeps invoking AI turns until the active
      player is human or the game ends.

Each call validates and applies actions through the same `apply_action` / `end_turn` paths
as a human submission.
"""
from __future__ import annotations

from collections.abc import Iterable

from conquest.ai.archetypes import policy_for
from conquest.ai.policy import Policy
from conquest.game import setup as setup_engine
from conquest.game import turn as turn_engine
from conquest.game.actions import apply_action
from conquest.game.rng import SeededRNG
from conquest.models.action import (
    PlaceCapital,
    PlaceReinforcements,
    PlaceResearcher,
    PlaceTroop,
)
from conquest.models.player import Player
from conquest.models.snapshot import GameSnapshot
from conquest.models.virus import VirusPhaseResult


def _policy_for_player(player: Player) -> Policy:
    if player.kind != "ai" or player.ai_config is None:
        raise ValueError(f"player {player.player_id} is not AI")
    return policy_for(player.ai_config.archetype)


def run_ai_setup_step(snapshot: GameSnapshot, rng: SeededRNG) -> bool:
    """If the active setup seat is AI, perform one placement.

    Returns True if an action was taken (caller should re-check phase),
    False if the active seat is human or setup is done.
    """
    if snapshot.game.setup.phase == "done":
        return False
    seat = snapshot.game.setup.active_seat_order
    player = snapshot.player_by_seat(seat)
    if player.kind != "ai":
        return False
    policy = _policy_for_player(player)

    if snapshot.game.setup.phase == "troops":
        target = policy.setup_troop_target(snapshot, player.player_id, rng)
        setup_engine.place_troop(snapshot, player.player_id, PlaceTroop(country_id=target))
        return True
    if snapshot.game.setup.phase == "researchers":
        target = policy.setup_researcher_target(snapshot, player.player_id, rng)
        setup_engine.place_researcher(
            snapshot, player.player_id, PlaceResearcher(country_id=target)
        )
        return True
    if snapshot.game.setup.phase == "capitals":
        target = policy.setup_capital_target(snapshot, player.player_id, rng)
        setup_engine.place_capital(
            snapshot, player.player_id, PlaceCapital(country_id=target)
        )
        return True
    return False


def run_ai_turn(snapshot: GameSnapshot, rng: SeededRNG) -> VirusPhaseResult | None:
    """Run a single AI player's full turn. Returns the virus result if end-of-round fires."""
    if snapshot.game.status != "in_progress":
        return None
    player_id = snapshot.game.turn.active_player_id
    if player_id is None:
        return None
    player = snapshot.players[player_id]
    if player.kind != "ai":
        return None
    policy = _policy_for_player(player)

    # Reinforcements sub-phase (auto-place capital bonus already applied at turn start).
    if snapshot.game.turn.reinforcements_to_place > 0:
        placements = policy.reinforce(
            snapshot, player_id, snapshot.game.turn.reinforcements_to_place, rng
        )
        # Fall back: dump everything on the first owned country.
        if not placements:
            owned = snapshot.countries_owned_by(player_id)
            if owned:
                placements = [(owned[0], snapshot.game.turn.reinforcements_to_place)]
        if placements:
            apply_action(
                snapshot,
                player_id,
                PlaceReinforcements(placements=placements),
                rng,
            )

    # Actions sub-phase.
    intents = policy.take_actions(snapshot, player_id, rng)
    for action in _materialize(intents):
        if snapshot.game.status != "in_progress":
            break
        if snapshot.game.turn.actions_remaining <= 0:
            break
        try:
            apply_action(snapshot, player_id, action, rng)
        except Exception:  # noqa: BLE001 — invalid intent: skip rather than crash a sim
            continue

    # End the turn (also runs virus phase if this closes the round).
    if snapshot.game.status != "in_progress":
        return None
    return turn_engine.end_turn(snapshot, player_id, rng)


def run_ai_until_human(snapshot: GameSnapshot, rng: SeededRNG, *, max_iters: int = 100) -> None:
    """Keep running AI turns until the active player is human or the game ends.

    `max_iters` guards against runaway loops (e.g., misconfigured all-AI game using this
    helper instead of the simulation harness).
    """
    for _ in range(max_iters):
        if snapshot.game.status != "in_progress":
            return
        pid = snapshot.game.turn.active_player_id
        if pid is None:
            return
        if snapshot.players[pid].kind != "ai":
            return
        run_ai_turn(snapshot, rng)


def _materialize(intents: Iterable) -> list:  # type: ignore[type-arg]
    """Coerce a Sequence/Iterator of actions into a list."""
    return list(intents)
