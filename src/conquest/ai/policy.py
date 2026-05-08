"""Policy protocol — every AI archetype implements this.

Policies emit *intents*. The rules engine validates and applies them as if a human had
submitted them; there is no AI-only code path through the rules engine
(see CLAUDE.md § AI players).
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol

from conquest.game.rng import SeededRNG
from conquest.models.action import Action
from conquest.models.snapshot import GameSnapshot


class Policy(Protocol):
    archetype: str

    def setup_troop_target(self, snapshot: GameSnapshot, player_id: str, rng: SeededRNG) -> str:
        """Return the country_id where this AI should place its next setup troop."""
        ...

    def setup_researcher_target(
        self, snapshot: GameSnapshot, player_id: str, rng: SeededRNG
    ) -> str:
        """Return the country_id (must be owned) for the researcher placement."""
        ...

    def setup_capital_target(self, snapshot: GameSnapshot, player_id: str, rng: SeededRNG) -> str:
        """Return the country_id (must be owned) for the capital placement."""
        ...

    def reinforce(
        self, snapshot: GameSnapshot, player_id: str, total: int, rng: SeededRNG
    ) -> list[tuple[str, int]]:
        """Return (country_id, count) placements summing to `total`."""
        ...

    def take_actions(
        self, snapshot: GameSnapshot, player_id: str, rng: SeededRNG
    ) -> Sequence[Action]:
        """Yield up to `actions_remaining` actions. The runner stops at end_turn."""
        ...
