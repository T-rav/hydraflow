from __future__ import annotations

from pathlib import Path

from auto_tighten.models import Observation
from file_util import append_jsonl, file_lock


class ObservationStore:
    def __init__(self, path: Path) -> None:
        self._path = path

    def append(self, obs: Observation) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        with file_lock(self._path):
            append_jsonl(self._path, obs.model_dump_json())

    def window(self, ratchet_id: str, limit: int) -> list[Observation]:
        if not self._path.exists():
            return []
        out: list[Observation] = []
        for raw_line in self._path.read_text(encoding="utf-8").splitlines():
            line = raw_line.strip()
            if not line:
                continue
            try:
                obs = Observation.model_validate_json(line)
            except ValueError:
                continue
            if obs.ratchet_id == ratchet_id:
                out.append(obs)
        return out[-limit:]
