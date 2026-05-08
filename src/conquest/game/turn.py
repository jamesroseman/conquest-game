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
    snapshot.game.activePlayerOrder = [
        p.playerId
        for p in sorted(snapshot.players.values(), key=lambda p: p.seatOrder)
        if not p.eliminated
    ]
    snapshot.game.turn.roundNumber = 1
    snapshot.game.turn.turnNumber = 1
    snapshot.game.turn.activePlayerId = snapshot.game.activePlayerOrder[0]
    _start_turn(snapshot)


def _start_turn(snapshot: GameSnapshot) -> None:
    """Compute reinforcements + auto-place capital bonus, set sub-phase to reinforcements."""
    cfg = snapshot.game.config
    pid = snapshot.game.turn.activePlayerId
    assert pid is not None
    total = compute_reinforcements(snapshot, pid)
    placed_to_capital = apply_capital_bonus(snapshot, pid)
    snapshot.game.turn.reinforcementsToPlace = max(0, total - placed_to_capital)
    snapshot.game.turn.actionsRemaining = cfg.actions_per_turn
    snapshot.game.turn.phase = "reinforcements" if snapshot.game.turn.reinforcementsToPlace > 0 else "actions"


def end_turn(snapshot: GameSnapshot, actor_id: str, rng: SeededRNG) -> VirusPhaseResult | None:
    """Voluntarily end your turn early. Returns virus result if this end-of-turn closes the round.

    A player may end their turn at any time after reinforcements have been placed (even if they
    have actions remaining).
    """
    if snapshot.game.status != "in_progress":
        raise WrongPhase("game not in progress")
    if snapshot.game.turn.activePlayerId != actor_id:
        raise NotYourTurn("not your turn")
    if snapshot.game.turn.reinforcementsToPlace > 0:
        raise ReinforcementsNotPlaced("place all reinforcements before ending turn")

    return _advance_to_next_turn(snapshot, rng)


def _advance_to_next_turn(snapshot: GameSnapshot, rng: SeededRNG) -> VirusPhaseResult | None:
    """Move to next non-eliminated player; if we wrap, run virus phase."""
    order = [
        p.playerId
        for p in sorted(snapshot.players.values(), key=lambda p: p.seatOrder)
        if not p.eliminated
    ]
    snapshot.game.activePlayerOrder = order

    if not order:
        # Everyone eliminated — that's a draw / game already ended.
        return None

    current = snapshot.game.turn.activePlayerId
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
            snapshot.game.turn.activePlayerId = None
            return virus_result
        snapshot.game.turn.roundNumber += 1
        next_idx = 0

    # Win condition check (e.g., elimination cascade earlier this turn already eliminated others).
    winner = check_win_condition(snapshot)
    if winner is not None:
        snapshot.game.status = "ended"
        snapshot.game.endedReason = "victory"
        snapshot.game.winnerPlayerId = winner
        snapshot.game.turn.activePlayerId = None
        return virus_result

    snapshot.game.turn.activePlayerId = order[next_idx]
    snapshot.game.turn.turnNumber += 1
    _start_turn(snapshot)
    return virus_result
