"""Strawberry GraphQL types. Mirror Pydantic models with explicit field names."""
from __future__ import annotations

from typing import Optional

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
    email: Optional[str]
    displayName: str

    @classmethod
    def from_model(cls, m: UserModel) -> "User":
        return cls(userId=m.userId, email=m.email, displayName=m.displayName)


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
    def from_model(cls, m: GameConfigModel) -> "GameConfig":
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
    actionsPerTurn: Optional[int] = None
    startingTroopsPerPlayer: Optional[int] = None
    outbreakLossThreshold: Optional[int] = None

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
    countryId: Optional[str]

    @classmethod
    def from_model(cls, m: TileModel) -> "Tile":
        return cls(x=m.x, y=m.y, terrain=m.terrain, countryId=m.countryId)


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
    def from_model(cls, m: PathModel) -> "Path":
        return cls(
            pathId=m.pathId, countryAId=m.countryAId, countryBId=m.countryBId, kind=m.kind
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
    def from_model(cls, m: CountryModel) -> "Country":
        return cls(
            countryId=m.countryId,
            name=m.name,
            continentId=m.continentId,
            centroidX=m.centroid[0],
            centroidY=m.centroid[1],
            pathIds=list(m.pathIds),
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
    def from_model(cls, m: ContinentModel) -> "Continent":
        return cls(
            continentId=m.continentId,
            name=m.name,
            isIsland=m.isIsland,
            countryIds=list(m.countryIds),
            tileCount=m.tileCount,
            bonusArmies=m.bonusArmies,
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
    def from_model(cls, m: MapModel) -> "Map":
        return cls(
            mapId=m.mapId,
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
    ownerPlayerId: Optional[str]
    armies: int
    diseaseCubes: int
    vaccinated: bool
    isCapitalOf: Optional[str]
    hasResearcher: Optional[str]

    @classmethod
    def from_model(cls, m: CountryStateModel) -> "CountryState":
        return cls(
            countryId=m.countryId,
            ownerPlayerId=m.ownerPlayerId,
            armies=m.armies,
            diseaseCubes=m.diseaseCubes,
            vaccinated=m.vaccinated,
            isCapitalOf=m.isCapitalOf,
            hasResearcher=m.hasResearcher,
        )


@strawberry.type
class Player:
    playerId: str
    seatOrder: int
    color: str
    kind: str
    userId: Optional[str]
    archetype: Optional[str]
    difficulty: Optional[str]
    troopsRemainingToPlace: int
    researcherCountryId: Optional[str]
    capitalCountryId: Optional[str]
    eliminated: bool
    countriesOwned: int
    totalArmies: int

    @classmethod
    def from_model(cls, m: PlayerModel) -> "Player":
        return cls(
            playerId=m.playerId,
            seatOrder=m.seatOrder,
            color=m.color,
            kind=m.kind,
            userId=m.userId,
            archetype=m.aiConfig.archetype if m.aiConfig else None,
            difficulty=m.aiConfig.difficulty if m.aiConfig else None,
            troopsRemainingToPlace=m.troopsRemainingToPlace,
            researcherCountryId=m.researcherCountryId,
            capitalCountryId=m.capitalCountryId,
            eliminated=m.eliminated,
            countriesOwned=m.stats.countriesOwned,
            totalArmies=m.stats.totalArmies,
        )


@strawberry.type
class TurnState:
    activePlayerId: Optional[str]
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
    inviteCode: Optional[str]
    playerCount: int
    mapId: Optional[str]
    config: GameConfig
    setup: SetupState
    turn: TurnState
    outbreakCount: int
    winnerPlayerId: Optional[str]
    endedReason: Optional[str]

    @classmethod
    def from_model(cls, m: GameModel) -> "Game":
        return cls(
            gameId=m.gameId,
            name=m.name,
            status=m.status,
            isJoinable=m.is_joinable,
            ownerUserId=m.ownerUserId,
            minPlayers=m.minPlayers,
            maxPlayers=m.maxPlayers,
            isPublic=m.isPublic,
            inviteCode=m.inviteCode,
            playerCount=m.playerCount,
            mapId=m.mapId,
            config=GameConfig.from_model(m.config),
            setup=SetupState(phase=m.setup.phase, activeSeatOrder=m.setup.activeSeatOrder),
            turn=TurnState(
                activePlayerId=m.turn.activePlayerId,
                actionsRemaining=m.turn.actionsRemaining,
                reinforcementsToPlace=m.turn.reinforcementsToPlace,
                turnNumber=m.turn.turnNumber,
                roundNumber=m.turn.roundNumber,
                phase=m.turn.phase,
            ),
            outbreakCount=m.outbreaks.count,
            winnerPlayerId=m.winnerPlayerId,
            endedReason=m.endedReason,
        )


@strawberry.type
class GameStateView:
    """Composed view of a single game — game root, players, country states, optional map."""

    game: Game
    players: list[Player]
    countryStates: list[CountryState]
    map: Optional[Map]

    @classmethod
    def from_snapshot(cls, snap: GameSnapshot) -> "GameStateView":
        return cls(
            game=Game.from_model(snap.game),
            players=[Player.from_model(p) for p in snap.players.values()],
            countryStates=[CountryState.from_model(s) for s in snap.countryStates.values()],
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
