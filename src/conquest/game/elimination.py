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
    eliminated.eliminated_by_player_id = conqueror_id
    eliminated.eliminated_at_round = round_number

    # Transfer all owned countries.
    for state in snapshot.country_states.values():
        if state.owner_player_id == eliminated_id:
            state.owner_player_id = conqueror_id
        if state.is_capital_of == eliminated_id:
            state.is_capital_of = None
        if state.has_researcher == eliminated_id:
            state.has_researcher = None

    eliminated.researcher_country_id = None
    eliminated.capital_country_id = None

    # Recompute active player order.
    snapshot.game.active_player_order = [
        p.player_id
        for p in sorted(snapshot.players.values(), key=lambda p: p.seat_order)
        if not p.eliminated
    ]


def check_win_condition(snapshot: GameSnapshot) -> str | None:
    """Return the winner's player_id if the configured win condition is satisfied; else None."""
    cfg = snapshot.game.config
    alive = [p for p in snapshot.players.values() if not p.eliminated]
    if cfg.win_condition == "last_competitor":
        if len(alive) == 1:
            return alive[0].player_id
    elif cfg.win_condition == "capital_control":
        # Single owner of all capitals (proxy: only one alive with a capital).
        capital_owners = {s.is_capital_of for s in snapshot.country_states.values() if s.is_capital_of}
        if len(capital_owners) == 1:
            return next(iter(capital_owners))
    return None
