"""IssueGroomerLoop — backlog-wide dedup, priority scoring, rolling operator digest.

Spec: ``docs/superpowers/specs/2026-07-19-issue-groomer-loop-design.md`` (#9957).

The loop is the integration core: it owns all GitHub I/O (via ``PRPort``) and
all LLM spend (via an injectable ``groom_llm.complete``), and delegates every
content decision to the pure engine in :mod:`issue_groomer` (index diff,
candidate prefilter, judged-pair cache, judgment prompts, action tiering,
guardrails, digest render). The engine never calls an LLM or the clock; this
loop threads both in.

Tick pipeline (spec §3, steps 1-6):

1. Fetch the open backlog (``list_open_issues``), drop the groomer's own
   rolling digest issue (by stored number AND ``hydraflow-groom-digest``
   label) so its every-tick self-update never re-triggers a groom, then diff
   the rest against the persisted change-detection index → the *changed* set
   (new issues count as changed). A weekly full sweep
   (``groom_last_full_sweep`` marker) treats every open issue as changed.
2. Prefilter duplicate-candidate pairs among the changed set, within the
   per-tick ``issue_groomer_pair_budget``; judge each with one structured LLM
   call. An unparseable/failed verdict degrades to a low-confidence digest
   proposal and the pair is still cached (no re-spend next tick).
3. Score priority for changed issues lacking a P-label (all issues on a full
   sweep).
4. Tier the judged verdicts + priority scores into concrete actions, then
   apply them: exact-dup/high pairs auto-close, gating every side effect on a
   still-open re-check + a confirmed close (stale-guard → evidence comment →
   close → ``groomed-auto`` label); safe priority deltas relabel. Every apply
   is wrapped per-action — one failure never aborts the tick, and credit/auth
   errors always reraise. A failed/stale close leaves the pair un-cached so it
   re-judges next tick.
4b. Accumulate still-open operator questions (dup proposals + priority
    questions) in ``groom_open_proposals``, pruned to the live backlog, so the
    digest renders EVERY open question, not just this tick's.
5. Rewrite the rolling digest issue, recovering it if the stored issue was
   closed (reopen if supported, else mint a fresh one) or if state lost the
   number but the create-once dedup key survives (adopt the open digest found
   by label).
6. Persist index + judged-pair cache + full-sweep marker + open proposals, and
   publish one ``GROOM_UPDATE`` event for the dashboard.

Kill-switch (ADR-0049): ``_enabled_cb`` AND ``issue_groomer_enabled`` both gate
the tick at the top. An empty backlog, or no changes with no full sweep due, is
a cheap no-op — no LLM calls.
"""

from __future__ import annotations

import itertools
import logging
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Protocol

from base_background_loop import BaseBackgroundLoop, LoopDeps
from events import EventType, HydraFlowEvent
from exception_classify import reraise_on_credit_or_bug
from execution import get_default_runner
from issue_groomer import (
    AutoClose,
    DupVerdict,
    GroomActions,
    GroomIssue,
    PriorityVerdict,
    RelabelAction,
    VerdictParseError,
    body_hash,
    build_dup_judgment_prompt,
    build_priority_prompt,
    find_dup_candidates,
    is_guarded,
    merge_open_proposals,
    open_proposals_to_actions,
    pair_key,
    parse_dup_verdict,
    parse_priority_verdict,
    plan_actions,
    prune_open_proposals,
    render_digest,
)
from runner_utils import run_lightweight_agent

if TYPE_CHECKING:
    from config import HydraFlowConfig
    from dedup_store import DedupStore
    from loop_fitness import FitnessContext, LoopFitness
    from models import GitHubIssueSummary, WorkCycleResult
    from pr_manager import PRManager
    from state import StateTracker

logger = logging.getLogger("hydraflow.issue_groomer_loop")

# Digest issue identity — single-sourced so create + update never drift.
_DIGEST_TITLE = "Groom digest — backlog health"
_DIGEST_LABEL = "hydraflow-groom-digest"
_DIGEST_DEDUP_KEY = "issue_groomer:digest"

# Applied to an auto-closed duplicate so the fitness scorer (loop_fitness) can
# attribute closes back to the groomer and a human can spot auto-actions.
_GROOMED_AUTO_LABEL = "groomed-auto"

# Priority labels the groomer manages. Mirrors ``issue_groomer._PRIORITY_LABELS``
# (kept local rather than importing a private) — used only to skip re-scoring an
# already-prioritised issue on an incremental tick.
_PRIORITY_LABELS: tuple[str, ...] = ("P0", "P1", "P2")

# Hard bound on one structured judgment/priority LLM call (seconds). Mirrors the
# refine loop's per-call bound; the LONG_LLM_CYCLE watchdog bounds the whole tick.
_GROOM_LLM_TIMEOUT_SECONDS = 300


class _GroomLLM(Protocol):
    """Minimal one-shot text-completion seam for judgment/priority calls.

    Tests inject a fake; production lazily builds :class:`_CLIGroomLLM`.
    """

    async def complete(self, prompt: str) -> str: ...


class _CLIGroomLLM:
    """Production groom client: one-shot RAW-text completion via the shared
    lightweight-agent seam (credit-aware, telemetried).

    Returns the CLI's raw stdout so the caller can parse the structured JSON
    verdict. Never exercised under test; the loop's ``groom_llm`` kwarg injects
    a fake for all unit coverage.
    """

    def __init__(self, config: HydraFlowConfig, model: str) -> None:
        self._config = config
        self._model = model

    async def complete(self, prompt: str) -> str:
        result = await run_lightweight_agent(
            runner=get_default_runner(),
            config=self._config,
            tool="claude",
            model=self._model,
            prompt=prompt,
            source="issue_groomer",
            timeout=float(_GROOM_LLM_TIMEOUT_SECONDS),
            issue_labels=(),
        )
        if result.returncode != 0:
            msg = f"groom LLM failed (rc={result.returncode}): {result.stderr[:200]}"
            raise RuntimeError(msg)
        return result.stdout


class IssueGroomerLoop(BaseBackgroundLoop):
    """Backlog-wide dedup + priority scoring + rolling operator digest (#9957)."""

    # Judgment + priority scoring spend LLM calls, so the loop earns the longer
    # per-cycle watchdog bound (#9455 / #9556).
    LONG_LLM_CYCLE = True

    def __init__(
        self,
        *,
        config: HydraFlowConfig,
        state: StateTracker,
        pr_manager: PRManager,
        dedup: DedupStore,
        deps: LoopDeps,
        groom_llm: _GroomLLM | None = None,
    ) -> None:
        super().__init__(
            worker_name="issue_groomer",
            config=config,
            deps=deps,
            run_on_startup=False,
        )
        self._state = state
        self._pr = pr_manager
        self._dedup = dedup
        # Injected fake under test; production lazily builds `_CLIGroomLLM`.
        self._groom_llm = groom_llm

    def _get_default_interval(self) -> int:
        return self._config.issue_groomer_interval

    def loop_fitness(self, ctx: FitnessContext) -> LoopFitness:
        # Objective: auto-close precision. Of the duplicates the groomer
        # auto-closed (``groomed-auto`` label) in the window, how many stayed
        # closed rather than being reopened by a human — a reopened auto-close
        # is a false-positive dedup and scores against the loop. Pure over ctx.
        from loop_fitness import proposal_acceptance_fitness

        return proposal_acceptance_fitness(
            ctx,
            worker_name=self._worker_name,
            label=_GROOMED_AUTO_LABEL,
            min_samples=self._config.fitness_min_samples,
        )

    # --- LLM seam -------------------------------------------------------------

    async def _groom_complete(self, prompt: str) -> str:
        """Complete *prompt* via the injected fake or a lazily-built CLI client."""
        if self._groom_llm is None:
            model = (
                self._config.issue_groomer_model
                or self._config.background_model
                or "sonnet"
            )
            self._groom_llm = _CLIGroomLLM(self._config, model)
        return await self._groom_llm.complete(prompt)

    # --- Tick -----------------------------------------------------------------

    async def _do_work(self) -> WorkCycleResult:
        """One groom tick (spec §3, steps 1-6)."""
        # Kill-switch (ADR-0049): UI toggle AND static config, in-body so the
        # gate is testable and survives catchup/direct-invocation paths.
        if not self._enabled_cb(self._worker_name):
            return {"status": "disabled"}
        if not self._config.issue_groomer_enabled:
            return {"status": "disabled"}

        now = datetime.now(UTC)

        # 1. Fetch backlog. Drop the groomer's own rolling digest issue up front
        # (by stored number AND by label) so its every-tick self-update never
        # re-marks it "changed" and drives an endless non-quiet loop — a quiet
        # tick after a groom must genuinely short-circuit (spec #9957, review
        # finding: digest self-participation).
        raw_issues = await self._pr.list_open_issues()
        digest_number = self._state.get_groom_digest_issue()
        issues = [
            groomed
            for r in raw_issues
            if (groomed := self._to_groom_issue(r)).number != digest_number
            and _DIGEST_LABEL not in groomed.labels
        ]
        if not issues:
            # Empty backlog: prune the index, heartbeat only (no LLM, no event).
            self._state.set_groom_index({})
            return self._noop_stats(backlog=0)

        issues_by_number = {issue.number: issue for issue in issues}

        # 1b. Change-detection diff against the persisted index.
        stored_index = self._state.get_groom_index()
        new_index = {str(issue.number): self._index_entry(issue) for issue in issues}
        changed = self._compute_changed(stored_index, new_index)

        # 1c. Weekly full sweep — treat every open issue as changed.
        last_sweep = self._state.get_groom_last_full_sweep()
        full_sweep = last_sweep is None or (now - last_sweep) >= timedelta(
            seconds=self._config.issue_groomer_full_sweep_interval
        )
        if full_sweep:
            changed = {issue.number for issue in issues}

        if not changed and not full_sweep:
            # Nothing new since last tick and no sweep due — persist the pruned
            # index and short-circuit before any LLM spend.
            self._state.set_groom_index(new_index)
            return self._noop_stats(backlog=len(issues))

        # 2. Duplicate-candidate prefilter + per-pair judgment.
        judged_keys = set(self._state.get_judged_pairs())
        cache_hits = self._count_cache_hits(issues, changed, judged_keys)
        candidates = find_dup_candidates(
            issues, changed, judged_keys, self._config.issue_groomer_pair_budget
        )
        verdicts: dict[tuple[int, int], DupVerdict] = {}
        newly_judged: list[str] = []
        judge_errors = 0
        for cand in candidates:
            issue_a = issues_by_number[cand.a]
            issue_b = issues_by_number[cand.b]
            key = pair_key(issue_a, issue_b)
            prompt = build_dup_judgment_prompt(issue_a, issue_b)
            try:
                raw = await self._groom_complete(prompt)
            except Exception as exc:  # noqa: BLE001 — classify then fail-soft
                reraise_on_credit_or_bug(exc)
                logger.warning(
                    "groom dup judgment failed for #%d/#%d: %s",
                    cand.a,
                    cand.b,
                    exc,
                )
                judge_errors += 1
                # Transport failure (not a bad verdict): leave uncached so the
                # pair is retried next tick rather than silently dropped.
                continue
            try:
                verdicts[(cand.a, cand.b)] = parse_dup_verdict(raw)
            except VerdictParseError as exc:
                # Unparseable/refused verdict → low-confidence digest proposal,
                # but STILL cache the pair (spec §Error handling: avoid re-spend).
                logger.warning(
                    "groom dup verdict unparseable for #%d/#%d: %s",
                    cand.a,
                    cand.b,
                    exc,
                )
                verdicts[(cand.a, cand.b)] = DupVerdict(
                    verdict="likely_dup",
                    canonical=min(cand.a, cand.b),
                    evidence="LLM returned an unparseable verdict — queued for "
                    "manual review",
                    confidence="low",
                )
            newly_judged.append(key)

        # 3. Priority scoring for the changed set (all issues on a full sweep).
        priorities: dict[int, PriorityVerdict] = {}
        for issue in self._priority_targets(issues, changed, full_sweep=full_sweep):
            prompt = build_priority_prompt(issue)
            try:
                raw = await self._groom_complete(prompt)
            except Exception as exc:  # noqa: BLE001 — classify then fail-soft
                reraise_on_credit_or_bug(exc)
                logger.warning(
                    "groom priority scoring failed for #%d: %s", issue.number, exc
                )
                continue
            try:
                priorities[issue.number] = parse_priority_verdict(raw)
            except VerdictParseError as exc:
                # A bad priority verdict is silently skipped (the priority
                # asymmetry, spec §2): it is re-scored on the next change/sweep,
                # so digesting it every tick would only bury the operator.
                logger.warning(
                    "groom priority verdict unparseable for #%d: %s",
                    issue.number,
                    exc,
                )
                continue

        # 4. Tier + apply. A failed/stale auto-close returns the pair so we do
        # NOT cache it — it must re-judge next tick against fresh content.
        actions = plan_actions(verdicts, priorities, issues_by_number, now)
        closed, relabeled, failures, uncache_pairs = await self._apply(actions)
        if uncache_pairs:
            stale_keys = {
                pair_key(issues_by_number[a], issues_by_number[b])
                for a, b in uncache_pairs
                if a in issues_by_number and b in issues_by_number
            }
            newly_judged = [k for k in newly_judged if k not in stale_keys]

        # 4b. Accumulate open operator questions across ticks: merge this tick's
        # dup proposals + priority questions into the persisted set, prune the
        # ones whose issues left the backlog or whose P-label the operator has
        # since changed, and render the WHOLE open set — a question first raised
        # earlier stays visible until it is actioned (spec #9957, review finding:
        # proposal persistence).
        current_labels = {i.number: self._current_priority_label(i) for i in issues}
        open_proposals = prune_open_proposals(
            merge_open_proposals(
                self._state.get_groom_open_proposals(), actions, now.isoformat()
            ),
            current_labels,
        )
        self._state.set_groom_open_proposals(open_proposals)
        digest_actions = open_proposals_to_actions(actions, open_proposals)

        # 5. Rolling digest. Stats measure THIS tick's flow (new work); the
        # digest's Operator-questions section renders the accumulated open set.
        stats = {
            "backlog": len(issues),
            "changed": len(changed),
            "full_sweep": full_sweep,
            "judged": len(newly_judged),
            "cache_hits": cache_hits,
            "judge_errors": judge_errors,
            "closed": closed,
            "relabeled": relabeled,
            "proposals": len(actions.dup_proposals),
            "priority_questions": len(actions.priority_questions),
            "open_questions": len(open_proposals),
            "skipped_rows": actions.skipped_rows,
            "apply_failures": len(failures),
        }
        await self._write_digest(digest_actions, stats, failures)

        # 6. Persist + publish.
        self._state.set_groom_index(new_index)
        if newly_judged:
            self._state.add_judged_pairs(newly_judged)
        if full_sweep:
            self._state.set_groom_last_full_sweep(now)

        if failures:
            logger.warning(
                "groom: %d apply failure(s) this tick: %s", len(failures), failures
            )
        if actions.skipped_rows:
            logger.warning(
                "groom: %d priority row(s) skipped (malformed record)",
                actions.skipped_rows,
            )

        await self._publish_groom_event(
            closed=closed,
            relabeled=relabeled,
            proposals=len(actions.dup_proposals),
            judged=len(newly_judged),
            cache_hits=cache_hits,
        )
        return {"status": "ok", **stats}

    # --- Apply ----------------------------------------------------------------

    async def _apply(
        self, actions: GroomActions
    ) -> tuple[int, int, list[str], list[tuple[int, int]]]:
        """Apply auto-closes + relabels, isolating each action.

        Returns ``(closed, relabeled, failures, uncache_pairs)``. A single
        failing action is recorded and surfaced in the digest but never aborts
        the tick; a credit/auth error always reraises
        (``reraise_on_credit_or_bug``). ``uncache_pairs`` are the
        ``(canonical, duplicate)`` pairs whose close failed or was stale — the
        caller drops their judged-pair keys so they re-judge next tick rather
        than being cached against a close that never landed.
        """
        closed = 0
        relabeled = 0
        failures: list[str] = []
        uncache_pairs: list[tuple[int, int]] = []

        for close in actions.auto_closes:
            try:
                await self._apply_auto_close(close)
                closed += 1
            except Exception as exc:  # noqa: BLE001 — classify then fail-soft
                reraise_on_credit_or_bug(exc)
                logger.warning(
                    "groom auto-close failed for #%d: %s", close.duplicate, exc
                )
                failures.append(f"close #{close.duplicate}: {exc}")
                uncache_pairs.append((close.canonical, close.duplicate))

        for relabel in actions.relabels:
            try:
                await self._apply_relabel(relabel)
                relabeled += 1
            except Exception as exc:  # noqa: BLE001 — classify then fail-soft
                reraise_on_credit_or_bug(exc)
                logger.warning("groom relabel failed for #%d: %s", relabel.number, exc)
                failures.append(f"relabel #{relabel.number}: {exc}")

        return closed, relabeled, failures, uncache_pairs

    async def _apply_auto_close(self, close: AutoClose) -> None:
        """Close the duplicate, gating every side effect on a confirmed close.

        Order is stale-guard -> comment -> close -> label:

        * Stale guard (review finding): re-read BOTH the duplicate and the
          canonical via the port and abort unless both are still ``OPEN`` —
          another loop or a human may have closed/merged one between the
          judgment read and now, and closing on a stale verdict is the exact
          false-positive dedup the fitness scorer punishes.
        * The ``groomed-auto`` label is added ONLY after the close reaches
          GitHub, so a failed close never leaves the fitness-attribution label
          on a still-open issue. ``close_issue`` returns False (rather than
          raising) on a gh failure; treat that as a failed action.
        """
        dup_state = await self._pr.get_issue_state(close.duplicate)
        canon_state = await self._pr.get_issue_state(close.canonical)
        if dup_state != "OPEN" or canon_state != "OPEN":
            msg = (
                "stale judgment — issue state changed mid-tick "
                f"(#{close.duplicate}={dup_state}, #{close.canonical}={canon_state})"
            )
            raise RuntimeError(msg)

        await self._pr.post_comment(
            close.duplicate,
            f"**Groom (auto):** duplicate of #{close.canonical} — {close.evidence}",
        )
        ok = await self._pr.close_issue(close.duplicate)
        if not ok:
            msg = f"close_issue returned False for #{close.duplicate}"
            raise RuntimeError(msg)
        await self._pr.add_labels(close.duplicate, [_GROOMED_AUTO_LABEL])

    async def _apply_relabel(self, relabel: RelabelAction) -> None:
        """Add the new P-label and remove the previous one if there was one."""
        await self._pr.add_labels(relabel.number, [relabel.priority])
        if relabel.previous in _PRIORITY_LABELS:
            await self._pr.remove_label(relabel.number, relabel.previous)

    # --- Digest ---------------------------------------------------------------

    async def _write_digest(
        self, actions: GroomActions, stats: dict[str, object], failures: list[str]
    ) -> None:
        """Create the digest issue on first run, else rewrite its body.

        Recovers from two ways the rolling digest can go missing (review
        finding: digest recovery):

        * The stored issue was CLOSED (a human tidied the backlog, or a stale
          GC pass closed it). Reopen it if the port supports reopening, else
          mint a fresh digest and re-point state at it — never silently write
          the body of a closed issue nobody is watching.
        * State lost the number (reset to 0) but the create-once dedup key
          survives, so a real digest is out there. Read-then-adopt: find the
          open ``hydraflow-groom-digest`` issue by label and reclaim it before
          creating a duplicate.
        """
        body = render_digest(actions, stats)
        if failures:
            body += "\n## Apply failures\n" + "\n".join(f"- {f}" for f in failures)
            body += "\n"

        digest_number = self._state.get_groom_digest_issue()
        if digest_number > 0:
            if await self._pr.get_issue_state(digest_number) == "OPEN":
                await self._pr.update_issue_body(digest_number, body)
                return
            if await self._reopen_digest(digest_number):
                await self._pr.update_issue_body(digest_number, body)
                return
            # Closed and un-reopenable — fall through to mint a fresh digest.
        elif _DIGEST_DEDUP_KEY in self._dedup.get():
            adopted = await self._find_open_digest_by_label()
            if adopted > 0:
                self._state.set_groom_digest_issue(adopted)
                await self._pr.update_issue_body(adopted, body)
                return

        created = await self._pr.create_issue(_DIGEST_TITLE, body, [_DIGEST_LABEL])
        if created > 0:
            self._state.set_groom_digest_issue(created)
            dedup = self._dedup.get()
            dedup.add(_DIGEST_DEDUP_KEY)
            self._dedup.set_all(dedup)

    async def _reopen_digest(self, number: int) -> bool:
        """Reopen the digest issue if the port exposes a ``reopen_issue`` seam.

        Capability-probed rather than assumed: the current ``PRPort`` has no
        reopen method, so this returns False and the caller mints a fresh
        digest. Kept as a seam so a port that later grows reopen support
        reuses the rolling issue instead of churning a new one each recovery.
        """
        reopen = getattr(self._pr, "reopen_issue", None)
        if reopen is None:
            return False
        try:
            result = await reopen(number)
        except Exception as exc:  # noqa: BLE001 — classify then fail-soft
            reraise_on_credit_or_bug(exc)
            logger.warning("groom digest reopen failed for #%d: %s", number, exc)
            return False
        return result is not False

    async def _find_open_digest_by_label(self) -> int:
        """Return the lowest-numbered open ``hydraflow-groom-digest`` issue, or 0."""
        labeled = await self._pr.list_issues_by_label(_DIGEST_LABEL)
        numbers = [int(item.get("number", 0)) for item in labeled]
        open_numbers = [n for n in numbers if n > 0]
        return min(open_numbers) if open_numbers else 0

    async def _publish_groom_event(
        self,
        *,
        closed: int,
        relabeled: int,
        proposals: int,
        judged: int,
        cache_hits: int,
    ) -> None:
        """Publish one GROOM_UPDATE event summarising the tick (dashboard)."""
        await self._bus.publish(
            HydraFlowEvent(
                type=EventType.GROOM_UPDATE,
                data={
                    "worker": self._worker_name,
                    "closed": closed,
                    "relabeled": relabeled,
                    "proposals": proposals,
                    "judged": judged,
                    "cache_hits": cache_hits,
                },
            )
        )

    # --- Helpers --------------------------------------------------------------

    @staticmethod
    def _to_groom_issue(raw: GitHubIssueSummary) -> GroomIssue:
        labels = tuple(
            str(lbl.get("name", ""))
            for lbl in (raw.get("labels") or [])
            if isinstance(lbl, dict) and lbl.get("name")
        )
        return GroomIssue(
            number=int(raw.get("number", 0)),
            title=str(raw.get("title", "")),
            body=str(raw.get("body", "")),
            labels=labels,
            updated_at=str(raw.get("updated_at", "")),
        )

    @staticmethod
    def _index_entry(issue: GroomIssue) -> dict[str, str]:
        """Small change-detection projection persisted per issue.

        A change to the title, body, or ``updated_at`` re-marks the issue as
        changed next tick (``body_hash`` also normalises the title cheaply).
        """
        return {
            "title_hash": body_hash(issue.title),
            "body_hash": body_hash(issue.body),
            "updated_at": issue.updated_at,
        }

    @staticmethod
    def _compute_changed(
        stored: dict[str, dict[str, str]], current: dict[str, dict[str, str]]
    ) -> set[int]:
        """Issue numbers whose index entry is new or differs from the stored one.

        Issues absent from ``current`` (closed since last tick) are naturally
        excluded — they need no grooming and drop from the index on persist.
        """
        changed: set[int] = set()
        for key, entry in current.items():
            if stored.get(key) != entry:
                changed.add(int(key))
        return changed

    def _priority_targets(
        self, issues: list[GroomIssue], changed: set[int], *, full_sweep: bool
    ) -> list[GroomIssue]:
        """Issues to score for priority this tick.

        Full sweep: every unguarded issue (re-score even already-P-labelled
        ones). Incremental: changed, unguarded issues that lack a P-label —
        scoring an already-prioritised issue would only spend an LLM call for a
        no-op delta.
        """
        targets: list[GroomIssue] = []
        for issue in issues:
            if is_guarded(issue):
                continue
            if full_sweep:
                targets.append(issue)
                continue
            if issue.number in changed and not self._has_priority_label(issue):
                targets.append(issue)
        return targets

    @staticmethod
    def _has_priority_label(issue: GroomIssue) -> bool:
        return any(label in issue.labels for label in _PRIORITY_LABELS)

    @staticmethod
    def _current_priority_label(issue: GroomIssue) -> str:
        """The issue's current P-label, or ``"none"``. Mirrors the engine's
        private ``_current_priority_label`` so the loop can build the
        live-label map ``prune_open_proposals`` needs without importing a
        private helper across modules."""
        for label in _PRIORITY_LABELS:
            if label in issue.labels:
                return label
        return "none"

    @staticmethod
    def _count_cache_hits(
        issues: list[GroomIssue], changed: set[int], judged_keys: set[str]
    ) -> int:
        """Judged-pair keys the cache spared us re-judging this tick.

        Counts changed-side pairs whose exact (numbers + body hashes) key is
        already cached — the re-spend the cache saved. Skipped entirely when
        the cache is empty. O(n^2) over the backlog like the engine prefilter,
        but only two body-hashes per pair (no similarity scoring), so it is far
        cheaper than the judgment pass it accounts for.
        """
        if not judged_keys:
            return 0
        hits = 0
        for x, y in itertools.combinations(issues, 2):
            if x.number not in changed and y.number not in changed:
                continue
            if pair_key(x, y) in judged_keys:
                hits += 1
        return hits

    @staticmethod
    def _noop_stats(*, backlog: int) -> dict[str, object]:
        return {
            "status": "ok",
            "backlog": backlog,
            "changed": 0,
            "judged": 0,
            "cache_hits": 0,
            "closed": 0,
            "relabeled": 0,
            "proposals": 0,
        }
