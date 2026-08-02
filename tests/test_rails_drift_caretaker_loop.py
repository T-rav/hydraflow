"""Unit tests for RailsDriftCaretakerLoop (#10936, ADR-0121)."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

from dedup_store import DedupStore
from rails_drift_caretaker_loop import (
    RailsDriftCaretakerLoop,
    _dedup_key,
    audit_repo_rails,
    observe_rails,
)
from rails_manifest import (
    FINDING_MISSING_LAYER,
    FINDING_UNKNOWN_LAYER,
    RailsDriftReport,
    RailsFinding,
    RailsManifest,
    write_manifest,
)
from tests.helpers import make_bg_loop_deps

_CLEAN = RailsDriftReport(repo="o/r", findings=())
_MISSING_LAYER = RailsDriftReport(
    repo="o/r",
    findings=(
        RailsFinding(
            check_id="missing-layer:language_pack",
            finding_class=FINDING_MISSING_LAYER,
            detail="the 'language_pack' layer is gone",
        ),
    ),
)
_UNKNOWN_ONLY = RailsDriftReport(
    repo="o/r",
    findings=(
        RailsFinding(
            check_id="unknown-layer:operator_agent_pack",
            finding_class=FINDING_UNKNOWN_LAYER,
            detail="tolerated future layer",
        ),
    ),
)
_UNMANAGED = RailsDriftReport(repo="o/r", findings=(), has_manifest=False)


def _build(
    tmp_path: Path,
    *,
    reports: list[RailsDriftReport],
    enabled: bool = True,
    loop_enabled: bool = True,
    **overrides,
):
    deps = make_bg_loop_deps(tmp_path, enabled=enabled, **overrides)
    config = deps.config.model_copy(
        update={"rails_drift_caretaker_loop_enabled": loop_enabled}
    )
    pr = MagicMock()
    pr.create_issue = AsyncMock(return_value=4242)
    pr.find_existing_issue = AsyncMock(return_value=0)
    pr.close_issue = AsyncMock()
    pr.post_comment = AsyncMock()
    dedup = DedupStore("rdc", tmp_path / "rdc.json")
    auditor = AsyncMock(return_value=reports)
    loop = RailsDriftCaretakerLoop(
        config=config,
        pr_manager=pr,
        dedup=dedup,
        deps=deps.loop_deps,
        auditor=auditor,
    )
    return loop, pr, dedup, auditor


async def test_clean_files_no_issue(tmp_path: Path) -> None:
    loop, pr, _dedup, _auditor = _build(tmp_path, reports=[_CLEAN])
    assert await loop._do_work() == {
        "status": "clean",
        "filed": 0,
        "deduped": 0,
        "resolved": 0,
    }
    pr.create_issue.assert_not_awaited()


async def test_drift_files_one_issue_with_check_ids(tmp_path: Path) -> None:
    loop, pr, dedup, _auditor = _build(tmp_path, reports=[_MISSING_LAYER])
    result = await loop._do_work()
    assert result["status"] == "drift"
    assert result["filed"] == 1
    pr.create_issue.assert_awaited_once()
    title, body = pr.create_issue.await_args.args[:2]
    assert "rails-drift" in title
    assert "missing-layer" in title
    assert "missing-layer:language_pack" in body
    assert pr.create_issue.await_args.kwargs["labels"] == [
        "hydraflow-find",
        "hydraflow-rails-drift",
    ]
    assert _dedup_key("o/r", FINDING_MISSING_LAYER) in dedup.get()


async def test_same_drift_is_deduped(tmp_path: Path) -> None:
    loop, pr, _dedup, _auditor = _build(tmp_path, reports=[_MISSING_LAYER])
    await loop._do_work()
    pr.create_issue.reset_mock()
    result = await loop._do_work()
    assert result["deduped"] == 1
    assert result["filed"] == 0
    pr.create_issue.assert_not_awaited()


async def test_unknown_layer_only_is_not_fatal(tmp_path: Path) -> None:
    # A manifest declaring only a future/unknown layer must never file an issue.
    loop, pr, dedup, _auditor = _build(tmp_path, reports=[_UNKNOWN_ONLY])
    result = await loop._do_work()
    assert result == {
        "status": "clean",
        "filed": 0,
        "deduped": 0,
        "resolved": 0,
    }
    pr.create_issue.assert_not_awaited()
    assert dedup.get() == set()


async def test_unmanaged_repo_is_skipped(tmp_path: Path) -> None:
    loop, pr, _dedup, _auditor = _build(tmp_path, reports=[_UNMANAGED])
    result = await loop._do_work()
    assert result["filed"] == 0
    pr.create_issue.assert_not_awaited()


async def test_resolved_drift_closes_issue_and_clears_dedup(tmp_path: Path) -> None:
    loop, pr, dedup, _auditor = _build(tmp_path, reports=[_MISSING_LAYER])
    await loop._do_work()
    assert _dedup_key("o/r", FINDING_MISSING_LAYER) in dedup.get()
    # Next tick: drift resolved (clean report). The open issue is found + closed.
    loop._auditor = AsyncMock(return_value=[_CLEAN])
    pr.find_existing_issue = AsyncMock(return_value=4242)
    result = await loop._do_work()
    assert result["resolved"] == 1
    pr.close_issue.assert_awaited_once_with(4242)
    assert dedup.get() == set()


async def test_disabled_kill_switch_skips_audit(tmp_path: Path) -> None:
    loop, _pr, _dedup, auditor = _build(
        tmp_path, reports=[_MISSING_LAYER], enabled=False
    )
    assert await loop._do_work() == {"status": "disabled"}
    auditor.assert_not_awaited()


async def test_config_kill_switch_skips_audit(tmp_path: Path) -> None:
    loop, _pr, _dedup, auditor = _build(
        tmp_path, reports=[_MISSING_LAYER], loop_enabled=False
    )
    assert await loop._do_work() == {"status": "config_disabled"}
    auditor.assert_not_awaited()


async def test_dry_run_skips_audit(tmp_path: Path) -> None:
    loop, _pr, _dedup, auditor = _build(
        tmp_path, reports=[_MISSING_LAYER], dry_run=True
    )
    assert await loop._do_work() is None
    auditor.assert_not_awaited()


async def test_auditor_failure_is_caught(tmp_path: Path) -> None:
    loop, pr, _dedup, _auditor = _build(tmp_path, reports=[_CLEAN])
    loop._auditor = AsyncMock(side_effect=Exception("transient fs failure"))
    assert await loop._do_work() == {"error": True}
    pr.create_issue.assert_not_awaited()


async def test_create_issue_zero_sentinel_not_tracked(tmp_path: Path) -> None:
    loop, pr, dedup, _auditor = _build(tmp_path, reports=[_MISSING_LAYER])
    pr.create_issue = AsyncMock(return_value=0)
    result = await loop._do_work()
    assert result["filed"] == 0
    # Phantom issue not tracked → retried next cycle.
    assert dedup.get() == set()


async def test_default_interval_from_config(tmp_path: Path) -> None:
    loop, _pr, _dedup, _auditor = _build(tmp_path, reports=[_CLEAN])
    assert loop._get_default_interval() == loop._config.rails_drift_caretaker_interval


# --------------------------------------------------------------------------- #
# observe_rails / audit_repo_rails                                             #
# --------------------------------------------------------------------------- #


def test_observe_rails_detects_layers_and_scripts(tmp_path: Path) -> None:
    (tmp_path / "docs" / "adr").mkdir(parents=True)
    (tmp_path / "docs" / "adr" / "0044-hydraflow-principles.md").write_text("x")
    (tmp_path / "pyproject.toml").write_text("x")
    (tmp_path / "scripts").mkdir()
    (tmp_path / "scripts" / "scan_secrets").write_text("x")
    observed = observe_rails(tmp_path, coverage=90.0)
    assert "universal" in observed.present_layers
    assert "language_pack" in observed.present_layers
    assert "scan_secrets" in observed.present_gate_scripts
    assert observed.coverage == 90.0


def test_audit_repo_rails_unmanaged_when_no_manifest(tmp_path: Path) -> None:
    report = audit_repo_rails("o/r", tmp_path)
    assert report.has_manifest is False


def test_audit_repo_rails_flags_missing_layer(tmp_path: Path) -> None:
    # Manifest declares language_pack, but the checkout has no language marker.
    write_manifest(
        tmp_path,
        RailsManifest(template_version="1", layers=("language_pack",)),
    )
    report = audit_repo_rails("o/r", tmp_path)
    assert report.has_manifest is True
    assert not report.clean
    assert any(f.finding_class == FINDING_MISSING_LAYER for f in report.findings)
