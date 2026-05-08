"""Strawberry GraphQL types.

Wire format is camelCase (the GraphQL convention). Strawberry auto-converts snake_case
Python attribute names to camelCase GraphQL field names, so Python code stays Pythonic
while clients see the canonical schema.
"""

from __future__ import annotations

import strawberry

from conquest.models.country_state import CountryState as CountryStateModel
from conquest.models.game import Game as GameModel
from conquest.models.game_config import GameConfig as GameConfigModel
from conquest.models.map import Continent as ContinentModel
from conquest.models.map import Country as CountryModel
from conquest.models.map import Map as MapModel
from conquest.models.map import Path as PathModel
from conquest.models.map import Tile as TileModel
from conquest.models.player import Player as PlayerModel
from conquest.models.snapshot import GameSnapshot
from conquest.models.user import User as UserModel


@strawberry.type
class User:
    user_id: str
    email: str | None
    display_name: str

    @classmethod
    def from_model(cls, m: UserModel) -> User:
        return cls(user_id=m.user_id, email=m.email, display_name=m.display_name)


@strawberry.type
class GameConfig:
    actions_per_turn: int
    starting_troops_per_player: int
    outbreak_loss_threshold: int
    max_cubes_per_country: int
    reinforcement_base: int
    reinforcement_per_country: int
    reinforcement_capital_bonus: int
    continent_bonus_pool: int
    win_condition: str

    @classmethod
    def from_model(cls, m: GameConfigModel) -> GameConfig:
        return cls(
            actions_per_turn=m.actions_per_turn,
            starting_troops_per_player=m.starting_troops_per_player,
            outbreak_loss_threshold=m.outbreak_loss_threshold,
            max_cubes_per_country=m.max_cubes_per_country,
            reinforcement_base=m.reinforcement_base,
            reinforcement_per_country=m.reinforcement_per_country,
            reinforcement_capital_bonus=m.reinforcement_capital_bonus,
            continent_bonus_pool=m.continent_bonus_pool,
            win_condition=m.win_condition,
        )


@strawberry.input
class GameConfigInput:
    actions_per_turn: int | None = None
    starting_troops_per_player: int | None = None
    outbreak_loss_threshold: int | None = None
    ai_action_delay_ms: int | None = None

    def to_model(self) -> GameConfigModel:
        defaults = GameConfigModel()
        return GameConfigModel(
            actions_per_turn=self.actions_per_turn or defaults.actions_per_turn,
            starting_troops_per_player=self.starting_troops_per_player
            or defaults.starting_troops_per_player,
            outbreak_loss_threshold=self.outbreak_loss_threshold or defaults.outbreak_loss_threshold,
            # 0 is a valid override (instant AI), so distinguish None from 0.
            ai_action_delay_ms=(
                self.ai_action_delay_ms
                if self.ai_action_delay_ms is not None
                else defaults.ai_action_delay_ms
            ),
        )


@strawberry.type
class Tile:
    x: int
    y: int
    terrain: str
    country_id: str | None
    biome: str

    @classmethod
    def from_model(cls, m: TileModel) -> Tile:
        return cls(x=m.x, y=m.y, terrain=m.terrain, country_id=m.country_id, biome=m.biome)


@strawberry.type
class TileCoord:
    x: int
    y: int


@strawberry.type
class Path:
    path_id: str
    country_a_id: str
    country_b_id: str
    kind: str

    @classmethod
    def from_model(cls, m: PathModel) -> Path:
        return cls(
            path_id=m.path_id,
            country_a_id=m.country_a_id,
            country_b_id=m.country_b_id,
            kind=m.kind,
        )


@strawberry.type
class Country:
    country_id: str
    name: str
    continent_id: str
    centroid_x: float
    centroid_y: float
    path_ids: list[str]
    tiles: list[TileCoord]

    @classmethod
    def from_model(cls, m: CountryModel) -> Country:
        return cls(
            country_id=m.country_id,
            name=m.name,
            continent_id=m.continent_id,
            centroid_x=m.centroid[0],
            centroid_y=m.centroid[1],
            path_ids=list(m.path_ids),
            tiles=[TileCoord(x=t[0], y=t[1]) for t in m.tiles],
        )


@strawberry.type
class Continent:
    continent_id: str
    name: str
    is_island: bool
    country_ids: list[str]
    tile_count: int
    bonus_armies: int
    climate: str

    @classmethod
    def from_model(cls, m: ContinentModel) -> Continent:
        return cls(
            continent_id=m.continent_id,
            name=m.name,
            is_island=m.is_island,
            country_ids=list(m.country_ids),
            tile_count=m.tile_count,
            bonus_armies=m.bonus_armies,
            climate=m.climate,
        )


@strawberry.type
class Map:
    map_id: str
    width: int
    height: int
    countries: list[Country]
    continents: list[Continent]
    paths: list[Path]
    tiles: list[Tile]

    @classmethod
    def from_model(cls, m: MapModel) -> Map:
        return cls(
            map_id=m.map_id,
            width=m.width,
            height=m.height,
            countries=[Country.from_model(c) for c in m.countries.values()],
            continents=[Continent.from_model(c) for c in m.continents.values()],
            paths=[Path.from_model(p) for p in m.paths.values()],
            tiles=[Tile.from_model(t) for t in m.tiles],
        )


@strawberry.type
class CountryState:
    country_id: str
    owner_player_id: str | None
    armies: int
    disease_cubes: int
    vaccinated: bool
    is_capital_of: str | None
    has_researcher: str | None

    @classmethod
    def from_model(cls, m: CountryStateModel) -> CountryState:
        return cls(
            country_id=m.country_id,
            owner_player_id=m.owner_player_id,
            armies=m.armies,
            disease_cubes=m.disease_cubes,
            vaccinated=m.vaccinated,
            is_capital_of=m.is_capital_of,
            has_researcher=m.has_researcher,
        )


@strawberry.type
class Player:
    player_id: str
    seat_order: int
    color: str
    kind: str
    user_id: str | None
    archetype: str | None
    difficulty: str | None
    troops_remaining_to_place: int
    researcher_country_id: str | None
    capital_country_id: str | None
    eliminated: bool
    countries_owned: int
    total_armies: int

    @classmethod
    def from_model(cls, m: PlayerModel) -> Player:
        return cls(
            player_id=m.player_id,
            seat_order=m.seat_order,
            color=m.color,
            kind=m.kind,
            user_id=m.user_id,
            archetype=m.ai_config.archetype if m.ai_config else None,
            difficulty=m.ai_config.difficulty if m.ai_config else None,
            troops_remaining_to_place=m.troops_remaining_to_place,
            researcher_country_id=m.researcher_country_id,
            capital_country_id=m.capital_country_id,
            eliminated=m.eliminated,
            countries_owned=m.stats.countries_owned,
            total_armies=m.stats.total_armies,
        )


@strawberry.type
class TurnState:
    active_player_id: str | None
    actions_remaining: int
    reinforcements_to_place: int
    turn_number: int
    round_number: int
    phase: str


@strawberry.type
class SetupState:
    phase: str
    active_seat_order: int


@strawberry.type
class Game:
    game_id: str
    name: str
    status: str
    is_joinable: bool
    owner_user_id: str
    min_players: int
    max_players: int
    is_public: bool
    invite_code: str | None
    player_count: int
    map_id: str | None
    config: GameConfig
    setup: SetupState
    turn: TurnState
    outbreak_count: int
    winner_player_id: str | None
    ended_reason: str | None

    @classmethod
    def from_model(cls, m: GameModel) -> Game:
        return cls(
            game_id=m.game_id,
            name=m.name,
            status=m.status,
            is_joinable=m.is_joinable,
            owner_user_id=m.owner_user_id,
            min_players=m.min_players,
            max_players=m.max_players,
            is_public=m.is_public,
            invite_code=m.invite_code,
            player_count=m.player_count,
            map_id=m.map_id,
            config=GameConfig.from_model(m.config),
            setup=SetupState(phase=m.setup.phase, active_seat_order=m.setup.active_seat_order),
            turn=TurnState(
                active_player_id=m.turn.active_player_id,
                actions_remaining=m.turn.actions_remaining,
                reinforcements_to_place=m.turn.reinforcements_to_place,
                turn_number=m.turn.turn_number,
                round_number=m.turn.round_number,
                phase=m.turn.phase,
            ),
            outbreak_count=m.outbreaks.count,
            winner_player_id=m.winner_player_id,
            ended_reason=m.ended_reason,
        )


@strawberry.type
class GameStateView:
    """Composed view of a single game — game root, players, country states, optional map."""

    game: Game
    players: list[Player]
    country_states: list[CountryState]
    map: Map | None

    @classmethod
    def from_snapshot(cls, snap: GameSnapshot) -> GameStateView:
        return cls(
            game=Game.from_model(snap.game),
            players=[Player.from_model(p) for p in snap.players.values()],
            country_states=[CountryState.from_model(s) for s in snap.country_states.values()],
            map=Map.from_model(snap.map),
        )


@strawberry.type
class GameError:
    code: str
    message: str


@strawberry.input
class TilePlacementInput:
    country_id: str
    count: int
