"""ContractRefreshLoop — weekly cassette refresh for fake contract tests (§4.2).

Phase 2 skeleton only: establishes the :class:`BaseBackgroundLoop` subclass,
its ``worker_name``, the injected dependencies (:class:`PRManager`,
:class:`StateTracker`, :class:`LoopDeps`), and the config-driven default
interval. The real tick body — per-adapter recording against live
``gh``/``git``/``docker``/``claude``, diffing against committed cassettes,
refresh-PR filing via ``open_automated_pr_async``, drift-issue companion
filing, and the 3-attempt per-adapter repair tracker — lands in
Tasks 13–18 of the ``2026-04-22-fake-contract-tests`` plan.

Until then ``_do_work`` is a no-op: it honours the kill-switch
(``enabled_cb(worker_name)``) and returns a bare status dict so the base
class's :meth:`_execute_cycle` reporter has something to publish. Keeping
the ``{"adapters_refreshed": 0, "adapters_drifted": 0}`` shape stable
here avoids churning the status contract later.

Kill-switch: :meth:`LoopDeps.enabled_cb` with
``worker_name="contract_refresh"``.

Spec: ``docs/superpowers/specs/2026-04-22-trust-architecture-hardening-design.md``
§4.2 "ContractRefreshLoop — full caretaker (refresh + auto-repair)".
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING

from base_background_loop import BaseBackgroundLoop, LoopDeps  # noqa: TCH001
from models import WorkCycleResult  # noqa: TCH001

if TYPE_CHECKING:
    from config import HydraFlowConfig
    from pr_manager import PRManager
    from state import StateTracker

logger = logging.getLogger("hydraflow.contract_refresh_loop")


@dataclass(frozen=True)
class AdapterPlan:
    """Per-adapter recording configuration.

    The ``name`` field identifies the adapter (``github``/``git``/``docker``/
    ``claude``); ``cassette_dir_relpath`` points at the committed cassette
    directory relative to the repo root. Tasks 13–18 consume these entries
    to drive per-adapter recording, diffing, and drift escalation.
    """

    name: str  # "github" | "git" | "docker" | "claude"
    cassette_dir_relpath: str  # under repo_root


ADAPTER_PLANS: tuple[AdapterPlan, ...] = (
    AdapterPlan(
        name="github", cassette_dir_relpath="tests/trust/contracts/cassettes/github"
    ),
    AdapterPlan(name="git", cassette_dir_relpath="tests/trust/contracts/cassettes/git"),
    AdapterPlan(
        name="docker", cassette_dir_relpath="tests/trust/contracts/cassettes/docker"
    ),
    AdapterPlan(
        name="claude", cassette_dir_relpath="tests/trust/contracts/claude_streams"
    ),
)


class ContractRefreshLoop(BaseBackgroundLoop):
    """Weekly refresh of fake-contract cassettes with autonomous repair dispatch.

    Skeleton (Phase 2 Task 11). Tick body will, across subsequent tasks:

    1. Re-record cassettes against live ``gh``, ``git``, ``docker``, ``claude``.
    2. Diff against committed cassettes. No diff → no-op.
    3. Open a refresh PR with the new cassettes.
    4. Replay the new cassettes against the scenario fakes.
       - Pass → PR flows through standard auto-merge path.
       - Fail → file ``fake-drift`` companion issue; factory repairs the fake.
    5. On stream-parser errors, file ``stream-protocol-drift``; factory
       repairs ``src/stream_parser.py``.
    6. Per-adapter 3-attempt repair tracker; exhaustion →
       ``hitl-escalation`` + ``fake-repair-stuck`` / ``stream-parser-stuck``.
    """

    def __init__(
        self,
        *,
        config: HydraFlowConfig,
        deps: LoopDeps,
        prs: PRManager,
        state: StateTracker,
    ) -> None:
        super().__init__(
            worker_name="contract_refresh",
            config=config,
            deps=deps,
            run_on_startup=False,
        )
        self._prs = prs
        self._state = state

    def _get_default_interval(self) -> int:
        return self._config.contract_refresh_interval

    async def _do_work(self) -> WorkCycleResult:
        """Tick the loop.

        The skeleton short-circuits with ``{"status": "disabled"}`` when
        the kill-switch is off and otherwise reports a noop with the
        stats shape that Tasks 13+ will populate. Keeping the
        ``adapters_refreshed`` / ``adapters_drifted`` keys stable here
        avoids churning the status contract later.
        """
        if not self._enabled_cb(self._worker_name):
            return {"status": "disabled"}

        # Real refresh / diff / PR / escalation logic lives in Tasks 13–18.
        return {
            "status": "noop",
            "adapters_refreshed": 0,
            "adapters_drifted": 0,
        }
