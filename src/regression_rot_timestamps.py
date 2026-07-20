"""Persisted first-seen timestamps for regression-rot aging (#9597).

``StaleIssueLoop`` needs to know how long a regression test has been sitting
``xfail`` RED while its linked issue is still OPEN (the "orphaned-RED"
classification, > M days). Deriving that from ``git log`` is unreliable —
CI/sandbox checkouts are frequently shallow, so a file's first-commit date
can look artificially recent or be unavailable entirely. Instead this store
records, in-place, the first tick a (still-open, still-RED) issue was
observed, and the loop computes age from that recorded timestamp on
subsequent ticks. It survives process restarts (unlike an in-memory
counter), which matters given the default cadence is once per day.

File format mirrors :class:`dedup_store.DedupStore` (a small JSON blob
written atomically) but stores ``{issue_number: iso_timestamp}`` rather than
a bare set.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

from file_util import atomic_write

logger = logging.getLogger("hydraflow.regression_rot_timestamps")


class RegressionRotTimestamps:
    """File-backed ``{issue_number: first_seen_iso}`` store."""

    def __init__(self, file_path: Path) -> None:
        self._file_path = file_path

    def _read(self) -> dict[str, str]:
        if not self._file_path.exists():
            return {}
        try:
            data = json.loads(self._file_path.read_text())
            return data if isinstance(data, dict) else {}
        except (json.JSONDecodeError, TypeError, OSError):
            return {}

    def _write(self, data: dict[str, str]) -> None:
        try:
            atomic_write(self._file_path, json.dumps(data, sort_keys=True))
        except OSError:
            logger.warning(
                "Could not persist regression-rot timestamps to %s",
                self._file_path,
                exc_info=True,
            )

    def get(self, issue_number: int) -> str | None:
        """Return the recorded first-seen ISO timestamp for *issue_number*, if any."""
        return self._read().get(str(issue_number))

    def set_if_absent(self, issue_number: int, timestamp_iso: str) -> str:
        """Record *timestamp_iso* as first-seen for *issue_number* unless already set.

        Returns the (possibly pre-existing) first-seen timestamp — callers
        use this to compute age without a separate read.
        """
        data = self._read()
        key = str(issue_number)
        if key not in data:
            data[key] = timestamp_iso
            self._write(data)
        return data[key]

    def discard(self, issue_number: int) -> None:
        """Remove *issue_number* if present; silent no-op when absent."""
        data = self._read()
        key = str(issue_number)
        if key not in data:
            return
        data.pop(key, None)
        self._write(data)

    def keep_only(self, issue_numbers: set[int]) -> None:
        """Prune every tracked issue NOT in *issue_numbers*.

        Called each tick with the current set of RED-and-not-yet-resolved
        candidates so a fixed/blocked/removed issue's clock resets instead
        of accumulating forever.
        """
        data = self._read()
        keep_keys = {str(n) for n in issue_numbers}
        pruned = {k: v for k, v in data.items() if k in keep_keys}
        if pruned != data:
            self._write(pruned)
