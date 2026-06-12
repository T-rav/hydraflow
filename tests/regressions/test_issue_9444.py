"""Regression for issue #9444 — verification-window mismatch (false stale insight).

`verify_proposals` compares a category's *current* frequency against the
``pre_count`` captured when the proposal was filed. ``pre_count`` is sampled
over ``review_insight_window`` (config default 10), but two of the three
verification call sites sampled ``current_count`` over a hardcoded
``load_recent(50)``:

* ``RetrospectiveLoop._handle_verify_proposals`` (src/retrospective_loop.py)
* ``HealthMonitorLoop._run_proposal_verification_cycle`` (inline fallback,
  src/health_monitor_loop.py)

Because the current count was measured over a 5x-wider window than the
baseline, ``current_count >= pre_count`` could never observe improvement for
any high-frequency category, so the verifier perpetually re-filed
``[HITL] Stale review insight: ...`` issues that no implementation change
could ever clear.

The matched/correct path (``ReviewPhase._record_review_insight``) already
samples both counts over ``review_insight_window``. These tests pin both loop
call sites to the configured window, not a literal 50.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

from tests.helpers import make_bg_loop_deps

_WINDOW = 7  # deliberately != the old hardcoded 50 and != the default 10


def test_retrospective_loop_verify_uses_configured_window(tmp_path: Path) -> None:
    from retrospective_loop import RetrospectiveLoop

    deps = make_bg_loop_deps(tmp_path, review_insight_window=_WINDOW)

    insights = MagicMock()
    insights.load_recent = MagicMock(return_value=[])
    insights.load_proposal_metadata = MagicMock(return_value={})

    loop = RetrospectiveLoop(
        config=deps.config,
        deps=deps.loop_deps,
        retrospective=MagicMock(),
        insights=insights,
        queue=MagicMock(),
        prs=None,
    )

    import asyncio

    asyncio.run(loop._handle_verify_proposals())

    insights.load_recent.assert_called_once_with(_WINDOW)


def test_health_monitor_verify_uses_configured_window(
    tmp_path: Path, monkeypatch
) -> None:
    import review_insights as ri_module
    from health_monitor_loop import HealthMonitorLoop

    deps = make_bg_loop_deps(tmp_path, review_insight_window=_WINDOW)

    fake_store = MagicMock()
    fake_store.load_recent = MagicMock(return_value=[])
    fake_store.load_proposal_metadata = MagicMock(return_value={})

    monkeypatch.setattr(
        ri_module,
        "ReviewInsightStore",
        MagicMock(return_value=fake_store),
    )

    loop = HealthMonitorLoop(
        config=deps.config,
        deps=deps.loop_deps,
        retrospective_queue=None,
    )

    loop._run_proposal_verification_cycle()

    fake_store.load_recent.assert_called_once_with(_WINDOW)
