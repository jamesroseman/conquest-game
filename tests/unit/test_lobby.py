"""Lobby flow: create, join, AI seats, start."""

from __future__ import annotations

import pytest

from conquest.game.errors import GameNotJoinable, GameNotStartable, RuleError
from conquest.services.game_service import GameService


def test_create_game_owner_auto_joins(game_service: GameService) -> None:
    g = game_service.create_game(owner_user_id="u1", owner_display_name="Alice", seed=1)
    assert g.status == "lobby"
    assert g.is_joinable
    assert g.player_count == 1
    assert g.owner_user_id == "u1"


def test_join_with_invite_code(game_service: GameService) -> None:
    g = game_service.create_game(owner_user_id="u1", owner_display_name="Alice", seed=1)
    g2 = game_service.join_game(
        game_id=g.game_id, user_id="u2", display_name="Bob", invite_code=g.invite_code
    )
    assert g2.player_count == 2


def test_join_without_invite_rejected(game_service: GameService) -> None:
    g = game_service.create_game(owner_user_id="u1", owner_display_name="Alice", seed=1)
    with pytest.raises(GameNotJoinable):
        game_service.join_game(game_id=g.game_id, user_id="u2", display_name="Bob")


def test_add_ai_seats_and_start(game_service: GameService) -> None:
    g = game_service.create_game(
        owner_user_id="u1", owner_display_name="Alice", seed=1, max_players=3
    )
    game_service.add_ai_seat(game_id=g.game_id, owner_user_id="u1", archetype="aggressor")
    game_service.add_ai_seat(game_id=g.game_id, owner_user_id="u1", archetype="medic")
    snap = game_service.start_game(game_id=g.game_id, owner_user_id="u1")
    assert snap.game.status == "placing_troops"
    assert snap.game.player_count == 3
    assert snap.map is not None
    # All countries initialized.
    assert len(snap.country_states) == len(snap.map.countries)
    # All players have starting troops to place.
    for p in snap.players.values():
        assert p.troops_remaining_to_place == snap.game.config.starting_troops_per_player


def test_start_requires_min_players(game_service: GameService) -> None:
    g = game_service.create_game(owner_user_id="u1", owner_display_name="Alice", seed=1)
    with pytest.raises(GameNotStartable):
        game_service.start_game(game_id=g.game_id, owner_user_id="u1")


def test_start_requires_owner(game_service: GameService) -> None:
    g = game_service.create_game(
        owner_user_id="u1", owner_display_name="Alice", seed=1, max_players=2
    )
    game_service.add_ai_seat(game_id=g.game_id, owner_user_id="u1", archetype="aggressor")
    with pytest.raises(RuleError):
        game_service.start_game(game_id=g.game_id, owner_user_id="someone-else")


def test_game_not_joinable_after_start(game_service: GameService) -> None:
    g = game_service.create_game(
        owner_user_id="u1", owner_display_name="Alice", seed=1, max_players=2
    )
    game_service.add_ai_seat(game_id=g.game_id, owner_user_id="u1", archetype="aggressor")
    game_service.start_game(game_id=g.game_id, owner_user_id="u1")
    g2 = game_service._must_get_game(g.game_id)
    assert not g2.is_joinable
    with pytest.raises(GameNotJoinable):
        game_service.join_game(
            game_id=g.game_id, user_id="u2", display_name="Bob", invite_code=g.invite_code
        )
