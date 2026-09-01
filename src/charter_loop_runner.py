"""One generic worker, parameterised by a repo's charter (#11861, ADR-0145).

HydraFlow's runners take their role from a catalogued Python class:
`DirectorTurnRunner`, `PlanWorkerRunner`, `ReviewWorkerRunner`. Adding an agent
to a repo therefore means adding a class to the factory. This takes its role
from the TARGET REPO's declaration instead — the loop's `actor` names a
markdown contract, and that contract is the system prompt.

The ownership split is the point: the repo declares which actors exist, what
each is for, when it runs and what done looks like; the factory owns worktree
isolation, PR lifecycle, gates, escalation, credit exhaustion and GC. The repo
half is markdown plus one YAML block. The factory half is machinery a repo
should never reimplement — and the parts a repo would get wrong are exactly the
parts it no longer writes.

**Scope.** Selection, dispatch, envelope, receipts and both refusal paths. Loop
registration, kill switch and dedup are #11866; the sandbox e2e layer is
#11863, on the epic's single shared fixture repo.

Three rulings are structural here rather than documented:

* **An unparseable actor contract REFUSES the run and alerts** — it never
  degrades to a default prompt. A default prompt produces plausible work
  attributed to an actor whose contract nobody could read, which is worse than
  no run because it looks like one (ADR-0145 Ruling 2).
* **A per-run `goal` override is allowed and RECORDED.** Unrecorded input is
  disqualifying; recorded input is fine. The receipt is what makes the
  difference, not the override (Ruling 1).
* **The runner never enables a loop and never writes `charter.yaml`.** Not by
  convention — it has no write path to either. Enabling is an ENACT belonging
  to a human (ADR-0143 Ruling 6 guard 4).
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from cron_window import CronError, fired_since

if TYPE_CHECKING:  # pragma: no cover - typing only
    from collections.abc import Callable, Mapping
    from pathlib import Path

    from charter_model import Charter, LoopSpec

logger = logging.getLogger(__name__)

#: Receipt outcomes. Every selection decision writes one, including the
#: negative ones: a loop that did not run for a reason nobody recorded is
#: indistinguishable from a loop nobody looked at.
OUTCOME_RAN = "ran"
OUTCOME_SKIPPED_DORMANT = "skipped-dormant"
OUTCOME_SKIPPED_NOT_DUE = "skipped-not-due"
OUTCOME_REFUSED_NO_CONTRACT = "refused-no-contract"
OUTCOME_REFUSED_BUDGET = "refused-budget"
OUTCOME_BAD_SCHEDULE = "refused-bad-schedule"


@dataclass(frozen=True)
class LoopDecision:
    """Why one loop did or did not run this tick. **Pure.**"""

    loop: str
    actor: str
    outcome: str
    detail: str = ""
    window: datetime | None = None
    trigger: str = ""

    @property
    def should_run(self) -> bool:
        return self.outcome == OUTCOME_RAN


@dataclass(frozen=True)
class RunReceipt:
    """What happened, in enough detail to audit without the transcript."""

    repo: str
    loop: str
    actor: str
    outcome: str
    observed_at: str
    window: str = ""
    trigger: str = ""
    goal: str = ""
    goal_overridden: bool = False
    budget_usd: float | None = None
    timeout_s: int | None = None
    model: str = ""
    branch: str = ""
    pr_url: str = ""
    cost_usd: float | None = None
    detail: str = ""

    def to_json(self) -> str:
        return json.dumps(self.__dict__, sort_keys=True)


def select_due_loops(
    charter: Charter,
    *,
    now: datetime,
    last_fired: Mapping[str, datetime | None],
) -> list[LoopDecision]:
    """Decide, for every declared loop, whether it runs. **Pure.**

    Returns a decision for EVERY loop, not only the due ones. A tick that
    reported just the runs would leave "dormant", "not due" and "never looked
    at" identical to a reader, and that distinction is the whole reason the
    receipt exists.

    Catch-up policy: a loop fires at most once per tick and never backfills.
    A factory down for a day must not wake and run a daily loop thirty times.
    """
    decisions: list[LoopDecision] = []
    for loop in charter.loops.loops:
        if not loop.enabled:
            decisions.append(
                LoopDecision(
                    loop=loop.name,
                    actor=loop.actor,
                    outcome=OUTCOME_SKIPPED_DORMANT,
                    detail="enabled: false — dormancy is a declared value",
                )
            )
            continue
        window: datetime | None = None
        fired_clause = ""
        bad: str = ""
        for clause in loop.triggers:
            try:
                candidate = fired_since(clause.cron, last_fired.get(loop.name), now)
            except CronError as exc:
                bad = str(exc)
                break
            if candidate is not None and (window is None or candidate > window):
                window, fired_clause = candidate, clause.cron
        if bad:
            # A schedule that cannot be evaluated is refused, never treated as
            # "not due" — the second reads as a healthy quiet loop forever.
            decisions.append(
                LoopDecision(
                    loop=loop.name,
                    actor=loop.actor,
                    outcome=OUTCOME_BAD_SCHEDULE,
                    detail=bad,
                )
            )
            continue
        if window is None:
            decisions.append(
                LoopDecision(
                    loop=loop.name,
                    actor=loop.actor,
                    outcome=OUTCOME_SKIPPED_NOT_DUE,
                    detail="no trigger clause fired since the last receipt",
                )
            )
            continue
        decisions.append(
            LoopDecision(
                loop=loop.name,
                actor=loop.actor,
                outcome=OUTCOME_RAN,
                window=window,
                trigger=fired_clause,
            )
        )
    return decisions


def resolve_actor_contract(actors_dir: Path, actor: str) -> str | None:
    """The actor's contract text, or None when it cannot be read.

    None means REFUSE — never "use a default". Both layouts are accepted
    (`x.md` and `x/README.md`) for the same reason the enumeration predicate
    accepts both: a narrower one stops seeing an actor the day it moves into a
    package, and a membership test that matches nothing simply returns nothing
    while the loop silently runs on a prompt nobody wrote (#11669).
    """
    for candidate in (actors_dir / f"{actor}.md", actors_dir / actor / "README.md"):
        try:
            if candidate.is_file():
                text = candidate.read_text(encoding="utf-8").strip()
                return text or None
        except OSError:
            logger.warning("charter-loop: could not read %s", candidate, exc_info=True)
            return None
    return None


@dataclass
class CharterLoopRunner:
    """Runs a repo's charter-declared loops. One runner, zero per-loop code."""

    repo: str
    repo_root: Path
    receipts_path: Path
    #: REQUIRED, and injected rather than imported. `file_util.append_jsonl`
    #: carries the ADR-0085 secret redaction and the fsync this durable audit
    #: stream needs, so the runner must be handed a writer that does that work
    #: — reimplementing the append inline would drop the redaction. It is
    #: injected because importing `file_util` here crosses the concentration
    #: ratchet's god-file threshold (fan-in 40), and the ratchet only shrinks.
    #: No default: a runner constructed without a writer would drop every
    #: receipt silently, and "no receipt" is the one thing this design cannot
    #: tolerate.
    receipt_writer: Callable[[Path, str], None]
    #: Injected so the runner is unit-testable without a broker, and so the
    #: dispatch surface stays the ONE place a goal override can enter.
    dispatch: Any = None
    #: Raised to the operator; never a filed issue. A refusal that files an
    #: issue looks like work in progress rather than a stop.
    alert: Any = None

    def _receipt(self, written: list[RunReceipt], receipt: RunReceipt) -> None:
        written.append(receipt)
        try:
            self.receipts_path.parent.mkdir(parents=True, exist_ok=True)
            self.receipt_writer(self.receipts_path, receipt.to_json())
        except OSError:
            logger.warning(
                "charter-loop: could not write a receipt to %s",
                self.receipts_path,
                exc_info=True,
            )

    async def tick(
        self,
        charter: Charter,
        *,
        now: datetime | None = None,
        last_fired: Mapping[str, datetime | None] | None = None,
        goal_overrides: Mapping[str, str] | None = None,
    ) -> list[RunReceipt]:
        """One pass: decide, dispatch the due loops, receipt every decision."""
        stamped = now or datetime.now(UTC)
        overrides = goal_overrides or {}
        decisions = select_due_loops(charter, now=stamped, last_fired=last_fired or {})
        # The actors directory is a CHARTER-level pointer, resolved once. A
        # per-loop override would be a second place to declare where actors
        # live — the two-tables shape, one field over.
        actors_dir = self.repo_root / charter.actors
        by_name = charter.loops.by_name()

        # Per-tick, deliberately not instance state: `tick()` reports what THIS
        # pass decided, and the durable history is the JSONL stream. An
        # instance accumulator would make every return value over-report
        # monotonically and retain the receipts for the process lifetime
        # (#11962).
        written: list[RunReceipt] = []

        for decision in decisions:
            if not decision.should_run:
                self._receipt(
                    written,
                    RunReceipt(
                        repo=self.repo,
                        loop=decision.loop,
                        actor=decision.actor,
                        outcome=decision.outcome,
                        observed_at=stamped.isoformat(),
                        detail=decision.detail,
                    ),
                )
                continue
            await self._run_one(
                by_name[decision.loop],
                decision,
                stamped,
                overrides,
                actors_dir,
                written,
            )
        return written

    async def _run_one(
        self,
        loop: LoopSpec,
        decision: LoopDecision,
        stamped: datetime,
        overrides: Mapping[str, str],
        actors_dir: Path,
        written: list[RunReceipt],
    ) -> None:
        contract = resolve_actor_contract(actors_dir, loop.actor)
        if contract is None:
            # Ruling 2: refuse and ALERT. No issue, no default prompt.
            detail = (
                f"actor '{loop.actor}' has no readable contract; the run is "
                "refused rather than dispatched on a default prompt, which "
                "would produce plausible work attributed to an actor nobody "
                "could read (ADR-0145 Ruling 2)"
            )
            if self.alert is not None:
                await self.alert(repo=self.repo, loop=loop.name, detail=detail)
            self._receipt(
                written,
                RunReceipt(
                    repo=self.repo,
                    loop=loop.name,
                    actor=loop.actor,
                    outcome=OUTCOME_REFUSED_NO_CONTRACT,
                    observed_at=stamped.isoformat(),
                    window=decision.window.isoformat() if decision.window else "",
                    trigger=decision.trigger,
                    detail=detail,
                ),
            )
            return

        override = overrides.get(loop.name, "")
        goal = override or loop.goal
        result: dict[str, Any] = {}
        if self.dispatch is not None:
            result = (
                await self.dispatch(
                    repo=self.repo,
                    loop=loop.name,
                    actor=loop.actor,
                    system_prompt=contract,
                    goal=goal,
                    budget_usd=loop.budget_usd,
                    timeout_s=loop.timeout_s,
                    model=loop.model,
                    branch_prefix=loop.output.branch_prefix,
                )
                or {}
            )

        refused = bool(result.get("budget_refused"))
        self._receipt(
            written,
            RunReceipt(
                repo=self.repo,
                loop=loop.name,
                actor=loop.actor,
                outcome=OUTCOME_REFUSED_BUDGET if refused else OUTCOME_RAN,
                observed_at=stamped.isoformat(),
                window=decision.window.isoformat() if decision.window else "",
                trigger=decision.trigger,
                goal=goal,
                goal_overridden=bool(override),
                budget_usd=loop.budget_usd,
                timeout_s=loop.timeout_s,
                model=loop.model,
                branch=str(result.get("branch", "")),
                pr_url=str(result.get("pr_url", "")),
                cost_usd=result.get("cost_usd"),
                detail=str(result.get("detail", "")),
            ),
        )
