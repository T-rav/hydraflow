"""s81 — LabelDriftWatcherLoop reconciles a seeded issue/PR label-drift pair.

Last #9155 test-pyramid backfill loop: LabelDriftWatcherLoop (ADR-0088) had
unit coverage (``tests/test_label_drift_watcher_loop.py``,
``tests/test_label_drift_watcher_integration.py``) and a MockWorld scenario
(``tests/scenarios/test_label_drift_watcher_scenario.py``) but no sandbox
Tier-2 scenario, so its trigger had never run end-to-end through the real
Docker/UI stack.

Seeds an issue at ``hydraflow-plan`` (a pre-PR label) alongside its PR at
``hydraflow-review`` with commits — ``FakeGitHub.find_label_drift``
classifies this as ``pr_ahead_of_issue`` drift (see
``FakeGitHub.find_label_drift`` and ``LabelDrift`` in ``src/models.py``):
the issue lags behind the PR's stage, so a watcher cycle must pull it
forward. ``FakePR.commits`` defaults to 1, so no new ``MockWorldSeed`` field
is needed — the existing ``issues``/``prs`` seed fields already express the
trigger.

Why the fixture also carries ``hydraflow-in-progress``. Unlike the other
active-trigger governance scenarios (s57 seeds label-free issues, s68 uses
``hydraflow-epic``), a ``pr_ahead_of_issue`` fixture *must* sit at a live
pre-PR pipeline label — and the sandbox runs the real phase orchestrators
(they consult ``BGWorkerManager``, not ``loops_enabled``, so ``loops_enabled``
can't switch them off). The plan phase polls ``hydraflow-plan`` issues, so a
bare ``hydraflow-plan`` fixture gets picked up and advanced
plan→ready→review→merged within the first ~60s — destroying the drift before
the watcher's default-60s poll ever sees it (the RC-gate hang this scenario
repairs). The durable build-claim marker (#10168) is exactly the guard for
this: ``IssueStore._is_eligible`` skips any in-progress-claimed issue at every
stage, so #8100 stays put at ``hydraflow-plan`` for the whole run.
``FakeGitHub.find_label_drift`` explicitly ignores the in-progress marker when
picking the stage label, so the ``pr_ahead_of_issue`` classification is
unchanged — the drift now simply *persists* until the watcher reconciles it.

The loop's real side effect (``LabelDriftWatcherLoop._reconcile``) is a
``swap_pipeline_labels`` call moving the issue to ``hydraflow-review`` plus
an audit comment on the issue — not a heartbeat. This scenario asserts the
loop's own reported counters (``detected``/``reconciled``, the only surface
the sandbox Tier-2 ``/api/events`` stream exposes); the Tier-1 companion in
``tests/scenarios/test_governance_active_trigger_scenarios.py`` additionally
asserts the label swap and comment against the shared FakeGitHub state.
"""

from __future__ import annotations

from mockworld.seed import MockWorldSeed

NAME = "s81_label_drift_watcher_reconciles_pr_ahead"
DESCRIPTION = (
    "LabelDriftWatcherLoop reconciles a seeded pr_ahead_of_issue label-drift "
    "pair (details.reconciled >= 1), not just a heartbeat."
)

# One constant pair across the seeded issue/PR and the assertions.
_ISSUE = 8100
_PR = 8101


def seed() -> MockWorldSeed:
    return MockWorldSeed(
        loops_enabled=["label_drift_watcher"],
        # Tick fast so the watcher's first cycle lands well within the 90s
        # assert window on CI's slower runners (mirrors s57). The default 60s
        # cadence pushed the first poll to ~57s — right at the edge.
        sandbox_loop_interval=10,
        cycles_to_run=2,
        issues=[
            {
                "number": _ISSUE,
                "title": "Feature work lagging its PR",
                "body": "Issue label hasn't caught up to the PR's review stage.",
                # ``hydraflow-in-progress`` is the durable build-claim marker
                # (#10168) — it keeps the live sandbox pipeline from consuming
                # this pre-PR-labelled fixture and advancing it out of the drift
                # state before the watcher polls (see the module docstring).
                # ``find_label_drift`` ignores it when picking the stage label,
                # so the ``pr_ahead_of_issue`` classification is unchanged.
                "labels": ["hydraflow-plan", "hydraflow-in-progress"],
            }
        ],
        # No explicit commits field on the seed's ``prs`` dict — ``FakePR``
        # defaults ``commits=1``, which is exactly what the drift classifier
        # requires (commits > 0) for the ``pr_ahead_of_issue`` kind.
        prs=[
            {
                "number": _PR,
                "issue_number": _ISSUE,
                "branch": f"hf/issue-{_ISSUE}",
                "labels": ["hydraflow-review"],
            }
        ],
    )


async def assert_outcome(api, page) -> None:
    """A label_drift_watcher cycle detects and reconciles the seeded pair."""

    def _reconciled(payload: object) -> bool:
        events = payload if isinstance(payload, list) else []
        return any(
            e.get("type") == "background_worker_status"
            and e.get("data", {}).get("worker") == "label_drift_watcher"
            and (e.get("data", {}).get("details") or {}).get("reconciled", 0) >= 1
            for e in events
        )

    events_payload = await api.wait_until("/api/events", _reconciled, timeout=90.0)

    watcher_events = [
        e
        for e in events_payload
        if e.get("type") == "background_worker_status"
        and e.get("data", {}).get("worker") == "label_drift_watcher"
    ]
    assert any(
        (e.get("data", {}).get("details") or {}).get("detected", 0) >= 1
        for e in watcher_events
    ), (
        f"Expected label_drift_watcher to detect drift for issue #{_ISSUE} / "
        f"PR #{_PR} (details.detected >= 1); worker events: {watcher_events!r}"
    )
    assert any(
        (e.get("data", {}).get("details") or {}).get("reconciled", 0) >= 1
        for e in watcher_events
    ), (
        f"Expected label_drift_watcher to reconcile the seeded drift for "
        f"issue #{_ISSUE} / PR #{_PR} (details.reconciled >= 1); worker "
        f"events: {watcher_events!r}"
    )
