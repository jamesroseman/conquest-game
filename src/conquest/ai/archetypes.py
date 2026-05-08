"""12 archetypes. See CLAUDE.md § Archetypes.

Each is a single-line tweak of `BaselinePolicy.weights`. They share the rest of the decision
pipeline so they're predictable and easy to balance.
"""

from __future__ import annotations

from .baseline import BaselinePolicy, Weights
from .policy import Policy


def _make(name: str, **w: float) -> BaselinePolicy:
    return BaselinePolicy(archetype=name, weights=Weights(**w))


# Each archetype dialed to its strategic prior. See the table in CLAUDE.md.
ARCHETYPES: dict[str, Policy] = {
    "aggressor": _make("aggressor", attack=1.8, expand=1.4, risk_tolerance=1.5, cure=0.5),
    "turtle": _make("turtle", attack=0.3, consolidate=1.5, risk_tolerance=0.6),
    "medic": _make("medic", attack=0.6, cure=2.0, cooperate_on_vaccine=1.5),
    "opportunist": _make("opportunist", attack=1.2, risk_tolerance=0.7, expand=1.2),
    "expansionist": _make("expansionist", attack=1.4, expand=2.0, consolidate=0.3),
    "consolidator": _make("consolidator", attack=0.8, consolidate=1.8, expand=0.8),
    "saboteur": _make("saboteur", attack=1.4, target_leader=2.0, expand=0.6),
    "kingmaker": _make("kingmaker", attack=1.0, target_leader=2.5),
    "doomsayer": _make("doomsayer", attack=0.5, cure=1.8, cooperate_on_vaccine=2.0),
    "isolationist": _make("isolationist", attack=0.5, consolidate=1.4, risk_tolerance=0.5),
    "bandwagon": _make("bandwagon", attack=1.2, target_leader=1.0, randomness=0.3),
    "chaos": _make("chaos", attack=1.2, expand=1.2, randomness=1.0),
}


def policy_for(archetype: str) -> Policy:
    """Return the singleton policy for an archetype id. Raises KeyError on unknown."""
    return ARCHETYPES[archetype]


__all__ = ["ARCHETYPES", "policy_for"]
