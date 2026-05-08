"""Baseline policy. All archetypes extend this and tweak weights / priorities.

Strategic priors live in `WEIGHTS` and a few overridable methods. Archetypes change those
constants — no archetype rewrites the whole decision pipeline. This keeps the AI predictable
to test and reason about.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from conquest.game.rng import SeededRNG
from conquest.models.action import (
    Action,
    Attack,
    CreateVaccine,
    Cure,
    MoveResearcherAdjacent,
    MoveTroops,
)
from conquest.models.snapshot import GameSnapshot


@dataclass
class Weights:
    """Soft strategic priors. Range is roughly 0.0 (never) to 2.0 (very eager)."""

    attack: float = 1.0
    expand: float = 1.0  # bias toward attacking unowned/weak countries
    cure: float = 1.0
    cooperate_on_vaccine: float = 0.5
    consolidate: float = 0.5  # move troops toward borders
    target_leader: float = 0.0  # extra eagerness vs the leading player
    risk_tolerance: float = 1.0
    randomness: float = 0.0


@dataclass
class BaselinePolicy:
    archetype: str = "baseline"
    weights: Weights = field(default_factory=Weights)

    # --- Setup -----------------------------------------------------------------

    def setup_troop_target(self, snapshot: GameSnapshot, player_id: str, rng: SeededRNG) -> str:
        # Until every country has an owner, claim a fresh one.
        unclaimed = [cid for cid, s in snapshot.country_states.items() if s.owner_player_id is None]
        if unclaimed:
            return rng.choice(sorted(unclaimed))
        # Otherwise reinforce our largest country.
        owned = [
            (cid, s.armies)
            for cid, s in snapshot.country_states.items()
            if s.owner_player_id == player_id
        ]
        owned.sort(key=lambda t: (-t[1], t[0]))
        return owned[0][0]

    def setup_researcher_target(
        self, snapshot: GameSnapshot, player_id: str, rng: SeededRNG
    ) -> str:
        # Place on a country with disease cubes if we own one nearby; else our biggest.
        owned = snapshot.countries_owned_by(player_id)
        infected = [cid for cid in owned if snapshot.country_states[cid].disease_cubes > 0]
        if infected:
            return min(
                infected,
                key=lambda c: -snapshot.country_states[c].disease_cubes,
            )
        return max(owned, key=lambda c: snapshot.country_states[c].armies)

    def setup_capital_target(self, snapshot: GameSnapshot, player_id: str, rng: SeededRNG) -> str:
        # Capital on a centrally-connected, well-armied country, ideally inland.
        owned = snapshot.countries_owned_by(player_id)

        def score(cid: str) -> tuple[int, int]:
            country = snapshot.map.countries[cid]
            return (len(country.path_ids), snapshot.country_states[cid].armies)

        return max(owned, key=score)

    # --- Reinforcements --------------------------------------------------------

    def reinforce(
        self, snapshot: GameSnapshot, player_id: str, total: int, rng: SeededRNG
    ) -> list[tuple[str, int]]:
        if total <= 0:
            return []
        owned = snapshot.countries_owned_by(player_id)
        if not owned:
            return []
        # Prefer border countries (have an enemy or unowned neighbor).
        scored: list[tuple[str, float]] = []
        for cid in owned:
            border = self._is_border(snapshot, cid, player_id)
            armies = snapshot.country_states[cid].armies
            score = (1.5 if border else 1.0) - armies * 0.05
            scored.append((cid, score))
        scored.sort(key=lambda t: -t[1])
        # Drop most onto the top scorer; throw a few onto the runner-up.
        primary = scored[0][0]
        out: list[tuple[str, int]] = []
        if len(scored) > 1 and total > 3:
            out.append((primary, total - 2))
            out.append((scored[1][0], 2))
        else:
            out.append((primary, total))
        return out

    # --- Actions ---------------------------------------------------------------

    def take_actions(self, snapshot: GameSnapshot, player_id: str, rng: SeededRNG) -> list[Action]:
        actions: list[Action] = []
        max_actions = snapshot.game.turn.actions_remaining
        cfg = snapshot.game.config
        for _ in range(max_actions):
            # Cure if our researcher sits on a heavily-infected country.
            cure_action = self._maybe_cure(snapshot, player_id)
            if cure_action is not None and rng.random() < self.weights.cure * 0.5:
                actions.append(cure_action)
                # Mutate snapshot lightly so subsequent decisions don't repeat.
                cur = snapshot.players[player_id].researcher_country_id
                if cur is not None:
                    snapshot.country_states[cur].disease_cubes = 0
                continue
            # Vaccine if all conditions look good (uncommon — most archetypes won't get this).
            vax = self._maybe_vaccine(snapshot, player_id)
            if vax is not None and rng.random() < self.weights.cooperate_on_vaccine:
                actions.append(vax)
                cur = snapshot.players[player_id].researcher_country_id
                if cur is not None:
                    snapshot.country_states[cur].vaccinated = True
                continue
            # Attack a weak adjacent enemy.
            atk = self._maybe_attack(snapshot, player_id, rng)
            if atk is not None and rng.random() < self.weights.attack * 0.6:
                actions.append(atk)
                # Apply naively: ignore success vs failure for planning, just decrement source.
                snapshot.country_states[atk.from_country_id].armies -= atk.armies
                continue
            # Move researcher toward an infected country if we can.
            mv = self._maybe_move_researcher(snapshot, player_id)
            if mv is not None and rng.random() < self.weights.cure * 0.4:
                actions.append(mv)
                snapshot.players[player_id].researcher_country_id = mv.to_country_id
                continue
            # Consolidate troops toward a border.
            mvt = self._maybe_consolidate(snapshot, player_id, rng)
            if mvt is not None and rng.random() < self.weights.consolidate:
                actions.append(mvt)
                snapshot.country_states[mvt.from_country_id].armies -= mvt.armies
                snapshot.country_states[mvt.to_country_id].armies += mvt.armies
                continue
            # No good move — stop spending actions.
            break
        # Discard unused budget (caller calls end_turn).
        _ = cfg
        return actions

    # --- helpers ---------------------------------------------------------------

    def _is_border(self, snapshot: GameSnapshot, cid: str, player_id: str) -> bool:
        for nb in snapshot.map.neighbors(cid):
            owner = snapshot.country_states[nb].owner_player_id
            if owner != player_id:
                return True
        return False

    def _maybe_cure(self, snapshot: GameSnapshot, player_id: str) -> Cure | None:
        cur = snapshot.players[player_id].researcher_country_id
        if cur is None:
            return None
        if snapshot.country_states[cur].disease_cubes >= 2:
            return Cure()
        return None

    def _maybe_vaccine(self, snapshot: GameSnapshot, player_id: str) -> CreateVaccine | None:
        cur = snapshot.players[player_id].researcher_country_id
        if cur is None:
            return None
        # Only viable if every alive player's researcher is co-located here.
        for p in snapshot.players.values():
            if p.eliminated:
                continue
            if p.researcher_country_id != cur:
                return None
        if snapshot.country_states[cur].vaccinated:
            return None
        return CreateVaccine()

    def _maybe_attack(
        self, snapshot: GameSnapshot, player_id: str, rng: SeededRNG
    ) -> Attack | None:
        candidates: list[tuple[Attack, float]] = []
        for cid, state in snapshot.country_states.items():
            if state.owner_player_id != player_id or state.armies < 3:
                continue
            for nb in snapshot.map.neighbors(cid):
                target = snapshot.country_states[nb]
                if target.owner_player_id == player_id:
                    continue
                # Power gap times tolerance + leader bias.
                gap = state.armies - target.armies
                bias = 1.0 + self.weights.expand * (1.0 if target.owner_player_id is None else 0.0)
                if target.owner_player_id is not None:
                    bias += self.weights.target_leader * self._leader_bias(
                        snapshot, target.owner_player_id
                    )
                score = gap * bias * self.weights.risk_tolerance
                if score <= 0:
                    continue
                attack = Attack(
                    from_country_id=cid,
                    to_country_id=nb,
                    armies=max(1, state.armies - 1),
                )
                candidates.append((attack, score))
        if not candidates:
            return None
        candidates.sort(key=lambda t: -t[1])
        # Add a touch of noise.
        if self.weights.randomness > 0 and rng.random() < self.weights.randomness:
            return rng.choice([c[0] for c in candidates])
        return candidates[0][0]

    def _maybe_move_researcher(
        self, snapshot: GameSnapshot, player_id: str
    ) -> MoveResearcherAdjacent | None:
        cur = snapshot.players[player_id].researcher_country_id
        if cur is None:
            return None
        best: tuple[str, int] | None = None
        for nb in snapshot.map.neighbors(cur):
            cubes = snapshot.country_states[nb].disease_cubes
            if cubes > 0 and (best is None or cubes > best[1]):
                best = (nb, cubes)
        if best is None:
            return None
        return MoveResearcherAdjacent(to_country_id=best[0])

    def _maybe_consolidate(
        self, snapshot: GameSnapshot, player_id: str, rng: SeededRNG
    ) -> MoveTroops | None:
        # Move from a safe interior country toward a border.
        for cid, state in snapshot.country_states.items():
            if state.owner_player_id != player_id or state.armies < 4:
                continue
            if self._is_border(snapshot, cid, player_id):
                continue
            for nb in snapshot.map.neighbors(cid):
                if snapshot.country_states[nb].owner_player_id == player_id and self._is_border(
                    snapshot, nb, player_id
                ):
                    return MoveTroops(
                        from_country_id=cid,
                        to_country_id=nb,
                        armies=state.armies - 1,
                    )
        return None

    def _leader_bias(self, snapshot: GameSnapshot, target_player_id: str) -> float:
        # 1.0 if the target is currently leading by countries-owned, else 0.
        ranked = sorted(
            snapshot.players.values(),
            key=lambda p: (-p.stats.countries_owned, p.seat_order),
        )
        if not ranked:
            return 0.0
        return 1.0 if ranked[0].player_id == target_player_id else 0.0
