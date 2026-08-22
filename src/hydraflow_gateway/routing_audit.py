"""Append-only, hash-linked, sanitized routing-decision audit (ADR-0139).

Each record carries the hash of the record before it, so the log is a chain: a
row edited or removed after the fact breaks every link downstream of it and
:meth:`RoutingAuditLog.verify` reports exactly where. That is the difference
between "we wrote a log" and "we can prove what the resolver decided" — and it
is a precondition for the enforcement phases, which will be asked *why* a spawn
was routed where it was, long after the process that decided it exited.

Two details make the chain hold in this repo rather than in the abstract:

* **Hash the scrubbed bytes, not the intended ones.** ``file_util.append_jsonl``
  redacts credential-shaped substrings on the way to disk (ADR-0085). Hashing
  the pre-scrub payload would produce a chain that fails to verify the moment
  the redactor actually fires — a self-inflicted "tamper" alarm on the one
  record that most needed to be trustworthy. The payload is scrubbed here,
  first, and the digest is taken over what will actually be stored.
* **The tail is read, not remembered.** ``prev_hash`` comes from the last line
  on disk, read back through a bounded seek, so a second writer or a restarted
  process continues the same chain instead of forking a private one.
"""

from __future__ import annotations

import hashlib
import json
import os
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

from file_util import append_jsonl
from secret_scrub import scrub_secrets

if TYPE_CHECKING:
    from collections.abc import Iterator

ROUTING_AUDIT_SCHEMA_VERSION = 1

GENESIS_HASH = "sha256:" + "0" * 64
"""The ``prev_hash`` of the first record in a chain."""

_TAIL_READ_BYTES = 64 * 1024
"""Bounded seek for the last line: the chain head is O(1), not O(file)."""


class AuditChainError(ValueError):
    """The audit file could not be read as a coherent chain."""


@dataclass(frozen=True, slots=True)
class AuditRecord:
    """One immutable, hash-linked entry."""

    seq: int
    recorded_at: str
    prev_hash: str
    payload_hash: str
    record_hash: str
    payload: dict[str, Any]

    def to_json_dict(self) -> dict[str, Any]:
        """The exact shape persisted to the log."""
        return {
            "schema_version": ROUTING_AUDIT_SCHEMA_VERSION,
            "seq": self.seq,
            "recorded_at": self.recorded_at,
            "prev_hash": self.prev_hash,
            "payload_hash": self.payload_hash,
            "record_hash": self.record_hash,
            "payload": self.payload,
        }


@dataclass(frozen=True, slots=True)
class ChainVerification:
    """The result of walking a chain end to end."""

    ok: bool
    records: int
    broken_at_seq: int | None = None


def _canonical(payload: dict[str, Any]) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)


def payload_hash(payload: dict[str, Any]) -> str:
    """Digest of the *scrubbed* canonical payload — what verification recomputes."""
    scrubbed = scrub_secrets(_canonical(payload))
    return "sha256:" + hashlib.sha256(scrubbed.encode("utf-8")).hexdigest()


def link_hash(*, seq: int, prev_hash: str, payload_digest: str) -> str:
    """Digest binding one record to its position and its predecessor."""
    material = f"{seq}|{prev_hash}|{payload_digest}"
    return "sha256:" + hashlib.sha256(material.encode("utf-8")).hexdigest()


class RoutingAuditLog:
    """The append-only chain of routing decisions for one repository."""

    def __init__(self, path: Path) -> None:
        self._path = Path(path)
        self._lock = threading.Lock()

    @property
    def path(self) -> Path:
        """The JSONL file this chain lives in."""
        return self._path

    def append(self, payload: dict[str, Any], *, recorded_at: str) -> AuditRecord:
        """Link *payload* onto the end of the chain and persist it.

        Raises :class:`OSError` if the sink is unwritable; the shadow caller
        treats that as "no record", never as a reason to change a route.
        """
        with self._lock:
            head = self._head()
            seq = 0 if head is None else head.seq + 1
            prev = GENESIS_HASH if head is None else head.record_hash
            # The payload is scrubbed here so the persisted bytes, the digest,
            # and what verify() recomputes are all the same string.
            scrubbed = json.loads(scrub_secrets(_canonical(payload)))
            digest = payload_hash(scrubbed)
            record = AuditRecord(
                seq=seq,
                recorded_at=recorded_at,
                prev_hash=prev,
                payload_hash=digest,
                record_hash=link_hash(seq=seq, prev_hash=prev, payload_digest=digest),
                payload=scrubbed,
            )
            append_jsonl(self._path, _canonical(record.to_json_dict()))
            return record

    def read_all(self) -> tuple[AuditRecord, ...]:
        """Every record in order. A malformed line raises rather than being skipped."""
        return tuple(self._iter_records())

    def verify(self) -> ChainVerification:
        """Walk the chain and report the first record whose links do not hold."""
        expected_prev = GENESIS_HASH
        count = 0
        try:
            records = self._iter_records()
            for index, record in enumerate(records):
                count += 1
                if (
                    record.seq != index
                    or record.prev_hash != expected_prev
                    or record.payload_hash != payload_hash(record.payload)
                    or record.record_hash
                    != link_hash(
                        seq=record.seq,
                        prev_hash=record.prev_hash,
                        payload_digest=record.payload_hash,
                    )
                ):
                    return ChainVerification(
                        ok=False, records=count, broken_at_seq=record.seq
                    )
                expected_prev = record.record_hash
        except AuditChainError:
            return ChainVerification(ok=False, records=count, broken_at_seq=count)
        return ChainVerification(ok=True, records=count)

    def _iter_records(self) -> Iterator[AuditRecord]:
        try:
            raw = self._path.read_text(encoding="utf-8")
        except FileNotFoundError:
            return
        for line in raw.splitlines():
            if line.strip():
                yield _parse(line)

    def _head(self) -> AuditRecord | None:
        """Return the last record via a bounded tail read, or None for a new chain."""
        try:
            size = self._path.stat().st_size
        except FileNotFoundError:
            return None
        if size == 0:
            return None
        with open(self._path, "rb") as handle:
            if size > _TAIL_READ_BYTES:
                handle.seek(size - _TAIL_READ_BYTES, os.SEEK_SET)
            chunk = handle.read()
        tail = chunk.rstrip(b"\n")
        cut = tail.rfind(b"\n")
        if cut == -1 and size > _TAIL_READ_BYTES:
            # One record outgrew the bounded window; pay for the full read
            # rather than link onto a line that was sliced in half.
            tail = self._path.read_bytes().rstrip(b"\n")
            cut = tail.rfind(b"\n")
        last = tail[cut + 1 :]
        if not last.strip():
            return None
        return _parse(last.decode("utf-8"))


def _parse(line: str) -> AuditRecord:
    try:
        raw = json.loads(line)
        return AuditRecord(
            seq=int(raw["seq"]),
            recorded_at=str(raw["recorded_at"]),
            prev_hash=str(raw["prev_hash"]),
            payload_hash=str(raw["payload_hash"]),
            record_hash=str(raw["record_hash"]),
            payload=dict(raw["payload"]),
        )
    except (ValueError, TypeError, KeyError) as exc:
        raise AuditChainError(f"unreadable audit record: {exc}") from exc
