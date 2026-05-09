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

from collections.abc import Callable, Iterable
from typing import Any

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


def run_ai_setup_step(
    snapshot: GameSnapshot,
    rng: SeededRNG,
    *,
    on_event: Callable[[str, str | None, dict[str, Any]], None] | None = None,
) -> bool:
    """If the active setup seat is AI, perform one placement.

    `on_event(type, actor, payload)` is invoked after the snapshot is mutated
    so the service layer can append an entry to the event log AND persist
    the snapshot. Without this, AI setup placements would be invisible to
    the live HUD — they'd just appear in the next polled snapshot with no
    explanation of who placed where.

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
        action = PlaceTroop(country_id=target)
        setup_engine.place_troop(snapshot, player.player_id, action)
        if on_event:
            on_event("place_troop", player.player_id, action.model_dump())
        return True
    if snapshot.game.setup.phase == "researchers":
        target = policy.setup_researcher_target(snapshot, player.player_id, rng)
        action_r = PlaceResearcher(country_id=target)
        setup_engine.place_researcher(snapshot, player.player_id, action_r)
        if on_event:
            on_event("place_researcher", player.player_id, action_r.model_dump())
        return True
    if snapshot.game.setup.phase == "capitals":
        target = policy.setup_capital_target(snapshot, player.player_id, rng)
        action_c = PlaceCapital(country_id=target)
        setup_engine.place_capital(snapshot, player.player_id, action_c)
        if on_event:
            on_event("place_capital", player.player_id, action_c.model_dump())
        return True
    return False


StepEvent = tuple[str, str | None, dict[str, Any]]


def run_ai_turn(
    snapshot: GameSnapshot,
    rng: SeededRNG,
    *,
    on_step: Callable[[GameSnapshot, StepEvent | None], None] | None = None,
) -> VirusPhaseResult | None:
    """Run a single AI player's full turn. Returns the virus result if end-of-round fires.

    `on_step` (optional): invoked after each mutation. The second argument
    describes the event the caller should append to the log:
    `(event_type, actor_player_id, payload_dict)`, or None for a no-event
    bookkeeping save. The service layer uses this to (a) emit events for
    AI actions (so the player sees the bot move in the EventLog) and
    (b) sleep + persist between actions to pace the playback.
    """
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
        if not placements:
            owned = snapshot.countries_owned_by(player_id)
            if owned:
                placements = [(owned[0], snapshot.game.turn.reinforcements_to_place)]
        if placements:
            reinforce_action = PlaceReinforcements(placements=placements)
            extras = apply_action(snapshot, player_id, reinforce_action, rng)
            if on_step is not None:
                on_step(
                    snapshot,
                    (
                        "place_reinforcements",
                        player_id,
                        {**reinforce_action.model_dump(), **extras},
                    ),
                )

    # Actions sub-phase.
    intents = policy.take_actions(snapshot, player_id, rng)
    for action in _materialize(intents):
        if snapshot.game.status != "in_progress":
            break
        if snapshot.game.turn.actions_remaining <= 0:
            break
        try:
            extras = apply_action(snapshot, player_id, action, rng)
        except Exception:  # noqa: BLE001 — invalid intent: skip rather than crash a sim
            continue
        if on_step is not None:
            on_step(
                snapshot,
                (str(action.type), player_id, {**action.model_dump(), **extras}),
            )

    # End the turn (also runs virus phase if this closes the round).
    if snapshot.game.status != "in_progress":
        return None
    result = turn_engine.end_turn(snapshot, player_id, rng)
    if on_step is not None:
        on_step(snapshot, ("turn_ended", player_id, {}))
        if result is not None:
            on_step(
                snapshot,
                ("round_end_virus", None, _virus_payload(result)),
            )
    return result


def _virus_payload(result: VirusPhaseResult) -> dict[str, Any]:
    """Flatten a VirusPhaseResult into a JSON-friendly dict for the event log.

    The web client unpacks this to drive country-by-country damage and
    cube-spread animations during the virus phase playback.
    """
    return {
        "casualties": [
            {
                "country_id": c.country_id,
                "cubes": c.cubes,
                "armies_before": c.armies_before,
                "armies_lost": c.armies_lost,
            }
            for c in result.casualties
        ],
        "placements": [
            {
                "country_id": p.country_id,
                "triggered_outbreak": p.triggered_outbreak,
            }
            for p in result.placements
        ],
        "outbreaks": [
            {
                "origin_country_id": o.origin_country_id,
                "chained_country_ids": list(o.chained_country_ids),
            }
            for o in result.outbreaks
        ],
        "game_ended": result.game_ended,
    }


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
