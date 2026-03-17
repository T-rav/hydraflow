"""Crash-recovery state persistence for HydraFlow.

This package decomposes ``StateTracker`` into domain-based mixins for
maintainability while preserving the single-class public API.

Usage unchanged::

    from state import StateTracker
"""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any, TypeVar

from pydantic import ValidationError

from file_util import atomic_write
from models import StateData

if TYPE_CHECKING:
    from dolt_backend import DoltBackend

from ._epic import EpicStateMixin
from ._hitl import HITLStateMixin
from ._issue import IssueStateMixin
from ._lifetime import LifetimeStatsMixin
from ._report import ReportStateMixin
from ._review import ReviewStateMixin
from ._session import SessionStateMixin
from ._worker import WorkerStateMixin
from ._worktree import WorktreeStateMixin

logger = logging.getLogger("hydraflow.state")

_V = TypeVar("_V")

__all__ = ["StateTracker", "build_state_tracker"]


class StateTracker(
    IssueStateMixin,
    WorktreeStateMixin,
    HITLStateMixin,
    ReviewStateMixin,
    EpicStateMixin,
    LifetimeStatsMixin,
    SessionStateMixin,
    WorkerStateMixin,
    ReportStateMixin,
):
    """JSON-file backed state for crash recovery.

    Writes ``<repo_root>/.hydraflow/state.json`` after every mutation.

    Composed from domain-specific mixins; all methods are available
    directly on this class.
    """

    # --- int↔str key conversion helpers ---

    @staticmethod
    def _key(issue_id: int | str) -> str:
        """Convert an issue/PR/epic number to the string key used in state dicts."""
        return str(issue_id)

    @staticmethod
    def _int_keys(d: dict[str, _V]) -> dict[int, _V]:
        """Return a copy of *d* with all keys converted from ``str`` to ``int``.

        Non-integer keys are skipped with a warning.
        """
        result: dict[int, _V] = {}
        for k, v in d.items():
            try:
                result[int(k)] = v
            except (ValueError, TypeError):
                logger.warning("Skipping non-integer state key: %r", k)
        return result

    def __init__(
        self,
        state_file: Path,
        *,
        dolt: DoltBackend | None = None,
    ) -> None:
        self._path = state_file
        self._dolt = dolt
        self._data: StateData = StateData()
        self.load()

    # --- persistence ---

    def load(self) -> None:
        """Load state from Dolt (if configured) or disk."""
        if self._dolt:
            try:
                loaded = self._dolt.load_state()
                if loaded and isinstance(loaded, dict):
                    self._data = StateData.model_validate(loaded)
                    logger.info("State loaded from Dolt")
                else:
                    # Dolt empty — try file fallback for initial migration
                    self._load_from_file()
            except (ValueError, ValidationError) as exc:
                logger.warning("Corrupt Dolt state, resetting: %s", exc, exc_info=True)
                self._data = StateData()
        else:
            self._load_from_file()
        self._maybe_migrate_worker_states()

    def _load_from_file(self) -> None:
        """Load state from the JSON file."""
        if self._path.exists():
            try:
                loaded = json.loads(self._path.read_text())
                if not isinstance(loaded, dict):
                    raise ValueError("State file must contain a JSON object")
                self._data = StateData.model_validate(loaded)
                logger.info("State loaded from %s", self._path)
            except (
                json.JSONDecodeError,
                OSError,
                ValueError,
                UnicodeDecodeError,
                ValidationError,
            ) as exc:
                logger.warning("Corrupt state file, resetting: %s", exc, exc_info=True)
                self._data = StateData()

    def save(self) -> None:
        """Flush current state to Dolt (if configured) or disk."""
        self._data.last_updated = datetime.now(UTC).isoformat()
        data = self._data.model_dump_json(indent=2)
        if self._dolt:
            self._dolt.save_state(data)
        else:
            atomic_write(self._path, data)

    def commit_state(self, message: str = "state update") -> None:
        """Create a Dolt version commit (no-op when using file backend)."""
        if self._dolt:
            self._dolt.commit(message)

    # --- reset ---

    def reset(self) -> None:
        """Clear all state and persist.  Lifetime stats are preserved."""
        saved_lifetime = self._data.lifetime_stats.model_copy()
        self._data = StateData(lifetime_stats=saved_lifetime)
        self.save()

    def to_dict(self) -> dict[str, Any]:
        """Return a copy of the raw state dict."""
        return self._data.model_dump()


def build_state_tracker(config: Any) -> StateTracker:
    """Construct a ``StateTracker`` with the appropriate backend.

    When ``config.dolt_enabled`` is ``True`` and the ``dolt`` CLI is
    available, the state is persisted to an embedded Dolt repo.
    Otherwise the default JSON-file backend is used.
    """
    dolt_backend = None
    if getattr(config, "dolt_enabled", False):
        try:
            from dolt_backend import DoltBackend

            dolt_dir = Path(str(config.state_file)).parent / "dolt"
            dolt_backend = DoltBackend(dolt_dir)
            logger.info("Dolt state backend enabled at %s", dolt_dir)
        except FileNotFoundError:
            logger.warning("dolt CLI not found — falling back to file-based state")
        except Exception:
            logger.warning(
                "Dolt init failed — falling back to file-based state", exc_info=True
            )
    return StateTracker(config.state_file, dolt=dolt_backend)
