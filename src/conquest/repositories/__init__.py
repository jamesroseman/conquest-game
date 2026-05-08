"""Repositories — persistence layer.

The in-memory implementation in `memory.py` is the v0.1 default. A persistent backend
will land later behind the same `Repository` protocol.
"""

from .memory import InMemoryRepository, Repository

__all__ = ["InMemoryRepository", "Repository"]
