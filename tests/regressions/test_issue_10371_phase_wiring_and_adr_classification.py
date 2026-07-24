"""Regression: judge-independence production wiring must not silently unwire,
and the ADR-review surface must classify (two #10371 review findings).

Two real seams the unit suite was blind to before these tests:

1. **Untested ``_phase.py`` wiring.** ``ReviewPhase._run_post_verify_for_surface``
   constructs the ``PostVerifyAdvisor`` with ``ledger_path=``, ``event_bus=``
   and ``independent_model=``. Deleting any of the three kwargs from
   ``_phase.py`` previously left the whole suite green — the feature could be
   silently unwired. These tests drive the REAL ``_phase.py`` surface and assert
   each kwarg is load-bearing: an independent dispatch + on-disk classed-verdict
   ledger row (``ledger_path`` + ``independent_model``) and a ``judge_fail_open``
   SYSTEM_ALERT on the phase bus (``event_bus``).

2. **ADR-review classification bypass.** ``_run_post_verify_advisor_for_adr``
   feeds the ADR markdown body (which has no ``+++ b/`` / ``diff --git``
   headers) as ``diff``; ``classify_diff`` found zero paths → unclassed → no
   independent verdict for the canonical structural / ADR-touching class. The
   ADR surface now declares the ADR corpus path so a no-PR ADR review classifies
   STRUCTURAL and, with the flag on, gets an independent verdict.

Both feature flags stay DEFAULT-OFF; these tests opt in explicitly. Nothing here
changes a merge OUTCOME (a classed change still APPROVEs; a non-self-mod
fail-open still passes) — the assertions are about routing, ledgering, and
alarming, never about flipping the verdict for the ordinary path.
"""

from __future__ import annotations

from typing import Any

import judge_independence as ji
from tests.conftest import TaskFactory
from tests.helpers import make_review_phase

_APPROVE = '{"verdict":"APPROVE","reasoning":"ok","disagreements":[]}'


class _RecordingRunner:
    """Records the dispatch model per call; returns a canned payload or raises."""

    def __init__(self, payload: str | Exception) -> None:
        self._payload = payload
        self.calls: list[dict[str, Any]] = []

    async def run(
        self, *, model: str, subagent_type: str, prompt: str, role: str
    ) -> str:
        self.calls.append({"model": model, "role": role})
        if isinstance(self._payload, Exception):
            raise self._payload
        return self._payload


def _structural_diff() -> str:
    # ``src/orchestrator.py`` is STRUCTURAL (module-graph-critical) but is NOT
    # one of the T29 self-modifying paths (review_advisor.py / review_phase.py),
    # so post-verify authority stays the surface default — we are exercising the
    # independence budget, not the self-mod authority override.
    p = "src/orchestrator.py"
    return f"diff --git a/{p} b/{p}\n--- a/{p}\n+++ b/{p}\n@@ -1 +1 @@\n-a\n+b\n"


def _enable_independence(config: Any) -> None:
    """Opt in to the (default-off) independence flag + configure a cross-family
    judge. ``gpt-4o`` is the ``openai`` family, outside the default ``claude``
    roster (model/review_model=sonnet), so it counts as independent."""
    object.__setattr__(config, "judge_independence_enabled", True)
    object.__setattr__(config, "judge_independent_model", "gpt-4o")


async def test_phase_wires_ledger_and_independent_model(config: Any) -> None:
    """Classed change on the real ``_phase.py`` surface → independent dispatch +
    on-disk classed-verdict ledger row.

    Load-bearing for ``ledger_path=`` and ``independent_model=`` in
    ``_run_post_verify_for_surface``: dropping ``independent_model`` reverts the
    dispatch model to the same-family advisor (``opus``) and marks the row
    ``independent: false``; dropping ``ledger_path`` writes no row at all.
    """
    _enable_independence(config)
    phase = make_review_phase(config)
    runner = _RecordingRunner(_APPROVE)
    phase._post_verify_runner = runner

    result = await phase._run_post_verify_for_surface(
        surface="pr_review",
        diff=_structural_diff(),
        spec=None,
        executor_verdict_summary="approved",
        issue_number=4242,
    )

    assert result is not None
    assert result.verdict == "APPROVE"  # outcome unchanged for the ordinary pass
    # independent_model wired: dispatch routed to the configured independent family.
    assert runner.calls[0]["model"] == "gpt-4o"
    # ledger_path wired: an independent classed-verdict row landed on disk.
    records = ji.read_records(ji.ledger_path_for(config))
    classed = [r for r in records if r["kind"] == ji.KIND_CLASSED_VERDICT]
    assert len(classed) == 1
    assert classed[0]["independent"] is True
    assert classed[0]["judge_family"] == "openai"
    assert classed[0]["pr"] == 4242


async def test_phase_wires_event_bus_alarm_on_fail_open(
    config: Any, event_bus: Any
) -> None:
    """Dispatch failure on the real ``_phase.py`` surface → ``judge_fail_open``
    SYSTEM_ALERT on the phase bus + a fail-open ledger row.

    Load-bearing for ``event_bus=`` (and, again, ``ledger_path=``): dropping
    ``event_bus`` silences the alarm; dropping ``ledger_path`` drops the row.
    """
    _enable_independence(config)
    phase = make_review_phase(config, event_bus=event_bus)
    runner = _RecordingRunner(RuntimeError("judge unavailable"))
    phase._post_verify_runner = runner

    result = await phase._run_post_verify_for_surface(
        surface="pr_review",
        diff=_structural_diff(),
        spec=None,
        executor_verdict_summary="approved",
        issue_number=4242,
    )

    # Non-self-mod class fails open (APPROVE) — outcome unchanged, but loud.
    assert result is not None
    assert result.verdict == "APPROVE"
    # event_bus wired: the alarm was published on the phase bus.
    alarms = [
        e for e in event_bus.get_history() if e.data.get("kind") == "judge_fail_open"
    ]
    assert len(alarms) == 1
    assert alarms[0].data["pr"] == 4242
    # ledger_path wired: the fail-open row landed on disk.
    fo = [
        r
        for r in ji.read_records(ji.ledger_path_for(config))
        if r["kind"] == ji.KIND_FAIL_OPEN
    ]
    assert len(fo) == 1


async def test_no_pr_adr_review_is_classed_structural_and_gets_independent_verdict(
    config: Any,
) -> None:
    """A no-PR ADR review (ADR body, no diff headers) classifies STRUCTURAL and,
    with the independence flag on, routes to an independent judge family.

    Guards the ADR-review classification bypass end-to-end through the real ADR
    caller: it declares the ADR corpus path via ``classification_paths=``.
    Dropping that kwarg makes the header-less body classify as unclassed — the
    dispatch reverts to the same-family advisor and no classed-verdict row is
    written, failing this test.
    """
    _enable_independence(config)
    phase = make_review_phase(config)
    runner = _RecordingRunner(_APPROVE)
    phase._post_verify_runner = runner

    adr_body = (
        "# ADR-9999: Something structural\n\n"
        "## Context\nThe factory needs a decision.\n\n"
        "## Decision\nWe will adopt the approach described here in enough "
        "detail to comfortably clear the sixty-character minimum the ADR "
        "validator enforces on the decision section.\n\n"
        "## Consequences\nTrade-offs apply.\n"
    )
    issue = TaskFactory.create(
        id=7777, title="ADR: something structural", body=adr_body
    )

    result = await phase._run_post_verify_advisor_for_adr(
        issue=issue,
        # The ADR body IS the "diff" for this surface — it carries no
        # unified-diff headers, which is exactly the classification bypass.
        diff=adr_body,
        executor_verdict_summary="ADR structural validation passed",
    )

    assert result is None  # advisor APPROVEd → proceed to finalize
    # The header-less ADR body still classifies STRUCTURAL via the declared
    # corpus path, so the verdict routed to the independent family.
    assert runner.calls[0]["model"] == "gpt-4o"
    records = ji.read_records(ji.ledger_path_for(config))
    classed = [r for r in records if r["kind"] == ji.KIND_CLASSED_VERDICT]
    assert len(classed) == 1
    assert "structural" in classed[0]["failure_class"]
    assert classed[0]["independent"] is True
