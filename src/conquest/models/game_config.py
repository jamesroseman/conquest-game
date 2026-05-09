"""Per-game tuning parameters. See CLAUDE.md § Game configuration."""

from __future__ import annotations

from typing import Literal

from pydantic import Field

from .base import CamelModel


class GameConfig(CamelModel):
    """Gameplay parameters. Persisted verbatim on each game; never changed mid-game."""

    actions_per_turn: int = 5
    starting_troops_per_player: int = 30

    cost_move_researcher_adjacent: int = 1
    cost_airdrop_researcher: int = 2
    cost_cure: int = 1
    cost_create_vaccine: int = 1
    cost_attack: int = 1
    cost_move_troops: int = 1

    setup_disease_2cube_count: int = 3
    setup_disease_1cube_count: int = 7

    max_cubes_per_country: int = 3
    outbreak_loss_threshold: int = 6

    spread_schedule: list[tuple[int, int, int]] = Field(
        default_factory=lambda: [(0, 3, 3), (4, 6, 5), (7, 10, 7)]
    )

    casualty_fraction_one_cube: float = 1 / 3
    casualty_fraction_two_cubes: float = 1 / 2
    casualty_fraction_three_cubes: float = 1.0

    reinforcement_base: int = 10
    reinforcement_per_country: int = 1
    reinforcement_capital_bonus: int = 2
    continent_bonus_pool: int = 12
    continent_bonus_enabled: bool = True

    vaccine_requires_all_researchers: bool = True
    vaccinated_blocks_outbreak_chain: bool = True

    capital_loss_eliminates_player: bool = True
    win_condition: Literal["last_competitor", "capital_control", "score"] = "last_competitor"

    ai_action_delay_ms: int = 0

    def cubes_to_spread(self, outbreak_count: int) -> int:
        """Look up the cube count to add this end-of-round from `spread_schedule`."""
        for lo, hi, cubes in self.spread_schedule:
            if lo <= outbreak_count <= hi:
                return cubes
        return self.spread_schedule[-1][2]
