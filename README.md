# Conquest

Turn-based strategy game with a shared pandemic mechanic. **Backend-only** — the entire game
is playable through the GraphQL API. See `CLAUDE.md` for the full design.

## Status

v0.1 ships:

- All Pydantic models — Python attrs are `snake_case`, JSON wire is `camelCase` via a
  shared `CamelModel` base.
- Deterministic procedural map generator (4 continents, 1 designated island, ≥ 2 sea paths
  to the island, proportional continent bonuses). Map size scales with player count and is
  hard-capped to keep memory bounded.
- Pure rules engine: 4-phase setup, round/turn state machine, all 6 in-game actions,
  reinforcements, end-of-round virus phase with outbreak chains, capital-conquest cascade.
- Lobby flow: `createGame` → `joinGame` (invite code) / `addAiSeat` → `startGame`. Players
  can `leaveGame` (lobby) or `abandonGame` (in progress, AI takes over). Multiple
  concurrent games per user with a configurable cap.
- 12 AI archetypes + an `ai_runner` that drives setup placements and full turns. Service
  layer auto-runs AI seats whenever the active player is AI.
- Simulation harness (`scripts/run_simulation.py`) for parameter sweeps + balance reports.
- GraphQL API (Strawberry + FastAPI) plus REST auth (`/auth/google`, `/auth/dev-login`,
  `/auth/me`). Production Google ID-token verification uses Google's JWKS with TTL caching
  and rotation-aware refresh.
- In-memory repository (single process, not durable). Persistence backend is deferred.
- Tests covering rules engine, lobby, AI, simulation, hypothesis property invariants, and
  the JWT round-trip / Google verification gate.

## Run locally

```bash
poetry install
./scripts/run_local.sh
# GraphiQL at http://localhost:8000/graphql
```

## Test

```bash
poetry run pytest
poetry run pytest tests/property -q     # hypothesis suite
poetry run python scripts/run_simulation.py --games 200 --players 4 --out balance.csv
```

## Auth

- `POST /auth/google` — verify a Google ID token, upsert `users/{userId}`, return a
  Conquest JWT. In dev (`CONQUEST_DEV_LOGIN=1`, default) signature verification is
  skipped so any well-formed token works.
- `POST /auth/dev-login` — dev shortcut. Disabled when `CONQUEST_DEV_LOGIN=0`.
- `GET /auth/me` — return the authenticated user.

Every GraphQL request must carry `Authorization: Bearer <conquest_jwt>`.

## Lobby flow

```
createGame(config?, maxPlayers?)         → status: lobby   (creator joins seat 0)
joinGame(gameId, inviteCode?)            → status: lobby   (must be joinable)
leaveGame(gameId)                        → self-service (lobby only)
addAiSeat(gameId, archetype, ...)        → status: lobby   (owner only)
removeSeat(gameId, targetPlayerId)       → status: lobby   (owner only)
startGame(gameId)                        → status: placing_troops
abandonGame(gameId, archetype?)          → in-progress, hands seat to AI
```

A game is **joinable** while `status == "lobby"` and `playerCount < maxPlayers`. Players
are 2–6 (hard-capped); map size scales accordingly.
