"""Smoke tests for the simulation harness."""

from __future__ import annotations

import pytest

from conquest.simulation import run_simulation


def test_two_player_game_runs_to_completion() -> None:
    out = run_simulation(seed=1, archetypes=["aggressor", "turtle"], max_rounds=80)
    assert out.rounds_played > 0
    # Either someone won or the outbreak limit hit, but the game must end one way.
    assert out.ended_reason in {"victory", "outbreak_limit", "max_rounds", "setup_failed"}


@pytest.mark.parametrize("seed", [7, 42, 99])
def test_four_player_game_finishes_setup(seed: int) -> None:
    out = run_simulation(
        seed=seed,
        archetypes=["aggressor", "medic", "turtle", "expansionist"],
        max_rounds=120,
    )
    assert out.ended_reason != "setup_failed"
