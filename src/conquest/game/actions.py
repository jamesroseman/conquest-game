"""Action validation + dispatch. See CLAUDE.md § Player turn — N actions.

Pure: takes (snapshot, actor_id, action, rng), mutates snapshot, raises a `RuleError` subclass
on invalid actions. The service layer wraps this in a transaction.
"""

from __future__ import annotations

from typing import cast

from conquest.game.combat import resolve_attack
from conquest.game.elimination import check_win_condition, eliminate_player
from conquest.game.errors import (
    CountryAlreadyVaccinated,
    InvalidAction,
    NotAdjacent,
    NotAllResearchersPresent,
    NotEnoughActions,
    NotEnoughTroops,
    NotYourCountry,
    NotYourTurn,
    ReinforcementsNotPlaced,
    ResearcherNotInCountry,
    WrongPhase,
)
from conquest.game.reinforcements import recompute_player_stats
from conquest.game.rng import SeededRNG
from conquest.models.action import (
    Action,
    AirdropResearcher,
    Attack,
    CreateVaccine,
    Cure,
    MoveResearcherAdjacent,
    MoveTroops,
    PlaceReinforcements,
)
from conquest.models.snapshot import GameSnapshot


def apply_action(
    snapshot: GameSnapshot,
    actor_id: str,
    action: Action,
    rng: SeededRNG,
) -> None:
    """Validate and apply a single in-turn action. Raises `RuleError` subclasses."""
    if snapshot.game.status != "in_progress":
        raise WrongPhase(f"game status is {snapshot.game.status}")
    if snapshot.game.turn.active_player_id != actor_id:
        raise NotYourTurn("not your turn")

    actor = snapshot.players[actor_id]
    if actor.eliminated:
        raise NotYourTurn("eliminated players cannot act")

    # Reinforcements sub-phase comes first; only `place_reinforcements` allowed there.
    if snapshot.game.turn.phase == "reinforcements":
        if not isinstance(action, PlaceReinforcements):
            raise ReinforcementsNotPlaced("place reinforcements before spending actions")
        _apply_place_reinforcements(snapshot, actor_id, action)
        if snapshot.game.turn.reinforcements_to_place == 0:
            snapshot.game.turn.phase = "actions"
        return

    if snapshot.game.turn.phase != "actions":
        raise WrongPhase(f"cannot act during phase {snapshot.game.turn.phase}")

    cfg = snapshot.game.config
    if isinstance(action, MoveResearcherAdjacent):
        _spend(snapshot, cfg.cost_move_researcher_adjacent)
        _move_researcher_adjacent(snapshot, actor_id, action)
    elif isinstance(action, AirdropResearcher):
        _spend(snapshot, cfg.cost_airdrop_researcher)
        _airdrop_researcher(snapshot, actor_id, action)
    elif isinstance(action, Cure):
        _spend(snapshot, cfg.cost_cure)
        _cure(snapshot, actor_id)
    elif isinstance(action, CreateVaccine):
        _spend(snapshot, cfg.cost_create_vaccine)
        _create_vaccine(snapshot, actor_id)
    elif isinstance(action, Attack):
        _spend(snapshot, cfg.cost_attack)
        _attack(snapshot, actor_id, action, rng)
    elif isinstance(action, MoveTroops):
        _spend(snapshot, cfg.cost_move_troops)
        _move_troops(snapshot, actor_id, action)
    else:
        raise InvalidAction(f"action type not allowed in actions phase: {type(action).__name__}")

    recompute_player_stats(snapshot)


def _spend(snapshot: GameSnapshot, cost: int) -> None:
    if snapshot.game.turn.actions_remaining < cost:
        raise NotEnoughActions(f"need {cost}, have {snapshot.game.turn.actions_remaining}")
    snapshot.game.turn.actions_remaining -= cost


def _apply_place_reinforcements(
    snapshot: GameSnapshot, actor_id: str, action: PlaceReinforcements
) -> None:
    total = sum(count for _, count in action.placements)
    if total <= 0:
        raise InvalidAction("must place at least one reinforcement")
    if total > snapshot.game.turn.reinforcements_to_place:
        raise InvalidAction(
            f"placing {total} but only {snapshot.game.turn.reinforcements_to_place} reinforcements available"
        )
    for cid, count in action.placements:
        if count <= 0:
            raise InvalidAction("reinforcement count must be positive")
        state = snapshot.country_states.get(cid)
        if state is None:
            raise InvalidAction(f"unknown country {cid}")
        if state.owner_player_id != actor_id:
            raise NotYourCountry("can only place reinforcements on your countries")
        state.armies += count
    snapshot.game.turn.reinforcements_to_place -= total
    recompute_player_stats(snapshot)


def _move_researcher_adjacent(
    snapshot: GameSnapshot, actor_id: str, action: MoveResearcherAdjacent
) -> None:
    actor = snapshot.players[actor_id]
    if actor.researcher_country_id is None:
        raise InvalidAction("no researcher placed")
    if action.to_country_id not in snapshot.map.countries:
        raise InvalidAction(f"unknown country {action.to_country_id}")
    if action.to_country_id not in snapshot.map.neighbors(actor.researcher_country_id):
        raise NotAdjacent("destination is not adjacent to current researcher country")
    _move_researcher_to(snapshot, actor_id, action.to_country_id)


def _airdrop_researcher(snapshot: GameSnapshot, actor_id: str, action: AirdropResearcher) -> None:
    if action.to_country_id not in snapshot.map.countries:
        raise InvalidAction(f"unknown country {action.to_country_id}")
    _move_researcher_to(snapshot, actor_id, action.to_country_id)


def _move_researcher_to(snapshot: GameSnapshot, actor_id: str, country_id: str) -> None:
    actor = snapshot.players[actor_id]
    if actor.researcher_country_id is not None:
        prev = snapshot.country_states[actor.researcher_country_id]
        if prev.has_researcher == actor_id:
            prev.has_researcher = None
    actor.researcher_country_id = country_id
    snapshot.country_states[country_id].has_researcher = actor_id


def _cure(snapshot: GameSnapshot, actor_id: str) -> None:
    actor = snapshot.players[actor_id]
    if actor.researcher_country_id is None:
        raise ResearcherNotInCountry("no researcher placed")
    state = snapshot.country_states[actor.researcher_country_id]
    state.disease_cubes = 0


def _create_vaccine(snapshot: GameSnapshot, actor_id: str) -> None:
    cfg = snapshot.game.config
    actor = snapshot.players[actor_id]
    if actor.researcher_country_id is None:
        raise ResearcherNotInCountry("no researcher placed")
    target_id = actor.researcher_country_id
    state = snapshot.country_states[target_id]
    if state.vaccinated:
        raise CountryAlreadyVaccinated("country is already vaccinated")
    if cfg.vaccine_requires_all_researchers:
        for p in snapshot.players.values():
            if p.eliminated:
                continue
            if p.researcher_country_id != target_id:
                raise NotAllResearchersPresent("all non-eliminated researchers must be co-located")
    state.vaccinated = True


def _attack(snapshot: GameSnapshot, actor_id: str, action: Attack, rng: SeededRNG) -> None:
    src = snapshot.country_states.get(action.from_country_id)
    dst = snapshot.country_states.get(action.to_country_id)
    if src is None or dst is None:
        raise InvalidAction("unknown country")
    if src.owner_player_id != actor_id:
        raise NotYourCountry("attack source must be owned by you")
    if dst.owner_player_id == actor_id:
        raise InvalidAction("cannot attack your own country")
    if action.to_country_id not in snapshot.map.neighbors(action.from_country_id):
        raise NotAdjacent("attack target must be adjacent to source")
    if action.armies < 1 or action.armies >= src.armies:
        raise NotEnoughTroops("must commit at least 1 and leave at least 1 behind")

    result = resolve_attack(rng, attacker_armies=action.armies, defender_armies=dst.armies)
    src.armies -= action.armies  # commit them
    dst.armies = result.defender_remaining

    if result.captured:
        previous_owner = dst.owner_player_id
        dst.owner_player_id = actor_id
        dst.armies = result.attacker_remaining
        # Capital conquest?
        if previous_owner is not None and dst.is_capital_of == previous_owner:
            cfg = snapshot.game.config
            if cfg.capital_loss_eliminates_player:
                eliminate_player(
                    snapshot,
                    eliminated_id=previous_owner,
                    conqueror_id=actor_id,
                    round_number=snapshot.game.turn.round_number,
                )
                # Mid-turn win check.
                winner = check_win_condition(snapshot)
                if winner is not None:
                    snapshot.game.status = "ended"
                    snapshot.game.ended_reason = "victory"
                    snapshot.game.winner_player_id = winner
    else:
        # Attackers retreat home with whatever survived.
        src.armies += result.attacker_remaining


def _move_troops(snapshot: GameSnapshot, actor_id: str, action: MoveTroops) -> None:
    src = snapshot.country_states.get(action.from_country_id)
    dst = snapshot.country_states.get(action.to_country_id)
    if src is None or dst is None:
        raise InvalidAction("unknown country")
    if src.owner_player_id != actor_id or dst.owner_player_id != actor_id:
        raise NotYourCountry("move requires both ends to be owned by you")
    if action.to_country_id not in snapshot.map.neighbors(action.from_country_id):
        raise NotAdjacent("destination must be adjacent")
    if action.armies < 1 or action.armies >= src.armies:
        raise NotEnoughTroops("must move at least 1 and leave at least 1 behind")
    src.armies -= action.armies
    dst.armies += action.armies


__all__ = ["apply_action"]


# silence unused imports flagged by linters but used at runtime via `cast`
_ = cast
