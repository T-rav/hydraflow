"""Append-only gateway request ledger and policy-gated raw body store."""

from __future__ import annotations

import json
import logging
import os
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, BinaryIO, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from file_util import append_jsonl, file_lock
from hydraflow_gateway.models import (
    BodyCapturePolicy,
    GatewayIdentity,
    GatewayRequestStatus,
    Principal,
    ProviderBinding,
    RepoClass,
)
from jsonl_ledger import AppendOnlyJsonlLedger

logger = logging.getLogger("hydraflow.gateway.ledger")
_CAPTURE_ID_PATTERN = re.compile(r"\A[A-Za-z0-9_-]{1,128}\Z")


class GatewayLedgerRow(BaseModel):
    """Metadata-only observation emitted exactly once per upstream attempt."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    request_id: str
    source: Literal["gateway"] = "gateway"
    key_id: str
    principal: Principal
    repo_slug: str
    repo_class: RepoClass
    body_capture_policy: BodyCapturePolicy
    timestamp: datetime
    latency_ms: float = Field(ge=0)
    status_code: int = Field(ge=0, le=599)
    status: GatewayRequestStatus
    upstream_provider: ProviderBinding
    model_requested: str | None = None
    model_served: str | None = None
    input_tokens: int = Field(default=0, ge=0)
    output_tokens: int = Field(default=0, ge=0)
    cache_read_input_tokens: int = Field(default=0, ge=0)
    cache_creation_input_tokens: int = Field(default=0, ge=0)
    completed: bool
    client_aborted: bool
    observer_malformed_events: int = Field(default=0, ge=0)
    body_capture_id: str | None = None
    body_capture_complete: bool | None = None
    cost_usd: float | None = Field(default=None, ge=0)
    cost_unknown: bool

    @model_validator(mode="after")
    def enforce_unknown_cost_semantics(self) -> GatewayLedgerRow:
        """An unknown price is never serialized as a misleading numeric zero."""
        if self.cost_unknown and self.cost_usd is not None:
            raise ValueError("cost_usd must be null when cost_unknown is true")
        if not self.cost_unknown and self.cost_usd is None:
            raise ValueError("cost_usd is required when cost_unknown is false")
        return self

    def to_json_dict(self) -> dict[str, Any]:
        """Return JSON-native data for ``AppendOnlyJsonlLedger``."""
        return self.model_dump(mode="json")

    @classmethod
    def from_json_dict(cls, raw: dict[str, Any]) -> Self:
        """Validate a durable JSON object as a gateway ledger row."""
        return cls.model_validate(raw)


class GatewayLedger(AppendOnlyJsonlLedger[GatewayLedgerRow]):
    """Crash-safe append-only metadata ledger for gateway requests."""

    def __init__(self, path: Path) -> None:
        super().__init__(path, GatewayLedgerRow, logger=logger)

    def append(self, record: GatewayLedgerRow) -> None:
        """Persist one scrubbed row with fsync before returning."""
        lock_path = Path(f"{self.path}.lock")
        with file_lock(lock_path):
            append_jsonl(
                self.path, json.dumps(record.to_json_dict(), separators=(",", ":"))
            )


@dataclass
class GatewayBodyCapture:
    """Two immutable raw-body files belonging to one gateway request."""

    capture_id: str
    request_path: Path
    response_path: Path
    _request_file: BinaryIO
    _response_file: BinaryIO
    _closed: bool = False

    def write_request(self, chunk: bytes) -> None:
        """Append an original request chunk without decoding it."""
        self._require_open()
        self._request_file.write(chunk)

    def write_response(self, chunk: bytes) -> None:
        """Append an original response chunk without decoding it."""
        self._require_open()
        self._response_file.write(chunk)

    def close(self) -> None:
        """Flush, fsync, and close both body artifacts exactly once."""
        if self._closed:
            return
        first_error: OSError | None = None
        for body_file in (self._request_file, self._response_file):
            try:
                body_file.flush()
                os.fsync(body_file.fileno())
            except OSError as exc:
                first_error = first_error or exc
            finally:
                try:
                    body_file.close()
                except OSError as exc:
                    first_error = first_error or exc
        self._closed = True
        if first_error is not None:
            raise first_error

    def _require_open(self) -> None:
        if self._closed:
            raise RuntimeError("body capture is already closed")


class GatewayBodyStore:
    """Policy gate and exclusive-create storage for optional raw bodies."""

    def __init__(self, directory: Path) -> None:
        self._directory = directory

    @property
    def directory(self) -> Path:
        return self._directory

    def start(
        self, request_id: str, identity: GatewayIdentity
    ) -> GatewayBodyCapture | None:
        """Open body artifacts only when immutable key policy permits capture."""
        if identity.body_capture_policy is BodyCapturePolicy.METADATA_ONLY:
            return None
        if identity.repo_class is not RepoClass.HYDRAFLOW:
            raise ValueError("body capture is prohibited for client and personal repos")
        if _CAPTURE_ID_PATTERN.fullmatch(request_id) is None:
            raise ValueError("request_id is not a safe body capture id")
        self._directory.mkdir(mode=0o700, parents=True, exist_ok=True)
        self._directory.chmod(0o700)
        request_path = self._directory / f"{request_id}.request.body"
        response_path = self._directory / f"{request_id}.response.body"
        request_file = _open_exclusive(request_path)
        try:
            response_file = _open_exclusive(response_path)
        except BaseException:
            request_file.close()
            request_path.unlink(missing_ok=True)
            raise
        return GatewayBodyCapture(
            capture_id=request_id,
            request_path=request_path,
            response_path=response_path,
            _request_file=request_file,
            _response_file=response_file,
        )

    def reap_older_than(self, cutoff_epoch: float) -> int:
        """Delete expired body artifacts and return the number of files reaped."""
        if not self._directory.is_dir():
            return 0
        reaped = 0
        for path in self._directory.glob("*.body"):
            try:
                if path.is_file() and path.stat().st_mtime < cutoff_epoch:
                    path.unlink()
                    reaped += 1
            except FileNotFoundError:
                continue
        return reaped


def _open_exclusive(path: Path) -> BinaryIO:
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    return os.fdopen(descriptor, "wb")
