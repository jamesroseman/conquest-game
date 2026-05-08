"""Repositories — persistence layer.

The in-memory implementation in `memory.py` is the v0.1 default. A Firestore-backed
implementation will land later behind the same protocol.
"""
from .memory import InMemoryRepository, Repository

__all__ = ["FirestoreRepository", "InMemoryRepository", "Repository"]


def __getattr__(name: str):  # type: ignore[no-untyped-def]
    """Lazy import of FirestoreRepository — `google-cloud-firestore` is optional."""
    if name == "FirestoreRepository":
        from .firestore import FirestoreRepository as _F  # noqa: N814
        return _F
    raise AttributeError(name)
