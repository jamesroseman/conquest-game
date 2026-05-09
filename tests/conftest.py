"""Shared pytest fixtures."""

from __future__ import annotations

import pytest

from conquest.repositories import InMemoryRepository
from conquest.services.game_service import GameService


@pytest.fixture
def repo() -> InMemoryRepository:
    return InMemoryRepository()


@pytest.fixture
def game_service(repo: InMemoryRepository) -> GameService:
    # Tests run AI drains synchronously so assertions can inspect the
    # post-drain state without waiting on a background thread.
    return GameService(repo, run_ai_in_background=False)
