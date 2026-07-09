"""Hash-chained append-only audit streams (CH-1, #9729).

Tamper-evident wrapper around HydraFlow's JSONL audit append sites. Each
appended record carries two extra fields:

* ``prev_hash`` — the ``record_hash`` of the preceding record (or the genesis
  sentinel for the first chained record of a stream).
* ``record_hash`` — sha256 over the canonical JSON of the record's payload
  plus its ``prev_hash``.

Any out-of-band edit, deletion, insertion, or corruption (the #9474 failure
shape: a stash conflict marker silently becoming an audit baseline) breaks the
chain and is reported by :func:`verify_file` / :meth:`AuditChain.verify`,
turning tampering into a detected event instead of silent drift.

Chained streams (see :func:`audit_streams`):

* preflight — ``<data_root>/auto_agent/audit.jsonl`` (``preflight.audit``)
* health_decisions — ``<memory_dir>/decisions.jsonl`` (``health_monitor_loop``)
* inference_telemetry — ``<repo_data_root>/metrics/prompt/inferences.jsonl``
  (``prompt_telemetry``)
* approval_records — ``<repo_data_root>/audit/approval_records.jsonl``
  (``approval_records``, CH-2 #9730: structured merge sign-off evidence)
* evidence_packs — ``<repo_data_root>/audit/evidence_packs.jsonl``
  (``evidence_pack``, CH-4 #9732: one summary record per compiled release
  evidence pack, pinning the pack's per-file sha256 digests)

Adoption baseline
-----------------
Chains start at adoption (2026-07-08, CH-1). Records written before adoption
carry no hash fields and are **not** retrofitted (same principle as the
no-retroactive-telemetry-migration rule): they form a contiguous unchained
prefix that verification tolerates. Once a chained record appears, every
subsequent record must be chained and linked.

Rotation safety
---------------
The current chain head is persisted in an atomic sidecar file
(``<stream>.chainhead.json``). If a stream file is rotated (renamed away),
the next append starts the new file with ``prev_hash`` equal to the carried
forward head, so the chain spans rotated files. Verification of a single file
accepts any first ``prev_hash`` (genesis or carry-forward) and validates every
link and record hash after it; the sidecar additionally pins the expected tail
so truncation of chained records is detected.

Named limitations
-----------------
* ``DedupStore`` is intentionally **not** chained: it persists a mutable set
  snapshot (full atomic rewrite of a sorted JSON list on every ``add``), not
  an append-only stream — there is no stable per-record identity to chain.
* ``decisions.jsonl`` has one sanctioned amendment path
  (``_update_decision`` marking ``outcome_verified``); it re-chains via
  :meth:`AuditChain.rewrite`, so helper-mediated amendments remain verifiable
  while out-of-band edits still break the chain.
* THREAT MODEL / DETECTION PRECONDITION: detection assumes the sidecar
  head file is not tampered in coordination with the stream. Single-file
  tampering (any edit, insertion, deletion, or partial truncation of the
  JSONL with the sidecar untouched) is detected. A writer who can modify
  BOTH the stream and its ``.chainhead.json`` sidecar consistently — they
  live in the same directory under the same OS permissions — can truncate
  the tail or, with full re-chaining, rewrite history undetected. Raising
  that bar needs an out-of-band trust anchor (OS permission separation for
  the sidecar, an HMAC key held elsewhere, or periodic head escrow) —
  follow-up hardening, not claimed here. Truncating a stream to zero
  chained records is additionally indistinguishable from a clean rotation.
"""

from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

from file_util import append_jsonl, atomic_write, file_lock
from secret_scrub import scrub_secrets

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

    from config import HydraFlowConfig

logger = logging.getLogger("hydraflow.audit_chain")

#: ``prev_hash`` sentinel for the first chained record of a stream.
GENESIS_PREV_HASH = "0" * 64

_HASH_FIELDS = ("prev_hash", "record_hash")


def canonical_json(payload: Mapping[str, Any]) -> str:
    """Serialize *payload* to canonical JSON: sorted keys, compact separators,
    raw UTF-8 (no ASCII escaping), NaN/Infinity rejected.

    The byte-stability of this form is load-bearing: record hashes are
    computed over it, so any change breaks verification of existing chains.
    """
    return json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )


def compute_record_hash(payload: Mapping[str, Any], prev_hash: str) -> str:
    """Return sha256 hex digest over canonical JSON of *payload* + *prev_hash*.

    *payload* must not contain the reserved hash fields.
    """
    body = dict(payload)
    body["prev_hash"] = prev_hash
    return hashlib.sha256(canonical_json(body).encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class ChainBreak:
    """A single verification failure at a 1-based record index."""

    record_no: int
    reason: str


@dataclass(frozen=True)
class ChainVerifyResult:
    """Outcome of walking one stream file's hash chain."""

    path: Path
    total_records: int
    chained_records: int
    breaks: tuple[ChainBreak, ...]
    head: str | None

    @property
    def ok(self) -> bool:
        return not self.breaks


@dataclass(frozen=True)
class AuditStreamSpec:
    """One chained audit stream: where it lives and how it is retained."""

    name: str
    path: Path
    timestamp_key: str
    retention_days: int | None


def audit_streams(config: HydraFlowConfig) -> tuple[AuditStreamSpec, ...]:
    """Registry of every chained audit stream, resolved from *config*.

    ``retention_days=None`` (the default) means keep forever; a set value is
    the retention floor RunsGCLoop enforces — records younger than the floor
    can never be pruned.
    """
    return (
        AuditStreamSpec(
            name="preflight",
            path=config.data_root / "auto_agent" / "audit.jsonl",
            timestamp_key="ts",
            retention_days=config.audit_retention_days_preflight,
        ),
        AuditStreamSpec(
            name="health_decisions",
            path=config.memory_dir / "decisions.jsonl",
            timestamp_key="timestamp",
            retention_days=config.audit_retention_days_health_decisions,
        ),
        AuditStreamSpec(
            name="inference_telemetry",
            path=config.cost_inferences_path,
            timestamp_key="timestamp",
            retention_days=config.audit_retention_days_inference_telemetry,
        ),
        AuditStreamSpec(
            name="approval_records",
            path=config.approval_records_path,
            timestamp_key="timestamp",
            retention_days=config.audit_retention_days_approval_records,
        ),
        AuditStreamSpec(
            name="evidence_packs",
            path=config.evidence_packs_path,
            timestamp_key="timestamp",
            retention_days=config.audit_retention_days_evidence_packs,
        ),
    )


def _scrub_payload(payload: Mapping[str, Any]) -> dict[str, Any]:
    """Redact credential-shaped strings from *payload* BEFORE hashing.

    ``append_jsonl`` scrubs every line it writes (ADR-0085); hashing the
    pre-scrub content would make the stored record fail verification the
    moment a secret is redacted. Scrubbing is idempotent, so the second pass
    inside ``append_jsonl`` is a no-op.
    """
    canonical = canonical_json(payload)
    scrubbed = scrub_secrets(canonical)
    if scrubbed == canonical:
        return dict(payload)
    parsed: dict[str, Any] = json.loads(scrubbed)
    return parsed


def _is_chained(record: Mapping[str, Any]) -> bool:
    return any(field in record for field in _HASH_FIELDS)


def _parse_timestamp(value: object) -> datetime | None:
    """Parse an ISO-8601 timestamp; naive values are assumed UTC."""
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed


def _iter_records(path: Path) -> list[tuple[int, str, dict[str, Any] | None]]:
    """Return ``(record_no, raw_line, parsed-or-None)`` for each non-blank line."""
    out: list[tuple[int, str, dict[str, Any] | None]] = []
    record_no = 0
    with path.open("r", encoding="utf-8") as fh:
        for raw in fh:
            stripped = raw.strip()
            if not stripped:
                continue
            record_no += 1
            try:
                parsed = json.loads(stripped)
            except json.JSONDecodeError:
                parsed = None
            if not isinstance(parsed, dict):
                parsed = None
            out.append((record_no, stripped, parsed))
    return out


def verify_file(path: Path, expected_head: str | None = None) -> ChainVerifyResult:
    """Walk one stream file and validate its hash chain.

    A contiguous unchained prefix (pre-adoption records) is tolerated; from
    the first chained record onward every record must be chained, must link
    ``prev_hash`` to the previous ``record_hash``, and must hash to its own
    ``record_hash``. The first chained record's ``prev_hash`` is accepted
    as-is (genesis or rotation carry-forward). When *expected_head* is given
    and the file contains chained records, the final ``record_hash`` must
    match it (tail-truncation detection).
    """
    if not path.exists():
        return ChainVerifyResult(
            path=path, total_records=0, chained_records=0, breaks=(), head=None
        )

    breaks: list[ChainBreak] = []
    total = 0
    chained = 0
    head: str | None = None

    for record_no, _raw, record in _iter_records(path):
        total = record_no
        if record is None:
            breaks.append(ChainBreak(record_no, "invalid JSON line"))
            continue
        if not _is_chained(record):
            if chained or head is not None:
                breaks.append(
                    ChainBreak(record_no, "unchained record after chained records")
                )
            continue

        prev_hash = record.get("prev_hash")
        record_hash = record.get("record_hash")
        if not isinstance(prev_hash, str) or not isinstance(record_hash, str):
            breaks.append(ChainBreak(record_no, "missing or non-string hash fields"))
            continue
        if head is not None and prev_hash != head:
            breaks.append(
                ChainBreak(
                    record_no,
                    "prev_hash does not match preceding record_hash "
                    "(record deleted, inserted, or reordered)",
                )
            )
        payload = {k: v for k, v in record.items() if k not in _HASH_FIELDS}
        try:
            recomputed = compute_record_hash(payload, prev_hash)
        except ValueError:
            breaks.append(
                ChainBreak(
                    record_no, "record_hash mismatch (uncanonicalizable payload)"
                )
            )
            head = record_hash
            chained += 1
            continue
        if recomputed != record_hash:
            breaks.append(
                ChainBreak(record_no, "record_hash mismatch (record content altered)")
            )
        head = record_hash
        chained += 1

    if expected_head is not None and chained and head != expected_head:
        breaks.append(
            ChainBreak(
                total,
                "chain head mismatch against sidecar (tail truncated or "
                "appended out-of-band)",
            )
        )

    return ChainVerifyResult(
        path=path,
        total_records=total,
        chained_records=chained,
        breaks=tuple(breaks),
        head=head,
    )


class AuditChain:
    """Hash-chained appender/verifier for one JSONL audit stream.

    All mutations happen under a per-stream file lock; the chain head is
    persisted in an atomic sidecar (``<stream>.chainhead.json``) so appends
    are O(1) and heads survive file rotation.
    """

    def __init__(self, path: Path) -> None:
        self._path = path
        self._head_path = path.with_name(path.name + ".chainhead.json")
        self._lock_path = path.with_name(path.name + ".chain.lock")

    @property
    def path(self) -> Path:
        return self._path

    # -- head state ---------------------------------------------------------

    def _load_head(self) -> str:
        """Return the current chain head: sidecar, else last chained record,
        else genesis (adoption / empty stream)."""
        head = self._load_sidecar_head()
        if head is not None:
            return head
        if self._path.exists():
            # One-time self-heal (first post-adoption append, or a sidecar
            # lost to data migration): recover the head from the last record.
            entries = _iter_records(self._path)
            if entries:
                _no, _raw, record = entries[-1]
                if record is not None and _is_chained(record):
                    record_hash = record.get("record_hash")
                    if isinstance(record_hash, str):
                        return record_hash
        return GENESIS_PREV_HASH

    def _load_sidecar_head(self) -> str | None:
        if not self._head_path.exists():
            return None
        try:
            data = json.loads(self._head_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            logger.warning("Unreadable chain-head sidecar %s", self._head_path)
            return None
        head = data.get("head") if isinstance(data, dict) else None
        return head if isinstance(head, str) and head else None

    def _store_head(self, head: str) -> None:
        atomic_write(
            self._head_path,
            json.dumps(
                {"head": head, "updated_at": datetime.now(UTC).isoformat()},
                sort_keys=True,
            ),
        )

    # -- mutations ----------------------------------------------------------

    def append(self, record: Mapping[str, Any]) -> dict[str, Any]:
        """Append *record* to the stream with chain hashes; return the full row."""
        for field in _HASH_FIELDS:
            if field in record:
                raise ValueError(
                    f"payload must not contain reserved chain field {field!r}"
                )
        payload = _scrub_payload(record)
        with file_lock(self._lock_path):
            prev_hash = self._load_head()
            record_hash = compute_record_hash(payload, prev_hash)
            full = {**payload, "prev_hash": prev_hash, "record_hash": record_hash}
            append_jsonl(self._path, json.dumps(full, sort_keys=True))
            self._store_head(record_hash)
        return full

    def rewrite(self, records: Sequence[Mapping[str, Any]]) -> None:
        """Atomically rewrite the stream, re-chaining from the amendment point.

        This is the sanctioned amendment path (e.g. ``_update_decision``
        marking ``outcome_verified``). Unchained prefix records are written
        back verbatim; the first chained record keeps its original
        ``prev_hash`` baseline and every chained record is re-hashed forward.
        """
        with file_lock(self._lock_path):
            lines: list[str] = []
            prev_hash: str | None = None
            for record in records:
                if prev_hash is None and not _is_chained(record):
                    lines.append(json.dumps(_scrub_payload(record), sort_keys=True))
                    continue
                if prev_hash is None:
                    baseline = record.get("prev_hash")
                    prev_hash = (
                        baseline if isinstance(baseline, str) else GENESIS_PREV_HASH
                    )
                payload = _scrub_payload(
                    {k: v for k, v in record.items() if k not in _HASH_FIELDS}
                )
                record_hash = compute_record_hash(payload, prev_hash)
                lines.append(
                    json.dumps(
                        {
                            **payload,
                            "prev_hash": prev_hash,
                            "record_hash": record_hash,
                        },
                        sort_keys=True,
                    )
                )
                prev_hash = record_hash
            body = "".join(line + "\n" for line in lines)
            atomic_write(self._path, body)
            if prev_hash is not None:
                self._store_head(prev_hash)

    def prune_before(self, cutoff: datetime, timestamp_key: str) -> int:
        """Drop the oldest records strictly older than *cutoff* (prefix cut).

        Retention enforcement for RunsGCLoop. Only a contiguous prefix is ever
        removed, so the surviving chain stays intact (the first survivor's
        ``prev_hash`` becomes its trusted baseline, same as rotation). A record
        with a missing or unparseable timestamp stops the cut — GC never
        deletes what it cannot date. Returns the number of records removed.
        """
        if not self._path.exists():
            return 0
        with file_lock(self._lock_path):
            entries = _iter_records(self._path)
            cut = 0
            for _no, _raw, record in entries:
                if record is None:
                    break
                ts = _parse_timestamp(record.get(timestamp_key))
                if ts is None or ts >= cutoff:
                    break
                cut += 1
            if cut == 0:
                return 0
            body = "".join(raw + "\n" for _no, raw, _rec in entries[cut:])
            atomic_write(self._path, body)
        return cut

    # -- verification -------------------------------------------------------

    def verify(self) -> ChainVerifyResult:
        """Verify the current stream file, pinning the tail to the sidecar head."""
        with file_lock(self._lock_path):
            return verify_file(self._path, expected_head=self._load_sidecar_head())
