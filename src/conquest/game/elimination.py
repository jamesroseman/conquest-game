"""Capital-conquest cascade. See CLAUDE.md § Player elimination — capital conquest."""
from __future__ import annotations

from conquest.models.snapshot import GameSnapshot


def eliminate_player(
    snapshot: GameSnapshot,
    *,
    eliminated_id: str,
    conqueror_id: str,
    round_number: int,
) -> None:
    """Hand all of eliminated's countries to the conqueror, clear the researcher and capital flag.

    See CLAUDE.md § Player elimination — capital conquest. Mid-turn elimination can satisfy
    the win condition; that check is the caller's responsibility (turn module).
    """
    eliminated = snapshot.players[eliminated_id]
    if eliminated.eliminated:
        return
    eliminated.eliminated = True
    eliminated.eliminatedByPlayerId = conqueror_id
    eliminated.eliminatedAtRound = round_number

    # Transfer all owned countries.
    for state in snapshot.countryStates.values():
        if state.ownerPlayerId == eliminated_id:
            state.ownerPlayerId = conqueror_id
        if state.isCapitalOf == eliminated_id:
            state.isCapitalOf = None
        if state.hasResearcher == eliminated_id:
            state.hasResearcher = None

    eliminated.researcherCountryId = None
    eliminated.capitalCountryId = None

    # Recompute active player order.
    snapshot.game.activePlayerOrder = [
        p.playerId
        for p in sorted(snapshot.players.values(), key=lambda p: p.seatOrder)
        if not p.eliminated
    ]


def check_win_condition(snapshot: GameSnapshot) -> str | None:
    """Return the winner's playerId if the configured win condition is satisfied; else None."""
    cfg = snapshot.game.config
    alive = [p for p in snapshot.players.values() if not p.eliminated]
    if cfg.win_condition == "last_competitor":
        if len(alive) == 1:
            return alive[0].playerId
    elif cfg.win_condition == "capital_control":
        # Single owner of all capitals (proxy: only one alive with a capital).
        capital_owners = {s.isCapitalOf for s in snapshot.countryStates.values() if s.isCapitalOf}
        if len(capital_owners) == 1:
            return next(iter(capital_owners))
    return None
