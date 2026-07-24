"""AdrTouchpointAuditorLoop — async caretaker replacing the deleted gate (ADR-0056).

Periodically scans recently-merged PRs and files `hydraflow-find` issues
when an Accepted/Proposed ADR's cited `src/` modules changed without the
ADR file appearing in the same diff. Bounded retry → HITL escalation
follows the `FakeCoverageAuditorLoop` pattern.

Cursor is `state.adr_audit_cursor` (ISO-8601 of the most-recently-scanned
merged-PR mergedAt). First run after deploy seeds it to "now" — pre-existing
merge history is frozen and not retroactively scanned.

Per-ADR rollup (#8987): findings are aggregated into **one issue per ADR**
listing all PRs that drifted it. Subsequent ticks update the body via
``PRPort.update_issue_body``. When an ADR's own file appears in a PR diff
the rollup is closed — drift is resolved by the same PR.

Fleet batch (#9662): a single cross-cutting PR drifting at least
``config.adr_drift_fleet_batch_threshold`` distinct ADRs files **one
batched issue** listing every affected ADR (dedup key
``adr_touchpoint_auditor:FLEET-<pr>``) instead of N per-ADR rollups.
Batched rollups are one-shot: they are never auto-closed by later
ADR-file updates — a human closes them with a one-line explanation, and
the manual-close reconcile pass clears the ``FLEET-<pr>`` state + dedup
key so nothing strands.

Migration: old per-tuple dedup keys (``adr_touchpoint_auditor:PR-N:ADR-N``)
and per-tuple attempt counters are silently ignored. They are not pruned —
the keys become dead weight in the dedup store until a future cleanup. New
keys are ``adr_touchpoint_auditor:ADR-NNNN`` (no PR component) and
``adr_touchpoint_auditor:FLEET-<pr>`` (fleet batches; the two sub-namespaces
never collide).
"""

from __future__ import annotations

import json
import logging
import re
import time
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from adr_drift import compute_drift_by_adr, partition_fleet_drift
from base_background_loop import BaseBackgroundLoop, LoopDeps  # noqa: TCH001
from escalation_reconcile import EscalationReconciler
from models import WorkCycleResult  # noqa: TCH001
from subprocess_util import SubprocessTimeoutError, run_subprocess_result

if TYPE_CHECKING:
    from adr_drift import AdrRollupEntry, DriftFinding, FleetDriftBatch
    from adr_index import ADRIndex
    from config import HydraFlowConfig
    from dedup_store import DedupStore
    from pr_manager import PRManager
    from state import StateTracker

logger = logging.getLogger("hydraflow.adr_touchpoint_auditor_loop")

_MAX_ATTEMPTS = 3
_DEFAULT_PR_LIMIT = 50  # gh pr list page size per tick

# Hard cap on each ``gh`` read. A wedged ``gh`` child (auth prompt, network
# black-hole) must not hang the loop cycle forever and freeze its heartbeat —
# the #9410 silent-stall failure class (#9454 / #9508). Bounded (and, via
# ``run_subprocess_result``, circuit-breaker/rate-limit/process-group
# hardened — #9554/#10028) rather than a raw ``create_subprocess_exec``.
_GH_TIMEOUT_SECONDS = 120


def _rollup_key(adr_number: int) -> str:
    return f"ADR-{adr_number:04d}"


def _dedup_key(adr_number: int) -> str:
    return f"adr_touchpoint_auditor:{_rollup_key(adr_number)}"


def _fleet_rollup_key(pr_number: int) -> str:
    """Rollup/state key for a fleet batch (#9662).

    The ``FLEET-`` discriminator keeps this sub-namespace disjoint from the
    per-ADR ``ADR-NNNN`` keys under the shared ``adr_touchpoint_auditor:``
    dedup prefix — a fleet batch for PR 42 and a rollup for ADR 42 coexist.
    """
    return f"FLEET-{pr_number}"


def _fleet_dedup_key(pr_number: int) -> str:
    return f"adr_touchpoint_auditor:{_fleet_rollup_key(pr_number)}"


def _pr_num_from_fleet_key(rollup_key: str) -> int | None:
    """Parse the PR number out of a ``FLEET-<pr>`` rollup key.

    Returns ``None`` for non-fleet or malformed keys so a corrupt state
    entry can't wedge the reconcile pass (mirrors ``_adr_num_from_key``).
    """
    if not rollup_key.startswith("FLEET-"):
        return None
    try:
        return int(rollup_key[6:])
    except ValueError:
        return None


# Parses ``_file_drift_escalation`` titles back to the dedup-key subject
# (the ``ADR-NNNN`` rollup key). Returns ``None`` for titles that aren't ours
# so the shared ``EscalationReconciler`` skips operator-created issues.
_ESCALATION_TITLE_RE = re.compile(r"^HITL: ADR drift (.+?) unresolved after ")


def _escalation_subject(title: str) -> str | None:
    m = _ESCALATION_TITLE_RE.match(title)
    return m.group(1) if m else None


def _adr_num_from_key(rollup_key: str) -> int | None:
    """Parse the ADR number out of an ``ADR-NNNN`` rollup key.

    Returns ``None`` for malformed keys so a corrupt state entry can't wedge
    the reconcile pass.
    """
    if not rollup_key.startswith("ADR-"):
        return None
    try:
        return int(rollup_key[4:])
    except ValueError:
        return None


class AdrTouchpointAuditorLoop(BaseBackgroundLoop):
    """ADR drift auditor (ADR-0056). Replaces the deleted touchpoint gate.

    Files **one rollup issue per ADR** (#8987) listing all PRs that drifted
    its cited modules.
    """

    def __init__(
        self,
        *,
        config: HydraFlowConfig,
        state: StateTracker,
        pr_manager: PRManager,
        dedup: DedupStore,
        adr_index: ADRIndex,
        deps: LoopDeps,
    ) -> None:
        super().__init__(
            worker_name="adr_touchpoint_auditor",
            config=config,
            deps=deps,
            run_on_startup=False,
        )
        self._state = state
        self._pr = pr_manager
        self._dedup = dedup
        self._adr_index = adr_index
        self._escalations = EscalationReconciler(
            prs=pr_manager,
            dedup=dedup,
            key_prefix="adr_touchpoint_auditor",
            stuck_label=config.adr_drift_stuck_label[0],
            clear_attempts=self._clear_drift_state,
            subject_from_title=_escalation_subject,
        )

    def _clear_drift_state(self, subject: str) -> None:
        """Clear both the attempt counter and the rollup state for *subject*
        (an ``ADR-NNNN`` rollup key). The pre-migration reconciler cleared
        both on a closed escalation; the shared reconciler drives this via a
        single ``clear_attempts`` callback."""
        self._state.clear_adr_audit_attempts(subject)
        self._state.clear_adr_rollup(subject)

    def _get_default_interval(self) -> int:
        return self._config.adr_touchpoint_auditor_interval

    async def _list_recent_merged_prs(self, cursor: str) -> list[dict]:
        """Return merged PRs in the configured repo with mergedAt > cursor.

        Result entries carry: number, mergedAt, title, files (list[{path,additions,deletions}]).
        """
        cmd = [
            "gh",
            "pr",
            "list",
            "--repo",
            self._config.repo,
            "--state",
            "merged",
            "--limit",
            str(_DEFAULT_PR_LIMIT),
            "--json",
            "number,mergedAt,title,files",
        ]
        if cursor:
            cmd.extend(["--search", f"merged:>{cursor}"])
        try:
            result = await run_subprocess_result(*cmd, timeout=_GH_TIMEOUT_SECONDS)
        except SubprocessTimeoutError:
            logger.warning(
                "gh pr list timed out after %ss; skipping tick",
                _GH_TIMEOUT_SECONDS,
            )
            return []
        if result.returncode != 0:
            logger.warning(
                "gh pr list failed (rc=%s): %s",
                result.returncode,
                result.stderr,
            )
            return []
        try:
            payload = json.loads(result.stdout or "[]")
        except json.JSONDecodeError:
            logger.warning("gh pr list returned non-JSON")
            return []
        return sorted(payload, key=lambda r: r.get("mergedAt") or "")

    async def _fetch_pr_changed_files(self, pr_number: int) -> list[str]:
        """Return one PR's changed file paths via ``gh pr view N --json files``.

        Bounded by :data:`_GH_TIMEOUT_SECONDS`. Returns ``[]`` on any failure
        (timeout, non-zero exit, malformed JSON) so a single unreadable PR
        can't wedge the stale-rollup reconcile pass. Used to re-fetch a
        tracked rollup's OWN historical PR diffs — which may predate the scan
        cursor — so drift can be recomputed for just those PRs (#9622).
        """
        cmd = [
            "gh",
            "pr",
            "view",
            str(pr_number),
            "--repo",
            self._config.repo,
            "--json",
            "files",
        ]
        try:
            result = await run_subprocess_result(*cmd, timeout=_GH_TIMEOUT_SECONDS)
        except SubprocessTimeoutError:
            logger.warning(
                "gh pr view %s timed out after %ss; treating as no files",
                pr_number,
                _GH_TIMEOUT_SECONDS,
            )
            return []
        if result.returncode != 0:
            logger.warning(
                "gh pr view %s failed (rc=%s): %s",
                pr_number,
                result.returncode,
                result.stderr,
            )
            return []
        try:
            payload = json.loads(result.stdout or "{}")
        except json.JSONDecodeError:
            logger.warning("gh pr view %s returned non-JSON", pr_number)
            return []
        return [f.get("path", "") for f in payload.get("files", []) if f.get("path")]

    @staticmethod
    def _changed_paths(pr: dict) -> list[str]:
        return [f.get("path", "") for f in pr.get("files", []) if f.get("path")]

    def _rollup_body(
        self,
        adr,
        pr_entries: list[dict],
    ) -> str:
        """Render the rollup issue body.

        ``pr_entries`` is a list of ``{number, mergedAt, changed_cited_files}``
        dicts, one per PR currently included in the rollup.
        """
        pr_entries = sorted(pr_entries, key=lambda e: int(e.get("number", 0)))
        repo = self._config.repo
        lines = [
            "## ADR drift rollup",
            "",
            f"PRs whose diff changed `src/` modules cited by "
            f"**ADR-{adr.number:04d}: {adr.title}** (status: {adr.status}) "
            f"without the ADR file being in the same diff:",
            "",
        ]
        for entry in pr_entries:
            pr_number = int(entry.get("number", 0))
            merged_at = entry.get("mergedAt") or "?"
            files = entry.get("changed_cited_files") or []
            files_str = ", ".join(f"`{p}`" for p in files) or "(no paths recorded)"
            lines.append(
                f"- PR [#{pr_number}](https://github.com/{repo}/pull/{pr_number}) "
                f"(merged {merged_at}): {files_str}"
            )
        lines.extend(
            [
                "",
                "**Repair options:**",
                f"1. Update `docs/adr/{adr.number:04d}-*.md` to reflect the new "
                "behavior (closes this rollup automatically on the next tick), OR",
                "2. Confirm the changes are consistent with the existing ADR — close "
                "this issue with a one-line explanation (the close comment is the "
                "audit trail).",
                "",
                "_Filed by `adr_touchpoint_auditor` per ADR-0056 (per-ADR rollup, #8987)._",
                "",
                "<!-- [hydraflow-auditor: source=ADRTouchpointAuditorLoop] -->",
            ]
        )
        return "\n".join(lines)

    def _rollup_title(self, adr, pr_count: int) -> str:
        plural = "PR" if pr_count == 1 else "PRs"
        return (
            f"ADR drift: ADR-{adr.number:04d} cited modules drifted "
            f"across {pr_count} {plural}"
        )

    async def _file_drift_rollup(
        self,
        adr,
        pr_entries: list[dict],
    ) -> int:
        title = self._rollup_title(adr, len(pr_entries))
        body = self._rollup_body(adr, pr_entries)
        return await self._pr.create_issue(
            title,
            body,
            [*self._config.find_label, *self._config.adr_drift_label],
        )

    async def _update_drift_rollup(
        self,
        issue_number: int,
        adr,
        pr_entries: list[dict],
    ) -> None:
        body = self._rollup_body(adr, pr_entries)
        await self._pr.update_issue_body(issue_number, body)

    def _fleet_rollup_title(self, pr_number: int, adr_count: int) -> str:
        plural = "ADR" if adr_count == 1 else "ADRs"
        return (
            f"ADR drift: fleet PR #{pr_number} drifted {adr_count} {plural} (batched)"
        )

    def _fleet_rollup_body(
        self,
        pr_number: int,
        entries: list[AdrRollupEntry],
        merged_at: str,
    ) -> str:
        """Render the batched fleet-rollup body (#9662).

        ``entries`` is the batch's member ``AdrRollupEntry`` list (one
        single-contributor entry per drifted ADR).
        """
        repo = self._config.repo
        threshold = self._config.adr_drift_fleet_batch_threshold
        lines = [
            "## ADR drift rollup — cross-cutting fleet PR (batched)",
            "",
            f"PR [#{pr_number}](https://github.com/{repo}/pull/{pr_number}) "
            f"(merged {merged_at or '?'}) changed `src/` modules cited by "
            f"**{len(entries)} ADRs** without any of those ADR files in the "
            f"same diff. Per the #9662 batching heuristic (threshold: "
            f"{threshold}), they are batched into ONE issue instead of "
            f"{len(entries)} per-ADR rollups:",
            "",
        ]
        for entry in entries:
            adr = entry.adr
            files = sorted(
                {p for f in entry.contributors for p in f.changed_cited_files}
            )
            files_str = ", ".join(f"`{p}`" for p in files) or "(no paths recorded)"
            lines.append(
                f"- **ADR-{adr.number:04d}: {adr.title}** "
                f"(status: {adr.status}): {files_str}"
            )
        lines.extend(
            [
                "",
                "**Repair options:**",
                "1. If the sweep genuinely changed a decision, update the "
                "affected `docs/adr/NNNN-*.md` file(s), then close this "
                "issue referencing that PR, OR",
                "2. Confirm the sweep is implementation-only and consistent "
                "with every ADR listed — close this issue with a one-line "
                "explanation (the close comment is the audit trail).",
                "",
                "**Close semantics (differs from per-ADR rollups):** this "
                "batched issue is one-shot — it is NOT auto-closed when a "
                "member ADR's file is later updated. Closing it clears the "
                f"`FLEET-{pr_number}` tracking state and dedup key.",
                "",
                "_Filed by `adr_touchpoint_auditor` per ADR-0056 "
                "(fleet batch, #9662)._",
                "",
                "<!-- [hydraflow-auditor: source=ADRTouchpointAuditorLoop] -->",
            ]
        )
        return "\n".join(lines)

    async def _file_fleet_rollup(
        self,
        pr_number: int,
        entries: list[AdrRollupEntry],
        merged_at: str,
    ) -> int:
        title = self._fleet_rollup_title(pr_number, len(entries))
        body = self._fleet_rollup_body(pr_number, entries, merged_at)
        return await self._pr.create_issue(
            title,
            body,
            [*self._config.find_label, *self._config.adr_drift_label],
        )

    async def _file_drift_escalation(self, key: str, attempts: int) -> int:
        title = f"HITL: ADR drift {key} unresolved after {attempts}"
        body = (
            f"`adr_touchpoint_auditor` has re-filed `{key}` "
            f"{attempts} times without closure. Human review needed.\n\n"
            f"_Closing this issue clears the dedup key (ADR-0056)._"
        )
        return await self._pr.create_issue(
            title,
            body,
            [
                *self._config.hitl_escalation_label,
                *self._config.adr_drift_stuck_label,
            ],
        )

    async def _reconcile_closed_escalations(self) -> None:
        """Clear dedup keys + attempt counters for closed drift escalations.

        Delegates to the shared :class:`EscalationReconciler` (PRPort-based;
        replaced the raw ``gh issue list`` subprocess — #9932). Subjects (the
        ``ADR-NNNN`` rollup key) are parsed from the escalation-title shape
        ``"HITL: ADR drift <ADR-NNNN> unresolved after N"``; the matching
        ``adr_touchpoint_auditor:<ADR-NNNN>`` dedup key, attempt counter, and
        rollup state (:meth:`_clear_drift_state`) are cleared.
        """
        await self._escalations.reconcile_closed()

    def _adrs_updated_in_diff(self, changed_files: list[str]) -> set[int]:
        """Return ADR numbers whose own markdown file appears in *changed_files*."""
        updated: set[int] = set()
        for adr in self._adr_index.adrs():
            prefix = f"docs/adr/{adr.number:04d}-"
            if any(f.startswith(prefix) for f in changed_files):
                updated.add(adr.number)
        return updated

    @staticmethod
    def _contribs_to_pr_entries(
        contribs: tuple[DriftFinding, ...], pr_meta: dict[int, dict]
    ) -> list[dict]:
        entries: list[dict] = []
        for f in contribs:
            meta = pr_meta.get(f.pr_number, {})
            entries.append(
                {
                    "number": f.pr_number,
                    "mergedAt": meta.get("mergedAt", ""),
                    "changed_cited_files": list(f.changed_cited_files),
                }
            )
        return entries

    async def _close_and_clear_rollup(self, rollup_key: str, issue_number: int) -> None:
        """Close a rollup issue and clear its state, attempts, and dedup key.

        Atomic teardown shared by the ADR-file-resolved close path, the
        stale-rollup reconcile pass (#9622), and the fleet-batch manual-close
        reconcile (#9662) — *rollup_key* is either ``ADR-NNNN`` or
        ``FLEET-<pr>``; the matching ``adr_touchpoint_auditor:<key>`` dedup
        key is cleared alongside state + attempts so re-detection can re-file
        cleanly. Closing an already-closed issue is idempotent, so this is
        safe to call for a manually-closed rollup.
        """
        dedup_key = f"adr_touchpoint_auditor:{rollup_key}"
        try:
            await self._pr.close_issue(int(issue_number))
        except (
            RuntimeError,
            AttributeError,
        ) as exc:  # pragma: no cover - defensive
            logger.warning(
                "Could not close ADR rollup issue #%s: %s",
                issue_number,
                exc,
            )
        self._state.clear_adr_rollup(rollup_key)
        self._state.clear_adr_audit_attempts(rollup_key)
        current = self._dedup.get()
        if dedup_key in current:
            self._dedup.set_all(current - {dedup_key})

    async def _reconcile_stale_rollups(
        self,
        *,
        drifting_adrs: set[int],
        adrs_resolved_this_tick: set[int],
    ) -> int:
        """Close tracked rollups obsoleted outside this tick's scan window (#9622).

        ``compute_drift_by_adr`` only scans PRs merged since the cursor, so
        when a module is later added to ``_SHARED_INFRA_MODULES`` (or an ADR's
        citations change), a rollup whose contributor PRs predate the cursor is
        never rescanned — drift recomputes empty and the rollup strands open
        forever, unable to update or auto-close.

        For every tracked rollup whose ADR is NOT drifting in this tick's
        window and was NOT resolved by an ADR-file touch this tick:

        * if the rollup issue was manually closed (a non-escalated close that
          :meth:`_reconcile_closed_escalations` never sees), clear its orphaned
          state; otherwise
        * re-fetch the rollup's OWN tracked PR diffs by stored ``pr_number`` and
          recompute drift over JUST those PRs. Empty ⇒ obsolete ⇒ close + clear.

        CRITICAL: recompute is scoped to the rollup's OWN PRs, never this
        tick's window — otherwise every rollup would be wrongly closed on a
        quiet tick.

        Returns the number of rollups closed/cleared.
        """
        closed = 0
        for rollup_key, entry in self._state.all_adr_rollups().items():
            fleet_pr = _pr_num_from_fleet_key(rollup_key)
            if fleet_pr is not None:
                # Fleet batch (#9662): one-shot by design — no drift-recompute
                # auto-close. The only lifecycle event to reconcile is a manual
                # close, whose orphaned state + FLEET-<pr> dedup key would
                # otherwise strand forever (this loop's escalation reconcile
                # only sees escalation-labeled closes).
                issue_number = int(entry.get("issue_number", 0))
                if not issue_number:
                    continue
                state = await self._pr.get_issue_state(issue_number)
                if state and state not in ("OPEN", "UNKNOWN"):
                    await self._close_and_clear_rollup(rollup_key, issue_number)
                    closed += 1
                continue
            adr_num = _adr_num_from_key(rollup_key)
            if adr_num is None:
                continue
            # Actively drifting this tick, or resolved by an ADR-file touch this
            # tick — both are handled by the main scan; don't second-guess them.
            if adr_num in drifting_adrs or adr_num in adrs_resolved_this_tick:
                continue
            issue_number = int(entry.get("issue_number", 0))
            if not issue_number:
                continue

            # Manually-closed non-escalated rollup: state is orphaned because
            # ``_reconcile_closed_escalations`` only sees escalation-labeled
            # closes. ``get_issue_state`` returns ``OPEN`` while open,
            # ``COMPLETED``/``NOT_PLANNED`` when closed, and ``''``/``UNKNOWN``
            # on error — only act on a *definitive* closed state (fail-closed).
            state = await self._pr.get_issue_state(issue_number)
            if state and state not in ("OPEN", "UNKNOWN"):
                await self._close_and_clear_rollup(rollup_key, issue_number)
                closed += 1
                continue

            # Recompute drift over the rollup's OWN tracked PRs (NOT this tick's
            # window). Empty ⇒ a shared-infra addition / citation change made
            # the rollup obsolete.
            pr_numbers = [int(n) for n in entry.get("pr_numbers", [])]
            if not pr_numbers:
                continue
            pr_diffs: list[tuple[int, list[str]]] = []
            for n in pr_numbers:
                files = await self._fetch_pr_changed_files(n)
                pr_diffs.append((n, files))
            recomputed = compute_drift_by_adr(
                self._adr_index,
                pr_diffs,
                shared_infra_fanout_threshold=(
                    self._config.adr_drift_shared_infra_fanout_threshold
                ),
            )
            if any(e.adr.number == adr_num for e in recomputed):
                continue  # still genuinely drifts — leave the rollup open
            await self._close_and_clear_rollup(rollup_key, issue_number)
            closed += 1
        return closed

    async def _process_fleet_batches(
        self,
        batches: list[FleetDriftBatch],
        *,
        adrs_resolved_this_tick: set[int],
        pr_meta: dict[int, dict],
        dedup: set[str],
    ) -> tuple[int, int]:
        """File one batched rollup per fleet PR (#9662). Returns (filed, escalated).

        Mirrors the per-ADR fresh-file branch's guards: state + dedup make
        the batch one-shot across ticks/restarts; attempts increment with the
        same once-at-threshold escalation (only reachable when a closed batch
        is re-observed, e.g. a cursor rewind re-scanning the fleet PR); and
        ``create_issue``'s 0-sentinel records neither state nor dedup so the
        next tick retries. Member ADRs whose own file appeared in another PR
        this tick were just resolved above and are dropped from the batch
        (mirrors the per-ADR ``adrs_resolved_this_tick`` skip).
        """
        filed = 0
        escalated = 0
        for batch in batches:
            members = [
                e for e in batch.entries if e.adr.number not in adrs_resolved_this_tick
            ]
            if not members:
                continue
            rollup_key = _fleet_rollup_key(batch.pr_number)
            dedup_key = _fleet_dedup_key(batch.pr_number)
            if self._state.get_adr_rollup(rollup_key) is not None:
                # Already filed and tracked — fleet batches are one-shot, no
                # in-place body updates (the batch derives from ONE merged PR
                # whose diff never changes).
                continue
            if dedup_key in dedup:
                # Rollup state was cleared (e.g. external close) but dedup not
                # yet reconciled — skip until reconcile catches up.
                continue
            attempts = self._state.inc_adr_audit_attempts(rollup_key)
            if attempts == _MAX_ATTEMPTS:
                await self._file_drift_escalation(rollup_key, attempts)
                escalated += 1
            else:
                merged_at = pr_meta.get(batch.pr_number, {}).get("mergedAt", "")
                issue_number = await self._file_fleet_rollup(
                    batch.pr_number, members, merged_at
                )
                if issue_number == 0:
                    logger.warning(
                        "adr_touchpoint_auditor: create_issue returned 0 "
                        "(sentinel) for %s fleet batch; skipping record/"
                        "dedup, will retry next cycle",
                        rollup_key,
                    )
                    continue
                self._state.set_adr_rollup(
                    rollup_key,
                    issue_number=issue_number,
                    pr_numbers=[batch.pr_number],
                    adr_numbers=[e.adr.number for e in members],
                )
                filed += 1
            dedup.add(dedup_key)
            self._dedup.set_all(dedup)
        return filed, escalated

    async def _do_work(self) -> WorkCycleResult:  # noqa: PLR0915
        """Scan recently-merged PRs vs ADR citations; file per-ADR drift
        rollups, batching cross-cutting fleet PRs into one issue (#9662)."""
        if not self._enabled_cb(self._worker_name):
            return {"status": "disabled"}
        if not self._config.adr_touchpoint_auditor_loop_enabled:
            return {"status": "config_disabled"}

        t0 = time.perf_counter()
        cursor = self._state.get_adr_audit_cursor()
        if not cursor:
            self._state.set_adr_audit_cursor(datetime.now(UTC).isoformat())
            return {"status": "seeded", "filed": 0, "scanned": 0}

        await self._reconcile_closed_escalations()

        prs = await self._list_recent_merged_prs(cursor)
        if not prs:
            self._emit_trace(t0, scanned=0, filed=0)
            return {
                "status": "ok",
                "scanned": 0,
                "filed": 0,
                "escalated": 0,
                "closed": 0,
                "updated": 0,
            }

        # Build (pr_number, changed_files) batch + per-PR metadata.
        pr_meta: dict[int, dict] = {}
        pr_diffs: list[tuple[int, list[str]]] = []
        adrs_resolved_this_tick: set[int] = set()
        new_cursor = cursor
        for pr in prs:
            pr_number = int(pr.get("number", 0))
            if not pr_number:
                continue
            changed = self._changed_paths(pr)
            pr_meta[pr_number] = {
                "mergedAt": pr.get("mergedAt") or "",
                "changed_files": changed,
            }
            pr_diffs.append((pr_number, changed))
            adrs_resolved_this_tick |= self._adrs_updated_in_diff(changed)
            merged_at = pr.get("mergedAt") or ""
            new_cursor = max(new_cursor, merged_at)

        rollups, fleet_batches = partition_fleet_drift(
            self._adr_index,
            pr_diffs,
            fleet_threshold=self._config.adr_drift_fleet_batch_threshold,
            shared_infra_fanout_threshold=(
                self._config.adr_drift_shared_infra_fanout_threshold
            ),
        )
        drifting_adrs = {entry.adr.number for entry in rollups}
        drifting_adrs |= {n for batch in fleet_batches for n in batch.adr_numbers}

        # Resolve rollups for ADRs that were updated in any PR diff this tick.
        closed = 0
        for adr_num in adrs_resolved_this_tick:
            existing = self._state.get_adr_rollup(_rollup_key(adr_num))
            if not existing:
                continue
            await self._close_and_clear_rollup(
                _rollup_key(adr_num), int(existing["issue_number"])
            )
            closed += 1

        # Stale-rollup reconciliation (#9622): a shared-infra addition /
        # citation change / manual close can obsolete a rollup whose original
        # contributor PRs predate the cursor and are never rescanned by
        # ``compute_drift_by_adr``. Re-evaluate those over their OWN PRs.
        closed += await self._reconcile_stale_rollups(
            drifting_adrs=drifting_adrs,
            adrs_resolved_this_tick=adrs_resolved_this_tick,
        )

        filed = 0
        updated = 0
        escalated = 0
        dedup = self._dedup.get()
        for entry in rollups:
            adr_num = entry.adr.number
            # Skip ADRs whose own file was in this tick's diffs — they were just
            # resolved above; their rollup (if any) was closed.
            if adr_num in adrs_resolved_this_tick:
                continue

            rollup_key = _rollup_key(adr_num)
            dedup_key = _dedup_key(adr_num)
            existing = self._state.get_adr_rollup(rollup_key)
            new_pr_entries = self._contribs_to_pr_entries(entry.contributors, pr_meta)
            new_pr_numbers = {int(e["number"]) for e in new_pr_entries}

            if existing:
                # Compute the set of PRs that this tick observed touching the
                # ADR's own file (and therefore "gained ADR coverage"). Any
                # tracked PR appearing in such a diff is dropped from the rollup.
                # (Rollup-wide close is handled above when *any* PR diff touches
                # the ADR file; this branch only runs for ADRs not in
                # ``adrs_resolved_this_tick``, so dropping here is a no-op in
                # practice — but kept as defense for partial-state cases.)
                gained_coverage: set[int] = set()
                for pr_num, meta in pr_meta.items():
                    if entry.adr.number in self._adrs_updated_in_diff(
                        meta["changed_files"]
                    ):
                        gained_coverage.add(pr_num)

                kept_existing = [
                    n for n in existing["pr_numbers"] if n not in gained_coverage
                ]
                merged_pr_numbers = sorted({*kept_existing, *new_pr_numbers})
                merged_entries: list[dict] = list(new_pr_entries)
                new_present = new_pr_numbers
                for n in merged_pr_numbers:
                    if n in new_present:
                        continue
                    merged_entries.append(
                        {
                            "number": n,
                            "mergedAt": "",
                            "changed_cited_files": [],
                        }
                    )
                await self._update_drift_rollup(
                    int(existing["issue_number"]), entry.adr, merged_entries
                )
                self._state.set_adr_rollup(
                    rollup_key,
                    issue_number=int(existing["issue_number"]),
                    pr_numbers=merged_pr_numbers,
                )
                updated += 1
                # Attempt-counter ticks per ADR; escalate at 3 strikes.
                attempts = self._state.inc_adr_audit_attempts(rollup_key)
                # Fire escalation exactly once at the threshold — using
                # ``==`` not ``>=`` so subsequent ticks for a still-open
                # rollup don't file a fresh HITL issue every tick.
                if attempts == _MAX_ATTEMPTS:
                    await self._file_drift_escalation(rollup_key, attempts)
                    escalated += 1
                continue

            if dedup_key in dedup:
                # Rollup state was cleared (e.g. external close) but dedup not
                # yet reconciled — skip until reconcile catches up.
                continue

            attempts = self._state.inc_adr_audit_attempts(rollup_key)
            # Same once-at-threshold guard as the existing-rollup branch
            # above. ``_reconcile_closed_escalations`` resets attempts on
            # human close so a recurrence after close can re-escalate.
            if attempts == _MAX_ATTEMPTS:
                await self._file_drift_escalation(rollup_key, attempts)
                escalated += 1
            else:
                issue_number = await self._file_drift_rollup(entry.adr, new_pr_entries)
                if issue_number == 0:
                    # create_issue's documented 0-sentinel: the gh call
                    # failed. Don't record the rollup or add the dedup key —
                    # that would suppress re-filing forever without a real
                    # issue (next tick's `dedup_key in dedup` would skip).
                    # Retry next cycle.
                    logger.warning(
                        "adr_touchpoint_auditor: create_issue returned 0 "
                        "(sentinel) for %s rollup; skipping record/dedup, "
                        "will retry next cycle",
                        rollup_key,
                    )
                    continue
                self._state.set_adr_rollup(
                    rollup_key,
                    issue_number=issue_number,
                    pr_numbers=sorted(new_pr_numbers),
                )
                filed += 1
            dedup.add(dedup_key)
            self._dedup.set_all(dedup)

        fleet_filed, fleet_escalated = await self._process_fleet_batches(
            fleet_batches,
            adrs_resolved_this_tick=adrs_resolved_this_tick,
            pr_meta=pr_meta,
            dedup=dedup,
        )
        filed += fleet_filed
        escalated += fleet_escalated

        if new_cursor != cursor:
            self._state.set_adr_audit_cursor(new_cursor)

        self._emit_trace(t0, scanned=len(prs), filed=filed)
        return {
            "status": "ok",
            "scanned": len(prs),
            "filed": filed,
            "updated": updated,
            "closed": closed,
            "escalated": escalated,
        }

    def _emit_trace(self, t0: float, *, scanned: int, filed: int) -> None:
        try:
            from trace_collector import emit_loop_subprocess_trace  # noqa: PLC0415
        except ImportError:
            return
        duration_ms = int((time.perf_counter() - t0) * 1000)
        emit_loop_subprocess_trace(
            loop=self._worker_name,
            command=["gh", "pr", "list", "--state", "merged"],
            exit_code=0,
            duration_ms=duration_ms,
            stderr_excerpt=f"scanned={scanned} filed={filed}",
        )
