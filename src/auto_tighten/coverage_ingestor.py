from __future__ import annotations

import json
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

from auto_tighten.models import CoverageRecord
from file_util import append_jsonl, file_lock


class CoverageIngestor:
    def __init__(
        self,
        path: Path,
        fetch_latest: Callable[[], tuple[str, str, str] | None],
    ) -> None:
        self._path = path
        self._fetch_latest = fetch_latest

    def _last_run_id(self) -> str | None:
        if not self._path.exists():
            return None
        lines = [line for line in self._path.read_text().splitlines() if line.strip()]
        if not lines:
            return None
        try:
            return CoverageRecord.model_validate_json(lines[-1]).run_id
        except ValueError:
            return None

    def ingest(self) -> CoverageRecord | None:
        fetched = self._fetch_latest()
        if fetched is None:
            return None
        run_id, commit_sha, cov_text = fetched
        if run_id == self._last_run_id():
            return None
        try:
            pct = float(json.loads(cov_text)["totals"]["percent_covered"])
        except (ValueError, KeyError):
            return None
        rec = CoverageRecord(
            timestamp=datetime.now(UTC).isoformat(),
            coverage_percent=pct,
            commit_sha=commit_sha,
            run_id=run_id,
        )
        self._path.parent.mkdir(parents=True, exist_ok=True)
        with file_lock(self._path):
            append_jsonl(self._path, rec.model_dump_json())
        return rec
