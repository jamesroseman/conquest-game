"""Repositories — persistence layer.

The in-memory implementation in `memory.py` is the v0.1 default. A Firestore-backed
implementation will land later behind the same protocol.
"""
from .memory import InMemoryRepository, Repository

__all__ = ["InMemoryRepository", "Repository"]
