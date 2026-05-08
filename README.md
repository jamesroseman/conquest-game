# Conquest

Turn-based strategy game with a shared pandemic mechanic. **Backend-only** — the entire game is
playable through the GraphQL API. See `CLAUDE.md` for the full design.

## Status

First version (v0.1):

- All core Pydantic models.
- Deterministic procedural map generator (4 continents, 1 island, ≥ 2 sea paths to the island).
- Pure rules engine: 4-phase setup, turn / round state machine, all 6 action types,
  reinforcements, end-of-round virus phase with outbreak chains, capital-conquest cascade.
- GraphQL API (Strawberry + FastAPI) covering game creation, setup, turns, queries.
- In-memory repository for local development; Firestore swap is a single interface.
- Stub auth (issues a Conquest JWT given a display name) — Google Sign-In wiring is the next milestone.
- Unit tests for the rules engine.

## Run locally

```bash
poetry install
poetry run uvicorn conquest.main:app --reload
# GraphiQL at http://localhost:8000/graphql
```

## Test

```bash
poetry run pytest
```

## Auth

Two REST endpoints sit alongside the GraphQL endpoint:

- `POST /auth/google` — verifies a Google ID token, upserts `users/{userId}`, returns a Conquest
  JWT.
- `POST /auth/dev-login` — dev-only shortcut that mints a JWT for an arbitrary display name. Disabled when `CONQUEST_DEV_LOGIN=0`.
- `GET /auth/me` — returns the authenticated user.

GraphQL requests carry `Authorization: Bearer <conquest_jwt>`.

## Lobby flow

```
createGame(config?)        → status: "lobby"   — creator joins seat 0
joinGame(gameId)           → status: "lobby"   — must be "joinable"
addAiSeat(gameId, ...)     → status: "lobby"   — owner only
removeSeat(gameId, ...)    → status: "lobby"   — owner only
startGame(gameId)          → status: "placing_troops"
```

A game is **joinable** while `status == "lobby"` and seats are below `maxPlayers`. Once started, no
one else can join, eliminated players are skipped, and AI takes its turns automatically. Map size
is chosen automatically based on the player count at start (see `map_size_for_players`).

## Layout

See `CLAUDE.md` § Repository layout. The v0.1 scope wires up `models/`, `game/`, `services/`,
`repositories/` (in-memory), `api/`, plus tests under `tests/unit/`.
