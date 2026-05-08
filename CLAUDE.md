# Conquest

A turn-based strategy game where players compete to dominate the world while a shared pandemic threatens to end the game for everyone. Inspired by Risk, Pandemic, and Monopoly.

## Architecture

**Backend-only repository.** The entire game is playable through the GraphQL API — no client required. The API owns the map, all game state, rule enforcement, turn resolution, and the virus AI. A separate frontend (future) will only render state and dispatch mutations.

This constraint is load-bearing: every rule, every random roll, every turn transition must be expressible and executable through the API. Anything that "lives in the UI" is a bug.

## Tech stack

- **Language:** Python 3.12+
- **API framework:** [Strawberry GraphQL](https://strawberry.rocks/) (code-first schema)
- **Web server:** FastAPI + Uvicorn (Strawberry's FastAPI integration)
- **Database:** **Google Cloud Firestore** (Native mode, NoSQL document store)
- **Auth:** Google Sign-In (OAuth 2.0). API verifies Google-issued ID tokens; sessions are JWTs minted by the API.
- **Infra-as-code:** **Terraform** — every GCP resource declared in `infra/`.
- **Deployment:** Google Cloud Platform — Cloud Run, Firestore (Native), Secret Manager, Artifact Registry. Deployed from GitHub Actions via **Workload Identity Federation** (no long-lived service account keys).
- **CI/CD:** **GitHub Actions** — lint/type/test on PRs, deploy to Cloud Run on merge to `main`.
- **Async:** Async-first throughout (async resolvers; Firestore async client).

## Tooling

- **Package / env management:** `uv`
- **Linting / formatting:** `ruff` (lint + format)
- **Type checking:** `mypy` (strict where practical)
- **Testing:** `pytest`, `pytest-asyncio`, `pytest-cov`, `hypothesis` (property-based)
- **Pre-commit:** `pre-commit` running ruff + mypy
- **Local Firestore:** Google Cloud Firestore Emulator. Started via `scripts/start_emulators.sh`. Tests and local dev point at the emulator via `FIRESTORE_EMULATOR_HOST`.

## Core domain concepts

### User vs Player

A **User** is an authenticated human identity, identified by Google `sub`, persisted in `users/{userId}`. A User is *not* a participant in any game.

A **Player** is a participant in a single game. Players exist only in the context of one game and have no meaning outside it. A Player is **either**:
- **Human** — backed by a `userId` reference.
- **AI** — backed by no User, with an `aiConfig` (archetype + difficulty).

Same User can be in many games as different Players. Authentication checks happen at the User layer; turn legitimacy checks at the Player layer.

### Map / continents / countries / tiles / paths

The game world is a **procedurally generated map** rendered on a grid of **tiles**.

- **Tiles** — rendering primitive. Each has integer `(x, y)` coordinates and terrain (`land` | `ocean`).
- **Landmasses** — maximal connected regions of `land` tiles (4-connected). Generator guarantees exactly **4 landmasses (continents)**, with **exactly one being an island continent**.
- **Countries** — partitions of landmasses. Every land tile belongs to exactly one country.
- **Paths** — adjacency. Every adjacency between two countries is a `Path` with `kind: land | sea`. Mechanically identical for movement and attack; `kind` exists purely for rendering (solid vs dotted).

Countries carry per-game state (owner, armies, disease cubes, vaccinated flag, capital flag, researcher presence). Country *shape* is part of the map and immutable for the life of a game.

### Game

A **Game** binds a generated `Map`, a `GameConfig`, a list of `Players`, and per-game state of every country.

## Map generation

Maps are **deterministically generated from a seed**. Same seed + same params → byte-identical map.

### Parameters

```python
class MapGenParams(BaseModel):
    seed: int
    width: int = 64
    height: int = 40
    continent_count: int = 4
    island_continent_count: int = 1
    target_country_count: int = 42
    min_country_tile_size: int = 6
    max_country_tile_size: int = 24
    sea_path_count: int = 6           # ≥ 2 must touch the island
    ocean_border: int = 2
```

### Algorithm (high level)

Implemented in `src/conquest/game/map_gen/`. Pure functions, no I/O.

1. **Seed RNG.** All randomness flows through this RNG.
2. **Place continent centers** via Poisson-disc sampling. One flagged as island.
3. **Grow landmasses** via noise-modulated flood fill. Island grows in isolation with a guaranteed ocean buffer.
4. **Verify topology.** Exactly 4 landmasses, exactly 1 island. Bounded retry on failure.
5. **Partition into countries** (Voronoi-style with min/max size enforcement).
6. **Compute land paths** for tile-edge-sharing countries on the same landmass.
7. **Add sea paths.** `sea_path_count` cross-landmass paths, biased to coastal proximity. Island has ≥ 2.
8. **Name countries and continents** deterministically.
9. **Emit the `Map`.**

### `Map` data structure

```python
class Tile(BaseModel):
    x: int
    y: int
    terrain: Literal["land", "ocean"]
    countryId: str | None

class Path(BaseModel):
    pathId: str
    countryAId: str
    countryBId: str
    kind: Literal["land", "sea"]

class Country(BaseModel):
    countryId: str
    name: str
    continentId: str
    tiles: list[tuple[int, int]]
    centroid: tuple[float, float]
    pathIds: list[str]

class Continent(BaseModel):
    continentId: str
    name: str
    isIsland: bool
    countryIds: list[str]
    tileCount: int                  # used for proportional bonus calculation
    bonusArmies: int                # computed from tileCount at gen time

class Map(BaseModel):
    mapId: str                      # hash of (seed + params)
    params: MapGenParams
    width: int
    height: int
    tiles: list[Tile]
    countries: dict[str, Country]
    continents: dict[str, Continent]
    paths: dict[str, Path]
```

The `Map` is immutable for the life of a game.

### Continent bonus calculation

Because continents are procedural, sizes vary per map. A continent's `bonusArmies` is computed at map-generation time as proportional to its land-tile count, snapped to an integer. Default formula:

```python
bonus = max(1, round(continent.tileCount / total_land_tiles * total_bonus_pool))
```

Where `total_bonus_pool` is `GameConfig.continent_bonus_pool` (default 12). So across 4 continents, ~12 bonus armies are distributed proportionally — small continents might be worth 2, large mainland continents 4–5.

The result is stored on the `Continent` so it's stable for the life of the game; it's not recomputed each turn.

## Game configuration

All gameplay parameters that might want tuning live in a `GameConfig` attached to each game. Defaults are defined once in code; any field can be overridden at game creation. The full config is persisted on the game root doc verbatim.

```python
class GameConfig(BaseModel):
    # Action economy
    actions_per_turn: int = 5
    starting_troops_per_player: int = 30

    # Action costs (in actions)
    cost_move_researcher_adjacent: int = 1
    cost_airdrop_researcher: int = 2          # move researcher to any country on map
    cost_cure: int = 1
    cost_create_vaccine: int = 1
    cost_attack: int = 1
    cost_move_troops: int = 1

    # Setup-phase disease seeding
    setup_disease_2cube_count: int = 3
    setup_disease_1cube_count: int = 7

    # Disease and outbreaks
    max_cubes_per_country: int = 3
    outbreak_loss_threshold: int = 11

    # Spread per END-OF-ROUND, scales with current outbreak count
    # (inclusive_min_outbreaks, inclusive_max_outbreaks, cubes_added)
    spread_schedule: list[tuple[int, int, int]] = [
        (0,  3,  3),
        (4,  6,  5),
        (7, 10,  7),
    ]

    # Casualties (always round DOWN; minimum 0)
    casualty_fraction_one_cube: float = 1/3
    casualty_fraction_two_cubes: float = 1/2
    casualty_fraction_three_cubes: float = 1.0

    # Reinforcements (per turn, computed at start of player's turn)
    reinforcement_base: int = 10                # flat each turn
    reinforcement_per_country: int = 1          # +1 per country owned
    reinforcement_capital_bonus: int = 2        # +2 placed in capital country
    continent_bonus_pool: int = 12              # divided proportionally across continents at gen
    continent_bonus_enabled: bool = True

    # Vaccine
    vaccine_requires_all_researchers: bool = True   # all non-eliminated players' researchers co-located
    vaccinated_blocks_outbreak_chain: bool = True   # vaccinated countries don't propagate outbreaks

    # Win / loss
    capital_loss_eliminates_player: bool = True
    win_condition: Literal["last_competitor", "capital_control", "score"] = "last_competitor"

    # AI
    ai_action_delay_ms: int = 0
```

### Casualty rounding (locked)

Casualties **always round down**, with a minimum of 0. There is no "always at least 1" rule.

## Game rules (canonical)

These rules are the source of truth. **Numeric values come from `GameConfig`** unless explicitly stated as fixed.

### Setup phase — four sub-phases

**1. Troop placement.**
- 2–6 players. Each has `starting_troops_per_player` (default 30) troops.
- Players take turns in seat order, placing **one troop at a time** on a country of their choice. The first time a country receives a troop, the placing player claims ownership; thereafter only the owner may add troops to it.
- Risk-style claim rule: until every country is claimed at least once, players may only place on unclaimed countries.

**2. Setup disease seeding.**
- Server places cubes automatically: `setup_disease_2cube_count` (3) random countries get 2 cubes, then `setup_disease_1cube_count` (7) more disjoint random countries get 1 cube. Total 10 infected countries.

**3. Researcher placement.**
- Each player, in seat order, places their researcher on **any country they own**.
- Researchers cannot be attacked, captured, or destroyed by enemy actions.

**4. Capital placement.**
- Each player, in seat order, places their capital on **any country they own**.
- A capital is a flag (`isCapitalOf: playerId`) on a country state. Capitals do not move once placed.

After capital placement, the first player begins their first normal turn.

### Round structure

A **round** is one full pass through all non-eliminated players in seat order. The virus phase runs **at the end of the round**.

Round = P1 → P2 → ... → Pn → virus phase.

### Player turn — N actions (default 5)

At the **start** of the player's turn, reinforcements are calculated and placed (see below). Then the player spends up to `actions_per_turn` (default 5) actions. Repeats and any combination allowed.

Action types (cost → effect):

1. **Move researcher (adjacent)** — 1 action. Researcher moves to a country connected by any path to its current country.
2. **Airdrop researcher** — 2 actions. Researcher moves to **any country on the map**. The 2-action cost reflects the strategic power of unrestricted positioning.
3. **Cure** — 1 action. Removes all disease cubes from the country your researcher currently occupies. Does **not** vaccinate.
4. **Create vaccine** — 1 action. Permanently vaccinates the country your researcher occupies. **Requires all non-eliminated players' researchers to be on the same country.** The action is charged only to the active player (typically the last researcher to arrive). Vaccinated countries never receive new cubes for the rest of the game; vaccination does **not** remove existing cubes.
5. **Attack** — 1 action. Attack a country adjacent (any path) to one you own. Combat resolution TBD.
6. **Move troops** — 1 action. Move any number of troops from a country you own to an **adjacent** country you own (one path step only — no chaining).

### Reinforcements

Computed and placed at the **start** of each player's turn, before they spend any actions. Formula:

```
reinforcements_total = reinforcement_base
                     + reinforcement_per_country × countries_owned
                     + sum(continent.bonusArmies for continents fully owned)
```

Of these, `reinforcement_capital_bonus` (default 2) troops are placed automatically on the player's capital country. The remainder is placed by the player as part of their turn — implementation note: this can either be a discrete "place reinforcements" sub-phase before action-spending, or treated as a reserve the player draws from. v1 uses an explicit sub-phase: at turn start, the server computes the total, auto-places the capital bonus, and sets `reinforcementsToPlace` on the player; the player must place all of them (one or more `place_reinforcements` mutations choosing target countries they own) before spending actions.

Defaults give: 10 base + 1 per country + 2 in capital + continent bonuses (proportional to continent size, total pool of 12 across all 4 continents).

### End-of-round virus phase

Runs once per round, after the last non-eliminated player's turn.

**Step 1: Apply army casualties.** For each country with disease cubes:
- 1 cube → lose `floor(armies × casualty_fraction_one_cube)` troops, min 0.
- 2 cubes → lose `floor(armies × casualty_fraction_two_cubes)`, min 0.
- 3 cubes → lose all troops.

Vaccinated countries with pre-existing cubes still take casualties — vaccination prevents *new* cubes, not existing infection.

**Step 2: Place new cubes.** Look up cube count from `spread_schedule` based on current outbreak count:
- 0–3 outbreaks → 3 cubes.
- 4–6 outbreaks → 5 cubes.
- 7–10 outbreaks → 7 cubes.

Each cube is placed on a **uniformly randomly chosen country** (re-rolling vaccinated countries). Same country can be chosen multiple times. If a placement would push a country over `max_cubes_per_country` (3), an **outbreak** occurs instead: every adjacent country gains 1 cube (skipping vaccinated countries; vaccinated countries also do not propagate the chain when `vaccinated_blocks_outbreak_chain = true`). Outbreaks chain, but each country can outbreak at most once per virus phase.

When the outbreak counter reaches `outbreak_loss_threshold` (11), the game ends and **all players lose**.

### Player elimination — capital conquest

When a player's capital country becomes owned by another player (via a successful attack), the capital owner is **immediately eliminated** at the moment of conquest, not at end-of-round. Effects of elimination:

1. **Capture.** All countries previously owned by the eliminated player become owned by the conquering player. Army counts on those countries are unchanged (the conquering player inherits them).
2. **Researcher removed.** The eliminated player's researcher disappears from the board entirely.
3. **Capital flag.** The conquered capital country retains the conquering player's existing capital (if any). The eliminated player's capital flag is cleared. The conquering player does **not** gain a second capital.
4. **Turn order.** Eliminated players are skipped in subsequent rounds.
5. **Vaccine eligibility.** With one fewer researcher in play, the threshold for `vaccine_requires_all_researchers` becomes "all *remaining* non-eliminated players' researchers." A 2-player vaccine becomes possible after a 3-player game has eliminated one.

If a player's elimination would cause the conquering player to satisfy the win condition mid-turn, the game ends immediately.

### Win condition

`GameConfig.win_condition` selects the rule. Default `last_competitor`: a player wins when all other players are eliminated. The win condition must be reachable before the outbreak threshold in most games or competitive play collapses; this is a primary target for simulation-driven tuning.

## AI players

AI is a first-class citizen. The same rules engine executes for human and AI players.

### Archetypes

12 archetypes ship at launch, randomly selected (with optional weighting) when an AI player is created.

| # | Archetype | Strategic prior |
|---|---|---|
| 1 | **Aggressor** | Maximizes attacks; favors offensive territorial expansion; tolerates disease risk. |
| 2 | **Turtle** | Builds defensive mass on a few well-defended countries; rarely attacks first. |
| 3 | **Medic** | Heavily prioritizes curing disease; positions researcher proactively in hotspots. |
| 4 | **Opportunist** | Picks fights only with weakened neighbors; cherry-picks low-cube targets. |
| 5 | **Expansionist** | Optimizes for territory count, even thin holdings; spreads wide and shallow. |
| 6 | **Consolidator** | Optimizes for completing/holding contiguous regions for reinforcement bonuses. |
| 7 | **Saboteur** | Targets the current leader; especially fond of capital strikes. |
| 8 | **Kingmaker** | Pursues moderate gains while disproportionately punishing whoever is in 1st. |
| 9 | **Doomsayer** | Behaves as if outbreak threshold is closer than it is; vaccine-cooperative. |
| 10 | **Isolationist** | Defends a defensible cluster, avoids border conflicts unless provoked. |
| 11 | **Bandwagon** | Joins attacks on whoever was most recently attacked; reactive. |
| 12 | **Chaos** | Higher randomness in action selection; deliberately unpredictable. |

Each archetype is a `Policy` subclass under `src/conquest/ai/policies/`. Each must encode a stance on the cooperative vaccine — Doomsayer / Medic weight it heavily; Aggressor / Saboteur / Chaos may free-ride.

### Difficulty

Orthogonal to archetype. `easy | medium | hard | brutal` driving lookahead depth, action selection noise, threat awareness, mistake rate.

```python
class AIConfig(BaseModel):
    archetype: ArchetypeId
    difficulty: Literal["easy", "medium", "hard", "brutal"]
    seed: int
```

### Policy interface

```python
class Policy(Protocol):
    def take_turn(
        self,
        view: GameStateView,           # read-only snapshot, includes GameConfig
        player_id: PlayerId,
        rng: SeededRNG,
    ) -> Sequence[Action]:
        ...
```

Policies emit *intents*; the rules engine validates and resolves them exactly as it does for human-submitted actions. **There is no AI-only code path through the rules engine.**

### AI runner

Conquest is turn-based, so AI moves resolve as fast as the policy can compute. `services/ai_runner.py`:
1. Detect that the active player is AI.
2. Load snapshot.
3. Place reinforcements (auto-policy delegated to the archetype).
4. Invoke the policy for action-spending.
5. Validate and apply each emitted action (transaction batch per turn by default).
6. Advance to the next non-eliminated player; loop if also AI.
7. After the last player, run the virus phase.

`GameConfig.ai_action_delay_ms` adds a server-side delay for spectator UX. Default 0.

For batch playtesting, the simulation harness calls policies directly against an in-memory state.

### All-AI mode

`scripts/run_simulation.py` runs thousands of all-AI games per minute against the in-memory engine and produces balance reports.

## Repository layout

```
conquest/
├── CLAUDE.md
├── README.md
├── pyproject.toml
├── Dockerfile
├── .github/workflows/{ci.yml, deploy.yml}
├── infra/                          # Terraform
├── scripts/
│   ├── start_emulators.sh
│   ├── stop_emulators.sh
│   ├── seed_dev.py
│   ├── run_local.sh
│   ├── render_map.py
│   └── run_simulation.py
├── src/
│   └── conquest/
│       ├── main.py
│       ├── config.py               # app config (env vars), NOT GameConfig
│       ├── api/                    # GraphQL: context, schema, types/, queries/, mutations/, loaders, errors
│       ├── auth/                   # google, jwt, deps
│       ├── models/                 # pydantic data shapes
│       │   ├── user.py
│       │   ├── player.py
│       │   ├── game.py
│       │   ├── game_config.py
│       │   ├── country_state.py
│       │   ├── map.py              # Tile, Path, Country, Continent, Map
│       │   ├── action.py
│       │   ├── virus.py
│       │   ├── events.py
│       │   └── snapshot.py
│       ├── repositories/           # base, users, games, maps, players, country_states, events, snapshot
│       ├── services/               # game_service, action_service, auth_service, ai_runner
│       ├── game/                   # PURE rules engine
│       │   ├── map_gen/            # continents, countries, paths, naming, verify
│       │   ├── setup.py            # 4-phase setup state machine
│       │   ├── turn.py             # round + turn state machine
│       │   ├── actions.py          # validation + dispatch
│       │   ├── combat.py
│       │   ├── virus.py            # end-of-round phase
│       │   ├── reinforcements.py
│       │   ├── elimination.py      # capital-conquest cascade
│       │   └── rng.py
│       ├── ai/
│       ├── simulation/
│       └── observability/
└── tests/
    ├── unit/{game/, models/, ai/, auth/}
    ├── integration/{repositories/, services/}
    ├── api/
    ├── property/
    └── sim/
```

## Firestore data model

**Subcollection-first.**

```
users/{userId}
maps/{mapId}                                     # immutable, content-addressed
games/{gameId}
games/{gameId}/players/{playerId}
games/{gameId}/countryStates/{countryId}
games/{gameId}/events/{eventId}
```

### `users/{userId}`

```
{ userId, email, displayName, createdAt, lastLoginAt }
```

### `maps/{mapId}`

```
{
  mapId, params,
  width, height,
  continents: [...],   # includes tileCount and bonusArmies per continent
  countries: [...],
  paths: [...],
  tiles: [...],
  generatedAt
}
```

### `games/{gameId}` — root metadata

```
{
  gameId, mapId,
  config: { ...GameConfig },
  status: "lobby" | "placing_troops" | "seeding_disease" | "placing_researchers"
        | "placing_capitals" | "in_progress" | "ended",
  createdAt, updatedAt,
  rngSeed, rngCursor,

  playerIds: [string],           # ordered by seatOrder; includes eliminated players
  activePlayerOrder: [string],   # seat-ordered IDs of CURRENTLY non-eliminated players
  playerCount: number,

  setup: {
    phase: "troops" | "disease_seed" | "researchers" | "capitals" | "done",
    activeSeatOrder: number
  },

  turn: {
    activePlayerId: string,
    actionsRemaining: number,
    reinforcementsToPlace: number,    # set at turn start; must be 0 before actions can be spent
    turnNumber: number,
    roundNumber: number,
    phase: "reinforcements" | "actions" | "virus"
  },

  outbreaks: {
    count: number,
    history: [ { roundNumber, originCountryId, chainedCountryIds: [string] } ]
  },

  winnerPlayerId: string | null,
  endedReason: "outbreak_limit" | "victory" | null
}
```

### `games/{gameId}/players/{playerId}`

```
{
  playerId, seatOrder, color,
  kind: "human" | "ai",
  userId | null,
  aiConfig: { archetype, difficulty, seed } | null,
  troopsRemainingToPlace,
  researcherCountryId | null,
  capitalCountryId | null,
  eliminated: bool,
  eliminatedByPlayerId: string | null,
  eliminatedAtRound: number | null,
  stats: { countriesOwned, totalArmies }
}
```

### `games/{gameId}/countryStates/{countryId}`

```
{
  countryId,
  ownerPlayerId | null,
  armies,
  diseaseCubes,                  # 0..max_cubes_per_country
  vaccinated: bool,              # permanent once true
  isCapitalOf: playerId | null,  # cleared when owner is eliminated
  hasResearcher: playerId | null
}
```

### `games/{gameId}/events/{eventId}`

```
{
  eventId, sequence,
  type: "place_troop" | "place_researcher" | "place_capital" | "seed_disease"
      | "place_reinforcements"
      | "move_researcher_adjacent" | "airdrop_researcher"
      | "cure" | "create_vaccine" | "attack" | "move_troops"
      | "round_end_virus" | "outbreak"
      | "player_eliminated" | "capital_conquered"
      | "game_started" | "game_ended",
  actorPlayerId | null,
  payload,
  createdAt
}
```

### Read / write patterns

`repositories/snapshot.py` builds a `GameSnapshot` inside a Firestore transaction. The map is immutable; once loaded for a game it can be held in process memory across requests for that game.

Every mutation: read snapshot → apply pure rules logic → write changed docs → append event(s), all atomic.

A capital-conquest mutation can cascade significantly: it transfers ownership of all eliminated player's countries and clears the eliminated player's researcher. This may write more docs in one transaction than a typical action — well within Firestore's 500-write transaction cap for any reasonable map size, but worth noting as the largest single transaction in the system.

DataLoaders at the API layer batch nested resolver reads. No caching in v1.

### Indexes

- `games/{gameId}/events` ordered by `sequence`.
- `games/{gameId}/countryStates` filtered by `ownerPlayerId`.
- `games` filtered by `status` and ordered by `updatedAt`.

## API design principles

- **State is server-authoritative.** Clients never compute state.
- **Mutations are atomic.** Transaction wraps validation + state update + event append.
- **Typed errors.** Strawberry union types per mutation (`Success | NotYourTurn | InvalidAction | NotEnoughActions | NotYourCountry | ResearcherNotInCountry | NotAllResearchersPresent | CountryAlreadyVaccinated | ReinforcementsNotPlaced | NotAdjacent | ...`).
- **Deterministic randomness.** All randomness via the seeded RNG persisted on the game root doc.
- **AI turns** are authored by the server.
- **DataLoaders** on every nested resolver.

## Auth

- Client obtains a Google ID token via Google Sign-In.
- `POST /auth/google` verifies against Google's JWKS, upserts `users/{userId}`, returns a Conquest JWT.
- All GraphQL requests carry `Authorization: Bearer <conquest_jwt>`.
- A `current_user` Strawberry context dependency loads the User; service-layer code translates User → Player(s) per game as needed.

## Infrastructure (Terraform)

Everything in GCP is declared in `infra/`. No clicking in the console.

Owned by Terraform: project APIs (`run`, `firestore`, `secretmanager`, `artifactregistry`, `iamcredentials`, `iam`, `sts`); Firestore database (Native, single region) + composite indexes; Artifact Registry; Cloud Run service per env; service accounts (`conquest-runtime`, `conquest-deployer`); Secret Manager secrets (`google-oauth-client-id`, `jwt-signing-key`); IAM bindings (least privilege); WIF pool + GitHub provider scoped to this repo; remote state in versioned GCS bucket.

## CI/CD (GitHub Actions)

**`ci.yml`** — every PR / non-main push: ruff + mypy + Firestore emulator + pytest with coverage + terraform fmt/validate.

**`deploy.yml`** — push to `main`: WIF auth → build/tag/push to Artifact Registry → deploy revision to Cloud Run.

No long-lived service account keys anywhere.

## Local development

```bash
uv sync
pre-commit install
./scripts/start_emulators.sh
./scripts/run_local.sh

./scripts/render_map.py --seed 42 --out /tmp/map.png
./scripts/run_simulation.py --games 1000 --players 4
```

## Testing strategy

### Unit tests (`tests/unit/`)

- **`tests/unit/game/map_gen/`** — determinism, invariants (4 continents, 1 island, all land tiles assigned, paths form connected meta-graph, island has ≥ 2 sea paths), continent bonus is proportional to tile count and totals to within 1 of `continent_bonus_pool`, robustness across 1,000 sample seeds.
- **`tests/unit/game/`** — rules engine, all numbers from `GameConfig`:
  - 4-phase setup state machine.
  - Action validation per type (including airdrop costs 2 actions; vaccine requires all non-eliminated researchers co-located).
  - Reinforcement formula: `base + per-country × owned + continent bonuses`, capital auto-placement of 2.
  - Vaccine effects: vaccinated countries skipped during spread and outbreak chains; existing cubes remain.
  - Casualty rounding-down boundary cases.
  - End-of-round virus phase (not per-player); spread schedule lookup; outbreak chaining; once-per-virus-phase outbreak cap.
  - **Capital-conquest cascade**: attack that captures a capital triggers immediate elimination, transfers all owned countries to attacker, removes researcher, clears capital flag, updates `activePlayerOrder`. Mid-turn elimination can trigger immediate game end.
  - Eliminated players skipped in turn order; `vaccine_requires_all_researchers` re-evaluates against remaining players.
  - Configurability: parameter sweeps over `actions_per_turn`, `outbreak_loss_threshold`, `spread_schedule`, `setup_disease_*`, `starting_troops_per_player`, `reinforcement_*`, `cost_*`.
- **`tests/unit/models/`** — pydantic validators, serialization.
- **`tests/unit/ai/`** — each archetype's priors and difficulty knobs.
- **`tests/unit/auth/`** — JWT mint/verify, Google token verification.

### Integration tests (`tests/integration/`)

Run against the Firestore emulator. Each test gets a fresh game.

- Repositories: per-collection CRUD, snapshot composition, transactional writes across subcollections (especially the multi-doc capital-conquest cascade), optimistic concurrency, event ordering, index-backed queries.
- Services: full flow from create-game (with map gen) through 4-phase setup, several rounds of play, capital conquests, virus phases, end conditions.

### API tests (`tests/api/`)

Auth gating; one Player can't act for another; typed error round-trip; DataLoader batching (no N+1).

### Property-based (`tests/property/`) — hypothesis

Invariants: total troops conserved minus casualties; outbreak count monotonic; cubes ∈ `[0, max]`; exactly 1 researcher per non-eliminated player after researcher placement; vaccinated countries never gain cubes; no country exceeds `max_cubes_per_country` after any virus phase; capital-conquest invariant (eliminated player has 0 owned countries afterward; conqueror has all of them); game ends iff outbreaks ≥ threshold or win condition met; map invariants under random seeds.

### Simulation / balance (`tests/sim/`)

Thousands of all-AI games. Sanity bands; parameter sweeps over `GameConfig` (e.g., `actions_per_turn`, `outbreak_loss_threshold`, `spread_schedule`, `reinforcement_base`, `cost_airdrop_researcher`). CSV reports for human inspection.

### Coverage targets

- `game/` ≥ 95%.
- `ai/` ≥ 85%.
- `services/` and `repositories/` ≥ 85%.
- Overall ≥ 80%.

## Open design questions

- **Combat resolution.** Risk dice, deterministic, card-based?
- **Reinforcement placement timing.** Currently a discrete sub-phase before action-spending (must place all before any action). Alternative: held in reserve, placed mid-turn alongside other actions.
- **Capital re-establishment.** Currently capitals do not move; a player without a capital is eliminated. There's no edge case where a player exists without a capital after setup. Confirm.
- **Double capital after conquest.** Currently the conqueror keeps their own capital and the conquered country becomes a normal owned country. Alternative: conqueror could *choose* to relocate their capital.
- **Spread weighting.** Currently uniform random over unvaccinated countries. Earlier draft proposed weighting toward neighbors of infected countries; current spec is uniform. Confirm.
- **Win condition default.** `last_competitor` — needs simulation validation.
- **AI runner cadence.** Per-action transactions vs per-turn batches.
- **Map size scaling.** 64×40 default; if larger needed, move tiles to a subcollection.

## Conventions

- **Branching:** trunk-based; short-lived feature branches off `main`.
- **Commits:** Conventional Commits.
- **PRs:** Must pass CI. Self-review before merge if solo.
- **Code style:** ruff defaults, line length 100. Explicit over clever.
- **Docstrings:** Public game-logic and AI-policy functions get docstrings explaining the rule or strategy they enforce, with a back-reference to the relevant section of this file.
- **No magic numbers in the rules engine.** All gameplay constants live on `GameConfig`.
