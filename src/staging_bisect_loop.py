"""Staging-red attribution bisect loop (spec §4.3).

Polls ``StateTracker.last_rc_red_sha`` every ``staging_bisect_interval``
seconds. When the red SHA changes, the loop:

1. Flake-filters the red (Task 10).
2. Bisects between ``last_green_rc_sha`` and ``current_red_rc_sha``
   (Task 12).
3. Attributes the first-bad commit to its originating PR (Task 14).
4. Enforces the second-revert-in-cycle guardrail (Task 16).
5. Files an auto-revert PR (Task 17) and a retry issue (Task 19).
6. Watchdogs the next RC cycle for outcome verification (Task 20).

Trigger mechanism: state-tracker poll (not an event bus). Matches
HydraFlow's existing cadence-style loops; no new event infra.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from base_background_loop import BaseBackgroundLoop, LoopDeps
from config import HydraFlowConfig
from dedup_store import DedupStore

if TYPE_CHECKING:
    from ports import PRPort
    from state import StateTracker

logger = logging.getLogger("hydraflow.staging_bisect")


class StagingBisectLoop(BaseBackgroundLoop):
    """Watchdog that reacts to RC-red state transitions. See ADR-0042 §4.3."""

    def __init__(
        self,
        *,
        config: HydraFlowConfig,
        prs: PRPort,
        deps: LoopDeps,
        state: StateTracker,
    ) -> None:
        super().__init__(worker_name="staging_bisect", config=config, deps=deps)
        self._prs = prs
        self._state = state
        # Persisted high-water mark of RC-red SHAs that have already been
        # processed (or skipped as flakes, or escalated). Keyed on rc_red_sha
        # (§4.3 idempotency); survives crash-restart.
        self._processed_dedup = DedupStore(
            "staging_bisect_processed_rc_red",
            config.data_root / "dedup" / "staging_bisect_processed.json",
        )
        # Seed from persisted store on startup; empty on first boot.
        processed = self._processed_dedup.get()
        self._last_processed_rc_red_sha: str = (
            max(processed, key=len) if processed else ""
        )

    def _get_default_interval(self) -> int:
        return self._config.staging_bisect_interval

    async def _do_work(self) -> dict[str, Any] | None:
        if not self._config.staging_enabled:
            return {"status": "staging_disabled"}

        red_sha = self._state.get_last_rc_red_sha()
        if not red_sha:
            return {"status": "no_red"}

        if red_sha == self._last_processed_rc_red_sha:
            return {"status": "already_processed", "sha": red_sha}

        if red_sha in self._processed_dedup.get():
            self._last_processed_rc_red_sha = red_sha
            return {"status": "already_processed", "sha": red_sha}

        # Flake filter — second probe against the red head (spec §4.3 step 1).
        probe_passed, probe_output = await self._run_bisect_probe(red_sha)
        if probe_passed:
            logger.warning(
                "StagingBisectLoop: second probe passed for %s — dismissing as flake",
                red_sha,
            )
            self._state.increment_flake_reruns_total()
            self._processed_dedup.add(red_sha)
            self._last_processed_rc_red_sha = red_sha
            return {"status": "flake_dismissed", "sha": red_sha}

        # Confirmed red — run the full bisect + revert + retry pipeline.
        result = await self._run_full_bisect_pipeline(red_sha, probe_output)
        self._processed_dedup.add(red_sha)
        self._last_processed_rc_red_sha = red_sha
        return result

    async def _run_bisect_probe(self, rc_sha: str) -> tuple[bool, str]:
        """Run ``make bisect-probe`` once against *rc_sha*.

        Returns ``(passed, combined_output)``. Task 12 replaces this with a
        worktree-scoped invocation; for now it shells out against the
        configured repo root.
        """
        from subprocess import run  # noqa: PLC0415 — lazy import

        logger.info("Running bisect-probe against %s", rc_sha)
        proc = run(
            ["make", "bisect-probe"],
            cwd=self._config.repo_root,
            capture_output=True,
            text=True,
            check=False,
            timeout=self._config.staging_bisect_runtime_cap_seconds,
        )
        return proc.returncode == 0, (proc.stdout + proc.stderr)

    async def _run_full_bisect_pipeline(
        self, red_sha: str, probe_output: str
    ) -> dict[str, Any]:
        """Run bisect -> attribute -> guardrail -> revert -> retry -> watchdog.

        Implemented across Tasks 12-20. Stub returns a placeholder so the
        flake-filter test proves the flow routes past the filter.
        """
        logger.info(
            "StagingBisectLoop: pipeline not yet wired for %s (probe_output=%d chars)",
            red_sha,
            len(probe_output),
        )
        return {"status": "pipeline_stub", "sha": red_sha}
