"""Reinforcement calculation. See CLAUDE.md § Reinforcements."""
from __future__ import annotations

from collections import Counter

from conquest.models.snapshot import GameSnapshot


def compute_reinforcements(snapshot: GameSnapshot, player_id: str) -> int:
    """Total reinforcements at start of `player_id`'s turn.

    Formula:
        base + per_country * countries_owned + sum(continent.bonus_armies for fully-owned)
    """
    cfg = snapshot.game.config
    owned = snapshot.countries_owned_by(player_id)
    total = cfg.reinforcement_base + cfg.reinforcement_per_country * len(owned)
    if cfg.continent_bonus_enabled:
        # Fully-owned continents.
        owned_set = set(owned)
        for cont in snapshot.map.continents.values():
            if cont.country_ids and all(cid in owned_set for cid in cont.country_ids):
                total += cont.bonus_armies
    return total


def apply_capital_bonus(snapshot: GameSnapshot, player_id: str) -> int:
    """Auto-place `reinforcement_capital_bonus` troops on the player's capital.

    Returns the number actually placed (0 if the player has no capital — should not happen post-setup).
    """
    cfg = snapshot.game.config
    actor = snapshot.players[player_id]
    if actor.capital_country_id is None:
        return 0
    cap_state = snapshot.country_states[actor.capital_country_id]
    cap_state.armies += cfg.reinforcement_capital_bonus
    actor.stats.total_armies += cfg.reinforcement_capital_bonus
    return cfg.reinforcement_capital_bonus


def recompute_player_stats(snapshot: GameSnapshot) -> None:
    """Refresh `Player.stats` from authoritative `country_states`."""
    counts: Counter[str] = Counter()
    armies: Counter[str] = Counter()
    for s in snapshot.country_states.values():
        if s.owner_player_id is not None:
            counts[s.owner_player_id] += 1
            armies[s.owner_player_id] += s.armies
    for p in snapshot.players.values():
        p.stats.countries_owned = counts.get(p.player_id, 0)
        p.stats.total_armies = armies.get(p.player_id, 0)
