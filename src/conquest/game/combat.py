"""Risk-style dice combat.

Resolution (open design question § Combat resolution — using Risk dice for v1):
    - Attacker rolls min(armies, 3) dice; defender rolls min(armies, 2).
    - Pair dice high-to-high. Attacker must beat defender; ties go to defender.
    - Repeat until attacker withdraws (caller's responsibility), attacker has 1 left, or
      defender has 0 left. v1: resolves the entire engagement in one shot using all attacker
      armies committed via the action.

If defender hits 0, attacker captures the country with `attacker_committed - attacker_losses`
troops, leaving 1 troop on the source country's pre-attack remainder.
"""

from __future__ import annotations

from dataclasses import dataclass

from conquest.game.rng import SeededRNG


@dataclass
class CombatResult:
    attacker_losses: int
    defender_losses: int
    attacker_remaining: int
    defender_remaining: int
    captured: bool


def resolve_attack(
    rng: SeededRNG,
    *,
    attacker_armies: int,
    defender_armies: int,
) -> CombatResult:
    """Run a Risk-style engagement. `attacker_armies` are the troops actually committed."""
    if attacker_armies < 1:
        return CombatResult(0, 0, attacker_armies, defender_armies, captured=False)

    a_losses = 0
    d_losses = 0
    a = attacker_armies
    d = defender_armies

    while a >= 1 and d >= 1:
        a_dice = sorted([rng.randint(1, 6) for _ in range(min(3, a))], reverse=True)
        d_dice = sorted([rng.randint(1, 6) for _ in range(min(2, d))], reverse=True)
        for ad, dd in zip(a_dice, d_dice, strict=False):
            if ad > dd:
                d -= 1
                d_losses += 1
            else:
                a -= 1
                a_losses += 1

    captured = d == 0 and a >= 1
    return CombatResult(
        attacker_losses=a_losses,
        defender_losses=d_losses,
        attacker_remaining=a,
        defender_remaining=d,
        captured=captured,
    )
