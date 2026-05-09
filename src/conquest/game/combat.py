"""Risk-style dice combat with explicit per-round breakdown.

Each round both sides roll up to 6 dice (one per committed troop, capped at 6).
Dice are paired high-to-high; ties go to the defender. The round records the
losses on each side so the UI can animate them. Combat continues until either
the attacker has 0 troops left or the defender has 0 — there is no "withdraw"
mechanic in v1.

If the defender hits 0, the attacker captures the country with the surviving
attacker armies; otherwise the surviving attackers retreat home.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from conquest.game.rng import SeededRNG

# Each round both sides commit up to this many troops to the dice. The user-
# visible damage cap per country per round is therefore 6.
DICE_PER_ROUND = 6


@dataclass
class CombatRound:
    attacker_losses: int
    defender_losses: int
    attacker_after: int
    defender_after: int


@dataclass
class CombatResult:
    rounds: list[CombatRound] = field(default_factory=list)
    attacker_losses: int = 0
    defender_losses: int = 0
    attacker_remaining: int = 0
    defender_remaining: int = 0
    captured: bool = False


def resolve_attack(
    rng: SeededRNG,
    *,
    attacker_armies: int,
    defender_armies: int,
) -> CombatResult:
    """Run a full engagement until one side is depleted. `attacker_armies`
    are the troops actually committed to the assault."""
    if attacker_armies < 1:
        return CombatResult(
            attacker_remaining=attacker_armies,
            defender_remaining=defender_armies,
        )

    a = attacker_armies
    d = defender_armies
    rounds: list[CombatRound] = []

    while a >= 1 and d >= 1:
        a_dice_count = min(DICE_PER_ROUND, a)
        d_dice_count = min(DICE_PER_ROUND, d)
        a_dice = sorted([rng.randint(1, 6) for _ in range(a_dice_count)], reverse=True)
        d_dice = sorted([rng.randint(1, 6) for _ in range(d_dice_count)], reverse=True)
        a_round_losses = 0
        d_round_losses = 0
        for ad, dd in zip(a_dice, d_dice, strict=False):
            if ad > dd:
                d_round_losses += 1
            else:
                a_round_losses += 1
        a -= a_round_losses
        d -= d_round_losses
        rounds.append(
            CombatRound(
                attacker_losses=a_round_losses,
                defender_losses=d_round_losses,
                attacker_after=a,
                defender_after=d,
            )
        )

    captured = d == 0 and a >= 1
    return CombatResult(
        rounds=rounds,
        attacker_losses=sum(r.attacker_losses for r in rounds),
        defender_losses=sum(r.defender_losses for r in rounds),
        attacker_remaining=a,
        defender_remaining=d,
        captured=captured,
    )
