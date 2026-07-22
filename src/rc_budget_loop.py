"""RCBudgetLoop — 4h RC CI wall-clock regression detector (spec §4.8).

Reads the last 30 days of ``rc-promotion-scenario.yml`` runs from the
shared ``GitHubDataCache`` run snapshot (#9814 — one staleness-bounded
gh fetch serves every consumer), extracts per-run wall-clock duration,
and emits a
``hydraflow-find`` + ``rc-duration-regression`` issue when the newest
run trips either:

- *Gradual bloat*: ``current_s >= rc_budget_threshold_ratio *
  rolling_median`` (default ratio ``1.5``).
- *Sudden spike*: ``current_s >= rc_budget_spike_ratio * max(recent-5,
  excluding current)`` (default ratio ``2.0``).

Signals are independent; both may fire on the same tick (two distinct
dedup keys). After 3 unresolved attempts per signal the loop files a
``hitl-escalation`` + ``rc-duration-stuck`` issue. Dedup keys clear on
escalation-close per spec §3.2.

Kill-switch: ``LoopDeps.enabled_cb("rc_budget")`` — **no
``rc_budget_enabled`` config field** (spec §12.2).
"""

from __future__ import annotations

import logging
import re
import statistics
import tempfile
import time
import xml.etree.ElementTree as ET
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING, Any

from base_background_loop import BaseBackgroundLoop, LoopDeps  # noqa: TCH001
from escalation_reconcile import EscalationReconciler, is_bot_close
from exception_classify import reraise_on_credit_or_bug
from models import WorkCycleResult  # noqa: TCH001
from subprocess_util import SubprocessTimeoutError, run_subprocess_result

if TYPE_CHECKING:
    from config import HydraFlowConfig
    from dedup_store import DedupStore
    from github_cache_loop import GitHubDataCache
    from pr_manager import PRManager
    from state import StateTracker

logger = logging.getLogger("hydraflow.rc_budget_loop")

_MAX_ATTEMPTS = 3
_WINDOW_DAYS = 30
_HISTORY_CAP = 60
_RECENT_N = 5
_MIN_HISTORY = 5
# The workflow itself is single-sourced as
# ``github_cache_loop.RC_PROMOTION_WORKFLOW`` (#9814): this loop reads the
# shared run snapshot, it no longer names the workflow in a gh command.

# Marker label on the HITL escalation issue (paired with ``hitl-escalation``).
# Single-sourced so the filing path (`_file_escalation`) and the reconciler
# can never drift apart.
_STUCK_LABEL = "rc-duration-stuck"

# Parses ``_file_escalation`` titles back to the dedup-key subject
# (``median``/``spike``). Returns ``None`` for titles that aren't ours so the
# shared ``EscalationReconciler`` skips operator-created issues untouched.
_ESCALATION_TITLE_RE = re.compile(
    r"^HITL: RC gate duration regression \((median|spike)\) unresolved after "
)


def _escalation_subject(title: str) -> str | None:
    m = _ESCALATION_TITLE_RE.match(title)
    return m.group(1) if m else None


# Parses ``_file_regression_issue`` titles back to the dedup-key subject
# (``median``/``spike``), mirroring ``_ESCALATION_TITLE_RE`` one tier down.
_REGRESSION_TITLE_RE = re.compile(
    r"^RC gate duration regression: \d+s vs \d+s \((median|spike)\)$"
)


def _regression_subject(title: str) -> str | None:
    m = _REGRESSION_TITLE_RE.match(title)
    return m.group(1) if m else None


# Hard cap on each ``gh`` read/download. A wedged child must not hang the loop
# cycle forever and freeze its heartbeat — the #9410 silent-stall failure
# class (#9454 / #9508). Bounded (and, via ``run_subprocess_result``,
# circuit-breaker/rate-limit/process-group hardened — #9554/#10028) rather
# than a raw ``create_subprocess_exec``.
_GH_TIMEOUT_SECONDS = 120


def _parse_iso(value: str | None) -> datetime | None:
    """Parse an ISO-8601 timestamp (allowing trailing ``Z``); return None on err."""
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


class RCBudgetLoop(BaseBackgroundLoop):
    """Detects RC wall-clock bloat via median + spike signals (spec §4.8)."""

    def __init__(
        self,
        *,
        config: HydraFlowConfig,
        state: StateTracker,
        pr_manager: PRManager,
        dedup: DedupStore,
        deps: LoopDeps,
        github_cache: GitHubDataCache,
    ) -> None:
        super().__init__(
            worker_name="rc_budget",
            config=config,
            deps=deps,
            run_on_startup=False,
        )
        self._state = state
        self._pr = pr_manager
        self._dedup = dedup
        self._github_cache = github_cache
        self._escalations = EscalationReconciler(
            prs=pr_manager,
            dedup=dedup,
            key_prefix="rc_budget",
            stuck_label=_STUCK_LABEL,
            clear_attempts=state.clear_rc_budget_attempts,
            subject_from_title=_escalation_subject,
        )

    def _get_default_interval(self) -> int:
        return self._config.rc_budget_interval

    async def _do_work(self) -> WorkCycleResult:
        """Run one tick: reconcile closures, fetch runs, detect, file/escalate."""
        if not self._enabled_cb(self._worker_name):
            return {"status": "disabled"}
        if not self._config.rc_budget_loop_enabled:
            return {"status": "config_disabled"}

        t0 = time.perf_counter()
        await self._reconcile_closed_escalations()
        runs = await self._fetch_recent_runs()
        if len(runs) < _MIN_HISTORY:
            return {"status": "warmup", "runs_seen": len(runs)}

        self._state.set_rc_budget_duration_history(
            [
                {
                    "run_id": int(r.get("databaseId", 0)),
                    "created_at": str(r.get("createdAt", "")),
                    "duration_s": int(r["duration_s"]),
                    "conclusion": str(r.get("conclusion", "")),
                }
                for r in runs
            ]
        )

        current, baselines = self._compute_baselines(runs)
        signals = self._check_signals(current, baselines)

        filed = 0
        escalated = 0
        dedup = set(self._dedup.get())
        previous_5 = [r for r in runs if r is not current][:5]
        jobs: list[dict[str, Any]] = []
        junit_tests: list[tuple[str, float]] = []
        if signals:
            jobs = await self._fetch_job_breakdown(current)
            junit_tests = await self._fetch_junit_tests(current)

        for kind, baseline_s in signals:
            key = f"rc_budget:{kind}"
            if key in dedup:
                continue
            attempts = self._state.inc_rc_budget_attempts(kind)
            if attempts >= _MAX_ATTEMPTS:
                await self._file_escalation(kind, attempts)
                escalated += 1
            else:
                await self._file_regression_issue(
                    kind=kind,
                    current=current,
                    baseline_s=baseline_s,
                    baselines=baselines,
                    previous_5=previous_5,
                    jobs=jobs,
                    junit_tests=junit_tests,
                )
                filed += 1
            dedup.add(key)
            self._dedup.set_all(dedup)

        self._emit_trace(t0, runs_seen=len(runs), signals=len(signals))
        return {
            "status": "ok",
            "runs_seen": len(runs),
            "filed": filed,
            "escalated": escalated,
            "current_duration_s": int(current["duration_s"]),
            "rolling_median_s": baselines["rolling_median"],
            "recent_max_s": baselines["recent_max"],
        }

    async def _fetch_recent_runs(self) -> list[dict[str, Any]]:
        """Fetch last 30 days of completed RC runs with per-run wall-clock.

        Served from the shared ``GitHubDataCache`` snapshot (#9814)
        instead of a per-tick raw ``gh run list`` subprocess. The old
        ``--status completed`` filter becomes a client-side ``status``
        check on the shared (status-agnostic) snapshot; rows keep the
        legacy gh-CLI key shape the baselines/issue bodies were built on.
        """
        rows = await self._github_cache.get_rc_workflow_runs()
        cutoff = datetime.now(UTC) - timedelta(days=_WINDOW_DAYS)
        out: list[dict[str, Any]] = []
        for row in rows:
            if str(row.get("status", "")) != "completed":
                continue
            # A run GH-Actions-cancelled at its own job timeout has no real
            # wall-clock signal to offer: its duration is an artifact of
            # when the kill landed, not of the gate actually running slow.
            # Counting it (as either the "current" subject or as baseline
            # history) is exactly the false positive that produced #10215's
            # "2729s vs 7s" report for a run that had in fact hung, not
            # regressed.
            if str(row.get("conclusion", "")).lower() == "cancelled":
                continue
            created = _parse_iso(row.get("created_at"))
            started = _parse_iso(row.get("run_started_at") or row.get("created_at"))
            updated = _parse_iso(row.get("updated_at"))
            if not created or not started or not updated or created < cutoff:
                continue
            out.append(
                {
                    "databaseId": row.get("id"),
                    "url": row.get("url", ""),
                    "conclusion": row.get("conclusion", ""),
                    "createdAt": row.get("created_at", ""),
                    "duration_s": max(0, int((updated - started).total_seconds())),
                }
            )
        out.sort(key=lambda r: r.get("createdAt", ""), reverse=True)
        return out[:_HISTORY_CAP]

    def _compute_baselines(
        self, runs: list[dict[str, Any]]
    ) -> tuple[dict[str, Any], dict[str, int]]:
        """Return ``(current, {rolling_median, recent_max})`` excluding current."""
        current = max(runs, key=lambda r: r.get("createdAt", ""))
        others = [r for r in runs if r.get("databaseId") != current.get("databaseId")]
        others.sort(key=lambda r: r.get("createdAt", ""), reverse=True)
        durations = [int(r["duration_s"]) for r in others]
        recent = durations[:_RECENT_N]
        return current, {
            "rolling_median": (int(statistics.median(durations)) if durations else 0),
            "recent_max": max(recent) if recent else 0,
        }

    def _check_signals(
        self, current: dict[str, Any], baselines: dict[str, int]
    ) -> list[tuple[str, int]]:
        """Return ``[(kind, baseline_s), ...]`` where kind in {median, spike}.

        Spec §4.8 + sibling plan: ``>=`` comparison.
        """
        cfg = self._config
        cur = int(current["duration_s"])
        hits: list[tuple[str, int]] = []
        m, r = baselines["rolling_median"], baselines["recent_max"]
        if m > 0 and cur >= cfg.rc_budget_threshold_ratio * m:
            hits.append(("median", m))
        if r > 0 and cur >= cfg.rc_budget_spike_ratio * r:
            hits.append(("spike", r))
        return hits

    async def _fetch_job_breakdown(self, run: dict[str, Any]) -> list[dict[str, Any]]:
        """Return up to 10 slowest jobs for *run* via the PRPort (#9814).

        ``PRPort.get_workflow_run_jobs`` replaced the raw ``gh run view``
        subprocess; failures stay fail-soft (empty breakdown, the issue
        body says "unavailable") but billing signals propagate.
        """
        try:
            run_id = int(run.get("databaseId") or 0)
        except (TypeError, ValueError):
            return []
        if not run_id:
            return []
        try:
            jobs = await self._pr.get_workflow_run_jobs(run_id)
        except Exception as exc:
            reraise_on_credit_or_bug(exc)
            logger.warning(
                "rc_budget: job breakdown unavailable for run %s",
                run_id,
                exc_info=True,
            )
            return []
        out: list[dict[str, Any]] = []
        for job in jobs:
            s = _parse_iso(job.get("started_at"))
            c = _parse_iso(job.get("completed_at"))
            if not s or not c:
                continue
            out.append(
                {
                    "name": job.get("name", "?"),
                    "duration_s": max(0, int((c - s).total_seconds())),
                }
            )
        out.sort(key=lambda j: j["duration_s"], reverse=True)
        return out[:10]

    async def _fetch_junit_tests(self, run: dict[str, Any]) -> list[tuple[str, float]]:
        """Return top-10 slowest tests from the ``junit-scenario`` artifact."""
        run_id = str(run.get("databaseId", ""))
        if not run_id:
            return []
        with tempfile.TemporaryDirectory() as td:
            cmd = [
                "gh",
                "run",
                "download",
                run_id,
                "--repo",
                self._config.repo,
                "--name",
                "junit-scenario",
                "--dir",
                td,
            ]
            try:
                result = await run_subprocess_result(*cmd, timeout=_GH_TIMEOUT_SECONDS)
            except SubprocessTimeoutError:
                return []
            if result.returncode != 0:
                return []
            results: list[tuple[str, float]] = []
            for xml_path in Path(td).rglob("*.xml"):
                try:
                    root = ET.fromstring(  # nosec B314  # JUnit XML from trusted CI artifacts
                        xml_path.read_bytes()
                    )
                except ET.ParseError:
                    continue
                for case in root.iter("testcase"):
                    cls = case.get("classname") or ""
                    name = case.get("name") or ""
                    test_id = f"{cls}.{name}".lstrip(".")
                    try:
                        dur = float(case.get("time") or 0.0)
                    except ValueError:
                        dur = 0.0
                    results.append((test_id, dur))
        results.sort(key=lambda t: t[1], reverse=True)
        return results[:10]

    async def _file_regression_issue(
        self,
        *,
        kind: str,
        current: dict[str, Any],
        baseline_s: int,
        baselines: dict[str, int],
        previous_5: list[dict[str, Any]],
        jobs: list[dict[str, Any]],
        junit_tests: list[tuple[str, float]],
    ) -> int:
        """File a ``hydraflow-find`` + ``rc-duration-regression`` issue."""
        cfg = self._config
        cur = int(current["duration_s"])
        title = (
            f"RC gate duration regression: {cur}s vs {baseline_s}s "
            f"({'spike' if kind == 'spike' else 'median'})"
        )
        job_lines = (
            "\n".join(f"- `{j['name']}` — {j['duration_s']}s" for j in jobs)
            or "_(job breakdown unavailable)_"
        )
        test_lines = (
            "\n".join(f"- `{t}` — {d:.2f}s" for t, d in junit_tests)
            or "_(junit-scenario artifact absent — top-10 tests elided)_"
        )
        prev_lines = "\n".join(
            f"- run {r.get('databaseId', '?')} "
            f"({r.get('createdAt', '?')}) — {int(r['duration_s'])}s"
            for r in previous_5
        )
        body = (
            f"## RC wall-clock regression (signal: `{kind}`)\n\n"
            f"Run [{current.get('databaseId', '?')}]({current.get('url', '')}) "
            f"took **{cur}s**. Trips `{kind}`:\n\n"
            f"- Current: **{cur}s**\n"
            f"- Rolling 30d median: **{baselines['rolling_median']}s** "
            f"(threshold_ratio `{cfg.rc_budget_threshold_ratio}` → fires at "
            f"`{int(cfg.rc_budget_threshold_ratio * baselines['rolling_median'])}s`)\n"
            f"- Max of recent 5 (excl. current): **{baselines['recent_max']}s** "
            f"(spike_ratio `{cfg.rc_budget_spike_ratio}` → fires at "
            f"`{int(cfg.rc_budget_spike_ratio * baselines['recent_max'])}s`)\n\n"
            f"### Previous 5 runs\n{prev_lines}\n\n"
            f"### Per-job breakdown (top 10)\n{job_lines}\n\n"
            f"### Top-10 slowest tests\n{test_lines}\n\n"
            f"_Auto-filed by HydraFlow `rc_budget` (spec §4.8). "
            f"Escalates after 3 unresolved attempts._"
        )
        return await self._pr.create_issue(
            title, body, ["hydraflow-find", "rc-duration-regression"]
        )

    async def _file_escalation(self, kind: str, attempts: int) -> int:
        """File a ``hitl-escalation`` + ``rc-duration-stuck`` issue."""
        title = (
            f"HITL: RC gate duration regression ({kind}) unresolved after "
            f"{attempts} attempts"
        )
        body = (
            f"`rc_budget` filed `rc-duration-regression` for `{kind}` "
            f"{attempts} times without closure. Close this to clear the "
            f"`rc_budget:{kind}` dedup key (spec §3.2)."
        )
        return await self._pr.create_issue(
            title, body, ["hitl-escalation", "rc-duration-stuck"]
        )

    async def _reconcile_closed_regressions(self) -> None:
        """Clear dedup keys (NOT attempt counters) for closed first-tier
        ``rc-duration-regression`` issues.

        Without this, the dedup key set on the first fire never clears
        (nothing else ever touches an ``rc_budget:*`` key besides the
        ``rc-duration-stuck`` escalation reconciler), which permanently
        blocks the ``if key in dedup: continue`` guard in ``_do_work`` —
        freezing ``attempts`` at 1 forever and making the "escalates after
        3 unresolved attempts" promise structurally unreachable (#10215).
        """
        closed = await self._pr.list_closed_issues_by_label(
            "rc-duration-regression", limit=100
        )
        keys = self._dedup.get()
        keep = set(keys)
        for issue in closed:
            subject = _regression_subject(issue.get("title", ""))
            if subject is None:
                continue
            key = f"rc_budget:{subject}"
            if key not in keep:
                continue
            if is_bot_close(issue):
                # Programmatic close — the subject is still detected at
                # HEAD; clearing here would refile a duplicate next tick
                # (#9437, mirrored from EscalationReconciler).
                continue
            keep.discard(key)
        if keep != keys:
            self._dedup.set_all(keep)

    async def _reconcile_closed_escalations(self) -> None:
        """Clear dedup state for closed HITL escalations + regression issues.

        Two tiers, both keyed ``rc_budget:{median,spike}``:

        - Terminal ``rc-duration-stuck`` escalations: delegates to the
          shared :class:`EscalationReconciler` (PRPort-based; replaced the
          raw ``gh issue list`` subprocess — #9932); clears dedup key AND
          resets the attempts counter (§3.2). Subjects are parsed from the
          escalation-title shape ``"HITL: RC gate duration regression
          (<kind>) unresolved after N …"``.
        - First-tier ``rc-duration-regression`` issues: see
          :meth:`_reconcile_closed_regressions` — clears the dedup key
          only, leaving attempts to keep climbing toward escalation
          (#10215).
        """
        await self._escalations.reconcile_closed()
        await self._reconcile_closed_regressions()

    def _emit_trace(self, t0: float, *, runs_seen: int, signals: int) -> None:
        """Best-effort subprocess trace via lazy-imported ``trace_collector``."""
        try:
            from trace_collector import emit_loop_subprocess_trace  # noqa: PLC0415
        except ImportError:
            return
        duration_ms = int((time.perf_counter() - t0) * 1000)
        emit_loop_subprocess_trace(
            loop=self._worker_name,
            command=["github_cache", "rc_workflow_runs"],
            exit_code=0,
            duration_ms=duration_ms,
            stderr_excerpt=f"runs_seen={runs_seen} signals={signals}",
        )
