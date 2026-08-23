"""CI, workflow-run and code-scanning surface of ``FakeGitHub``.

Extracted VERBATIM from ``src/mockworld/fakes/fake_github.py``
(god-class decomposition, Refs #11547) as a mixin. ``FakeGitHub`` inherits it,
so every method here still resolves as an attribute of ``FakeGitHub`` and every
seam that drives the fake through a Port resolves to the same object as before.

The cluster boundary mirrors the real adapter's: this module is the fake's
side of ``pr_manager_ci.PRManagerCIMixin``, so the fake and the thing it doubles read alike.

One concern: everything about a run's *verdict* — PR checks and the scripted
``wait_for_ci`` queue, CI failure logs, main-branch status, the seeded
workflow-run history with its jobs / artifacts / reruns, and the security-alert
reads.
"""

from __future__ import annotations

from collections import deque
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from typing import Any

    from ._common import FakePR


class FakeGitHubCIMixin:
    """CI, workflow-run and code-scanning surface of ``FakeGitHub``."""

    # ------------------------------------------------------------------
    # Collaborator seams — provided by ``FakeGitHub.__init__`` or by
    # a sibling mixin. The method declarations are TYPE_CHECKING-only
    # on purpose: a runtime ``...`` body would win over the
    # real implementation whenever this mixin precedes the
    # implementing one in ``FakeGitHub``'s MRO.
    # ------------------------------------------------------------------
    _alerts: dict[str, list[Any]]
    _arch_refresh_calls: dict[int, int]
    _arch_refresh_outcome: dict[int, bool]
    _ci_failure_logs: dict[int, str]
    _ci_main_status: tuple[str, str]
    _ci_scripts: dict[int, deque[tuple[bool, str]]]
    _prs: dict[int, FakePR]
    _workflow_artifacts: dict[int, int]
    _workflow_jobs: dict[int, list[dict[str, Any]]]
    _workflow_reruns: list[int]
    _workflow_runs: list[dict[str, Any]]

    if TYPE_CHECKING:

        def _maybe_rate_limit(self) -> None: ...  # provided by _seeding

    async def get_pr_checks(self, pr_number: int) -> list[dict[str, str]]:
        """Serve seeded ``FakePR.checks`` (#10260). Defaults to empty — same
        falsy-empty contract as before, so epic detail rendering
        (EpicManager._enrich_pr_status) derives no CI status rather than
        AttributeError-ing when a scenario hasn't seeded checks."""
        self._maybe_rate_limit()
        pr = self._prs.get(pr_number)
        if pr is None:
            return []
        return [{"name": name, "state": state} for name, state in pr.checks]

    async def fetch_code_scanning_alerts(self, branch: str, **_kw: Any) -> list:
        self._maybe_rate_limit()
        return list(self._alerts.get(branch, []))

    async def wait_for_ci(
        self, pr_number: int, *_args: Any, **_kw: Any
    ) -> tuple[bool, str]:
        self._maybe_rate_limit()
        q = self._ci_scripts.get(pr_number)
        if q:
            return q.popleft()
        return (True, "CI passed")

    async def fetch_ci_failure_logs(self, pr_number: int, **_kw: Any) -> str:
        self._maybe_rate_limit()
        return self._ci_failure_logs.get(pr_number, "")

    async def refresh_pr_branch_with_arch_regen(
        self, pr_number: int, branch: str, **_kw: Any
    ) -> bool:
        """Fake of the arch-staleness self-heal.

        Records the call. Returns the scripted outcome (default True). On a
        successful refresh, enqueues a fresh green CI result so the next
        ``wait_for_ci`` tick sees the heal land — mirroring production, where
        the merge+regen+push re-triggers CI which then passes.
        """
        self._maybe_rate_limit()
        self._arch_refresh_calls[pr_number] = (
            self._arch_refresh_calls.get(pr_number, 0) + 1
        )
        succeeds = self._arch_refresh_outcome.get(pr_number, True)
        if succeeds:
            self._ci_scripts.setdefault(pr_number, deque()).append(
                (True, "All checks passed")
            )
        return succeeds

    async def list_workflow_runs(self, limit: int = 50) -> list[dict[str, Any]]:
        """Newest-first slice of the seeded run history (#9974).

        Projects exactly the repo-wide blame-correlation shape — the
        #9814 seed extras stay out so pre-existing consumers see the
        same rows as before.
        """
        self._maybe_rate_limit()
        newest_first = sorted(
            self._workflow_runs, key=lambda r: str(r["created_at"]), reverse=True
        )
        return [
            {
                "id": r["id"],
                "workflow": r["workflow"],
                "conclusion": r["conclusion"],
                "created_at": r["created_at"],
                "pr_number": r["pr_number"],
            }
            for r in newest_first[:limit]
        ]

    async def list_runs_for_workflow(
        self, workflow: str, limit: int = 100
    ) -> list[dict[str, Any]]:
        """Newest-first runs of ONE workflow file in the port shape (#9814).

        Keyed on the seeded ``workflow_file`` (the file name, e.g. ``ci.yml``),
        mirroring the real adapter which passes the file name in the REST path
        ``actions/workflows/{workflow}/runs`` — NOT the display name that
        :meth:`list_workflow_runs` returns (#10899).
        """
        self._maybe_rate_limit()
        matching = sorted(
            (r for r in self._workflow_runs if r["workflow_file"] == workflow),
            key=lambda r: str(r["created_at"]),
            reverse=True,
        )
        return [
            {
                "id": r["id"],
                "url": r["url"],
                "status": r["status"],
                "conclusion": r["conclusion"],
                "created_at": r["created_at"],
                "run_started_at": r["run_started_at"],
                "updated_at": r["updated_at"],
            }
            for r in matching[:limit]
        ]

    async def get_workflow_run_jobs(self, run_id: int) -> list[dict[str, Any]]:
        self._maybe_rate_limit()
        return [dict(j) for j in self._workflow_jobs.get(run_id, [])]

    async def count_workflow_run_artifacts(self, run_id: int) -> int:
        self._maybe_rate_limit()
        return self._workflow_artifacts.get(run_id, 0)

    async def rerun_workflow_failed(self, run_id: int) -> bool:
        """Record a rerun trigger for *run_id* (#10027).

        Mirrors ``PRManager.rerun_workflow_failed``'s always-True success
        path; does not itself mutate the seeded run/job state — scenarios
        that want to simulate a rerun's effect re-seed via
        :meth:`add_workflow_run`.
        """
        self._maybe_rate_limit()
        self._workflow_reruns.append(run_id)
        return True

    async def get_latest_ci_status(self) -> tuple[str, str]:
        """Return (conclusion, url) for latest CI on main branch."""
        self._maybe_rate_limit()
        return self._ci_main_status
