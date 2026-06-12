"""Unit tests for GateActivatorLoop (ADR-0082, Slice 4)."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

from scripts.gates.activation import ActivationProposal

from dedup_store import DedupStore
from gate_activator_loop import GateActivatorLoop
from tests.helpers import make_bg_loop_deps

_NONE: list[ActivationProposal] = []
_PROPOSALS = [
    ActivationProposal(
        name="Browser Scenarios",
        dimension="browser-e2e",
        required_on=("main",),
        workflow="ci.yml",
        job="browser",
        make_target="test-browser",
    )
]


def _build(
    tmp_path: Path,
    *,
    proposals: list[ActivationProposal],
    enabled: bool = True,
    loop_enabled: bool = True,
    **overrides,
):
    deps = make_bg_loop_deps(tmp_path, enabled=enabled, **overrides)
    config = deps.config.model_copy(
        update={"gate_activator_loop_enabled": loop_enabled}
    )
    pr = MagicMock()
    pr.create_issue = AsyncMock(return_value=4242)
    pr.find_existing_issue = AsyncMock(return_value=0)
    pr.close_issue = AsyncMock()
    pr.post_comment = AsyncMock()
    dedup = DedupStore("ga", tmp_path / "ga.json")
    detector = AsyncMock(return_value=proposals)
    loop = GateActivatorLoop(
        config=config,
        pr_manager=pr,
        dedup=dedup,
        deps=deps.loop_deps,
        detector=detector,
    )
    return loop, pr, dedup, detector


async def test_no_proposals_files_no_issue(tmp_path: Path) -> None:
    loop, pr, _dedup, _detector = _build(tmp_path, proposals=_NONE)
    assert await loop._do_work() == {"status": "clean"}
    pr.create_issue.assert_not_awaited()


async def test_proposals_file_one_issue(tmp_path: Path) -> None:
    loop, pr, dedup, _detector = _build(tmp_path, proposals=_PROPOSALS)
    result = await loop._do_work()
    assert result == {"status": "proposals", "issue_created": 4242}
    pr.create_issue.assert_awaited_once()
    title, body = pr.create_issue.await_args.args[:2]
    assert "gate-activation" in title
    assert "Browser Scenarios" in body
    assert 'status = "active"' in body
    assert "make gen-gates" in body
    assert pr.create_issue.await_args.kwargs["labels"] == [
        "hydraflow-find",
        "hydraflow-gate-activation",
    ]
    assert len(dedup.get()) == 1


async def test_same_proposals_are_deduped(tmp_path: Path) -> None:
    loop, pr, _dedup, _detector = _build(tmp_path, proposals=_PROPOSALS)
    await loop._do_work()
    pr.create_issue.reset_mock()
    assert await loop._do_work() == {"status": "proposals", "deduped": True}
    pr.create_issue.assert_not_awaited()


async def test_sentinel_issue_zero_is_not_tracked(tmp_path: Path) -> None:
    loop, pr, dedup, _detector = _build(tmp_path, proposals=_PROPOSALS)
    pr.create_issue = AsyncMock(return_value=0)
    assert await loop._do_work() == {"status": "proposals", "error": True}
    assert dedup.get() == set()


async def test_disabled_kill_switch_skips_detection(tmp_path: Path) -> None:
    loop, _pr, _dedup, detector = _build(tmp_path, proposals=_PROPOSALS, enabled=False)
    assert await loop._do_work() == {"status": "disabled"}
    detector.assert_not_awaited()


async def test_config_kill_switch_skips_detection(tmp_path: Path) -> None:
    loop, _pr, _dedup, detector = _build(
        tmp_path, proposals=_PROPOSALS, loop_enabled=False
    )
    assert await loop._do_work() == {"status": "config_disabled"}
    detector.assert_not_awaited()


async def test_dry_run_skips_detection(tmp_path: Path) -> None:
    loop, _pr, _dedup, detector = _build(tmp_path, proposals=_PROPOSALS, dry_run=True)
    assert await loop._do_work() is None
    detector.assert_not_awaited()


async def test_detector_failure_is_caught(tmp_path: Path) -> None:
    loop, pr, _dedup, _detector = _build(tmp_path, proposals=_NONE)
    loop._detector = AsyncMock(side_effect=Exception("transient read failure"))
    assert await loop._do_work() == {"error": True}
    pr.create_issue.assert_not_awaited()


async def test_default_interval_from_config(tmp_path: Path) -> None:
    loop, _pr, _dedup, _detector = _build(tmp_path, proposals=_NONE)
    assert loop._get_default_interval() == loop._config.gate_activator_interval


async def test_clean_closes_open_issue_and_clears_dedup(tmp_path: Path) -> None:
    """#9359: when no proposals remain, close the open activation issue and
    clear the dedup so a future proposal re-files."""
    loop, pr, dedup, _detector = _build(tmp_path, proposals=_PROPOSALS)
    # First tick files + dedups.
    await loop._do_work()
    assert len(dedup.get()) == 1
    # Now the gates are activated → detector returns no proposals.
    loop._detector = AsyncMock(return_value=_NONE)  # type: ignore[attr-defined]
    pr.find_existing_issue = AsyncMock(return_value=4242)
    result = await loop._do_work()
    assert result == {"status": "clean"}
    pr.close_issue.assert_awaited_once_with(4242)
    assert dedup.get() == set()
