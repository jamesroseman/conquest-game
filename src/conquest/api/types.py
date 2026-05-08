"""Strawberry GraphQL types.

Wire format is camelCase (GraphQL convention); we read from snake_case Pydantic attrs.
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
    userId: str
    email: str | None
    displayName: str

    @classmethod
    def from_model(cls, m: UserModel) -> User:
        return cls(userId=m.user_id, email=m.email, displayName=m.display_name)


@strawberry.type
class GameConfig:
    actionsPerTurn: int
    startingTroopsPerPlayer: int
    outbreakLossThreshold: int
    maxCubesPerCountry: int
    reinforcementBase: int
    reinforcementPerCountry: int
    reinforcementCapitalBonus: int
    continentBonusPool: int
    winCondition: str

    @classmethod
    def from_model(cls, m: GameConfigModel) -> GameConfig:
        return cls(
            actionsPerTurn=m.actions_per_turn,
            startingTroopsPerPlayer=m.starting_troops_per_player,
            outbreakLossThreshold=m.outbreak_loss_threshold,
            maxCubesPerCountry=m.max_cubes_per_country,
            reinforcementBase=m.reinforcement_base,
            reinforcementPerCountry=m.reinforcement_per_country,
            reinforcementCapitalBonus=m.reinforcement_capital_bonus,
            continentBonusPool=m.continent_bonus_pool,
            winCondition=m.win_condition,
        )


@strawberry.input
class GameConfigInput:
    actionsPerTurn: int | None = None
    startingTroopsPerPlayer: int | None = None
    outbreakLossThreshold: int | None = None

    def to_model(self) -> GameConfigModel:
        defaults = GameConfigModel()
        return GameConfigModel(
            actions_per_turn=self.actionsPerTurn or defaults.actions_per_turn,
            starting_troops_per_player=self.startingTroopsPerPlayer
            or defaults.starting_troops_per_player,
            outbreak_loss_threshold=self.outbreakLossThreshold or defaults.outbreak_loss_threshold,
        )


@strawberry.type
class Tile:
    x: int
    y: int
    terrain: str
    countryId: str | None

    @classmethod
    def from_model(cls, m: TileModel) -> Tile:
        return cls(x=m.x, y=m.y, terrain=m.terrain, countryId=m.country_id)


@strawberry.type
class TileCoord:
    x: int
    y: int


@strawberry.type
class Path:
    pathId: str
    countryAId: str
    countryBId: str
    kind: str

    @classmethod
    def from_model(cls, m: PathModel) -> Path:
        return cls(
            pathId=m.path_id,
            countryAId=m.country_a_id,
            countryBId=m.country_b_id,
            kind=m.kind,
        )


@strawberry.type
class Country:
    countryId: str
    name: str
    continentId: str
    centroidX: float
    centroidY: float
    pathIds: list[str]
    tiles: list[TileCoord]

    @classmethod
    def from_model(cls, m: CountryModel) -> Country:
        return cls(
            countryId=m.country_id,
            name=m.name,
            continentId=m.continent_id,
            centroidX=m.centroid[0],
            centroidY=m.centroid[1],
            pathIds=list(m.path_ids),
            tiles=[TileCoord(x=t[0], y=t[1]) for t in m.tiles],
        )


@strawberry.type
class Continent:
    continentId: str
    name: str
    isIsland: bool
    countryIds: list[str]
    tileCount: int
    bonusArmies: int

    @classmethod
    def from_model(cls, m: ContinentModel) -> Continent:
        return cls(
            continentId=m.continent_id,
            name=m.name,
            isIsland=m.is_island,
            countryIds=list(m.country_ids),
            tileCount=m.tile_count,
            bonusArmies=m.bonus_armies,
        )


@strawberry.type
class Map:
    mapId: str
    width: int
    height: int
    countries: list[Country]
    continents: list[Continent]
    paths: list[Path]
    tiles: list[Tile]

    @classmethod
    def from_model(cls, m: MapModel) -> Map:
        return cls(
            mapId=m.map_id,
            width=m.width,
            height=m.height,
            countries=[Country.from_model(c) for c in m.countries.values()],
            continents=[Continent.from_model(c) for c in m.continents.values()],
            paths=[Path.from_model(p) for p in m.paths.values()],
            tiles=[Tile.from_model(t) for t in m.tiles],
        )


@strawberry.type
class CountryState:
    countryId: str
    ownerPlayerId: str | None
    armies: int
    diseaseCubes: int
    vaccinated: bool
    isCapitalOf: str | None
    hasResearcher: str | None

    @classmethod
    def from_model(cls, m: CountryStateModel) -> CountryState:
        return cls(
            countryId=m.country_id,
            ownerPlayerId=m.owner_player_id,
            armies=m.armies,
            diseaseCubes=m.disease_cubes,
            vaccinated=m.vaccinated,
            isCapitalOf=m.is_capital_of,
            hasResearcher=m.has_researcher,
        )


@strawberry.type
class Player:
    playerId: str
    seatOrder: int
    color: str
    kind: str
    userId: str | None
    archetype: str | None
    difficulty: str | None
    troopsRemainingToPlace: int
    researcherCountryId: str | None
    capitalCountryId: str | None
    eliminated: bool
    countriesOwned: int
    totalArmies: int

    @classmethod
    def from_model(cls, m: PlayerModel) -> Player:
        return cls(
            playerId=m.player_id,
            seatOrder=m.seat_order,
            color=m.color,
            kind=m.kind,
            userId=m.user_id,
            archetype=m.ai_config.archetype if m.ai_config else None,
            difficulty=m.ai_config.difficulty if m.ai_config else None,
            troopsRemainingToPlace=m.troops_remaining_to_place,
            researcherCountryId=m.researcher_country_id,
            capitalCountryId=m.capital_country_id,
            eliminated=m.eliminated,
            countriesOwned=m.stats.countries_owned,
            totalArmies=m.stats.total_armies,
        )


@strawberry.type
class TurnState:
    activePlayerId: str | None
    actionsRemaining: int
    reinforcementsToPlace: int
    turnNumber: int
    roundNumber: int
    phase: str


@strawberry.type
class SetupState:
    phase: str
    activeSeatOrder: int


@strawberry.type
class Game:
    gameId: str
    name: str
    status: str
    isJoinable: bool
    ownerUserId: str
    minPlayers: int
    maxPlayers: int
    isPublic: bool
    inviteCode: str | None
    playerCount: int
    mapId: str | None
    config: GameConfig
    setup: SetupState
    turn: TurnState
    outbreakCount: int
    winnerPlayerId: str | None
    endedReason: str | None

    @classmethod
    def from_model(cls, m: GameModel) -> Game:
        return cls(
            gameId=m.game_id,
            name=m.name,
            status=m.status,
            isJoinable=m.is_joinable,
            ownerUserId=m.owner_user_id,
            minPlayers=m.min_players,
            maxPlayers=m.max_players,
            isPublic=m.is_public,
            inviteCode=m.invite_code,
            playerCount=m.player_count,
            mapId=m.map_id,
            config=GameConfig.from_model(m.config),
            setup=SetupState(phase=m.setup.phase, activeSeatOrder=m.setup.active_seat_order),
            turn=TurnState(
                activePlayerId=m.turn.active_player_id,
                actionsRemaining=m.turn.actions_remaining,
                reinforcementsToPlace=m.turn.reinforcements_to_place,
                turnNumber=m.turn.turn_number,
                roundNumber=m.turn.round_number,
                phase=m.turn.phase,
            ),
            outbreakCount=m.outbreaks.count,
            winnerPlayerId=m.winner_player_id,
            endedReason=m.ended_reason,
        )


@strawberry.type
class GameStateView:
    """Composed view of a single game — game root, players, country states, optional map."""

    game: Game
    players: list[Player]
    countryStates: list[CountryState]
    map: Map | None

    @classmethod
    def from_snapshot(cls, snap: GameSnapshot) -> GameStateView:
        return cls(
            game=Game.from_model(snap.game),
            players=[Player.from_model(p) for p in snap.players.values()],
            countryStates=[CountryState.from_model(s) for s in snap.country_states.values()],
            map=Map.from_model(snap.map),
        )


@strawberry.type
class GameError:
    code: str
    message: str


@strawberry.input
class TilePlacementInput:
    countryId: str
    count: int
