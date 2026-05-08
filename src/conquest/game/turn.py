"""Round + turn state machine. See CLAUDE.md § Round structure.

A round = pass through all non-eliminated players in seat order, then virus phase.
A turn = one player's reinforcements sub-phase + actions sub-phase, ending with `end_turn`.
"""

from __future__ import annotations

from conquest.game.elimination import check_win_condition
from conquest.game.errors import (
    NotYourTurn,
    ReinforcementsNotPlaced,
    WrongPhase,
)
from conquest.game.reinforcements import apply_capital_bonus, compute_reinforcements
from conquest.game.rng import SeededRNG
from conquest.game.virus import run_virus_phase
from conquest.models.snapshot import GameSnapshot
from conquest.models.virus import VirusPhaseResult


def begin_first_turn(snapshot: GameSnapshot) -> None:
    """Setup is done; start the very first player turn."""
    snapshot.game.status = "in_progress"
    snapshot.game.active_player_order = [
        p.player_id
        for p in sorted(snapshot.players.values(), key=lambda p: p.seat_order)
        if not p.eliminated
    ]
    snapshot.game.turn.round_number = 1
    snapshot.game.turn.turn_number = 1
    snapshot.game.turn.active_player_id = snapshot.game.active_player_order[0]
    _start_turn(snapshot)


def _start_turn(snapshot: GameSnapshot) -> None:
    """Compute reinforcements + auto-place capital bonus, set sub-phase to reinforcements."""
    cfg = snapshot.game.config
    pid = snapshot.game.turn.active_player_id
    assert pid is not None
    total = compute_reinforcements(snapshot, pid)
    placed_to_capital = apply_capital_bonus(snapshot, pid)
    snapshot.game.turn.reinforcements_to_place = max(0, total - placed_to_capital)
    snapshot.game.turn.actions_remaining = cfg.actions_per_turn
    snapshot.game.turn.phase = (
        "reinforcements" if snapshot.game.turn.reinforcements_to_place > 0 else "actions"
    )


def end_turn(snapshot: GameSnapshot, actor_id: str, rng: SeededRNG) -> VirusPhaseResult | None:
    """Voluntarily end your turn early. Returns virus result if this end-of-turn closes the round.

    A player may end their turn at any time after reinforcements have been placed (even if they
    have actions remaining).
    """
    if snapshot.game.status != "in_progress":
        raise WrongPhase("game not in progress")
    if snapshot.game.turn.active_player_id != actor_id:
        raise NotYourTurn("not your turn")
    if snapshot.game.turn.reinforcements_to_place > 0:
        raise ReinforcementsNotPlaced("place all reinforcements before ending turn")

    return _advance_to_next_turn(snapshot, rng)


def _advance_to_next_turn(snapshot: GameSnapshot, rng: SeededRNG) -> VirusPhaseResult | None:
    """Move to next non-eliminated player; if we wrap, run virus phase."""
    order = [
        p.player_id
        for p in sorted(snapshot.players.values(), key=lambda p: p.seat_order)
        if not p.eliminated
    ]
    snapshot.game.active_player_order = order

    if not order:
        # Everyone eliminated — that's a draw / game already ended.
        return None

    current = snapshot.game.turn.active_player_id
    try:
        idx = order.index(current) if current in order else -1
    except ValueError:
        idx = -1

    next_idx = idx + 1
    virus_result: VirusPhaseResult | None = None

    if next_idx >= len(order):
        # End of round: run virus phase.
        snapshot.game.turn.phase = "virus"
        virus_result = run_virus_phase(snapshot, rng)
        if snapshot.game.status == "ended":
            snapshot.game.turn.active_player_id = None
            return virus_result
        snapshot.game.turn.round_number += 1
        next_idx = 0

    # Win condition check (e.g., elimination cascade earlier this turn already eliminated others).
    winner = check_win_condition(snapshot)
    if winner is not None:
        snapshot.game.status = "ended"
        snapshot.game.ended_reason = "victory"
        snapshot.game.winner_player_id = winner
        snapshot.game.turn.active_player_id = None
        return virus_result

    snapshot.game.turn.active_player_id = order[next_idx]
    snapshot.game.turn.turn_number += 1
    _start_turn(snapshot)
    return virus_result
