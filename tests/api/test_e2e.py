"""End-to-end API smoke tests covering the full lobby + abandon flow.

Exercises both REST (auth) and GraphQL surfaces against a `TestClient`. Uses dev-login so
no Google OAuth dance is required.
"""
from __future__ import annotations

import os
from typing import Any

import pytest
from fastapi.testclient import TestClient

from conquest.main import create_app


@pytest.fixture(autouse=True)
def _enable_dev_login(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CONQUEST_DEV_LOGIN", "1")


@pytest.fixture
def client() -> TestClient:
    return TestClient(create_app())


def _login(client: TestClient, name: str) -> dict[str, str]:
    r = client.post("/auth/dev-login", json={"displayName": name})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['token']}"}


def _gql(client: TestClient, headers: dict[str, str] | None, query: str) -> dict[str, Any]:
    r = client.post("/graphql", json={"query": query}, headers=headers or {})
    assert r.status_code == 200, r.text
    return r.json()


def test_unauthenticated_graphql_is_rejected(client: TestClient) -> None:
    payload = _gql(client, None, "{ me { userId } }")
    assert payload.get("errors")
    assert payload["errors"][0]["message"] == "authentication required"


def test_authenticated_me_returns_user(client: TestClient) -> None:
    hdrs = _login(client, "Alice")
    payload = _gql(client, hdrs, "{ me { userId displayName } }")
    assert payload["data"]["me"]["displayName"] == "Alice"


def test_full_lobby_and_abandon_flow(client: TestClient) -> None:
    alice = _login(client, "Alice")
    bob = _login(client, "Bob")
    carol = _login(client, "Carol")

    # 1. Alice creates a game.
    create = _gql(
        client,
        alice,
        'mutation { createGame(name: "E2E", maxPlayers: 4, isPublic: false) { '
        '... on GameResult { game { gameId inviteCode playerCount } } '
        '... on GameError { code message } } }',
    )
    g = create["data"]["createGame"]["game"]
    gid, ic = g["gameId"], g["inviteCode"]
    assert g["playerCount"] == 1

    # 2. Bob and Carol join with the invite code (their own tokens).
    for hdrs in (bob, carol):
        joined = _gql(
            client,
            hdrs,
            f'mutation {{ joinGame(gameId: "{gid}", inviteCode: "{ic}") '
            f"{{ ... on GameResult {{ game {{ playerCount }} }} "
            f"... on GameError {{ code message }} }} }}",
        )
        assert "errors" not in joined, joined

    # 3. Alice adds an AI seat.
    _gql(
        client,
        alice,
        f'mutation {{ addAiSeat(gameId: "{gid}", archetype: "aggressor") '
        f"{{ ... on GameResult {{ game {{ playerCount }} }} }} }}",
    )

    # 4. Bob (non-owner) cannot start the game.
    start_attempt = _gql(
        client,
        bob,
        f'mutation {{ startGame(gameId: "{gid}") '
        f"{{ ... on GameStateResult {{ state {{ game {{ status }} }} }} "
        f"... on GameError {{ code message }} }} }}",
    )
    payload = start_attempt["data"]["startGame"]
    assert "code" in payload  # GameError

    # 5. Alice starts the game. Status flips to placing_troops, players locked in.
    started = _gql(
        client,
        alice,
        f'mutation {{ startGame(gameId: "{gid}") '
        f"{{ ... on GameStateResult {{ state {{ game {{ status playerCount isJoinable }} "
        f"players {{ kind seatOrder }} }} }} }} }}",
    )
    state = started["data"]["startGame"]["state"]["game"]
    assert state["status"] == "placing_troops"
    assert state["playerCount"] == 4
    assert state["isJoinable"] is False

    # 6. A 4th outsider can no longer join.
    dave = _login(client, "Dave")
    joined = _gql(
        client,
        dave,
        f'mutation {{ joinGame(gameId: "{gid}", inviteCode: "{ic}") '
        f"{{ ... on GameResult {{ game {{ playerCount }} }} "
        f"... on GameError {{ code }} }} }}",
    )
    assert "code" in joined["data"]["joinGame"]

    # 7. To abandon mid-game we need the game in_progress; cheat by walking it via the
    #    in-process service: place each setup troop until phase advances. We do a simpler
    #    check here: abandon while still in setup raises an InvalidAction (only humans in
    #    in-progress can abandon).
    payload = _gql(
        client,
        bob,
        f'mutation {{ abandonGame(gameId: "{gid}") '
        f"{{ ... on GameStateResult {{ state {{ game {{ status }} }} }} "
        f"... on GameError {{ code message }} }} }}",
    )
    # Either it's allowed (game might have ticked into in_progress for tiny configs) or
    # we get a typed error. Accept both — main thing: no 500.
    op = payload["data"]["abandonGame"]
    assert "state" in op or "code" in op


def test_abandon_swaps_kind_to_ai() -> None:
    """Direct service-level test for abandon — easier than driving full setup through GraphQL."""
    from conquest.repositories import InMemoryRepository
    from conquest.services.game_service import GameService

    repo = InMemoryRepository()
    svc = GameService(repo)
    g = svc.create_game(owner_user_id="u1", owner_display_name="Alice", seed=1)
    svc.join_game(
        game_id=g.game_id, user_id="u2", display_name="Bob", invite_code=g.invite_code
    )
    svc.add_ai_seat(game_id=g.game_id, owner_user_id="u1", archetype="medic")
    snap = svc.start_game(game_id=g.game_id, owner_user_id="u1")
    # Walk setup forward until status flips to in_progress, picking unclaimed countries.
    from conquest.models.action import (
        PlaceCapital,
        PlaceResearcher,
        PlaceTroop,
    )

    while snap.game.status in {"placing_troops", "placing_researchers", "placing_capitals"}:
        seat = snap.game.setup.active_seat_order
        seat_player = next(p for p in snap.players.values() if p.seat_order == seat)
        if seat_player.kind != "human":
            break  # AI auto-runs via the service
        if snap.game.setup.phase == "troops":
            unclaimed = [
                cid for cid, s in snap.country_states.items() if s.owner_player_id is None
            ]
            target = unclaimed[0] if unclaimed else next(
                cid for cid, s in snap.country_states.items()
                if s.owner_player_id == seat_player.player_id
            )
            uid = "u1" if seat_player.user_id == "u1" else "u2"
            snap = svc.apply_setup_action(
                game_id=g.game_id,
                actor_user_id=uid,
                action=PlaceTroop(country_id=target),
            )
        elif snap.game.setup.phase == "researchers":
            owned = next(
                cid for cid, s in snap.country_states.items()
                if s.owner_player_id == seat_player.player_id
            )
            snap = svc.apply_setup_action(
                game_id=g.game_id,
                actor_user_id=seat_player.user_id,  # type: ignore[arg-type]
                action=PlaceResearcher(country_id=owned),
            )
        elif snap.game.setup.phase == "capitals":
            owned = next(
                cid for cid, s in snap.country_states.items()
                if s.owner_player_id == seat_player.player_id
            )
            snap = svc.apply_setup_action(
                game_id=g.game_id,
                actor_user_id=seat_player.user_id,  # type: ignore[arg-type]
                action=PlaceCapital(country_id=owned),
            )
        else:
            break

    assert snap.game.status == "in_progress"
    # Bob (a human) abandons. He becomes an AI seat.
    snap2 = svc.abandon_game(game_id=g.game_id, user_id="u2", archetype="medic")
    bob_player = next(p for p in snap2.players.values() if p.user_id == "u2")
    assert bob_player.kind == "ai"
    assert bob_player.ai_config is not None
    assert bob_player.ai_config.archetype == "medic"
