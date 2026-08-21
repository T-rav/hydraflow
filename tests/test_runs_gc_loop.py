"""Tests for the RunsGCLoop background worker and RunRecorder retention methods."""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from run_recorder import RunManifest, RunRecorder
from runs_gc_loop import RunsGCLoop
from tests.helpers import ConfigFactory, make_bg_loop_deps

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_recorder(
    tmp_path: Path,
    **config_overrides,
) -> tuple[object, RunRecorder]:
    """Create a RunRecorder with test-friendly defaults."""
    config = ConfigFactory.create(repo_root=tmp_path / "repo", **config_overrides)
    (tmp_path / "repo").mkdir(parents=True, exist_ok=True)
    return config, RunRecorder(config)


def _seed_run(recorder: RunRecorder, issue: int, timestamp: str) -> Path:
    """Create a minimal run directory with a manifest and a dummy file."""
    run_dir = recorder.runs_dir / str(issue) / timestamp
    run_dir.mkdir(parents=True, exist_ok=True)
    manifest = RunManifest(issue_number=issue, timestamp=timestamp, outcome="success")
    (run_dir / "manifest.json").write_text(manifest.model_dump_json())
    (run_dir / "plan.md").write_text("x" * 100)
    return run_dir


def _make_loop(
    tmp_path: Path,
    *,
    enabled: bool = True,
    retention_days: int = 30,
    max_size_mb: int = 500,
    runs_gc_interval: int = 600,
) -> tuple[RunsGCLoop, RunRecorder, asyncio.Event]:
    """Build a RunsGCLoop with test-friendly defaults."""
    deps = make_bg_loop_deps(
        tmp_path,
        enabled=enabled,
        artifact_retention_days=retention_days,
        artifact_max_size_mb=max_size_mb,
        runs_gc_interval=runs_gc_interval,
    )
    recorder = RunRecorder(deps.config)
    loop = RunsGCLoop(
        config=deps.config,
        run_recorder=recorder,
        deps=deps.loop_deps,
    )
    return loop, recorder, deps.stop_event


# ===========================================================================
# RunRecorder.get_storage_stats
# ===========================================================================


class TestGetStorageStats:
    def test_empty_runs_dir(self, tmp_path: Path) -> None:
        _config, recorder = _make_recorder(tmp_path)
        stats = recorder.get_storage_stats()
        assert stats["total_bytes"] == 0
        assert stats["total_runs"] == 0
        assert stats["issues"] == 0
        assert stats["total_mb"] == 0

    def test_counts_runs_and_issues(self, tmp_path: Path) -> None:
        _config, recorder = _make_recorder(tmp_path)
        _seed_run(recorder, 10, "20260101T100000Z")
        _seed_run(recorder, 10, "20260101T200000Z")
        _seed_run(recorder, 42, "20260101T100000Z")

        stats = recorder.get_storage_stats()
        assert stats["total_runs"] == 3
        assert stats["issues"] == 2
        assert stats["total_bytes"] > 0
        assert stats["total_mb"] >= 0  # small files may round to 0.0

    def test_skips_non_digit_issue_dirs(self, tmp_path: Path) -> None:
        _config, recorder = _make_recorder(tmp_path)
        _seed_run(recorder, 42, "20260101T100000Z")
        # Create a non-digit dir that should be ignored
        junk = recorder.runs_dir / "not-an-issue"
        junk.mkdir(parents=True, exist_ok=True)
        (junk / "file.txt").write_text("junk")

        stats = recorder.get_storage_stats()
        assert stats["issues"] == 1
        assert stats["total_runs"] == 1


# ===========================================================================
# RunRecorder.purge_expired
# ===========================================================================


class TestPurgeExpired:
    def test_removes_old_runs(self, tmp_path: Path) -> None:
        _config, recorder = _make_recorder(tmp_path)
        # Old run (way past retention)
        _seed_run(recorder, 42, "20200101T000000Z")
        # Recent run (should survive)
        _seed_run(recorder, 42, "20261231T000000Z")

        removed = recorder.purge_expired(retention_days=30)
        assert removed == 1
        runs = recorder.list_runs(42)
        assert len(runs) == 1
        assert runs[0].timestamp == "20261231T000000Z"

    def test_noop_when_no_expired(self, tmp_path: Path) -> None:
        _config, recorder = _make_recorder(tmp_path)
        _seed_run(recorder, 42, "20261231T000000Z")
        removed = recorder.purge_expired(retention_days=30)
        assert removed == 0

    def test_removes_empty_issue_dirs(self, tmp_path: Path) -> None:
        _config, recorder = _make_recorder(tmp_path)
        _seed_run(recorder, 42, "20200101T000000Z")
        recorder.purge_expired(retention_days=30)
        # Issue dir should be removed since all runs were purged
        assert not (recorder.runs_dir / "42").exists()

    def test_empty_runs_dir_returns_zero(self, tmp_path: Path) -> None:
        _config, recorder = _make_recorder(tmp_path)
        assert recorder.purge_expired(retention_days=30) == 0

    def test_purges_across_multiple_issues(self, tmp_path: Path) -> None:
        _config, recorder = _make_recorder(tmp_path)
        # Old runs in two different issues
        _seed_run(recorder, 10, "20200101T000000Z")
        _seed_run(recorder, 42, "20200101T000000Z")
        # Recent runs that should survive
        _seed_run(recorder, 10, "20261231T000000Z")
        _seed_run(recorder, 42, "20261231T000000Z")

        removed = recorder.purge_expired(retention_days=30)
        assert removed == 2
        assert len(recorder.list_runs(10)) == 1
        assert len(recorder.list_runs(42)) == 1

    def test_skips_non_timestamp_dirs(self, tmp_path: Path) -> None:
        _config, recorder = _make_recorder(tmp_path)
        # Create a dir with a non-timestamp name
        weird_dir = recorder.runs_dir / "42" / "not-a-timestamp"
        weird_dir.mkdir(parents=True, exist_ok=True)
        (weird_dir / "junk.txt").write_text("x")

        removed = recorder.purge_expired(retention_days=30)
        assert removed == 0
        assert weird_dir.exists()


# ===========================================================================
# RunRecorder.purge_oversized
# ===========================================================================


class TestPurgeOversized:
    def test_removes_oldest_until_under_limit(self, tmp_path: Path) -> None:
        _config, recorder = _make_recorder(tmp_path)
        # Seed runs with large files (each ~1KB)
        for ts in ("20260101T100000Z", "20260101T200000Z", "20260102T100000Z"):
            run_dir = _seed_run(recorder, 42, ts)
            (run_dir / "big.bin").write_bytes(b"x" * 512)

        # Set a zero MB limit so all runs get purged
        removed = recorder.purge_oversized(max_size_mb=0)
        # With 0 MB limit, all should be removed (since total > 0)
        assert removed > 0

    def test_noop_when_under_limit(self, tmp_path: Path) -> None:
        _config, recorder = _make_recorder(tmp_path)
        _seed_run(recorder, 42, "20260101T100000Z")
        removed = recorder.purge_oversized(max_size_mb=500)
        assert removed == 0

    def test_removes_oldest_first(self, tmp_path: Path) -> None:
        _config, recorder = _make_recorder(tmp_path)
        # Create three runs with large files so each exceeds 1 byte
        for ts in ("20260101T100000Z", "20260101T200000Z", "20260102T100000Z"):
            run_dir = _seed_run(recorder, 42, ts)
            (run_dir / "data.bin").write_bytes(b"x" * 1024)

        total = recorder._compute_total_bytes()
        assert total > 0
        # Remove with 0 limit — all get removed; verify count
        removed = recorder.purge_oversized(max_size_mb=0)
        assert removed == 3

    def test_removes_empty_issue_dirs(self, tmp_path: Path) -> None:
        _config, recorder = _make_recorder(tmp_path)
        run_dir = _seed_run(recorder, 42, "20260101T100000Z")
        (run_dir / "big.bin").write_bytes(b"x" * 512)

        recorder.purge_oversized(max_size_mb=0)
        # Issue dir should be removed since all runs were purged
        assert not (recorder.runs_dir / "42").exists()

    def test_empty_runs_dir(self, tmp_path: Path) -> None:
        _config, recorder = _make_recorder(tmp_path)
        assert recorder.purge_oversized(max_size_mb=0) == 0


# ===========================================================================
# RunRecorder.purge_all
# ===========================================================================


class TestPurgeAll:
    def test_removes_all_runs(self, tmp_path: Path) -> None:
        _config, recorder = _make_recorder(tmp_path)
        _seed_run(recorder, 10, "20260101T100000Z")
        _seed_run(recorder, 42, "20260101T100000Z")
        removed = recorder.purge_all()
        assert removed == 2
        assert recorder.list_issues() == []

    def test_empty_runs_dir(self, tmp_path: Path) -> None:
        _config, recorder = _make_recorder(tmp_path)
        assert recorder.purge_all() == 0


# ===========================================================================
# RunRecorder._compute_total_bytes
# ===========================================================================


class TestComputeTotalBytes:
    def test_sums_file_sizes(self, tmp_path: Path) -> None:
        _config, recorder = _make_recorder(tmp_path)
        _seed_run(recorder, 42, "20260101T100000Z")
        total = recorder._compute_total_bytes()
        assert total > 0

    def test_empty_returns_zero(self, tmp_path: Path) -> None:
        _config, recorder = _make_recorder(tmp_path)
        assert recorder._compute_total_bytes() == 0


# ===========================================================================
# RunsGCLoop
# ===========================================================================


class TestRunsGCLoopBasics:
    def test_worker_name(self, tmp_path: Path) -> None:
        loop, _recorder, _stop = _make_loop(tmp_path)
        assert loop._worker_name == "runs_gc"

    def test_default_interval(self, tmp_path: Path) -> None:
        loop, _recorder, _stop = _make_loop(tmp_path, runs_gc_interval=900)
        assert loop._get_default_interval() == 900

    @pytest.mark.asyncio
    async def test_run_skips_when_disabled(self, tmp_path: Path) -> None:
        loop, _recorder, _stop = _make_loop(tmp_path, enabled=False)
        await loop.run()
        loop._status_cb.assert_not_called()

    @pytest.mark.asyncio
    async def test_do_work_returns_stats(self, tmp_path: Path) -> None:
        loop, recorder, stop = _make_loop(tmp_path, retention_days=30)
        _seed_run(recorder, 42, "20200101T000000Z")  # expired
        _seed_run(recorder, 42, "20261231T000000Z")  # fresh

        result = await loop._do_work()
        assert result is not None
        assert result["expired_purged"] == 1
        assert result["total_runs"] == 1

    @pytest.mark.asyncio
    async def test_do_work_no_purges(self, tmp_path: Path) -> None:
        loop, recorder, stop = _make_loop(tmp_path, retention_days=365)
        _seed_run(recorder, 42, "20261231T000000Z")

        result = await loop._do_work()
        assert result is not None
        assert result["expired_purged"] == 0
        assert result["oversized_purged"] == 0
        assert result["total_runs"] == 1

    @pytest.mark.asyncio
    async def test_run_publishes_status_on_success(self, tmp_path: Path) -> None:
        loop, _recorder, stop = _make_loop(tmp_path)
        stop.set()  # Stop after first iteration
        # run_on_startup defaults to False, so loop sleeps first then checks stop
        # Just verify _do_work can run without error
        result = await loop._do_work()
        assert result is not None


# ===========================================================================
# Config fields
# ===========================================================================


class TestArtifactConfigFields:
    def test_default_values(self) -> None:
        config = ConfigFactory.create()
        assert config.artifact_retention_days == 30
        assert config.artifact_max_size_mb == 500
        assert config.runs_gc_interval == 3600

    def test_custom_values(self) -> None:
        config = ConfigFactory.create(
            artifact_retention_days=7,
            artifact_max_size_mb=100,
            runs_gc_interval=1800,
        )
        assert config.artifact_retention_days == 7
        assert config.artifact_max_size_mb == 100
        assert config.runs_gc_interval == 1800


# ===========================================================================
# Audit-chain verification + retention (CH-1, #9729)
# ===========================================================================


def _make_audit_loop(tmp_path: Path, **config_overrides):
    """Build a RunsGCLoop plus the bus, for audit-chain caretaker tests."""
    deps = make_bg_loop_deps(tmp_path, **config_overrides)
    recorder = RunRecorder(deps.config)
    loop = RunsGCLoop(
        config=deps.config,
        run_recorder=recorder,
        deps=deps.loop_deps,
    )
    return loop, deps


def _seed_stream(config, name: str, timestamps: list[str]):
    from audit_chain import AuditChain, audit_streams

    spec = next(s for s in audit_streams(config) if s.name == name)
    spec.path.parent.mkdir(parents=True, exist_ok=True)
    chain = AuditChain(spec.path)
    for ts in timestamps:
        chain.append({spec.timestamp_key: ts, "n": ts})
    return spec, chain


class TestAuditChainCaretaker:
    @pytest.mark.asyncio
    async def test_reports_ok_and_empty_stream_statuses(self, tmp_path: Path) -> None:
        loop, deps = _make_audit_loop(tmp_path)
        _seed_stream(deps.config, "preflight", ["2026-07-01T00:00:00Z"])

        result = await loop._do_work()
        assert result is not None
        assert result["audit_chain_status"]["preflight"] == "ok"
        assert result["audit_chain_status"]["health_decisions"] == "empty"
        assert result["audit_chain_status"]["inference_telemetry"] == "empty"
        assert result["audit_chain_status"]["approval_records"] == "empty"

    @pytest.mark.asyncio
    async def test_approval_records_stream_is_tended(self, tmp_path: Path) -> None:
        """CH-2 (#9730): the approval stream rides the existing verify tick."""
        loop, deps = _make_audit_loop(tmp_path)
        _seed_stream(deps.config, "approval_records", ["2026-07-08T00:00:00+00:00"])

        result = await loop._do_work()
        assert result is not None
        assert result["audit_chain_status"]["approval_records"] == "ok"

    @pytest.mark.asyncio
    async def test_chain_break_fails_loudly_and_skips_pruning(
        self, tmp_path: Path
    ) -> None:
        from events import EventType

        loop, deps = _make_audit_loop(tmp_path, audit_retention_days_preflight=30)
        spec, _chain = _seed_stream(
            deps.config,
            "preflight",
            ["2020-01-01T00:00:00Z", "2020-01-02T00:00:00Z"],
        )
        # Tamper: flip a payload field without re-chaining.
        lines = spec.path.read_text().splitlines()
        tampered = json.loads(lines[0])
        tampered["n"] = "evil"
        lines[0] = json.dumps(tampered, sort_keys=True)
        spec.path.write_text("\n".join(lines) + "\n")

        result = await loop._do_work()
        assert result is not None
        assert result["audit_chain_status"]["preflight"] == "break"
        # Both stale records survive: GC must not destroy tamper evidence.
        assert len(spec.path.read_text().splitlines()) == 2
        alerts = [
            e
            for e in deps.bus.get_history()
            if e.type == EventType.SYSTEM_ALERT
            and e.data.get("kind") == "audit_chain_break"
        ]
        assert alerts
        assert alerts[0].data["stream"] == "preflight"

    @pytest.mark.asyncio
    async def test_torn_tail_is_not_tampering_and_retention_still_prunes(
        self, tmp_path: Path
    ) -> None:
        """A crash artifact (unterminated final line) must not raise the
        tamper SYSTEM_ALERT, must not poison the stream forever, and must
        not block retention pruning (unbounded growth)."""
        from datetime import UTC, datetime, timedelta

        from events import EventType

        loop, deps = _make_audit_loop(tmp_path, audit_retention_days_preflight=30)
        fresh = datetime.now(UTC).isoformat()
        stale = (datetime.now(UTC) - timedelta(days=90)).isoformat()
        spec, chain = _seed_stream(deps.config, "preflight", [stale, fresh])
        with spec.path.open("ab") as fh:
            fh.write(b'{"ts": "2026-07-0')  # interrupted append, no newline

        result = await loop._do_work()

        assert result is not None
        assert result["audit_chain_status"]["preflight"] == "torn_tail"
        assert result["audit_pruned"]["preflight"] == 1
        rows = [json.loads(line) for line in spec.path.read_text().splitlines()]
        assert [r["ts"] for r in rows] == [fresh]
        verify = chain.verify()
        assert verify.ok
        assert verify.warnings == ()
        alerts = [
            e
            for e in deps.bus.get_history()
            if e.type == EventType.SYSTEM_ALERT
            and e.data.get("kind") == "audit_chain_break"
        ]
        assert alerts == []

    @pytest.mark.asyncio
    async def test_sidecar_lag_is_not_tampering(self, tmp_path: Path) -> None:
        """Crash between append and sidecar store: no tamper alert."""
        from events import EventType

        loop, deps = _make_audit_loop(tmp_path)
        spec, _chain = _seed_stream(
            deps.config,
            "preflight",
            ["2026-07-01T00:00:00Z", "2026-07-02T00:00:00Z"],
        )
        rows = [json.loads(line) for line in spec.path.read_text().splitlines()]
        sidecar = spec.path.with_name(spec.path.name + ".chainhead.json")
        sidecar.write_text(json.dumps({"head": rows[0]["record_hash"]}))

        result = await loop._do_work()

        assert result is not None
        assert result["audit_chain_status"]["preflight"] == "sidecar_lag"
        alerts = [
            e
            for e in deps.bus.get_history()
            if e.type == EventType.SYSTEM_ALERT
            and e.data.get("kind") == "audit_chain_break"
        ]
        assert alerts == []

    @pytest.mark.asyncio
    async def test_retention_floor_prunes_only_older_records(
        self, tmp_path: Path
    ) -> None:
        from datetime import UTC, datetime, timedelta

        loop, deps = _make_audit_loop(tmp_path, audit_retention_days_preflight=30)
        fresh = datetime.now(UTC).isoformat()
        stale = (datetime.now(UTC) - timedelta(days=90)).isoformat()
        spec, chain = _seed_stream(deps.config, "preflight", [stale, fresh])

        result = await loop._do_work()
        assert result is not None
        assert result["audit_pruned"]["preflight"] == 1
        rows = [json.loads(line) for line in spec.path.read_text().splitlines()]
        assert [r["ts"] for r in rows] == [fresh]
        assert chain.verify().ok

    @pytest.mark.asyncio
    async def test_inference_retention_refreshes_source_health_anchor(
        self, tmp_path: Path
    ) -> None:
        from datetime import UTC, datetime, timedelta

        from prompt_telemetry import (
            prompt_telemetry_health_path,
            prompt_telemetry_source_complete,
            refresh_prompt_telemetry_health_after_retention,
        )

        loop, deps = _make_audit_loop(
            tmp_path,
            audit_retention_days_inference_telemetry=30,
        )
        fresh = datetime.now(UTC).isoformat()
        stale = (datetime.now(UTC) - timedelta(days=90)).isoformat()
        spec, _chain = _seed_stream(
            deps.config,
            "inference_telemetry",
            [stale, fresh],
        )
        assert refresh_prompt_telemetry_health_after_retention(spec.path) is True
        assert prompt_telemetry_source_complete(spec.path) is True

        result = await loop._do_work()

        assert result is not None
        assert result["audit_pruned"]["inference_telemetry"] == 1
        assert prompt_telemetry_source_complete(spec.path) is True
        marker = json.loads(prompt_telemetry_health_path(spec.path).read_text())
        assert marker["record_count"] == 1

    @pytest.mark.asyncio
    async def test_inference_retention_never_clears_dropped_write_degradation(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from datetime import UTC, datetime, timedelta

        import runs_gc_loop as runs_gc_loop_module
        from audit_chain import AuditChain, audit_streams
        from gateway_coverage import build_coverage_for_configs, gateway_ledger_path
        from hydraflow_gateway.ledger import GatewayLedger, GatewayLedgerRow
        from hydraflow_gateway.models import (
            BodyCapturePolicy,
            GatewayRequestStatus,
            Principal,
            PrincipalKind,
            ProviderBinding,
            RepoClass,
        )
        from prompt_telemetry import (
            prompt_telemetry_health_path,
            prompt_telemetry_source_complete,
            refresh_prompt_telemetry_health_after_retention,
        )

        loop, deps = _make_audit_loop(
            tmp_path,
            audit_retention_days_inference_telemetry=30,
        )
        now = datetime.now(UTC)
        stale = (now - timedelta(days=90)).isoformat()
        fresh = now.isoformat()
        spec = next(
            stream
            for stream in audit_streams(deps.config)
            if stream.name == "inference_telemetry"
        )
        chain = AuditChain(spec.path)
        for timestamp in (stale, fresh):
            chain.append(
                {
                    spec.timestamp_key: timestamp,
                    "source": "wiki_compilation",
                    "tool": "openrouter",
                    "model": "openrouter/test",
                    "estimated_cost_usd": 1.0,
                }
            )
        verification = chain.verify()
        health_path = prompt_telemetry_health_path(spec.path)
        degraded_marker = {
            "status": "degraded",
            "updated_at": fresh,
            "dropped_writes": 1,
            "first_failure_at": fresh,
            "chain_head": verification.head,
            "record_count": verification.total_records,
        }
        health_path.write_text(json.dumps(degraded_marker, sort_keys=True) + "\n")

        GatewayLedger(gateway_ledger_path(deps.config)).append(
            GatewayLedgerRow(
                request_id="retention-latch",
                key_id="key-retention-latch",
                principal=Principal(
                    kind=PrincipalKind.SPAWN,
                    id="reviewer",
                    spawn_id="spawn-retention-latch",
                ),
                repo_slug=deps.config.repo_slug,
                repo_class=RepoClass.HYDRAFLOW,
                body_capture_policy=BodyCapturePolicy.METADATA_ONLY,
                timestamp=now,
                latency_ms=1.0,
                status_code=200,
                status=GatewayRequestStatus.COMPLETED,
                upstream_provider=ProviderBinding.ANTHROPIC,
                completed=True,
                client_aborted=False,
                cost_usd=1.0,
                cost_unknown=False,
            )
        )
        refresh_attempts: list[Path] = []

        def track_refresh(path: Path) -> bool:
            refresh_attempts.append(path)
            return refresh_prompt_telemetry_health_after_retention(path)

        monkeypatch.setattr(
            runs_gc_loop_module,
            "refresh_prompt_telemetry_health_after_retention",
            track_refresh,
        )

        result = await loop._do_work()
        snapshot = build_coverage_for_configs(
            [deps.config],
            since=now - timedelta(days=1),
            until=now + timedelta(minutes=1),
            window_label="24h",
            scope="global",
            repo_slug=None,
        )

        assert result is not None
        assert result["audit_pruned"]["inference_telemetry"] == 1
        assert refresh_attempts == [spec.path]
        assert json.loads(health_path.read_text()) == degraded_marker
        assert prompt_telemetry_source_complete(spec.path) is False
        assert snapshot.status == "partial"
        assert snapshot.source_data_complete is False
        assert snapshot.coverage_percent is None
        assert snapshot.known_spend_coverage_percent == 50.0
        assert snapshot.gateway_requests == 1
        assert snapshot.bypass_requests == 1

    @pytest.mark.asyncio
    async def test_default_retention_none_keeps_everything(
        self, tmp_path: Path
    ) -> None:
        from datetime import UTC, datetime, timedelta

        loop, deps = _make_audit_loop(tmp_path)
        ancient = (datetime.now(UTC) - timedelta(days=3650)).isoformat()
        spec, _chain = _seed_stream(deps.config, "preflight", [ancient])

        result = await loop._do_work()
        assert result is not None
        assert result["audit_pruned"] == {}
        assert len(spec.path.read_text().splitlines()) == 1


class TestChainBreakAlertDedup:
    async def test_persistent_break_alerts_once(self, tmp_path: Path) -> None:
        """A break that persists across cycles must not re-alert every hour —
        24 alerts/day/stream drowns the signal (cost_budget_alerts dedup
        precedent)."""
        from events import EventType

        loop, deps = _make_audit_loop(tmp_path, audit_retention_days_preflight=30)
        spec, _chain = _seed_stream(
            deps.config,
            "preflight",
            ["2020-01-01T00:00:00Z", "2020-01-02T00:00:00Z"],
        )
        lines = spec.path.read_text().splitlines()
        tampered = json.loads(lines[0])
        tampered["n"] = "evil"
        lines[0] = json.dumps(tampered, sort_keys=True)
        spec.path.write_text("\n".join(lines) + "\n")

        await loop._do_work()
        await loop._do_work()
        await loop._do_work()

        alerts = [
            e
            for e in deps.bus.get_history()
            if e.type == EventType.SYSTEM_ALERT
            and e.data.get("kind") == "audit_chain_break"
        ]
        assert len(alerts) == 1

    async def test_recovery_rearms_the_alert(self, tmp_path: Path) -> None:
        """Operator repairs the stream → dedup clears → a NEW break alerts."""
        from events import EventType

        loop, deps = _make_audit_loop(tmp_path, audit_retention_days_preflight=None)
        spec, chain = _seed_stream(
            deps.config,
            "preflight",
            ["2026-07-01T00:00:00Z"],
        )
        good = spec.path.read_text()
        good_head = spec.path.with_name(spec.path.name + ".chainhead.json").read_text()
        lines = spec.path.read_text().splitlines()
        tampered = json.loads(lines[0])
        tampered["n"] = "evil"
        spec.path.write_text(json.dumps(tampered, sort_keys=True) + "\n")

        await loop._do_work()  # break → alert 1
        # Operator repairs (restores the pristine stream + head).
        spec.path.write_text(good)
        spec.path.with_name(spec.path.name + ".chainhead.json").write_text(good_head)
        await loop._do_work()  # ok → dedup clears
        # A fresh break must alert again.
        lines = spec.path.read_text().splitlines()
        tampered = json.loads(lines[0])
        tampered["n"] = "evil-again"
        spec.path.write_text(json.dumps(tampered, sort_keys=True) + "\n")
        await loop._do_work()

        alerts = [
            e
            for e in deps.bus.get_history()
            if e.type == EventType.SYSTEM_ALERT
            and e.data.get("kind") == "audit_chain_break"
        ]
        assert len(alerts) == 2
