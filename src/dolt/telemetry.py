"""Repository for model pricing."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from dolt.connection import DoltConnection


class ModelPricingRepository:
    """CRUD on the ``model_pricing`` table."""

    def __init__(self, db: DoltConnection) -> None:
        self.db = db

    def upsert(self, model: str, pricing: dict) -> None:
        """Insert or replace pricing for a model."""
        self.db.execute(
            "REPLACE INTO model_pricing "
            "(model_id, input_cost_per_million, output_cost_per_million, "
            "cache_write_cost_per_million, cache_read_cost_per_million, aliases) "
            "VALUES (%s, %s, %s, %s, %s, %s)",
            (
                model,
                pricing.get("input_cost_per_million", 0),
                pricing.get("output_cost_per_million", 0),
                pricing.get("cache_write_cost_per_million", 0),
                pricing.get("cache_read_cost_per_million", 0),
                json.dumps(pricing.get("aliases", [])),
            ),
        )

    def get(self, model: str) -> dict | None:
        """Return pricing for a model, or ``None``."""
        row = self.db.fetchone(
            "SELECT model_id, input_cost_per_million, output_cost_per_million, "
            "cache_write_cost_per_million, cache_read_cost_per_million, aliases "
            "FROM model_pricing WHERE model_id = %s",
            (model,),
        )
        if not row:
            return None
        return {
            "model_id": row[0],
            "input_cost_per_million": row[1],
            "output_cost_per_million": row[2],
            "cache_write_cost_per_million": row[3],
            "cache_read_cost_per_million": row[4],
            "aliases": json.loads(row[5]) if row[5] else [],
        }

    def get_all(self) -> dict[str, dict]:
        """Return all model pricing as ``{model: pricing}``."""
        rows = self.db.fetchall(
            "SELECT model_id, input_cost_per_million, output_cost_per_million, "
            "cache_write_cost_per_million, cache_read_cost_per_million, aliases "
            "FROM model_pricing"
        )
        result = {}
        for r in rows:
            result[r[0]] = {
                "model_id": r[0],
                "input_cost_per_million": r[1],
                "output_cost_per_million": r[2],
                "cache_write_cost_per_million": r[3],
                "cache_read_cost_per_million": r[4],
                "aliases": json.loads(r[5]) if r[5] else [],
            }
        return result

    def delete(self, model: str) -> None:
        """Remove pricing for a model."""
        self.db.execute(
            "DELETE FROM model_pricing WHERE model_id = %s", (model,)
        )
