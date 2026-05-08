"""Pydantic base — snake_case Python attrs, camelCase JSON wire format.

Every model in this package inherits from `CamelModel`. This keeps Python idiomatic
(`game.player_id`) while the GraphQL / Firestore JSON shapes stay camelCase
(`{"playerId": "..."}`). Construction accepts either form, matching how Firestore
documents will deserialize on read.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict
from pydantic.alias_generators import to_camel


class CamelModel(BaseModel):
    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=True,
    )
