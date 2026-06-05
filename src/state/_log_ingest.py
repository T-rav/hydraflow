"""State accessors for LogIngestLoop — per-file byte-offset cursors.

The cursor implements the "cursor-from-now" contract: on the first run for a
given log file the loop primes the cursor to the file's current EOF (no
filing), then only parses bytes appended after that offset on subsequent runs.
This avoids re-filing historical errors that may already be fixed.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from models import StateData


class LogIngestStateMixin:
    """Per-log-file byte-offset cursor for the log-ingest loop."""

    _data: StateData

    def save(self) -> None: ...  # provided by CoreMixin

    def get_log_ingest_cursor(self, path: str) -> int | None:
        """Return the persisted byte offset for *path*, or ``None`` if unprimed.

        ``None`` (key absent) is distinct from ``0`` (an empty file primed at
        EOF zero): the first signals "prime and file nothing"; the second
        signals "scan from the start of an empty file".
        """
        cursor = self._data.log_ingest_cursor.get(path)
        return int(cursor) if cursor is not None else None

    def set_log_ingest_cursor(self, path: str, offset: int) -> None:
        """Persist the last-scanned EOF byte *offset* for *path*."""
        cursors = dict(self._data.log_ingest_cursor)
        cursors[path] = int(offset)
        self._data.log_ingest_cursor = cursors
        self.save()
