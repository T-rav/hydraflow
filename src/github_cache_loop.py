"""Centralized GitHub data cache — single poller, all consumers read from cache.

Replaces the pattern where every dashboard endpoint and background worker
makes its own ``gh api`` calls.  A single :class:`GitHubCacheLoop` polls
GitHub on a fixed interval and stores results in :class:`GitHubDataCache`.
Dashboard endpoints and background workers read from the cache instantly.

Write operations (create PR, merge, comment, label swap) still call ``gh``
directly — they're low-frequency and need immediate confirmation.
"""

from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

from base_background_loop import BaseBackgroundLoop, LoopDeps
from exception_classify import reraise_on_credit_or_bug

if TYPE_CHECKING:
    from config import HydraFlowConfig
    from issue_fetcher import IssueFetcher
    from models import GitHubIssueSummary, HITLItem, LabelCounts, PRListItem
    from pr_manager import PRManager

logger = logging.getLogger("hydraflow.github_cache")

# Workflow file whose CI-run history the shared cache serves (#9814).
# Single-sourced here so the cache and its consumers (flake_tracker,
# rc_budget) can never drift on which workflow they read.
RC_PROMOTION_WORKFLOW = "rc-promotion-scenario.yml"

# Nightly xdist-isolation audit workflow (#10141). FlakeTrackerLoop reads its
# run list through the same cache so the 4h loop never issues a per-tick raw
# ``gh run list`` (the #9814 principle) — single-sourced like the RC workflow.
XDIST_AUDIT_WORKFLOW = "xdist-audit.yml"

# One snapshot fetch covers every consumer's window: rc_budget previously
# ran ``gh run list --limit 100`` (30-day window), flake_tracker ``--limit
# 20``. Also the REST runs endpoint's per_page cap.
_RC_RUNS_FETCH_LIMIT = 100

# The xdist audit is nightly (≤~30 runs/month); a smaller window suffices.
_XDIST_AUDIT_FETCH_LIMIT = 20

# On refresh failure a stale snapshot is still served while younger than
# this multiple of the caller's bound — the same x3 convention the
# dashboard uses to call the PR snapshots stale (``data_poll_interval *
# 3``). Beyond it, consumers get ``[]`` and skip the tick rather than
# make decisions on ancient run history. Shared by the RC-runs and
# issue-list datasets (#9814).
_STALE_SERVE_MULTIPLIER = 3.0
# Back-compat alias — the RC-runs slice landed under this name.
_RC_RUNS_STALE_SERVE_MULTIPLIER = _STALE_SERVE_MULTIPLIER


@dataclass
class CacheSnapshot:
    """Timestamped cache entry for a single dataset."""

    data: Any = None
    fetched_at: datetime | None = None

    @property
    def age_seconds(self) -> float:
        """Seconds since the data was fetched, or inf if never fetched."""
        if self.fetched_at is None:
            return float("inf")
        return (datetime.now(UTC) - self.fetched_at).total_seconds()


class GitHubDataCache:
    """In-memory + disk-persisted cache for GitHub API read data.

    Each dataset is fetched by :meth:`poll` and stored both in memory
    and on disk (JSON).  Dashboard endpoints and background workers
    read from memory via the ``get_*`` methods — never hitting the API.

    The cache is repo-scoped: each :class:`RepoRuntime` gets its own
    instance with its own disk file.
    """

    def __init__(
        self,
        config: HydraFlowConfig,
        pr_manager: PRManager,
        fetcher: IssueFetcher,
        cache_dir: Path | None = None,
    ) -> None:
        self._config = config
        self._prs = pr_manager
        self._fetcher = fetcher
        self._cache_dir = cache_dir or config.repo_data_root
        self._cache_file = self._cache_dir / "github_cache.json"
        self._poll_lock = asyncio.Lock()

        # In-memory snapshots
        self._open_prs = CacheSnapshot()
        self._all_open_prs = CacheSnapshot()
        self._hitl_items = CacheSnapshot()
        self._label_counts = CacheSnapshot()
        self._collaborators = CacheSnapshot()
        # RC-promotion CI runs (#9814): demand-refreshed, not polled — see
        # get_rc_workflow_runs. Single-flight lock so a thundering herd of
        # loop first-ticks coalesces on one gh call.
        self._rc_workflow_runs = CacheSnapshot()
        self._rc_workflow_runs_lock = asyncio.Lock()
        # xdist-audit CI runs (#10141): same demand-refresh contract as the RC
        # runs, so FlakeTrackerLoop reads them without a per-tick gh call.
        self._xdist_audit_runs = CacheSnapshot()
        self._xdist_audit_runs_lock = asyncio.Lock()
        # Shared issue-list-by-label snapshots (#9814): keyed by
        # ``state:label:limit``, demand-refreshed like the RC runs. One
        # lock for all keys — refreshes are rare (one per key per TTL) and
        # serializing them is itself a gh-load reduction.
        self._issue_lists: dict[str, CacheSnapshot] = {}
        self._issue_lists_lock = asyncio.Lock()

        # Load persisted cache on construction
        self._load_from_disk()

    # --- Read methods (instant, never hit the network) ---

    def get_open_prs(self) -> list[PRListItem]:
        """Return cached open PRs, or empty list if not yet fetched."""
        return self._open_prs.data or []

    def get_all_open_prs(self) -> list[PRListItem]:
        """Return ALL cached open PRs (label-agnostic), or empty if unfetched.

        Distinct from :meth:`get_open_prs`, which is filtered to workflow
        labels. ``DependabotMergeLoop`` reads this so it can see bot PRs that
        carry only GitHub-native labels (e.g. ``dependencies``) and would
        otherwise be excluded from the label-filtered snapshot.
        """
        return self._all_open_prs.data or []

    def get_hitl_items(self) -> list[HITLItem]:
        """Return cached HITL items, or empty list if not yet fetched."""
        return self._hitl_items.data or []

    def get_label_counts(self) -> LabelCounts | None:
        """Return cached label counts, or None if not yet fetched."""
        return self._label_counts.data

    def get_collaborators(self) -> set[str] | None:
        """Return cached collaborator set, or None if not yet fetched."""
        return self._collaborators.data

    def get_cache_age(self, dataset: str) -> float:
        """Return seconds since the given dataset was last fetched."""
        snap = getattr(self, f"_{dataset}", None)
        if isinstance(snap, CacheSnapshot):
            return snap.age_seconds
        return float("inf")

    async def get_rc_workflow_runs(
        self, *, max_age_seconds: float | None = None
    ) -> list[dict[str, Any]]:
        """Return the shared RC-promotion workflow-run snapshot (#9814).

        The read carries an explicit staleness bound (default
        ``data_poll_interval * 3`` — the same multiplier the dashboard
        uses to call the PR snapshots stale):

        - snapshot younger than the bound → served with no gh call;
        - otherwise one refresh via ``PRPort.list_runs_for_workflow``,
          with concurrent callers coalescing on the lock so a restart
          thundering-herd costs one gh call, not one per loop;
        - refresh failure → the stale snapshot is served while younger
          than 3x the bound, else ``[]`` so decision loops skip the tick
          instead of acting on ancient run history.

        Demand-refreshed rather than fetched in :meth:`poll`: the
        consumers (``flake_tracker``, ``rc_budget``) tick every 4h, so
        polling runs every ``data_poll_interval`` would multiply gh load
        ~50x instead of cutting it. This is also why the dashboard's
        cache-health staleness check must NOT include this dataset — a
        4h-cadence snapshot is healthy at ages that convention calls
        stale.

        Rows use the port's shape: ``{"id", "url", "status",
        "conclusion", "created_at", "run_started_at", "updated_at"}``,
        newest first.
        """
        if max_age_seconds is None:
            max_age_seconds = float(self._config.data_poll_interval * 3)
        snap = self._rc_workflow_runs
        if snap.data is not None and snap.age_seconds <= max_age_seconds:
            return list(snap.data)
        async with self._rc_workflow_runs_lock:
            snap = self._rc_workflow_runs
            if snap.data is not None and snap.age_seconds <= max_age_seconds:
                return list(snap.data)
            try:
                runs = await self._prs.list_runs_for_workflow(
                    RC_PROMOTION_WORKFLOW, limit=_RC_RUNS_FETCH_LIMIT
                )
            except Exception as exc:
                reraise_on_credit_or_bug(exc)
                grace = max_age_seconds * _STALE_SERVE_MULTIPLIER
                serve_stale = snap.data is not None and snap.age_seconds <= grace
                logger.warning(
                    "rc_workflow_runs refresh failed (age=%.0fs); %s",
                    snap.age_seconds,
                    "serving stale snapshot" if serve_stale else "returning empty",
                    exc_info=True,
                )
                return list(snap.data) if serve_stale else []
            self._rc_workflow_runs = CacheSnapshot(
                data=runs, fetched_at=datetime.now(UTC)
            )
            self._save_to_disk()
            return list(runs)

    async def get_xdist_audit_runs(
        self, *, max_age_seconds: float | None = None
    ) -> list[dict[str, Any]]:
        """Return the shared xdist-audit workflow-run snapshot (#10141).

        Same demand-refresh contract as :meth:`get_rc_workflow_runs` (staleness
        bound, single-flight lock, stale-serve grace, empty on hard failure) so
        FlakeTrackerLoop's 4h tick never issues a per-tick raw ``gh run list``.
        Rows use the port shape; newest first.
        """
        if max_age_seconds is None:
            max_age_seconds = float(self._config.data_poll_interval * 3)
        snap = self._xdist_audit_runs
        if snap.data is not None and snap.age_seconds <= max_age_seconds:
            return list(snap.data)
        async with self._xdist_audit_runs_lock:
            snap = self._xdist_audit_runs
            if snap.data is not None and snap.age_seconds <= max_age_seconds:
                return list(snap.data)
            try:
                runs = await self._prs.list_runs_for_workflow(
                    XDIST_AUDIT_WORKFLOW, limit=_XDIST_AUDIT_FETCH_LIMIT
                )
            except Exception as exc:
                reraise_on_credit_or_bug(exc)
                grace = max_age_seconds * _STALE_SERVE_MULTIPLIER
                serve_stale = snap.data is not None and snap.age_seconds <= grace
                logger.warning(
                    "xdist_audit_runs refresh failed (age=%.0fs); %s",
                    snap.age_seconds,
                    "serving stale snapshot" if serve_stale else "returning empty",
                    exc_info=True,
                )
                return list(snap.data) if serve_stale else []
            self._xdist_audit_runs = CacheSnapshot(
                data=runs, fetched_at=datetime.now(UTC)
            )
            self._save_to_disk()
            return list(runs)

    async def get_issues_by_label(
        self,
        label: str,
        *,
        state: str = "open",
        limit: int = 100,
        max_age_seconds: float | None = None,
    ) -> list[GitHubIssueSummary]:
        """Return the shared issue-list snapshot for *label* (#9814).

        Serves ``PRPort.list_issues_by_label`` (``state="open"``) or
        ``PRPort.list_closed_issues_by_label`` (``state="closed"``) results
        through the same demand-refreshed, staleness-bounded discipline as
        :meth:`get_rc_workflow_runs`:

        - snapshot younger than the bound → served with no gh call;
        - otherwise one refresh through the port (which honors the gh
          circuit breaker), with concurrent callers coalescing on the lock
          so a restart thundering-herd costs one gh call per key;
        - refresh failure → the stale snapshot is served while younger
          than 3x the bound (with a staleness log line), else ``[]`` so
          consumer loops skip the tick instead of crashing;
        - billing/bug signals always propagate
          (``reraise_on_credit_or_bug``).

        The default bound is the ``github_cache_issue_list_ttl_s`` knob
        (re-read on every call — live-tunable from the System tab). A bound
        of 0 disables caching: every read refreshes, still single-flight
        and degrade-safe. Snapshots are keyed by ``state:label:limit`` and
        disk-persisted for restart recovery.

        Rows keep the port's ``GitHubIssueSummary`` dict shape (``number``,
        ``title``, ``body``, ``updated_at``, plus ``labels`` for open /
        ``closed_at`` for closed).
        """
        if state not in ("open", "closed"):
            msg = f"get_issues_by_label: unsupported state {state!r}"
            raise ValueError(msg)
        if max_age_seconds is None:
            max_age_seconds = float(self._config.github_cache_issue_list_ttl_s)
        key = f"{state}:{label}:{limit}"
        snap = self._issue_lists.get(key, CacheSnapshot())
        if snap.data is not None and snap.age_seconds <= max_age_seconds:
            return list(snap.data)
        async with self._issue_lists_lock:
            snap = self._issue_lists.get(key, CacheSnapshot())
            if snap.data is not None and snap.age_seconds <= max_age_seconds:
                return list(snap.data)
            try:
                if state == "open":
                    rows = await self._prs.list_issues_by_label(label)
                else:
                    rows = await self._prs.list_closed_issues_by_label(
                        label, limit=limit
                    )
            except Exception as exc:
                reraise_on_credit_or_bug(exc)
                grace = max_age_seconds * _STALE_SERVE_MULTIPLIER
                serve_stale = snap.data is not None and snap.age_seconds <= grace
                logger.warning(
                    "issue_lists[%s] refresh failed (age=%.0fs); %s",
                    key,
                    snap.age_seconds,
                    "serving stale snapshot" if serve_stale else "returning empty",
                    exc_info=True,
                )
                return list(snap.data) if serve_stale else []
            self._issue_lists[key] = CacheSnapshot(
                data=list(rows), fetched_at=datetime.now(UTC)
            )
            self._save_to_disk()
            return list(rows)

    # --- Poll (called by GitHubCacheLoop) ---

    async def poll(self) -> dict[str, Any]:
        """Fetch all datasets from GitHub and update the cache.

        Returns a stats dict for background worker status reporting.
        """
        async with self._poll_lock:
            stats: dict[str, Any] = {}
            now = datetime.now(UTC)

            # Open PRs
            try:
                all_labels = list(
                    dict.fromkeys(
                        [
                            *self._config.ready_label,
                            *self._config.review_label,
                            *self._config.hitl_label,
                        ]
                    )
                )
                prs = await self._prs.list_open_prs(all_labels)
                self._open_prs = CacheSnapshot(data=prs, fetched_at=now)
                stats["open_prs"] = len(prs)
            except Exception as exc:
                reraise_on_credit_or_bug(exc)
                logger.warning("Cache poll failed for open_prs", exc_info=True)

            # All open PRs (label-agnostic) — consumed by DependabotMergeLoop,
            # which filters by author. Bot PRs carry only GitHub-native labels
            # (e.g. ``dependencies``) and are absent from the label-filtered
            # ``open_prs`` snapshot above. Without this, dependabot_merge never
            # sees a bot PR and merges nothing (the s09 production bug).
            try:
                all_open = await self._prs.list_all_open_prs()
                self._all_open_prs = CacheSnapshot(data=all_open, fetched_at=now)
                stats["all_open_prs"] = len(all_open)
            except Exception as exc:
                reraise_on_credit_or_bug(exc)
                logger.warning("Cache poll failed for all_open_prs", exc_info=True)

            # HITL items
            try:
                hitl_labels = list(
                    dict.fromkeys(
                        [*self._config.hitl_label, *self._config.hitl_active_label]
                    )
                )
                items = await self._prs.list_hitl_items(hitl_labels)
                self._hitl_items = CacheSnapshot(data=items, fetched_at=now)
                stats["hitl_items"] = len(items)
            except Exception as exc:
                reraise_on_credit_or_bug(exc)
                logger.warning("Cache poll failed for hitl_items", exc_info=True)

            # Label counts
            try:
                counts = await self._prs.get_label_counts(self._config)
                self._label_counts = CacheSnapshot(data=counts, fetched_at=now)
                stats["label_counts"] = True
            except Exception as exc:
                reraise_on_credit_or_bug(exc)
                logger.warning("Cache poll failed for label_counts", exc_info=True)

            # Collaborators
            try:
                collabs = await self._fetcher._get_collaborators()
                self._collaborators = CacheSnapshot(data=collabs, fetched_at=now)
                stats["collaborators"] = len(collabs) if collabs else 0
            except Exception as exc:
                reraise_on_credit_or_bug(exc)
                logger.warning("Cache poll failed for collaborators", exc_info=True)

            self._save_to_disk()
            return stats

    def invalidate(self, dataset: str | None = None) -> None:
        """Clear cache timestamps, forcing refetch on next poll.

        If *dataset* is None, invalidate all datasets.
        """
        if dataset in (None, "issue_lists"):
            self._issue_lists = {}
            if dataset == "issue_lists":
                return
        targets = (
            [f"_{dataset}"]
            if dataset
            else [
                "_open_prs",
                "_all_open_prs",
                "_hitl_items",
                "_label_counts",
                "_collaborators",
                "_rc_workflow_runs",
            ]
        )
        for attr in targets:
            snap = getattr(self, attr, None)
            if isinstance(snap, CacheSnapshot):
                setattr(self, attr, CacheSnapshot())

    # --- Disk persistence ---

    def _save_to_disk(self) -> None:
        """Persist cache to JSON for restart recovery."""
        try:
            self._cache_dir.mkdir(parents=True, exist_ok=True)
            data: dict[str, Any] = {}
            if self._open_prs.data is not None:
                data["open_prs"] = [
                    p.model_dump() if hasattr(p, "model_dump") else p
                    for p in self._open_prs.data
                ]
            if self._all_open_prs.data is not None:
                data["all_open_prs"] = [
                    p.model_dump() if hasattr(p, "model_dump") else p
                    for p in self._all_open_prs.data
                ]
            if self._hitl_items.data is not None:
                data["hitl_items"] = [
                    i.model_dump() if hasattr(i, "model_dump") else i
                    for i in self._hitl_items.data
                ]
            if self._label_counts.data is not None:
                lc = self._label_counts.data
                data["label_counts"] = (
                    lc.model_dump() if hasattr(lc, "model_dump") else lc
                )
            if self._collaborators.data is not None:
                data["collaborators"] = sorted(self._collaborators.data)
            if self._rc_workflow_runs.data is not None:
                data["rc_workflow_runs"] = self._rc_workflow_runs.data
            issue_lists: dict[str, Any] = {
                key: {
                    "rows": snap.data,
                    "fetched_at": (
                        snap.fetched_at.isoformat() if snap.fetched_at else None
                    ),
                }
                for key, snap in self._issue_lists.items()
                if snap.data is not None
            }
            if issue_lists:
                data["issue_lists"] = issue_lists
            data["fetched_at"] = datetime.now(UTC).isoformat()
            self._cache_file.write_text(json.dumps(data, indent=2))
        except Exception:
            logger.debug("Failed to persist github cache", exc_info=True)

    def _load_from_disk(self) -> None:
        """Load persisted cache from disk if available."""
        if not self._cache_file.is_file():
            return
        try:
            raw = json.loads(self._cache_file.read_text())
            fetched_str = raw.get("fetched_at")
            fetched_at = datetime.fromisoformat(fetched_str) if fetched_str else None

            if "open_prs" in raw:
                from models import PRListItem  # noqa: PLC0415

                self._open_prs = CacheSnapshot(
                    data=[
                        PRListItem.model_validate(p) if isinstance(p, dict) else p
                        for p in raw["open_prs"]
                    ],
                    fetched_at=fetched_at,
                )
            if "all_open_prs" in raw:
                from models import PRListItem  # noqa: PLC0415

                self._all_open_prs = CacheSnapshot(
                    data=[
                        PRListItem.model_validate(p) if isinstance(p, dict) else p
                        for p in raw["all_open_prs"]
                    ],
                    fetched_at=fetched_at,
                )
            if "hitl_items" in raw:
                self._hitl_items = CacheSnapshot(
                    data=raw["hitl_items"], fetched_at=fetched_at
                )
            if "label_counts" in raw:
                self._label_counts = CacheSnapshot(
                    data=raw["label_counts"], fetched_at=fetched_at
                )
            if "collaborators" in raw:
                self._collaborators = CacheSnapshot(
                    data=set(raw["collaborators"]), fetched_at=fetched_at
                )
            if "rc_workflow_runs" in raw:
                self._rc_workflow_runs = CacheSnapshot(
                    data=[r for r in raw["rc_workflow_runs"] if isinstance(r, dict)],
                    fetched_at=fetched_at,
                )
            if isinstance(raw.get("issue_lists"), dict):
                for key, entry in raw["issue_lists"].items():
                    if not isinstance(entry, dict):
                        continue
                    rows = entry.get("rows")
                    if not isinstance(rows, list):
                        continue
                    entry_ts = entry.get("fetched_at")
                    self._issue_lists[key] = CacheSnapshot(
                        data=[r for r in rows if isinstance(r, dict)],
                        fetched_at=(
                            datetime.fromisoformat(entry_ts) if entry_ts else None
                        ),
                    )
            logger.info("Loaded github cache from disk (%s)", self._cache_file)
        except Exception:
            logger.debug("Failed to load github cache from disk", exc_info=True)


class GitHubCacheLoop(BaseBackgroundLoop):
    """Background loop that polls GitHub and updates the data cache."""

    def __init__(
        self,
        config: HydraFlowConfig,
        cache: GitHubDataCache,
        *,
        deps: LoopDeps,
    ) -> None:
        super().__init__(
            worker_name="github_cache",
            config=config,
            deps=deps,
            run_on_startup=True,
        )
        self._cache = cache

    async def _do_work(self) -> dict[str, Any] | None:
        if not self._enabled_cb(self._worker_name):
            return {"status": "disabled"}
        if not self._config.github_cache_loop_enabled:
            return {"status": "config_disabled"}
        stats = await self._cache.poll()
        logger.info(
            "GitHub cache refreshed: %s",
            ", ".join(f"{k}={v}" for k, v in stats.items()),
        )
        return stats or None

    def _get_default_interval(self) -> int:
        return self._config.data_poll_interval
