"""Durable, append-only record of committed driver boundaries (#11535).

ADR-0137 C8 fixes the order of a phase boundary and names the two crash windows
this file has to survive:

* **killed between the artifact persist and the label swap** — the boundary did
  *not* commit. The journal must not claim it did, or recovery would skip a
  transition the label never took and the issue would sit at the old stage
  forever with nothing left to move it.
* **killed between the label swap and the checkpoint append** — the boundary
  *did* commit, on GitHub, where truth lives. The journal lags, and that is
  explicitly allowed: recovery reads the label (ADR-0137 C2/C5) and lands on the
  right stage without ever consulting this file.

So the invariant is one-directional and deliberately conservative: **an entry in
:meth:`DriverJournal.committed_keys` is written only after the label swap has
returned.** A missing entry costs one idempotent replay of a phase; a *premature*
entry would cost a stuck issue. When in doubt the journal under-claims.

That is why the artifact and the checkpoint are two different record kinds
rather than one: the artifact is written first and carries no commit claim,
while only the checkpoint marks a boundary as done.

The format is JSONL because it is append-only, survives a partial final line,
and can be read by an operator with ``tail``. It is not a database and is not a
source of truth — losing this file entirely degrades the factory to replaying
some phases, never to a wrong stage.
"""

from __future__ import annotations

import json
import logging
import os
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Mapping
    from pathlib import Path

    from driver_contracts import DriverCheckpoint

logger = logging.getLogger("driver_journal")

RECORD_ARTIFACT = "artifact"
RECORD_CHECKPOINT = "checkpoint"


class DriverJournal:
    """Append-only JSONL journal of driver artifacts and committed boundaries.

    Reads are cached in memory after the first load: within one process the
    journal is the only writer, so the cache cannot go stale, and recovery reads
    it exactly once at boot.
    """

    def __init__(self, path: Path) -> None:
        self._path = path
        self._committed: dict[int, set[str]] | None = None
        self._last_epoch: dict[int, int] = {}

    @property
    def path(self) -> Path:
        return self._path

    # -- reads --------------------------------------------------------------

    def committed_keys(self, issue_number: int) -> frozenset[str]:
        """Boundary keys whose label swap has returned for *issue_number*."""
        return frozenset(self._load().get(issue_number, ()))

    def last_epoch(self, issue_number: int) -> int | None:
        """Highest epoch any committed boundary for *issue_number* was made at.

        A driver rebuilt after a restart starts one above this, which fences any
        process from the previous generation that is somehow still alive — the
        recovery half of the epoch token, and the reason the journal records the
        epoch at all rather than only the key.
        """
        self._load()
        return self._last_epoch.get(issue_number)

    def _load(self) -> dict[int, set[str]]:
        if self._committed is not None:
            return self._committed
        committed: dict[int, set[str]] = {}
        if self._path.exists():
            for line in self._path.read_text(encoding="utf-8").splitlines():
                record = self._parse(line)
                if record is None or record.get("kind") != RECORD_CHECKPOINT:
                    continue
                issue = record.get("issue")
                key = record.get("key")
                if isinstance(issue, int) and isinstance(key, str):
                    committed.setdefault(issue, set()).add(key)
                    self._note_epoch(issue, record.get("checkpoint"))
        self._committed = committed
        return committed

    def _note_epoch(self, issue_number: int, checkpoint: object) -> None:
        if not isinstance(checkpoint, dict):
            return
        epoch = checkpoint.get("epoch")
        if not isinstance(epoch, int):
            return
        current = self._last_epoch.get(issue_number)
        if current is None or epoch > current:
            self._last_epoch[issue_number] = epoch

    @staticmethod
    def _parse(line: str) -> dict[str, Any] | None:
        """Decode one JSONL line, tolerating a truncated tail.

        A process killed mid-write leaves a partial final line. That is a normal
        consequence of the crash windows this journal exists for, so it is
        skipped rather than treated as corruption.
        """
        stripped = line.strip()
        if not stripped:
            return None
        try:
            record = json.loads(stripped)
        except json.JSONDecodeError:
            logger.debug("driver journal: skipping unparseable line")
            return None
        return record if isinstance(record, dict) else None

    # -- writes -------------------------------------------------------------

    def persist_artifact(
        self, issue_number: int, key: str, artifact: Mapping[str, object]
    ) -> None:
        """C8 step 2. Records the phase's output; claims **no** commit."""
        self._append(
            {
                "kind": RECORD_ARTIFACT,
                "issue": issue_number,
                "key": key,
                "artifact": {k: _jsonable(v) for k, v in artifact.items()},
            }
        )

    def append_checkpoint(
        self, issue_number: int, key: str, checkpoint: DriverCheckpoint
    ) -> None:
        """C8 step 4. Marks the boundary committed — only ever called after the swap."""
        self._append(
            {
                "kind": RECORD_CHECKPOINT,
                "issue": issue_number,
                "key": key,
                "checkpoint": checkpoint.model_dump(mode="json"),
            }
        )
        self._load().setdefault(issue_number, set()).add(key)
        self._note_epoch(issue_number, checkpoint.model_dump(mode="json"))

    def _append(self, record: Mapping[str, object]) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        with self._path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, sort_keys=True) + "\n")
            handle.flush()
            os.fsync(handle.fileno())


def _jsonable(value: object) -> object:
    """Coerce an artifact value to something ``json.dumps`` accepts.

    Artifacts come from phase adapters and may carry a result object. The
    journal is an audit trail, not a serializer contract, so an unencodable
    value degrades to its ``repr`` rather than failing the boundary — a
    boundary must never fail to commit because its audit line was awkward.
    """
    if isinstance(value, str | int | float | bool | type(None)):
        return value
    if isinstance(value, list | tuple):
        return [_jsonable(v) for v in value]
    if isinstance(value, dict):
        return {str(k): _jsonable(v) for k, v in value.items()}
    return repr(value)
