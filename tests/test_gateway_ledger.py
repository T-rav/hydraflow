"""Tests for append-only gateway metadata and raw body isolation."""

from __future__ import annotations

import os
import stat
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from hydraflow_gateway.ledger import GatewayBodyStore, GatewayLedger, GatewayLedgerRow
from hydraflow_gateway.models import (
    BodyCapturePolicy,
    GatewayIdentity,
    Principal,
    PrincipalKind,
    ProviderBinding,
    RepoClass,
)


def _identity(
    *,
    repo_class: RepoClass = RepoClass.HYDRAFLOW,
    policy: BodyCapturePolicy = BodyCapturePolicy.FULL,
) -> GatewayIdentity:
    now = datetime(2026, 8, 19, tzinfo=UTC)
    return GatewayIdentity(
        key_id="key-1",
        principal=Principal(
            kind=PrincipalKind.SPAWN,
            id="implementer",
            spawn_id="spawn-1",
        ),
        repo_slug="acme/repo",
        repo_class=repo_class,
        provider_binding=ProviderBinding.ANTHROPIC,
        body_capture_policy=policy,
        issued_at=now,
        expires_at=now + timedelta(minutes=5),
    )


def _row(request_id: str) -> GatewayLedgerRow:
    identity = _identity()
    return GatewayLedgerRow(
        request_id=request_id,
        key_id=identity.key_id,
        principal=identity.principal,
        repo_slug=identity.repo_slug,
        repo_class=identity.repo_class,
        body_capture_policy=identity.body_capture_policy,
        timestamp=identity.issued_at,
        latency_ms=12.5,
        status_code=200,
        status="completed",
        upstream_provider=identity.provider_binding,
        model_requested="claude-requested",
        model_served="claude-served",
        input_tokens=2,
        output_tokens=3,
        completed=True,
        client_aborted=False,
        body_capture_id=request_id,
        body_capture_complete=True,
        cost_usd=0.001,
        cost_unknown=False,
    )


class TestGatewayLedger:
    def test_append_roundtrips_in_order(self, tmp_path: Path) -> None:
        ledger = GatewayLedger(tmp_path / "nested" / "gateway.jsonl")
        ledger.append(_row("request-1"))
        ledger.append(_row("request-2"))

        assert [row.request_id for row in ledger.read_all()] == [
            "request-1",
            "request-2",
        ]

    def test_append_scrubs_secret_shaped_model_metadata(self, tmp_path: Path) -> None:
        path = tmp_path / "gateway.jsonl"
        row = _row("request-1").model_copy(
            update={"model_requested": "sk-ant-api03-secret-material"}
        )

        GatewayLedger(path).append(row)

        assert "sk-ant-api03-secret-material" not in path.read_text(encoding="utf-8")

    def test_cost_unknown_requires_null_cost(self) -> None:
        payload = _row("request-1").model_dump()
        payload["cost_unknown"] = True
        with pytest.raises(ValueError, match="must be null"):
            GatewayLedgerRow.model_validate(payload)

    def test_concurrent_append_keeps_every_row_valid_and_complete(
        self, tmp_path: Path
    ) -> None:
        path = tmp_path / "gateway.jsonl"

        def append(index: int) -> None:
            GatewayLedger(path).append(_row(f"request-{index}"))

        with ThreadPoolExecutor(max_workers=8) as pool:
            list(pool.map(append, range(64)))

        rows = GatewayLedger(path).read_all()
        assert len(rows) == 64
        assert {row.request_id for row in rows} == {
            f"request-{index}" for index in range(64)
        }


class TestGatewayBodyStore:
    def test_metadata_only_policy_creates_no_directory(self, tmp_path: Path) -> None:
        body_dir = tmp_path / "bodies"
        capture = GatewayBodyStore(body_dir).start(
            "request-1",
            _identity(policy=BodyCapturePolicy.METADATA_ONLY),
        )

        assert capture is None
        assert not body_dir.exists()

    def test_full_policy_writes_original_binary_bytes_with_private_permissions(
        self, tmp_path: Path
    ) -> None:
        body_dir = tmp_path / "bodies"
        capture = GatewayBodyStore(body_dir).start("request-1", _identity())
        assert capture is not None

        capture.write_request(b"request\x00bytes")
        capture.write_response(b"response\xffbytes")
        capture.close()

        assert capture.request_path.read_bytes() == b"request\x00bytes"
        assert capture.response_path.read_bytes() == b"response\xffbytes"
        assert stat.S_IMODE(capture.request_path.stat().st_mode) == 0o600
        assert stat.S_IMODE(capture.response_path.stat().st_mode) == 0o600

    def test_close_attempts_both_files_when_first_fsync_fails(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        capture = GatewayBodyStore(tmp_path / "bodies").start("request-1", _identity())
        assert capture is not None
        request_file = capture._request_file
        response_file = capture._response_file
        real_fsync = os.fsync
        calls = 0

        def fail_first_fsync(descriptor: int) -> None:
            nonlocal calls
            calls += 1
            if calls == 1:
                raise OSError("disk full")
            real_fsync(descriptor)

        monkeypatch.setattr(os, "fsync", fail_first_fsync)

        with pytest.raises(OSError, match="disk full"):
            capture.close()

        assert request_file.closed is True
        assert response_file.closed is True
        capture.close()

    def test_capture_files_are_exclusive_and_never_overwritten(
        self, tmp_path: Path
    ) -> None:
        store = GatewayBodyStore(tmp_path / "bodies")
        first = store.start("request-1", _identity())
        assert first is not None
        first.close()

        with pytest.raises(FileExistsError):
            store.start("request-1", _identity())
        assert first.request_path.read_bytes() == b""

    def test_body_retention_reaps_only_artifacts_older_than_cutoff(
        self, tmp_path: Path
    ) -> None:
        store = GatewayBodyStore(tmp_path / "bodies")
        old = store.start("request-old", _identity())
        current = store.start("request-current", _identity())
        assert old is not None
        assert current is not None
        old.close()
        current.close()
        for path in (old.request_path, old.response_path):
            os.utime(path, (100.0, 100.0))
        for path in (current.request_path, current.response_path):
            os.utime(path, (200.0, 200.0))

        assert store.reap_older_than(150.0) == 2
        assert old.request_path.exists() is False
        assert old.response_path.exists() is False
        assert current.request_path.exists() is True
        assert current.response_path.exists() is True

    def test_store_defends_repo_policy_even_for_constructed_identity(
        self, tmp_path: Path
    ) -> None:
        invalid = _identity().model_copy(
            update={
                "repo_class": RepoClass.CLIENT,
                "body_capture_policy": BodyCapturePolicy.FULL,
            }
        )

        with pytest.raises(ValueError, match="body capture is prohibited"):
            GatewayBodyStore(tmp_path / "bodies").start("request-1", invalid)

    def test_store_rejects_path_traversal_capture_id(self, tmp_path: Path) -> None:
        with pytest.raises(ValueError, match="safe body capture id"):
            GatewayBodyStore(tmp_path / "bodies").start("../escape", _identity())
        assert not (tmp_path / "escape.request.body").exists()
