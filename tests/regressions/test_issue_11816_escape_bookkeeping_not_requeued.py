"""Regression (#11816): a resolved escape-ledger surfacing must not be requeued.

`EscapeLedgerLoop._surface_findings` files HITL issues for aging / low-confidence
escapes (#10577). Their correct resolution is a row appended by
`scripts/resolve_escape.py` — **never a PR, never a code change**.

The review-orphan requeue (#9815) reads "review-labeled with no open agent PR"
as an interrupted implement attempt. True for code work; false here, where no PR
is the *expected* terminal state.

Issue #11787 lost that race by two minutes:

    12:19:10Z  auto-agent resolves correctly, appends the ledger row,
               reports "PR: none — no code change was required"
    12:21:18Z  Review Orphan Requeue fires: "no open agent PR
               (interrupted implement)" -> attempt counters reset,
               requeued to ready (requeue 1/3)

`_reconcile_surfaced_issues` would have closed it, but had not ticked yet. The
fresh cycle could not produce a PR either, so left alone this burns the whole
3-attempt budget and escalates to HITL. A human closed #11787 by hand, citing
the resolution row that had been correct all along.

Keyed on the OPEN link rather than a label the resolving agent must remember:
the link is written by the loop that filed the issue and disappears exactly when
reconciliation closes it, so it cannot be forgotten or fall out of date.
"""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

import pytest

from escape.surfaces import SurfacedIssue, SurfacedIssueLedger
from orchestrator_work import _is_escape_bookkeeping_issue


def _ledger(tmp_path: Path) -> tuple[SurfacedIssueLedger, Path]:
    diag = tmp_path / "diagnostics"
    diag.mkdir(parents=True, exist_ok=True)
    path = diag / "escape_surfaces.jsonl"
    return SurfacedIssueLedger(path), path


def _link(issue: int, *, closed: str = "") -> SurfacedIssue:
    return SurfacedIssue(
        fingerprint=f"surfaced:aging:esc{issue}",
        escape_id=f"esc{issue}",
        reason="aging",
        issue_number=issue,
        filed_at="2026-08-30T12:00:00Z",
        closed_at=closed,
    )


def _config(tmp_path: Path) -> MagicMock:
    cfg = MagicMock()
    cfg.diagnostics_dir = tmp_path / "diagnostics"
    return cfg


def test_an_open_surfacing_is_recognised_as_bookkeeping(tmp_path: Path) -> None:
    """The #11787 case: no PR is expected, so it is not an orphan."""
    ledger, _ = _ledger(tmp_path)
    ledger.append(_link(11787))
    assert _is_escape_bookkeeping_issue(_config(tmp_path), 11787) is True


def test_a_closed_surfacing_is_not_bookkeeping_any_more(tmp_path: Path) -> None:
    """Once reconciliation closes the link the exclusion must lapse, or a
    reused issue number would be permanently exempt from orphan detection."""
    ledger, _ = _ledger(tmp_path)
    ledger.append(_link(11787, closed="2026-08-30T12:30:00Z"))
    assert _is_escape_bookkeeping_issue(_config(tmp_path), 11787) is False


def test_an_unrelated_issue_is_still_a_normal_orphan(tmp_path: Path) -> None:
    """The #9815 behaviour this must not reintroduce: a genuine interrupted
    implement still gets requeued."""
    ledger, _ = _ledger(tmp_path)
    ledger.append(_link(11787))
    assert _is_escape_bookkeeping_issue(_config(tmp_path), 99999) is False


def test_a_missing_ledger_file_is_not_bookkeeping(tmp_path: Path) -> None:
    """A fresh deployment has no surfaces file; every issue must stay a normal
    orphan candidate rather than becoming silently exempt."""
    (tmp_path / "diagnostics").mkdir(parents=True, exist_ok=True)
    assert _is_escape_bookkeeping_issue(_config(tmp_path), 11787) is False


def test_an_unreadable_ledger_fails_soft_to_normal_orphan(tmp_path: Path) -> None:
    """Fail-soft direction is chosen deliberately.

    A bookkeeping issue wrongly requeued is recoverable — it costs one cycle.
    A real orphan wrongly skipped sits review-labeled forever, which is exactly
    the #9815 defect this check must not reintroduce. So a read error means
    "not bookkeeping", never "assume bookkeeping".
    """
    ledger, path = _ledger(tmp_path)
    ledger.append(_link(11787))
    path.write_text("{ this is not valid jsonl\n", encoding="utf-8")
    assert _is_escape_bookkeeping_issue(_config(tmp_path), 11787) is False


def test_has_open_link_for_issue_matches_only_open_rows(tmp_path: Path) -> None:
    """Ledger-level check, independent of the orchestrator wiring."""
    ledger, _ = _ledger(tmp_path)
    ledger.append(_link(100))
    ledger.append(_link(200, closed="2026-08-30T13:00:00Z"))
    assert ledger.has_open_link_for_issue(100) is True
    assert ledger.has_open_link_for_issue(200) is False
    assert ledger.has_open_link_for_issue(300) is False


@pytest.mark.parametrize("issue_id", [11787, 100])
def test_the_check_is_not_vacuously_true_for_everything(
    tmp_path: Path, issue_id: int
) -> None:
    """Anti-vacuity: a helper that returned True unconditionally would pass the
    positive test above and silently exempt every issue from orphan detection —
    disabling #9815 entirely."""
    ledger, _ = _ledger(tmp_path)
    ledger.append(_link(issue_id))
    cfg = _config(tmp_path)
    assert _is_escape_bookkeeping_issue(cfg, issue_id) is True
    assert _is_escape_bookkeeping_issue(cfg, issue_id + 1) is False


# ---------------------------------------------------------------------------
# The WIRING. Every test above calls the helper directly, so deleting its call
# from `_handle_review_orphan` leaves them all green while the fix is inert —
# the same vacuity shape as the defect. Mutation-checked: removing the call
# fails these two and only these two.
# ---------------------------------------------------------------------------

from types import SimpleNamespace  # noqa: E402
from unittest.mock import AsyncMock  # noqa: E402

from models import Task  # noqa: E402
from orchestrator import HydraFlowOrchestrator  # noqa: E402


def _task(n: int) -> Task:
    return Task(
        id=n,
        title="Escape-ledger bookkeeping",
        body="x" * 60,
        labels=[],
        links=[],
        complexity_score=0,
        created_at="",
        metadata={},
    )


def _orch(tmp_path: Path, state):
    config = MagicMock()
    # threshold=1 so a single call would requeue if the exclusion did not fire —
    # without this the test could pass on the strike counter, not the fix.
    config.review_orphan_strike_threshold = 1
    config.review_orphan_max_requeues = 3
    config.ready_label = ["hydraflow-ready"]
    config.hitl_label = ["hydraflow-hitl"]
    config.diagnostics_dir = tmp_path / "diagnostics"
    prs = MagicMock()
    prs.swap_pipeline_labels = AsyncMock()
    prs.post_comment = AsyncMock()
    return (
        SimpleNamespace(_config=config, _state=state, _svc=SimpleNamespace(prs=prs)),
        prs,
    )


@pytest.mark.asyncio
async def test_handle_review_orphan_skips_an_open_surfacing(tmp_path: Path) -> None:
    """#11787's exact path: the issue must NOT be requeued or relabelled."""
    ledger, _ = _ledger(tmp_path)
    ledger.append(_link(11787))
    state = MagicMock()
    orch, prs = _orch(tmp_path, state)

    handled = await HydraFlowOrchestrator._handle_review_orphan(orch, _task(11787))

    assert handled is False
    prs.swap_pipeline_labels.assert_not_awaited()
    state.increment_review_orphan_strike.assert_not_called()


@pytest.mark.asyncio
async def test_handle_review_orphan_still_requeues_a_real_orphan(
    tmp_path: Path,
) -> None:
    """#9815 must survive: an issue with no surfacing still strikes normally."""
    ledger, _ = _ledger(tmp_path)
    ledger.append(_link(11787))
    state = MagicMock()
    state.increment_review_orphan_strike.return_value = 1
    state.increment_review_orphan_requeue.return_value = 1
    orch, _prs = _orch(tmp_path, state)

    await HydraFlowOrchestrator._handle_review_orphan(orch, _task(99999))

    state.increment_review_orphan_strike.assert_called_once_with(99999)
