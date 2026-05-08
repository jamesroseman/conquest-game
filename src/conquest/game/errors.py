"""Typed rule-violation errors. Raised by the pure rules engine."""
from __future__ import annotations


class RuleError(Exception):
    """Base class for all rule violations. Mapped to GraphQL union types at the API layer."""

    code: str = "RULE_ERROR"


class NotYourTurn(RuleError):
    code = "NOT_YOUR_TURN"


class NotInGame(RuleError):
    code = "NOT_IN_GAME"


class InvalidAction(RuleError):
    code = "INVALID_ACTION"


class NotEnoughActions(RuleError):
    code = "NOT_ENOUGH_ACTIONS"


class NotYourCountry(RuleError):
    code = "NOT_YOUR_COUNTRY"


class ResearcherNotInCountry(RuleError):
    code = "RESEARCHER_NOT_IN_COUNTRY"


class NotAllResearchersPresent(RuleError):
    code = "NOT_ALL_RESEARCHERS_PRESENT"


class CountryAlreadyVaccinated(RuleError):
    code = "COUNTRY_ALREADY_VACCINATED"


class ReinforcementsNotPlaced(RuleError):
    code = "REINFORCEMENTS_NOT_PLACED"


class NotAdjacent(RuleError):
    code = "NOT_ADJACENT"


class GameNotJoinable(RuleError):
    code = "GAME_NOT_JOINABLE"


class GameNotStartable(RuleError):
    code = "GAME_NOT_STARTABLE"


class WrongPhase(RuleError):
    code = "WRONG_PHASE"


class CountryNotEmpty(RuleError):
    code = "COUNTRY_NOT_EMPTY"


class CountryNotUnclaimed(RuleError):
    code = "COUNTRY_NOT_UNCLAIMED"


class NotEnoughTroops(RuleError):
    code = "NOT_ENOUGH_TROOPS"
