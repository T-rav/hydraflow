"""AdrConformanceLoop — keystone caretaker loop of ADR-0098.

Periodically evaluates every Accepted ADR's ``**Enforced by:**`` checks
(via ``adr_conformance.evaluate_adrs`` + an injected ``ConformanceRunnerPort``)
and remediates drift by filing/updating GitHub issues. Mirrors the shape of
``AdrTouchpointAuditorLoop`` (ADR-0056): bounded retry via a per-ADR attempt
counter, escalation to HITL once at the attempt threshold, kill-switch +
config-disabled short circuits, dedup keyed one issue per ADR.

Issue-only write surface (load-bearing, ADR-0098): this loop's ONLY
repo-write side effect is filing/updating GitHub issues through
``PRManager`` plus appending to the **gitignored**
``.hydraflow/metrics/{repo_slug}/adr_conformance.jsonl`` log. It never
writes any file under ``src/``, ``tests/``, or ``docs/`` — in particular it
never edits an ADR's ``**Enforcement:**``/``## Decision`` content or its
``**Enforced by:**`` line, and it never rewrites the git-tracked, static
``docs/arch/generated/adr-conformance.md`` structural map (that file is
owned by arch-regen). A REPOINT decision files an issue *proposing* a
rename; a human/pipeline applies it. This is unit-tested — see the
guardrail test in ``tests/test_adr_conformance_loop.py``.

There is no reducer/aggregation step for ``ADR_CONFORMANCE_UPDATE`` (Task 9
scope): per-ADR outcomes are packed directly into the event payload.

``_detect_rename`` is currently a conservative stub that always returns
``None`` — high-confidence rename detection (mapping an UNRESOLVED check to
a plausible new identity) is a follow-up. Returning ``None`` unconditionally
just routes every UNRESOLVED check to FILE_ISSUE, which is the safe default
per ``classify_remediation``.
"""

from __future__ import annotations

import logging
import time
from typing import TYPE_CHECKING

from base_background_loop import BaseBackgroundLoop, LoopDeps  # noqa: TCH001
from loop_fitness import FitnessContext, FitnessKind, LoopFitness  # noqa: TCH001
from models import WorkCycleResult  # noqa: TCH001

if TYPE_CHECKING:
    from adr_conformance import AdrConformance
    from adr_index import ADRIndex
    from config import HydraFlowConfig
    from dedup_store import DedupStore
    from ports import ConformanceRunnerPort
    from pr_manager import PRManager
    from state import StateTracker

logger = logging.getLogger("hydraflow.adr_conformance_loop")

_MAX_ATTEMPTS = 3


def _dedup_key(adr_id: str) -> str:
    return f"adr_conformance:{adr_id}"


class AdrConformanceLoop(BaseBackgroundLoop):
    """ADR conformance auditor (ADR-0098): evaluate + split-class remediation.

    Filed remediation is issue-only. See module docstring for the guardrail.
    """

    def __init__(
        self,
        *,
        config: HydraFlowConfig,
        state: StateTracker,
        pr_manager: PRManager,
        dedup: DedupStore,
        adr_index: ADRIndex,
        runner: ConformanceRunnerPort,
        deps: LoopDeps,
    ) -> None:
        super().__init__(
            worker_name="adr_conformance",
            config=config,
            deps=deps,
            run_on_startup=False,
        )
        self._state = state
        self._pr = pr_manager
        self._dedup = dedup
        self._adr_index = adr_index
        self._runner = runner
        self._repo_root = config.repo_root

    def _get_default_interval(self) -> int:
        return self._config.adr_conformance_interval

    def loop_fitness(self, ctx: FitnessContext) -> LoopFitness:
        # Read-only maintenance loop; no proposal/acceptance lifecycle of its
        # own to score — HOUSEKEEPING per ADR-0093's fitness contract.
        return LoopFitness(
            worker_name=self._worker_name,
            kind=FitnessKind.HOUSEKEEPING,
            timestamp=ctx.window_end,
        )

    def _detect_rename(self, conf: AdrConformance) -> str | None:
        """Detect a high-confidence renamed identity for an UNRESOLVED check.

        Stub (ADR-0098 follow-up): always returns ``None``. This routes
        every UNRESOLVED outcome to FILE_ISSUE via
        ``adr_conformance_remediation.classify_remediation`` rather than
        REPOINT, which is the conservative/safe default until confirmed-
        rename detection (e.g. git-log-following a moved pytest node or
        make target) is implemented.
        """
        return None

    def _metrics_path(self):  # noqa: ANN202
        return self._config.repo_data_root / "metrics" / "adr_conformance.jsonl"

    def _persist_jsonl(self, results: list[AdrConformance]) -> None:
        from file_util import append_jsonl  # noqa: PLC0415

        path = self._metrics_path()
        for conf in results:
            append_jsonl(path, conf.model_dump_json())

    def _issue_title(self, conf: AdrConformance) -> str:
        return f"ADR conformance: {conf.adr_id} is {conf.outcome.value}"

    def _issue_body(self, conf: AdrConformance) -> str:
        lines = [
            "## ADR conformance drift",
            "",
            f"**{conf.adr_id}** conformance check outcome: `{conf.outcome.value}` "
            f"(kind: `{conf.kind.value}`).",
            "",
            "**Checks:**",
            "",
        ]
        for c in conf.checks:
            detail = f" — {c.detail}" if c.detail else ""
            lines.append(f"- `{c.check}`: {c.outcome.value}{detail}")
        lines.extend(
            [
                "",
                "**Repair options:**",
                "1. Fix the underlying drift so the check passes again, OR",
                "2. If the check target moved/renamed, update the ADR's "
                "`**Enforced by:**` line to point at the new target, OR",
                "3. If the decision itself is stale, consider superseding the ADR.",
                "",
                "_Filed by `adr_conformance` per ADR-0098._",
                "",
                "<!-- [hydraflow-auditor: source=AdrConformanceLoop] -->",
            ]
        )
        return "\n".join(lines)

    async def _file_or_update_issue(self, conf: AdrConformance) -> None:
        """File (or refresh) the dedup'd remediation issue for *conf*."""
        rollup = self._state.get_adr_conformance_rollup(conf.adr_id)
        title = self._issue_title(conf)
        body = self._issue_body(conf)
        if rollup:
            await self._pr.update_issue_body(int(rollup["issue_number"]), body)
            return
        issue_number = await self._pr.create_issue(
            title,
            body,
            [*self._config.find_label],
        )
        if issue_number == 0:
            # gh call failed (documented 0-sentinel) — don't record a rollup
            # or add the dedup key, or re-filing would be suppressed forever
            # without a real issue. Retry next cycle.
            logger.warning(
                "adr_conformance: create_issue returned 0 (sentinel) for %s; "
                "skipping record/dedup, will retry next cycle",
                conf.adr_id,
            )
            return
        self._state.set_adr_conformance_rollup(conf.adr_id, issue_number=issue_number)
        # The state rollup above is the operative per-ADR double-file cap
        # (gates create-vs-update via get_adr_conformance_rollup); this dedup
        # write is the tracked-key set that _reconcile_closed_conformance_issues
        # reads on the next tick to detect externally-closed remediation
        # issues and clear stale state so the loop re-files instead of
        # updating a dead issue.
        dedup = self._dedup.get()
        dedup.add(_dedup_key(conf.adr_id))
        self._dedup.set_all(dedup)

    async def _file_repoint_issue(
        self, conf: AdrConformance, rename_match: str
    ) -> None:
        """File a dedup'd issue proposing a rename — the loop does NOT edit
        the ADR file itself; a human/pipeline applies the computed rename."""
        title = f"ADR conformance: {conf.adr_id} check may have been renamed"
        body = (
            "## ADR conformance — proposed repoint\n\n"
            f"**{conf.adr_id}** has an UNRESOLVED check that appears to have "
            f"been renamed to:\n\n```\n{rename_match}\n```\n\n"
            "If this is correct, update the ADR's `**Enforced by:**` line to "
            "point at the new target. This issue does not modify the ADR — "
            "human/pipeline review is required before repointing.\n\n"
            "_Filed by `adr_conformance` per ADR-0098._\n\n"
            "<!-- [hydraflow-auditor: source=AdrConformanceLoop] -->"
        )
        issue_number = await self._pr.create_issue(
            title, body, [*self._config.find_label]
        )
        if issue_number == 0:
            logger.warning(
                "adr_conformance: create_issue (repoint) returned 0 (sentinel) "
                "for %s; skipping record/dedup, will retry next cycle",
                conf.adr_id,
            )
            return
        self._state.set_adr_conformance_rollup(conf.adr_id, issue_number=issue_number)
        # The state rollup above is the operative per-ADR double-file cap
        # (gates create-vs-update via get_adr_conformance_rollup); this dedup
        # write is the tracked-key set that _reconcile_closed_conformance_issues
        # reads on the next tick to detect externally-closed remediation
        # issues and clear stale state so the loop re-files instead of
        # updating a dead issue.
        dedup = self._dedup.get()
        dedup.add(_dedup_key(conf.adr_id))
        self._dedup.set_all(dedup)

    async def _escalate_to_adr_reviewer(
        self, conf: AdrConformance, attempts: int
    ) -> None:
        """File a one-shot HITL/adr_reviewer supersession-proposal issue.

        Fired exactly once at the ``_MAX_ATTEMPTS`` threshold by the caller's
        ``==`` (not ``>=``) guard, so a still-open remediation doesn't file a
        fresh escalation every subsequent tick.
        """
        title = (
            f"HITL: {conf.adr_id} conformance unresolved after {_MAX_ATTEMPTS} attempts"
        )
        body = (
            f"`adr_conformance` has re-evaluated `{conf.adr_id}` as "
            f"`{conf.outcome.value}` {attempts} times without resolution. "
            "The decision may be stale — consider a supersession proposal, "
            "or fix the underlying drift.\n\n"
            "Human review needed.\n\n"
            "_Closing this issue does NOT clear the remediation dedup key "
            "or reset the attempt counter (ADR-0098) — the underlying "
            "FILE_ISSUE/REPOINT remediation issue must be closed (or the "
            "drift fixed) to do that._"
        )
        await self._pr.create_issue(
            title,
            body,
            [*self._config.find_label, *self._config.hitl_escalation_label],
        )

    async def _reconcile_closed_conformance_issues(self) -> None:
        """Clear dedup keys + attempt/rollup state for closed remediation issues.

        Mirrors ``AdrTouchpointAuditorLoop._reconcile_closed_escalations``
        (ADR-0056). Without this, a human closing a remediation issue
        without fixing the underlying drift leaves the loop's rollup state
        pointed at a dead (closed) issue: ``_file_or_update_issue`` would
        keep calling ``update_issue_body`` on the closed issue number
        forever instead of re-filing. Listing closed issues carrying our
        ``find_label`` and matching each tracked dedup key's ADR id against
        the issue title lets us detect this and clear state so the next
        evaluation re-files fresh.

        IMPORTANT — remediation-only match, not "any title containing the
        ADR id": the HITL escalation issue filed by
        ``_escalate_to_adr_reviewer`` ALSO carries ``find_label`` (it's
        ``[*find_label, *hitl_escalation_label]``) and its title
        (``f"HITL: {adr_id} conformance unresolved after {_MAX_ATTEMPTS}
        attempts"``) also contains the bare ``adr_id`` as a substring. A
        naive ``adr_id in title`` match would treat closing the escalation
        issue (the documented human action once escalated) as if the
        FILE_ISSUE/REPOINT remediation issue had been closed, wrongly
        clearing the attempt counter and rollup and resetting the 3-strikes
        escalation threshold while orphaning the still-open remediation
        issue. Both remediation title shapes
        (``_issue_title`` -> ``"ADR conformance: {adr_id} is {outcome}"``
        and ``_file_repoint_issue`` -> ``"ADR conformance: {adr_id} check
        may have been renamed"``) share the ``"ADR conformance: {adr_id} "``
        prefix, which the ``"HITL: ..."`` escalation title never matches —
        so anchor the match on that prefix instead of a bare substring
        check.
        """
        closed_titles: list[str] = []
        for label in self._config.find_label:
            try:
                closed = await self._pr.list_closed_issues_by_label(label)
            except (
                RuntimeError,
                AttributeError,
            ) as exc:  # pragma: no cover - defensive
                logger.warning(
                    "adr_conformance: could not list closed issues for label %s: %s",
                    label,
                    exc,
                )
                continue
            closed_titles.extend(str(item.get("title", "")) for item in closed)

        if not closed_titles:
            return

        current = self._dedup.get()
        keep = set(current)
        for title in closed_titles:
            for key in list(keep):
                if not key.startswith("adr_conformance:"):
                    continue
                adr_id = key.split(":", 1)[1]
                if not title.startswith(f"ADR conformance: {adr_id} "):
                    # Excludes the HITL escalation title
                    # ("HITL: {adr_id} conformance unresolved after N
                    # attempts") even though it also contains adr_id —
                    # closing an escalation issue must never clear
                    # FILE_ISSUE/REPOINT dedup/rollup/attempt state.
                    continue
                keep.discard(key)
                self._state.clear_adr_conformance_attempts(adr_id)
                self._state.clear_adr_conformance_rollup(adr_id)
        if keep != current:
            self._dedup.set_all(keep)

    async def _emit_event(self, results: list[AdrConformance]) -> None:
        """Publish ADR_CONFORMANCE_UPDATE with per-ADR outcomes packed into
        the payload.

        No reducer/aggregation step exists for this event (Task 9 scope) —
        the payload IS the full per-tick result set.
        """
        from events import EventType, HydraFlowEvent  # noqa: PLC0415

        payload = {
            "results": [
                {
                    "adr_id": conf.adr_id,
                    "kind": conf.kind.value,
                    "outcome": conf.outcome.value,
                    "timestamp": conf.timestamp.isoformat(),
                }
                for conf in results
            ]
        }
        await self._bus.publish(
            HydraFlowEvent(type=EventType.ADR_CONFORMANCE_UPDATE, data=payload)
        )

    async def _do_work(self) -> WorkCycleResult:
        if not self._enabled_cb(self._worker_name):
            return {"status": "disabled"}
        if not self._config.adr_conformance_loop_enabled:
            return {"status": "config_disabled"}

        from datetime import UTC, datetime  # noqa: PLC0415

        from adr_conformance import evaluate_adrs  # noqa: PLC0415
        from adr_conformance_remediation import (  # noqa: PLC0415
            RemediationAction,
            classify_remediation,
        )

        t0 = time.perf_counter()

        await self._reconcile_closed_conformance_issues()

        now = datetime.now(UTC)
        adrs = self._adr_index.adrs()
        results = evaluate_adrs(
            adrs, self._runner, repo_root=self._repo_root, timestamp=now
        )
        self._persist_jsonl(results)

        filed = escalated = repointed = 0
        for conf in results:
            rename_match = self._detect_rename(conf)
            attempts = (
                self._state.inc_adr_conformance_attempts(conf.adr_id)
                if conf.outcome.value in ("fail", "unresolved")
                else 0
            )
            decision = classify_remediation(
                conf,
                rename_match=rename_match,
                attempts=attempts,
                max_attempts=_MAX_ATTEMPTS,
            )
            if (
                decision.action is RemediationAction.REPOINT
                and rename_match is not None
            ):
                # rename_match is guaranteed non-None here: classify_remediation
                # only returns REPOINT when rename_match was truthy.
                await self._file_repoint_issue(conf, rename_match)
                repointed += 1
            elif decision.action is RemediationAction.FILE_ISSUE:
                await self._file_or_update_issue(conf)
                filed += 1
            elif decision.action is RemediationAction.ESCALATE:
                # Fire exactly once at the threshold. classify_remediation
                # returns ESCALATE for every attempts >= max_attempts, so
                # without this guard a still-unresolved ADR would re-file a
                # HITL issue every subsequent tick (attempts=4, 5, 6, ...).
                if attempts == _MAX_ATTEMPTS:
                    await self._escalate_to_adr_reviewer(conf, attempts)
                    escalated += 1
                # attempts > _MAX_ATTEMPTS: already escalated once; no-op.
            else:
                self._state.clear_adr_conformance_attempts(conf.adr_id)

        await self._emit_event(results)
        self._emit_trace(t0, evaluated=len(results), filed=filed)
        return {
            "status": "ok",
            "evaluated": len(results),
            "filed": filed,
            "escalated": escalated,
            "repointed": repointed,
        }

    def _emit_trace(self, t0: float, *, evaluated: int, filed: int) -> None:
        try:
            from trace_collector import emit_loop_subprocess_trace  # noqa: PLC0415
        except ImportError:
            return
        duration_ms = int((time.perf_counter() - t0) * 1000)
        emit_loop_subprocess_trace(
            loop=self._worker_name,
            command=["adr_conformance", "evaluate"],
            exit_code=0,
            duration_ms=duration_ms,
            stderr_excerpt=f"evaluated={evaluated} filed={filed}",
        )
