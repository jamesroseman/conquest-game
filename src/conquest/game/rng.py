"""Seeded RNG. All randomness in the game flows through this."""

from __future__ import annotations

import random
from collections.abc import Sequence
from typing import TypeVar

T = TypeVar("T")


class SeededRNG:
    """Thin wrapper around `random.Random` that keeps a cursor for replay.

    Cursor isn't used for replay yet but is incremented on every draw so we can persist it
    on the game root doc and reconstruct deterministic state if needed.
    """

    def __init__(self, seed: int, cursor: int = 0) -> None:
        self._seed = seed
        self._cursor = cursor
        self._rng = random.Random(seed)
        for _ in range(cursor):
            self._rng.random()

    @property
    def seed(self) -> int:
        return self._seed

    @property
    def cursor(self) -> int:
        return self._cursor

    def _tick(self) -> None:
        self._cursor += 1

    def randint(self, a: int, b: int) -> int:
        self._tick()
        return self._rng.randint(a, b)

    def random(self) -> float:
        self._tick()
        return self._rng.random()

    def choice(self, seq: Sequence[T]) -> T:
        self._tick()
        return self._rng.choice(seq)

    def shuffle(self, seq: list[T]) -> None:
        self._tick()
        self._rng.shuffle(seq)

    def sample(self, population: Sequence[T], k: int) -> list[T]:
        self._tick()
        return self._rng.sample(population, k)

    def weighted_choice(self, items: Sequence[T], weights: Sequence[float]) -> T:
        self._tick()
        return self._rng.choices(items, weights=weights, k=1)[0]
