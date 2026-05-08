"""Reinforcement calculation. See CLAUDE.md § Reinforcements."""
from __future__ import annotations

from collections import Counter

from conquest.models.snapshot import GameSnapshot


def compute_reinforcements(snapshot: GameSnapshot, player_id: str) -> int:
    """Total reinforcements at start of `player_id`'s turn.

    Formula:
        base + per_country * countries_owned + sum(continent.bonusArmies for fully-owned)
    """
    cfg = snapshot.game.config
    owned = snapshot.countries_owned_by(player_id)
    total = cfg.reinforcement_base + cfg.reinforcement_per_country * len(owned)
    if cfg.continent_bonus_enabled:
        # Fully-owned continents.
        owned_set = set(owned)
        for cont in snapshot.map.continents.values():
            if cont.countryIds and all(cid in owned_set for cid in cont.countryIds):
                total += cont.bonusArmies
    return total


def apply_capital_bonus(snapshot: GameSnapshot, player_id: str) -> int:
    """Auto-place `reinforcement_capital_bonus` troops on the player's capital.

    Returns the number actually placed (0 if the player has no capital — should not happen post-setup).
    """
    cfg = snapshot.game.config
    actor = snapshot.players[player_id]
    if actor.capitalCountryId is None:
        return 0
    cap_state = snapshot.countryStates[actor.capitalCountryId]
    cap_state.armies += cfg.reinforcement_capital_bonus
    actor.stats.totalArmies += cfg.reinforcement_capital_bonus
    return cfg.reinforcement_capital_bonus


def recompute_player_stats(snapshot: GameSnapshot) -> None:
    """Refresh `Player.stats` from authoritative `countryStates`."""
    counts: Counter[str] = Counter()
    armies: Counter[str] = Counter()
    for s in snapshot.countryStates.values():
        if s.ownerPlayerId is not None:
            counts[s.ownerPlayerId] += 1
            armies[s.ownerPlayerId] += s.armies
    for p in snapshot.players.values():
        p.stats.countriesOwned = counts.get(p.playerId, 0)
        p.stats.totalArmies = armies.get(p.playerId, 0)
