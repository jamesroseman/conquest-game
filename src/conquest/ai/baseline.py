"""Baseline policy. All archetypes extend this and tweak weights / priorities.

Strategic priors live in `WEIGHTS` and a few overridable methods. Archetypes change those
constants — no archetype rewrites the whole decision pipeline. This keeps the AI predictable
to test and reason about.
"""

from __future__ import annotations

import copy
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
        """Spend the full action budget. Each iteration considers every
        viable option for the current snapshot and picks one weighted by
        the archetype priors. We only stop early when NO action is
        currently viable (e.g. no border to attack, no troops to move),
        not just because a probability roll didn't fire.

        The previous implementation gated every option behind an
        independent `rng.random() < weight*const` check and `break`-ed
        when none fired — so a weights-low archetype could take 1 action
        out of 5 even with plenty of viable moves. That made AI turns
        feel inert and used roughly 1/5 of the action budget.
        """
        actions: list[Action] = []
        max_actions = snapshot.game.turn.actions_remaining
        # Reason over a deep copy. The runner calls apply_action against
        # the *real* snapshot, so we must not mutate it here — earlier
        # versions did, which left the actual state with already-spent
        # troops by the time apply_action validated the intent and
        # caused every attack after the first to fail validation
        # silently (see runner.run_ai_turn's broad except).
        sim = copy.deepcopy(snapshot)
        for _ in range(max_actions):
            options: list[tuple[Action, float]] = []

            cure_a = self._maybe_cure(sim, player_id)
            if cure_a is not None:
                options.append((cure_a, max(0.05, self.weights.cure)))

            vax_a = self._maybe_vaccine(sim, player_id)
            if vax_a is not None:
                options.append((vax_a, max(0.10, self.weights.cooperate_on_vaccine)))

            atk_a = self._maybe_attack(sim, player_id, rng)
            if atk_a is not None:
                options.append((atk_a, max(0.05, self.weights.attack)))

            mv_a = self._maybe_move_researcher(sim, player_id)
            if mv_a is not None:
                options.append((mv_a, max(0.05, self.weights.cure * 0.5)))

            mvt_a = self._maybe_consolidate(sim, player_id, rng)
            if mvt_a is not None:
                options.append((mvt_a, max(0.05, self.weights.consolidate)))

            if not options:
                break

            # Weighted random pick: archetype priors influence WHICH
            # option gets played, but we always take SOMETHING when any
            # option is viable.
            total = sum(w for _, w in options)
            roll = rng.random() * total
            cum = 0.0
            chosen: Action = options[0][0]
            for opt, w in options:
                cum += w
                if roll < cum:
                    chosen = opt
                    break

            actions.append(chosen)

            # Mutate the simulated copy so subsequent iterations see updated
            # state. The real snapshot is untouched.
            if isinstance(chosen, Cure):
                cur = sim.players[player_id].researcher_country_id
                if cur is not None:
                    sim.country_states[cur].disease_cubes = 0
            elif isinstance(chosen, CreateVaccine):
                cur = sim.players[player_id].researcher_country_id
                if cur is not None:
                    sim.country_states[cur].vaccinated = True
            elif isinstance(chosen, Attack):
                sim.country_states[chosen.from_country_id].armies -= chosen.armies
            elif isinstance(chosen, MoveResearcherAdjacent):
                sim.players[player_id].researcher_country_id = chosen.to_country_id
            elif isinstance(chosen, MoveTroops):
                sim.country_states[chosen.from_country_id].armies -= chosen.armies
                sim.country_states[chosen.to_country_id].armies += chosen.armies

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
