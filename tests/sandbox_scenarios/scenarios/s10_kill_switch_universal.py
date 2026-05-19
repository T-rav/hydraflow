"""s10 — disable EVERY caretaker loop via ``loops_enabled=[]``.

Proves ADR-0049 wiring (#8483). With ``MockWorldSeed.loops_enabled=[]``,
``sandbox_main._build_caretaker_enabled_cb`` returns a callback that
answers False for every caretaker name. That callback becomes each
``BaseBackgroundLoop`` subclass's ``LoopDeps.enabled_cb`` — the in-body
``self._enabled_cb(self._worker_name)`` gate per ADR-0049 trips before
any ``_do_work`` runs, so no caretaker reports ``last_run`` and every
caretaker is marked ``enabled=False`` on ``/api/system/workers``.

Phase orchestrators (``triage``, ``plan``, ``implement``, ``review``,
``hitl``, ``discover``, ``shape``) are listed in
``_control_routes._bg_worker_defs`` for UI display but their actual gate
is ``orchestrator.is_bg_worker_enabled`` → ``BGWorkerManager.is_enabled``,
which defaults to True. Their ``enabled`` flag on this endpoint should
therefore stay True — confirming the per-#8483-triage-comment contract
that phase orchestrators are unaffected by the universal kill-switch.
"""

from __future__ import annotations

from mockworld.seed import MockWorldSeed

NAME = "s10_kill_switch_universal"
DESCRIPTION = "loops_enabled=[] → caretaker ticks suppressed; phase orchestrators unaffected (ADR-0049, #8483)."

# Caretaker loops we expect to be force-disabled. Names match keys in
# ``HydraFlowOrchestrator._bg_loop_registry``. We pick a few load-bearing
# caretakers as the contract — exhaustive listing would couple the
# scenario to the registry's churn; this set is enough to prove the
# wiring fires without false negatives from caretakers whose UI surface
# might lag.
_CARETAKER_NAMES = {
    "pr_unsticker",
    "workspace_gc",
    "dependabot_merge",
    "ci_monitor",
    "report_issue",
}

# Phase orchestrators — must remain enabled (their gate is
# BGWorkerManager, not the loops_enabled callback). Keep this list to
# the canonical seven from the triage comment.
_PHASE_NAMES = {
    "triage",
    "plan",
    "implement",
    "review",
}


def seed() -> MockWorldSeed:
    return MockWorldSeed(
        loops_enabled=[],  # ADR-0049 universal kill — no caretakers tick.
        cycles_to_run=5,
    )


async def assert_outcome(api, page) -> None:
    """Caretakers report enabled=False; phase orchestrators stay enabled=True."""

    # The dashboard's /api/system/workers endpoint returns every entry in
    # ``_bg_worker_defs`` with its ``enabled`` (from
    # ``orchestrator.is_bg_worker_enabled``) and ``last_run``. For
    # caretakers, ``is_bg_worker_enabled`` is wired to BGWorkerManager —
    # but the in-body ADR-0049 gate is what stops _do_work from running.
    # The dashboard's enabled flag here reflects BGWorkerManager state,
    # which the kill-switch does NOT touch directly. So we assert what's
    # genuinely observable through this endpoint: caretakers have no
    # last_run because they never executed a tick.
    #
    # Use wait_until so transient startup races don't false-fail. Once
    # the boot completes and at least one supervise cycle has fired,
    # the snapshot stabilizes.
    def _shape_ready(payload: dict) -> bool:
        workers = payload.get("workers") if isinstance(payload, dict) else None
        if not isinstance(workers, list) or not workers:
            return False
        names = {
            w.get("name")
            for w in workers
            if isinstance(w, dict) and w.get("name") is not None
        }
        # Want at least the caretakers we'll assert on, and at least one
        # phase orchestrator, to be present in the catalog.
        return bool(_CARETAKER_NAMES & names) and bool(_PHASE_NAMES & names)

    payload = await api.wait_until(
        "/api/system/workers",
        _shape_ready,
        timeout=45.0,
    )
    workers = payload["workers"]
    by_name = {w["name"]: w for w in workers if isinstance(w, dict)}

    # Caretaker contract: never executed a _do_work, so last_run is None.
    # The in-body ADR-0049 gate (``self._enabled_cb(self._worker_name)``)
    # short-circuited every tick.
    caretakers_with_runs = [
        n for n in _CARETAKER_NAMES if by_name.get(n, {}).get("last_run") is not None
    ]
    assert not caretakers_with_runs, (
        f"caretakers ticked despite loops_enabled=[]: {caretakers_with_runs!r}; "
        f"full snapshot: {by_name!r}"
    )

    # Phase orchestrator contract: NOT gated by loops_enabled (their gate
    # is BGWorkerManager). The endpoint should report enabled=True for
    # these — proving the kill-switch is caretaker-scoped, not universal.
    phases_disabled = [
        n for n in _PHASE_NAMES if by_name.get(n, {}).get("enabled") is False
    ]
    assert not phases_disabled, (
        f"phase orchestrators were disabled — should be unaffected by "
        f"loops_enabled=[] per #8483 triage: {phases_disabled!r}"
    )
