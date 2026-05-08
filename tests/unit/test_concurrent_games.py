"""Multiple games can run independently; per-user active-game cap is enforced."""

from __future__ import annotations

import pytest

from conquest.game.errors import InvalidAction
from conquest.repositories import InMemoryRepository
from conquest.services.game_service import GameService


def test_multiple_games_for_same_user_dont_collide() -> None:
    repo = InMemoryRepository()
    svc = GameService(repo)
    g1 = svc.create_game(owner_user_id="u1", owner_display_name="A", seed=1)
    g2 = svc.create_game(owner_user_id="u1", owner_display_name="A", seed=2)
    assert g1.game_id != g2.game_id
    # Add an AI to g1 only.
    svc.add_ai_seat(game_id=g1.game_id, owner_user_id="u1", archetype="aggressor")
    g1_after = svc._must_get_game(g1.game_id)
    g2_after = svc._must_get_game(g2.game_id)
    assert g1_after.player_count == 2
    assert g2_after.player_count == 1


def test_multiple_users_play_concurrent_games() -> None:
    repo = InMemoryRepository()
    svc = GameService(repo)
    g_a = svc.create_game(owner_user_id="u1", owner_display_name="A", seed=1)
    g_b = svc.create_game(owner_user_id="u2", owner_display_name="B", seed=2)
    svc.add_ai_seat(game_id=g_a.game_id, owner_user_id="u1", archetype="aggressor")
    svc.add_ai_seat(game_id=g_b.game_id, owner_user_id="u2", archetype="medic")
    s_a = svc.start_game(game_id=g_a.game_id, owner_user_id="u1")
    s_b = svc.start_game(game_id=g_b.game_id, owner_user_id="u2")
    # Independent maps, independent country-state stores.
    assert s_a.map.map_id != s_b.map.map_id
    assert set(s_a.country_states) != set(s_b.country_states)


def test_active_games_cap_enforced() -> None:
    repo = InMemoryRepository()
    svc = GameService(repo, max_active_games_per_user=2)
    svc.create_game(owner_user_id="u1", owner_display_name="A", seed=1)
    svc.create_game(owner_user_id="u1", owner_display_name="A", seed=2)
    with pytest.raises(InvalidAction):
        svc.create_game(owner_user_id="u1", owner_display_name="A", seed=3)


def test_list_games_for_user_includes_seat_membership() -> None:
    repo = InMemoryRepository()
    svc = GameService(repo)
    g = svc.create_game(owner_user_id="u1", owner_display_name="A", seed=1)
    svc.join_game(game_id=g.game_id, user_id="u2", display_name="B", invite_code=g.invite_code)
    assert any(x.game_id == g.game_id for x in svc.list_games_for_user("u2"))
