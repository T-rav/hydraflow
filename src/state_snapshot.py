"""State snapshot/restore for isolated confidence system testing.

Enables transactional testing of the confidence system without
polluting production state.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from confidence import ConfidenceWeights
from dora_tracker import DORASnapshot

logger = logging.getLogger("hydraflow.state_snapshot")


class StateSnapshot(BaseModel):
    """Point-in-time snapshot of state for isolated testing."""

    timestamp: str = Field(default_factory=lambda: datetime.now(UTC).isoformat())
    state_data: dict[str, Any] = Field(default_factory=dict)
    confidence_weights: ConfidenceWeights = Field(default_factory=ConfidenceWeights)
    dora_snapshot: DORASnapshot = Field(default_factory=DORASnapshot)


class StateSnapshotManager:
    """Captures, stores, and restores state snapshots."""

    def __init__(self, snapshot_dir: Path) -> None:
        self._dir = snapshot_dir
        self._dir.mkdir(parents=True, exist_ok=True)

    def capture(
        self,
        state_data: dict[str, Any],
        weights: ConfidenceWeights | None = None,
        dora: DORASnapshot | None = None,
    ) -> StateSnapshot:
        """Capture current state into a snapshot."""
        snapshot = StateSnapshot(
            state_data=state_data,
            confidence_weights=weights or ConfidenceWeights(),
            dora_snapshot=dora or DORASnapshot(),
        )
        return snapshot

    def save(self, snapshot: StateSnapshot, name: str) -> Path:
        """Persist a snapshot to disk."""
        path = self._dir / f"{name}.json"
        path.write_text(snapshot.model_dump_json(indent=2))
        logger.info("Saved state snapshot to %s", path)
        return path

    def load(self, name: str) -> StateSnapshot | None:
        """Load a snapshot from disk."""
        path = self._dir / f"{name}.json"
        if not path.exists():
            return None
        try:
            return StateSnapshot.model_validate_json(path.read_text())
        except Exception:
            logger.warning("Failed to load snapshot %s", path, exc_info=True)
            return None

    def list_snapshots(self) -> list[str]:
        """List available snapshot names."""
        return sorted(p.stem for p in self._dir.glob("*.json"))

    def delete(self, name: str) -> bool:
        """Delete a snapshot."""
        path = self._dir / f"{name}.json"
        if path.exists():
            path.unlink()
            return True
        return False
