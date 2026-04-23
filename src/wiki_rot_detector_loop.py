"""WikiRotDetectorLoop — weekly wiki cite freshness detector (spec §4.9).

Walks every ``RepoWikiStore``-registered repo, extracts cited code
references from each wiki entry via three patterns (``path.py:symbol``,
dotted ``src.module.Class``, and bare identifiers inside ``python``
fences — hints only), and verifies each hard cite against:

- **HydraFlow-self** (``config.repo_root``) via AST introspection —
  catches re-exports and ``__init__.py`` re-bindings that grep misses.
- **Managed repos** via grep over wiki markdown mirrors only — full
  AST verification across every managed repo is out of scope for v1
  and noted below as a follow-up.

For each broken cite the loop files a ``hydraflow-find`` + ``wiki-rot``
issue through :class:`PRManager` with a fuzzy-match suggestion (via
:func:`difflib.get_close_matches`) when the containing module exists.
After 3 unresolved attempts per ``(slug, cite)`` subject the loop
escalates to ``hitl-escalation`` + ``wiki-rot-stuck``. Dedup keys and
attempt counters clear on escalation close per spec §3.2.

Kill-switch: :meth:`LoopDeps.enabled_cb` with ``worker_name="wiki_rot_detector"``
— **no ``wiki_rot_detector_enabled`` config field** (spec §12.2).
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from base_background_loop import BaseBackgroundLoop, LoopDeps
from models import WorkCycleResult

if TYPE_CHECKING:
    from config import HydraFlowConfig
    from dedup_store import DedupStore
    from pr_manager import PRManager
    from repo_wiki import RepoWikiStore
    from state import StateTracker

logger = logging.getLogger("hydraflow.wiki_rot_detector_loop")

_MAX_ATTEMPTS = 3
_EXCERPT_CHARS = 500
_ISSUE_LABELS_FIND: tuple[str, ...] = ("hydraflow-find", "wiki-rot")
_ISSUE_LABELS_ESCALATE: tuple[str, ...] = ("hitl-escalation", "wiki-rot-stuck")


class WikiRotDetectorLoop(BaseBackgroundLoop):
    """Detects broken code cites in per-repo wikis (spec §4.9)."""

    def __init__(
        self,
        *,
        config: HydraFlowConfig,
        state: StateTracker,
        pr_manager: PRManager,
        dedup: DedupStore,
        wiki_store: RepoWikiStore,
        deps: LoopDeps,
    ) -> None:
        super().__init__(
            worker_name="wiki_rot_detector",
            config=config,
            deps=deps,
            run_on_startup=False,
        )
        self._state = state
        self._pr = pr_manager
        self._dedup = dedup
        self._wiki = wiki_store

    def _get_default_interval(self) -> int:
        return self._config.wiki_rot_detector_interval

    # -- main tick ---------------------------------------------------------

    async def _do_work(self) -> WorkCycleResult:
        """Scan every repo wiki, file an issue per broken cite, escalate
        repeat offenders.  Guarded by the kill-switch at the top so a
        mid-tick flip takes effect on the next cycle.
        """
        if not self._enabled_cb(self._worker_name):
            return {"status": "disabled"}

        await self._reconcile_closed_escalations()

        self_slug = self._config.repo or ""
        repos = list(self._wiki.list_repos())
        if repos and self_slug and self_slug not in repos:
            # Ensure we always scan HydraFlow-self when the wiki has at
            # least one seeded repo (cite extraction yields 0 otherwise).
            repos.insert(0, self_slug)

        scanned = 0
        filed = 0
        escalated = 0
        for slug in repos:
            try:
                result = await self._tick_repo(slug, self_slug)
            except Exception:  # noqa: BLE001
                logger.exception("wiki_rot_detector: slug=%s failed", slug)
                continue
            scanned += 1
            filed += result["filed"]
            escalated += result["escalated"]

        status = "fired" if filed or escalated else "noop"
        return {
            "status": status,
            "repos_scanned": scanned,
            "issues_filed": filed,
            "escalations": escalated,
        }

    async def _tick_repo(
        self,
        slug: str,
        self_slug: str,
    ) -> dict[str, int]:
        """Task 5."""
        return {"filed": 0, "escalated": 0}

    async def _reconcile_closed_escalations(self) -> None:
        """Task 6."""
        return None
