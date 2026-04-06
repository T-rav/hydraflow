"""Tests for the TestAuditLoop background worker."""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from test_audit_loop import TestAuditLoop
from tests.helpers import ConfigFactory, make_bg_loop_deps

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_loop(
    tmp_path: Path,
    *,
    enabled: bool = True,
    dry_run: bool = False,
    test_audit_interval: int = 86400,
    existing_dedup: list[str] | None = None,
) -> tuple[TestAuditLoop, AsyncMock, asyncio.Event]:
    """Build a TestAuditLoop with test-friendly defaults."""
    deps = make_bg_loop_deps(
        tmp_path,
        enabled=enabled,
        dry_run=dry_run,
        test_audit_interval=test_audit_interval,
    )
    pr_manager = AsyncMock()
    pr_manager.create_issue = AsyncMock(return_value=42)

    # Seed dedup store file if needed
    dedup_path = deps.config.data_root / "memory" / "test_audit_dedup.json"
    if existing_dedup:
        dedup_path.parent.mkdir(parents=True, exist_ok=True)
        dedup_path.write_text(json.dumps(existing_dedup))

    loop = TestAuditLoop(
        config=deps.config,
        pr_manager=pr_manager,
        deps=deps.loop_deps,
    )
    return loop, pr_manager, deps.stop_event


# ===========================================================================
# Tests
# ===========================================================================


class TestTestAuditLoopBasics:
    def test_worker_name(self, tmp_path: Path) -> None:
        loop, _pm, _stop = _make_loop(tmp_path)
        assert loop._worker_name == "test_audit"

    def test_default_interval_from_config(self, tmp_path: Path) -> None:
        loop, _pm, _stop = _make_loop(tmp_path, test_audit_interval=43200)
        assert loop._get_default_interval() == 43200

    def test_default_interval_config_field(self) -> None:
        config = ConfigFactory.create(test_audit_interval=86400)
        assert config.test_audit_interval == 86400


class TestTestAuditLoopWork:
    @pytest.mark.asyncio
    async def test_no_findings_returns_zero(self, tmp_path: Path) -> None:
        loop, pm, _stop = _make_loop(tmp_path)
        with patch.object(loop, "_run_audit", new_callable=AsyncMock, return_value=[]):
            result = await loop._do_work()
        assert result is not None
        assert result["filed"] == 0
        pm.create_issue.assert_not_called()

    @pytest.mark.asyncio
    async def test_critical_finding_files_issue(self, tmp_path: Path) -> None:
        finding = {
            "id": "duplicate-helper-make-config",
            "severity": "critical",
            "title": "Duplicate test helper",
            "description": "tests/test_foo.py:make_config duplicates ConfigFactory",
        }
        loop, pm, _stop = _make_loop(tmp_path)
        with patch.object(
            loop, "_run_audit", new_callable=AsyncMock, return_value=[finding]
        ):
            result = await loop._do_work()
        assert result is not None
        assert result["filed"] == 1
        pm.create_issue.assert_called_once()
        call_args = pm.create_issue.call_args
        assert "[Test Audit]" in call_args[0][0]

    @pytest.mark.asyncio
    async def test_duplicate_finding_skipped(self, tmp_path: Path) -> None:
        finding = {
            "id": "duplicate-helper-make-config",
            "severity": "high",
            "title": "Duplicate test helper",
            "description": "Duplicate helper",
        }
        loop, pm, _stop = _make_loop(
            tmp_path, existing_dedup=["duplicate-helper-make-config"]
        )
        with patch.object(
            loop, "_run_audit", new_callable=AsyncMock, return_value=[finding]
        ):
            result = await loop._do_work()
        assert result is not None
        assert result["filed"] == 0
        assert result["skipped_dedup"] == 1
        pm.create_issue.assert_not_called()

    @pytest.mark.asyncio
    async def test_dry_run_returns_none(self, tmp_path: Path) -> None:
        loop, pm, _stop = _make_loop(tmp_path, dry_run=True)
        result = await loop._do_work()
        assert result is None
        pm.create_issue.assert_not_called()

    @pytest.mark.asyncio
    async def test_agent_failure_caught_gracefully(self, tmp_path: Path) -> None:
        loop, pm, _stop = _make_loop(tmp_path)
        with patch.object(
            loop,
            "_run_audit",
            new_callable=AsyncMock,
            side_effect=RuntimeError("agent crashed"),
        ):
            result = await loop._do_work()
        assert result is not None
        assert result["filed"] == 0
        assert result["error"] is True
        pm.create_issue.assert_not_called()

    @pytest.mark.asyncio
    async def test_low_severity_finding_skipped(self, tmp_path: Path) -> None:
        finding = {
            "id": "minor-naming-issue",
            "severity": "low",
            "title": "Minor naming issue",
            "description": "Non-standard test naming",
        }
        loop, pm, _stop = _make_loop(tmp_path)
        with patch.object(
            loop, "_run_audit", new_callable=AsyncMock, return_value=[finding]
        ):
            result = await loop._do_work()
        assert result is not None
        assert result["filed"] == 0
        assert result["skipped_severity"] == 1


class TestTestAuditLoopParseFindings:
    def test_parses_valid_findings(self) -> None:
        transcript = (
            "Some preamble\n"
            '{"id": "dup-helper-1", "severity": "high", "title": "Dup helper"}\n'
            "Some other text\n"
        )
        findings = TestAuditLoop._parse_findings(transcript)
        assert len(findings) == 1
        assert findings[0]["id"] == "dup-helper-1"

    def test_ignores_invalid_json(self) -> None:
        transcript = '{"id": "incomplete\nsome text\n'
        findings = TestAuditLoop._parse_findings(transcript)
        assert findings == []

    def test_ignores_objects_without_required_keys(self) -> None:
        transcript = '{"name": "missing-id-and-severity"}\n'
        findings = TestAuditLoop._parse_findings(transcript)
        assert findings == []

    def test_empty_transcript(self) -> None:
        findings = TestAuditLoop._parse_findings("")
        assert findings == []
