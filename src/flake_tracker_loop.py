"""FlakeTrackerLoop — 4h detector for persistently flaky tests.

Spec: `docs/superpowers/specs/2026-04-22-trust-architecture-hardening-design.md`
§4.5. Reads JUnit XML from the last 20 RC runs (uploaded by
`rc-promotion-scenario.yml`), counts mixed pass/fail occurrences per
test, and files a `hydraflow-find` + `flaky-test` issue when a test's
flake count crosses `flake_threshold` (default 3, comparison `>=`).

After 3 repair attempts for the same test_name the loop files a
second issue labeled `hitl-escalation` + `flaky-test-stuck`. The
dedup key clears when the escalation issue is closed (spec §3.2),
and stale open escalations — the test is no longer flaky at HEAD —
auto-close via the shared `EscalationReconciler` (#9618 class).
"""

from __future__ import annotations

import json
import logging
import re
import tempfile
import time
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import TYPE_CHECKING, Any

from base_background_loop import BaseBackgroundLoop, LoopDeps
from escalation_reconcile import EscalationReconciler
from models import WorkCycleResult
from subprocess_util import SubprocessTimeoutError, run_subprocess_result

if TYPE_CHECKING:
    from config import HydraFlowConfig
    from dedup_store import DedupStore
    from github_cache_loop import GitHubDataCache
    from pr_manager import PRManager
    from state import StateTracker

logger = logging.getLogger("hydraflow.flake_tracker_loop")

_MAX_ATTEMPTS = 3
_RUN_WINDOW = 20

# xdist-quarantine detection (#10141): read the nightly xdist-audit report
# (produced by .github/workflows/xdist-audit.yml → scripts/xdist_audit.py) and
# file a consent-package quarantine issue for a test consistently flagged
# fail-parallel/pass-serial across the window. The workflow name is
# single-sourced in github_cache_loop.XDIST_AUDIT_WORKFLOW (the cache lists it).
_XDIST_AUDIT_ARTIFACT = "xdist-audit"
_XDIST_AUDIT_REPORT = "xdist-audit.json"


def _quarantine_path_hint(test_id: str) -> str:
    """Best-effort test FILE path from a ``{classname}.{name}`` JUnit id.

    pytest's ``classname`` is the dotted module path, optionally suffixed with
    the class (``tests.scenarios.test_foo.TestBar``). Drop the test name and any
    trailing ``Capitalized`` class components to recover the module, then map
    dots to a ``.py`` path. Only a HINT for the consent package — a human
    confirms the exact ``PYTEST_SERIAL_PATHS`` entry.
    """
    classname = test_id.rsplit(".", 1)[0] if "." in test_id else test_id
    parts = classname.split(".")
    while parts and parts[-1][:1].isupper():
        parts.pop()
    return "/".join(parts) + ".py" if parts else ""


# Marker label on the HITL escalation issue. Single-sourced so the filing
# path (`_file_escalation`) and the reconciler can never drift apart — no
# config knob exists for this label (unlike e.g. fake_coverage_stuck_label).
_STUCK_LABEL = "flaky-test-stuck"

# Parses ``_file_escalation`` titles back to the ``test_id`` subject.
# ``(.+?)`` not ``(\\S+)``: parametrized test_ids can contain spaces
# (pytest emits them verbatim in JUnit names); a whitespace-bounded
# capture fails to match those titles AT ALL, leaving the escalation
# permanently unreconcilable (neither open- nor closed-path clears it).
_ESCALATION_TITLE_RE = re.compile(r"^HITL: flaky test (.+?) unresolved after ")


def _escalation_subject(title: str) -> str | None:
    m = _ESCALATION_TITLE_RE.match(title)
    return m.group(1) if m else None


# Hard cap on each ``gh`` read/download. A wedged child must not hang the loop
# cycle forever and freeze its heartbeat — the #9410 silent-stall failure
# class (#9454 / #9508). Bounded (and, via ``run_subprocess_result``,
# circuit-breaker/rate-limit/process-group hardened — #9554/#10028) rather
# than a raw ``create_subprocess_exec``.
_GH_TIMEOUT_SECONDS = 120


def parse_junit_xml(xml_bytes: bytes) -> dict[str, str]:
    """Return ``{test_id: "pass"|"fail"}`` per test case in a JUnit XML doc.

    ``test_id`` is ``{classname}.{name}``. A testcase is ``fail`` if it
    has any ``<failure>`` or ``<error>`` child element; ``skip`` is
    treated as ``pass`` (skipped tests are not flakes).
    """
    results: dict[str, str] = {}
    root = ET.fromstring(xml_bytes)  # nosec B314  # JUnit XML from trusted CI artifacts
    for case in root.iter("testcase"):
        cls = case.get("classname") or ""
        name = case.get("name") or ""
        test_id = f"{cls}.{name}".lstrip(".")
        failed = any(c.tag in ("failure", "error") for c in case)
        results[test_id] = "fail" if failed else "pass"
    return results


class FlakeTrackerLoop(BaseBackgroundLoop):
    """Detects persistently flaky tests in the RC window (spec §4.5)."""

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
            worker_name="flake_tracker",
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
            key_prefix="flake_tracker",
            stuck_label=_STUCK_LABEL,
            clear_attempts=state.clear_flake_attempts,
            subject_from_title=_escalation_subject,
        )

    def _get_default_interval(self) -> int:
        return self._config.flake_tracker_interval

    async def _fetch_recent_runs(self) -> list[dict[str, Any]]:
        """Return metadata for the last 20 RC promotion workflow runs.

        Served from the shared ``GitHubDataCache`` snapshot (#9814)
        instead of a per-tick raw ``gh run list`` subprocess, so N loops
        cost one gh call per freshness window and a gh outage degrades to
        the stale-snapshot path inside the cache (never a loop crash).
        Rows keep the legacy gh-CLI key shape the downstream helpers and
        issue bodies were built on.
        """
        rows = await self._github_cache.get_rc_workflow_runs()
        return [
            {
                "databaseId": row.get("id"),
                "url": row.get("url", ""),
                "conclusion": row.get("conclusion", ""),
                "createdAt": row.get("created_at", ""),
            }
            for row in rows[:_RUN_WINDOW]
        ]

    async def _download_junit(self, run: dict[str, Any]) -> dict[str, str]:
        """Download the ``junit-scenario`` artifact for a run; return per-test results."""
        run_id = str(run.get("databaseId", ""))
        if not run_id:
            return {}
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
                logger.info(
                    "gh run download timed out after %ss for run %s",
                    _GH_TIMEOUT_SECONDS,
                    run_id,
                )
                return {}
            if result.returncode != 0:
                logger.info(
                    "no junit-scenario artifact for run %s: %s",
                    run_id,
                    result.stderr[:200],
                )
                return {}
            combined: dict[str, str] = {}
            for xml_path in Path(td).rglob("*.xml"):
                try:
                    combined.update(parse_junit_xml(xml_path.read_bytes()))
                except ET.ParseError:
                    logger.debug("junit parse failed: %s", xml_path)
                    continue
            return combined

    def _tally_flakes(self, runs: list[dict[str, str]]) -> dict[str, int]:
        """Count fails per test, restricted to tests with a mixed
        pass/fail record across the window (spec §4.5 step 2).

        A test that fails in every run is *broken*, not flaky; the spec
        says only mixed-record tests count toward the flake threshold.
        Returns ``{test_id: fail_count}`` for every test that failed at
        least once AND passed at least once in the window.
        """
        fail_counts: dict[str, int] = {}
        pass_counts: dict[str, int] = {}
        for run in runs:
            for test_id, result in run.items():
                if result == "fail":
                    fail_counts[test_id] = fail_counts.get(test_id, 0) + 1
                elif result == "pass":
                    pass_counts[test_id] = pass_counts.get(test_id, 0) + 1
        # Restrict to mixed pass/fail: failure counter only kept when the
        # same test also passed at least once in the window.
        return {
            test_id: count
            for test_id, count in fail_counts.items()
            if pass_counts.get(test_id, 0) >= 1
        }

    @staticmethod
    def _flake_title(test_id: str) -> str:
        """Stable flake-issue title — single source for the file + close paths.

        The flake *rate* lives in the body (it varies tick-to-tick); keeping it
        out of the title lets the recovery path find-and-close the issue by exact
        title and avoids the per-rate title-drift class behind #9351/#9359.
        """
        return f"Flaky test: {test_id}"

    async def _file_flake_issue(
        self, test_id: str, flake_count: int, runs: list[dict[str, Any]]
    ) -> int:
        """File a ``hydraflow-find`` + ``flaky-test`` issue. Returns issue number."""
        title = self._flake_title(test_id)
        run_lines = "\n".join(
            f"- {r.get('url', '?')} ({r.get('createdAt', '?')})" for r in runs[:10]
        )
        body = (
            f"## Flake signal\n\n"
            f"Test `{test_id}` failed in {flake_count} of the last {_RUN_WINDOW} "
            f"RC promotion runs. This loop (`flake_tracker`, spec §4.5) filed "
            f"the issue so the standard implementer/reviewer pipeline can fix "
            f"the race, add a deterministic wait, or quarantine the test.\n\n"
            f"### Recent runs (up to 10)\n{run_lines}\n\n"
            f"_This issue was auto-filed by HydraFlow's `flake_tracker` loop._"
        )
        return await self._pr.create_issue(
            title, body, ["hydraflow-find", "flaky-test"]
        )

    async def _file_escalation(self, test_id: str, attempts: int) -> int:
        """File ``hitl-escalation`` + ``flaky-test-stuck`` after N failed repairs."""
        title = f"HITL: flaky test {test_id} unresolved after {attempts} attempts"
        body = (
            f"`flake_tracker` has filed `flaky-test` issues for `{test_id}` "
            f"{attempts} times without closure. Human review needed.\n\n"
            f"_Spec §3.2 escalation lifecycle: close this issue to clear the "
            f"dedup key and let the loop re-fire on the next drift._"
        )
        return await self._pr.create_issue(
            title, body, ["hitl-escalation", _STUCK_LABEL]
        )

    async def _resolve_flake_issue(self, test_id: str) -> bool:
        """Close the open ``flaky-test`` issue for *test_id* on recovery (#9359).

        Returns ``True`` if an issue was found and closed. The stable
        :meth:`_flake_title` lets us locate it by exact title.
        """
        existing = await self._pr.find_existing_issue(self._flake_title(test_id))
        if not existing:
            return False
        await self._pr.post_comment(
            existing,
            "Test no longer flaky in the recent RC-promotion window — "
            "auto-closing (#9359).",
        )
        await self._pr.close_issue(existing)
        return True

    async def _reconcile_closed_escalations(self) -> None:
        """Clear dedup keys whose escalation issue has been closed (spec §3.2).

        Delegates to the shared :class:`EscalationReconciler` (PRPort-based;
        replaced the raw ``gh issue list`` subprocess). Subjects are parsed
        from the escalation title shape
        ``"HITL: flaky test <id> unresolved after N attempts"``.
        """
        await self._escalations.reconcile_closed()

    async def _fetch_xdist_audit_runs(self) -> list[dict[str, Any]]:
        """Recent ``xdist-audit`` runs from the shared cache (no per-tick gh).

        Mirrors :meth:`_fetch_recent_runs`: served from the demand-refreshed
        ``GitHubDataCache`` snapshot so the 4h tick costs at most one gh call per
        freshness window and a gh outage degrades to an empty list (#9814).
        """
        rows = await self._github_cache.get_xdist_audit_runs()
        return [
            {
                "databaseId": row.get("id"),
                "url": row.get("url", ""),
                "conclusion": row.get("conclusion", ""),
                "createdAt": row.get("created_at", ""),
            }
            for row in rows[:_RUN_WINDOW]
        ]

    async def _download_xdist_audit(self, run: dict[str, Any]) -> list[str]:
        """Download a run's ``xdist-audit`` artifact; return its ``xdist_unsafe`` list."""
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
                _XDIST_AUDIT_ARTIFACT,
                "--dir",
                td,
            ]
            try:
                result = await run_subprocess_result(*cmd, timeout=_GH_TIMEOUT_SECONDS)
            except SubprocessTimeoutError:
                return []
            if result.returncode != 0:
                return []
            for report in Path(td).rglob(_XDIST_AUDIT_REPORT):
                try:
                    data = json.loads(report.read_text(encoding="utf-8"))
                except (json.JSONDecodeError, OSError):
                    continue
                unsafe = data.get("xdist_unsafe", []) if isinstance(data, dict) else []
                return [str(t) for t in unsafe] if isinstance(unsafe, list) else []
            return []

    @staticmethod
    def _tally_xdist_unsafe(per_run: list[list[str]]) -> dict[str, int]:
        """Count the audit runs (not occurrences) that flagged each test."""
        counts: dict[str, int] = {}
        for run_unsafe in per_run:
            for test_id in set(run_unsafe):
                counts[test_id] = counts.get(test_id, 0) + 1
        return counts

    async def _file_xdist_quarantine_issue(
        self, test_id: str, flagged: int, total: int
    ) -> int:
        """File a consent-package issue to quarantine an xdist-unsafe test.

        Mirrors the GateHealthLoop consent-package shape (evidence +
        recommendation + exact command); human-gated — the loop never edits the
        serial list itself.
        """
        path_hint = _quarantine_path_hint(test_id)
        hint_line = f"`{path_hint}`" if path_hint else "_(derive from the test id)_"
        title = f"xdist-unsafe test: {test_id}"
        body = (
            "## Evidence (xdist-audit, automated)\n\n"
            "| metric | value |\n|---|---|\n"
            f"| test | `{test_id}` |\n"
            f"| flagged fail-parallel/pass-serial | {flagged} of the last "
            f"{total} audit run(s) |\n"
            f"| likely file | {hint_line} |\n\n"
            "This test fails under `pytest -n auto` but passes serially across "
            "the audit window — a process-global isolation leak. Moving it to "
            "the serial lane unblocks the parallel bulk while the root isolation "
            "issue is fixed.\n\n"
            "## Consent package\n\n"
            "**Recommendation:** quarantine into `PYTEST_SERIAL_PATHS`, then "
            "fix the isolation leak and remove it again (shrink-only baseline).\n\n"
            "**Exact edit:** append the file to `PYTEST_SERIAL_PATHS` in the "
            "`Makefile` and keep the `ci.yml` serial lane in sync — add "
            f"`--ignore={path_hint or '<file>'}` to the parallel `test` step and "
            f"`{path_hint or '<file>'}` to the serial step. (A path already under "
            "`tests/regressions/` is covered by the blanket `--ignore=tests/"
            "regressions` in ci.yml; only the Makefile needs it.)\n\n"
            "Human-gated: `flake_tracker` will NOT apply this edit.\n\n"
            "_Auto-filed by HydraFlow's `flake_tracker` loop (#10141)._"
        )
        return await self._pr.create_issue(
            title, body, ["hydraflow-find", "flaky-test"]
        )

    async def _run_xdist_quarantine_detection(self) -> dict[str, int]:
        """Detect + file consent-package quarantines from the xdist-audit report.

        Independent of the RC flake-tally path: windows the nightly audit so a
        one-off transient parallel failure never triggers a quarantine (only a
        test flagged in ``xdist_quarantine_threshold`` runs). Dedup-keyed
        separately (``xdist_quarantine:``) from the flake keys.
        """
        if not self._config.xdist_quarantine_enabled:
            return {"filed": 0}
        runs = await self._fetch_xdist_audit_runs()
        if not runs:
            return {"filed": 0}
        per_run = [await self._download_xdist_audit(run) for run in runs[:_RUN_WINDOW]]
        counts = self._tally_xdist_unsafe(per_run)
        threshold = self._config.xdist_quarantine_threshold

        dedup = set(self._dedup.get())
        filed = 0
        dirty = False
        for test_id, flagged in counts.items():
            if flagged < threshold:
                continue
            key = f"xdist_quarantine:{test_id}"
            if key in dedup:
                continue
            await self._file_xdist_quarantine_issue(test_id, flagged, len(runs))
            dedup.add(key)
            dirty = True
            filed += 1
        if dirty:
            self._dedup.set_all(dedup)
        return {"filed": filed}

    async def _do_work(self) -> WorkCycleResult:
        """One flake-tracking cycle (spec §4.5)."""
        if not self._enabled_cb(self._worker_name):
            return {"status": "disabled"}
        if not self._config.flake_tracker_loop_enabled:
            return {"status": "config_disabled"}

        t0 = time.perf_counter()
        await self._reconcile_closed_escalations()

        # xdist-quarantine detection is independent of the RC flake tally
        # (different data source) — run it first so an empty RC window still
        # processes the audit report.
        xdist = await self._run_xdist_quarantine_detection()

        runs = await self._fetch_recent_runs()
        if not runs:
            return {"status": "no_runs", "filed": 0, "xdist_filed": xdist["filed"]}

        per_run_results: list[dict[str, str]] = []
        for run in runs:
            per_run_results.append(await self._download_junit(run))

        counts = self._tally_flakes(per_run_results)
        self._state.set_flake_counts(counts)

        threshold = self._config.flake_threshold
        flaky_now = {tid for tid, c in counts.items() if c >= threshold}
        dedup = set(self._dedup.get())
        dedup_dirty = False

        # Recovery (#9359): a test with an open flake key that is no longer
        # flaky this window has recovered — close its `flaky-test` issue and
        # drop the key so a future regression re-files. Gated on
        # `attempts < _MAX_ATTEMPTS` so the HITL `flaky-test-stuck` escalation
        # is left to the operator-close path (`_reconcile_closed_escalations`);
        # the attempt counter is intentionally NOT cleared here so repeated
        # flare-ups still accumulate toward escalation.
        resolved = 0
        for key in sorted(dedup):
            if not key.startswith("flake_tracker:"):
                continue
            test_id = key.split(":", 1)[1]
            if test_id in flaky_now:
                continue
            if self._state.get_flake_attempts(test_id) >= _MAX_ATTEMPTS:
                continue
            if await self._resolve_flake_issue(test_id):
                dedup.discard(key)
                dedup_dirty = True
                resolved += 1

        filed = 0
        escalated = 0
        for test_id, count in counts.items():
            if count < threshold:
                continue
            key = f"flake_tracker:{test_id}"
            if key in dedup:
                continue
            attempts = self._state.inc_flake_attempts(test_id)
            if attempts >= _MAX_ATTEMPTS:
                await self._file_escalation(test_id, attempts)
                escalated += 1
            else:
                await self._file_flake_issue(test_id, count, runs)
                filed += 1
            dedup.add(key)
            dedup_dirty = True

        if dedup_dirty:
            self._dedup.set_all(dedup)

        # Open-escalation re-verify: flakes fixed by later PRs (or false
        # positives) auto-close their stuck escalations instead of waiting
        # for a human (#9618 class). Runs only after a COMPLETED detection:
        # an empty runs fetch early-returns above and never reaches here.
        # When runs exist but every junit download came back empty, the
        # all-empty window is indistinguishable from "all tests healthy" —
        # pass None so the pass is skipped (detection not meaningful). The
        # #9359 find-issue recovery above is untouched: reconcile_open only
        # handles the `flaky-test-stuck` escalation issues.
        autoclosed = await self._escalations.reconcile_open(
            flaky_now if any(per_run_results) else None
        )

        self._emit_trace(t0, runs_seen=len(runs))
        return {
            "status": "ok",
            "filed": filed,
            "escalated": escalated,
            "resolved": resolved,
            "autoclosed": autoclosed,
            "tests_seen": len(counts),
            "xdist_filed": xdist["filed"],
        }

    def _emit_trace(self, t0: float, *, runs_seen: int) -> None:
        try:
            from trace_collector import (  # noqa: PLC0415
                emit_loop_subprocess_trace,
            )
        except ImportError:
            return
        duration_ms = int((time.perf_counter() - t0) * 1000)
        emit_loop_subprocess_trace(
            loop=self._worker_name,
            command=["github_cache", "rc_workflow_runs"],
            exit_code=0,
            duration_ms=duration_ms,
            stderr_excerpt=f"runs_seen={runs_seen}",
        )
