"""The fenced per-issue driver — one servo, one issue, one owner (#11535).

ADR-0137 permits this object only because it has three properties, and this
module is where all three are actually implemented:

* it **never becomes a second source of truth** — the pipeline label is re-read
  at the start of every boundary and written as the boundary's durable commit
  (C1/C5), and an externally changed label preempts the driver rather than being
  clobbered by it;
* it **never holds capacity while not working** — that is the manager's job, but
  the states it reports are what the manager reads (C6);
* it is **fenced and bounded by code** — a lease epoch and a phase attempt, both
  checked again after the phase's subprocess returns, so a result from a driver
  generation that no longer owns the issue cannot commit (C7).

**The boundary is a transaction with a fixed order** (ADR-0137 C8). Given a
phase that has just produced output::

    validate  ->  persist artifact under an idempotency key
              ->  swap the label   <-- THE DURABLE COMMIT
              ->  append the checkpoint
              ->  admit the next phase

A crash before the swap replays the idempotent persist and re-runs the phase; a
crash after it recovers from label truth even though the checkpoint never landed.
Getting this order wrong is how a ledger entry comes to record a transition the
label never committed, which would poison replay — so the order is expressed
here as one straight-line sequence with nothing between the steps, and
``tests/regressions/test_issue_11535_kill_mid_transition.py`` kills the process
in both gaps and asserts recovery lands on the right stage either way.

What this module is **not**: it is not a scheduler (that is
:mod:`issue_driver_policy` deciding and :mod:`driver_manager` allocating), and
it does not know how any phase does its work (that is
:mod:`driver_phase_adapters` wrapping the existing stage workers unchanged).
"""

from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from typing import TYPE_CHECKING, Protocol

from driver_contracts import DriverCheckpoint, DriverLease, DriverPhase, RejectionReason
from exception_classify import reraise_on_credit_or_bug
from issue_driver_policy import (
    TERMINAL_DRIVER_STATES,
    admit_phase_result,
    boundary_idempotency_key,
    phase_for_state,
)

if TYPE_CHECKING:
    from collections.abc import Mapping

    from models import Task

logger = logging.getLogger("issue_driver")

#: How long a phase lease is valid for. Generous relative to a phase subprocess
#: because expiry is a backstop against a wedged driver, not a phase timeout —
#: the phase's own timeout is the primary bound and is unchanged by this work.
DEFAULT_LEASE_TTL_SECONDS = 6 * 60 * 60


class AdvanceOutcome(StrEnum):
    """What one call to :meth:`IssueDriver.advance` did.

    Deterministic codes rather than booleans, because the canary's evidence bar
    (ADR-0137 B5) counts these directly: ``REJECTED`` with a stale-epoch reason
    *is* the ownership-theft counter, and ``ALREADY_COMMITTED`` is the
    idempotent-re-entry counter.
    """

    COMMITTED = "committed"
    """The phase ran and its boundary transaction completed."""

    ALREADY_COMMITTED = "already_committed"
    """Idempotent re-entry: this exact boundary was already committed."""

    PREEMPTED = "preempted"
    """The live label moved underneath the driver; it adopted the label."""

    REJECTED = "rejected"
    """A fence refused the result. ``reason`` says which."""

    FAILED = "failed"
    """The phase ran and reported failure; the attempt counter advanced."""

    RETIRED = "retired"
    """The issue reached a terminal state; the driver is done."""


@dataclass(frozen=True)
class PhaseOutcome:
    """What a single-item phase adapter reports back.

    ``next_label`` is the pipeline label this phase nominally takes the issue
    to. The driver reads the live label back and commits the swap only if the
    stage worker did not already make it, so declaring a target that the worker
    itself commits is correct and not a double write. ``None`` means the phase
    leaves the pipeline entirely (a merged issue).

    ``next_state`` overrides the state the driver derives from ``next_label``,
    and exists for exactly the states that have no pipeline label of their own —
    the terminal ones, and ``HITL_WAIT``, which shares the HITL label with
    ``HITL_APPLY`` but means "waiting on a human", not "working".
    """

    ok: bool
    next_label: str | None = None
    next_state: str | None = None
    artifact: Mapping[str, object] = field(default_factory=dict)
    detail: str = ""


@dataclass(frozen=True)
class DriverAdvance:
    """The record of one boundary attempt, suitable for a log line or a metric."""

    issue_number: int
    driver_id: str
    epoch: int
    phase: DriverPhase | None
    outcome: AdvanceOutcome
    state: str
    reason: RejectionReason | None = None
    detail: str = ""


class PhaseAdapter(Protocol):
    """A single-item runner for one pipeline phase.

    Deliberately narrow: the driver hands it one task and a lease and gets one
    outcome back. Everything about *how* the phase works — its prompt, its
    output markers, its subprocess, its retries — stays inside the existing
    stage worker the adapter wraps.
    """

    @property
    def phase(self) -> DriverPhase: ...

    @property
    def target_label(self) -> str | None:
        """The pipeline label this phase nominally moves the issue to.

        Declared up front, before the phase runs, because ADR-0137 C5(a)
        requires the transition intent to be recorded *before* anything can
        move the label — and on the nominal path the stage worker moves it
        itself, inside ``run``. ``None`` means this phase declares no single
        target (review may merge or route back; HITL stays put), so no stage
        intent is recorded for it.
        """
        ...

    async def run(self, task: Task, *, lease: DriverLease) -> PhaseOutcome: ...


class DriverLabels(Protocol):
    """Read, record intent for, and commit the issue's pipeline label.

    Labels are the truth; the intent record is how a crash *inside* the
    non-atomic swap is resolved without guessing a direction (ADR-0137 C5(a)).
    """

    async def read_stage_label(
        self, issue_number: int, *, epoch: int = 0, phase_attempt: int = 0
    ) -> str | None: ...

    def record_intent(
        self,
        issue_number: int,
        *,
        from_label: str,
        to_label: str,
        epoch: int,
        phase_attempt: int,
    ) -> None: ...

    def clear_intent(self, issue_number: int) -> None: ...

    async def commit_stage_label(self, issue_number: int, label: str) -> None: ...


class DriverJournalWriter(Protocol):
    """Durable, append-only record of committed boundaries.

    Not a source of truth — a cache and an audit trail. Recovery reads labels
    first (ADR-0137 C2) and consults the journal only to recognise a boundary it
    has already committed, so a lost journal costs a repeated idempotent step,
    never a wrong stage.
    """

    def committed_keys(self, issue_number: int) -> frozenset[str]: ...

    def persist_artifact(
        self, issue_number: int, key: str, artifact: Mapping[str, object]
    ) -> None: ...

    def append_checkpoint(
        self, issue_number: int, key: str, checkpoint: DriverCheckpoint
    ) -> None: ...


def _artifact_digest(artifact: Mapping[str, object]) -> str:
    """A stable digest of a boundary artifact, for the checkpoint record."""
    material = "|".join(f"{k}={artifact[k]!r}" for k in sorted(artifact))
    return hashlib.sha256(material.encode("utf-8", "replace")).hexdigest()[:32]


class IssueDriver:
    """Owns one issue across phases under ``issue_controller`` scheduling.

    Constructed by :class:`driver_manager.DriverManager` when a slot is granted
    and retired when the issue reaches a terminal state or the driver is fenced
    out. It holds no GitHub client and no config object: every effect goes
    through an injected port, which is what makes the whole boundary transaction
    testable — including by killing it between two of its steps.
    """

    def __init__(
        self,
        *,
        issue_number: int,
        driver_id: str,
        repo_slug: str,
        adapters: Mapping[DriverPhase, PhaseAdapter],
        labels: DriverLabels,
        journal: DriverJournalWriter,
        stage_labels: Mapping[str, str],
        driver_state: str = "TRIAGE",
        epoch: int = 0,
        lease_ttl_seconds: int = DEFAULT_LEASE_TTL_SECONDS,
    ) -> None:
        self._issue_number = issue_number
        self._driver_id = driver_id
        self._repo_slug = repo_slug
        self._adapters = adapters
        self._labels = labels
        self._journal = journal
        self._stage_labels = stage_labels
        self._state = driver_state
        self._epoch = epoch
        self._lease_ttl_seconds = lease_ttl_seconds
        self._phase_attempts: dict[DriverPhase, int] = {}

    # -- identity -----------------------------------------------------------

    @property
    def issue_number(self) -> int:
        return self._issue_number

    @property
    def driver_id(self) -> str:
        return self._driver_id

    @property
    def epoch(self) -> int:
        """The fencing token. Monotonic; bumped only by :meth:`recover`."""
        return self._epoch

    @property
    def driver_state(self) -> str:
        """Cache of the label. Never consulted in place of reading the label."""
        return self._state

    @property
    def is_retired(self) -> bool:
        return self._state in TERMINAL_DRIVER_STATES

    def phase_attempt(self, phase: DriverPhase) -> int:
        """Attempts already made at *phase* by this driver at this epoch."""
        return self._phase_attempts.get(phase, 0)

    # -- fencing ------------------------------------------------------------

    def recover(self, *, driver_state: str | None = None) -> int:
        """Fence the previous generation and take the issue at a new epoch.

        Called when a driver is reconstructed after a crash, a restart, or a
        stop/start cycle. Any phase still running under the old epoch will find
        its lease stale when it returns and will be refused at
        :func:`issue_driver_policy.admit_phase_result` — which is the whole
        point of the token. Attempt counters reset with the epoch because the
        pair ``(epoch, phase_attempt)`` is what makes a boundary key unique.
        """
        self._epoch += 1
        self._phase_attempts.clear()
        if driver_state is not None:
            self._state = driver_state
        return self._epoch

    def adopt_live_state(self, driver_state: str) -> None:
        """Take the state implied by the live label (ADR-0137 C5b).

        An operator dragging a label is ADR-0002's documented escape hatch, so
        the label wins over the driver's cache — always, and without an epoch
        bump, because ownership did not change hands.
        """
        self._state = driver_state

    def _lease_for(self, phase: DriverPhase, expected_label: str) -> DriverLease:
        return DriverLease(
            driver_id=self._driver_id,
            epoch=self._epoch,
            repo_slug=self._repo_slug,
            issue_number=self._issue_number,
            phase=phase,
            expected_stage_label=expected_label,
            phase_attempt=self.phase_attempt(phase),
            expires_at=datetime.now(UTC) + timedelta(seconds=self._lease_ttl_seconds),
        )

    def _state_for_label(self, label: str) -> str | None:
        """Reverse the state→label map. ``None`` for a non-pipeline label.

        Several states share one label (``DIAGNOSE`` with ``REVIEW``,
        ``HITL_APPLY`` with ``HITL_WAIT``); the map's insertion order decides
        which one a bare label resolves to, and it is ordered so the *nominal*
        state wins. ADR-0137 B1c makes that the rule rather than an accident:
        resume at the nominal state and re-detect the route-back fresh, which is
        safe because route-back detection is a pure function of CI state and diff.
        """
        for state, stage_label in self._stage_labels.items():
            if stage_label == label:
                return state
        return None

    def _resolve_state(self, outcome: PhaseOutcome, expected_label: str) -> str:
        """The state the driver holds after *outcome*.

        An explicit ``next_state`` wins (terminal states and ``HITL_WAIT`` have
        no label of their own); otherwise the committed label decides, which
        keeps the driver's cache derived from label truth rather than from the
        adapter's opinion.
        """
        if outcome.next_state is not None:
            return outcome.next_state
        label = outcome.next_label or expected_label
        return self._state_for_label(label) or self._state

    def _advance(
        self,
        outcome: AdvanceOutcome,
        *,
        phase: DriverPhase | None = None,
        reason: RejectionReason | None = None,
        detail: str = "",
    ) -> DriverAdvance:
        return DriverAdvance(
            issue_number=self._issue_number,
            driver_id=self._driver_id,
            epoch=self._epoch,
            phase=phase,
            outcome=outcome,
            state=self._state,
            reason=reason,
            detail=detail,
        )

    def _fenced(
        self,
        reason: RejectionReason | None,
        *,
        phase: DriverPhase,
        live_label: str | None,
    ) -> DriverAdvance | None:
        """Turn a fence verdict into a refusal, or ``None`` to proceed.

        One place interprets the reason codes, so the pre-flight check and the
        post-phase check cannot drift into disagreeing about what a duplicate
        key or a moved label means.
        """
        if reason is None:
            return None
        if reason is RejectionReason.DUPLICATE_IDEMPOTENCY_KEY:
            return self._advance(
                AdvanceOutcome.ALREADY_COMMITTED, phase=phase, reason=reason
            )
        if reason is RejectionReason.LIVE_LABEL_CHANGED:
            return self._preempt(live_label, phase=phase)
        logger.info(
            "driver %s: fenced a %s result for #%d (%s)",
            self._driver_id,
            phase.value,
            self._issue_number,
            reason.value,
        )
        return self._advance(AdvanceOutcome.REJECTED, phase=phase, reason=reason)

    # -- the boundary -------------------------------------------------------

    async def advance(
        self, task: Task, *, stop_requested: bool = False
    ) -> DriverAdvance:
        """Run one phase and commit its boundary. One call, one boundary.

        Returns rather than raises for every *expected* refusal — a stale
        epoch, a moved label, a re-entry — because those are decisions the
        manager records, not errors. Genuine infrastructure failures and code
        bugs propagate: :func:`exception_classify.reraise_on_credit_or_bug` is
        called before anything is swallowed, so a burnt credit balance stops the
        factory rather than being spent as a failed phase attempt.
        """
        phase = None if self.is_retired else phase_for_state(self._state)
        adapter = self._adapters.get(phase) if phase is not None else None
        if phase is None or adapter is None:
            # Terminal, or a phase this preset does not drive (P1 leaves Triage
            # to Classic). Neither is an error: the driver has nothing to do.
            return self._advance(AdvanceOutcome.RETIRED, phase=phase)

        expected_label = self._stage_labels[self._state]
        key = boundary_idempotency_key(
            issue_number=self._issue_number,
            epoch=self._epoch,
            phase=phase,
            phase_attempt=self.phase_attempt(phase),
        )

        # --- pre-flight fence: the same questions asked before the long call,
        # so a stopped factory, a dragged label or an already-committed
        # boundary costs nothing rather than a whole phase subprocess.
        live_before = await self._labels.read_stage_label(
            self._issue_number,
            epoch=self._epoch,
            phase_attempt=self.phase_attempt(phase),
        )
        pre = admit_phase_result(
            result_epoch=self._epoch,
            result_phase_attempt=self.phase_attempt(phase),
            lease_epoch=self._epoch,
            lease_phase_attempt=self.phase_attempt(phase),
            live_stage_label=live_before or expected_label,
            accepted_stage_labels=frozenset({expected_label}),
            stop_requested=stop_requested,
            committed_idempotency_keys=self._journal.committed_keys(self._issue_number),
            idempotency_key=key,
        )
        refused = self._fenced(pre, phase=phase, live_label=live_before)
        if refused is not None:
            return refused

        lease = self._lease_for(phase, expected_label)

        # --- C5(a): record where this boundary is going BEFORE anything can
        # move the label. The stage worker commits its own transition inside
        # ``adapter.run``, so the record has to precede the run, not just the
        # driver's own swap — otherwise the one swap that actually happens on
        # the nominal path is the one no intent covers. A crash between the
        # record and the add leaves one label, which rule 1 resolves as "the
        # transition never happened" and discards the record.
        target_label = adapter.target_label
        if target_label is not None and target_label != expected_label:
            self._labels.record_intent(
                self._issue_number,
                from_label=expected_label,
                to_label=target_label,
                epoch=lease.epoch,
                phase_attempt=lease.phase_attempt,
            )

        # --- the phase itself. Long, and the only place a subprocess runs.
        try:
            outcome = await adapter.run(task, lease=lease)
        except Exception as exc:
            reraise_on_credit_or_bug(exc)
            logger.warning(
                "driver %s: phase %s for #%d failed: %s",
                self._driver_id,
                phase.value,
                self._issue_number,
                exc,
            )
            self._phase_attempts[phase] = lease.phase_attempt + 1
            return self._advance(
                AdvanceOutcome.FAILED,
                phase=phase,
                detail=str(exc) or type(exc).__name__,
            )

        # --- C8 step 1: validate. The fence is re-asked with the lease's
        # tokens against the driver's *current* ones: if recovery bumped the
        # epoch while the phase ran, this result belongs to a generation that no
        # longer owns the issue and must not commit.
        live_after = await self._labels.read_stage_label(
            self._issue_number, epoch=lease.epoch, phase_attempt=lease.phase_attempt
        )
        accepted = frozenset(
            {expected_label} | ({outcome.next_label} if outcome.next_label else set())
        )
        reason = admit_phase_result(
            result_epoch=lease.epoch,
            result_phase_attempt=lease.phase_attempt,
            lease_epoch=self._epoch,
            lease_phase_attempt=self.phase_attempt(phase),
            live_stage_label=live_after or expected_label,
            accepted_stage_labels=accepted,
            stop_requested=stop_requested,
            committed_idempotency_keys=self._journal.committed_keys(self._issue_number),
            idempotency_key=key,
        )
        refused = self._fenced(reason, phase=phase, live_label=live_after)
        if refused is not None:
            return refused

        if not outcome.ok:
            self._phase_attempts[phase] = lease.phase_attempt + 1
            self._state = self._resolve_state(outcome, expected_label)
            return self._advance(
                AdvanceOutcome.FAILED, phase=phase, detail=outcome.detail
            )

        # --- C8 steps 2-4, in order, with nothing between them.
        #
        # Step 3 is the durable commit, and it is a *write* only when the stage
        # worker did not already make it. HydraFlow's planner, implementer and
        # reviewer each swap their own transition label as part of the contract
        # this PR is required to preserve, so in the normal case ``live_after``
        # already carries the target and re-issuing the swap would be a
        # redundant GitHub write. When the phase left the label where it found
        # it, the driver issues the swap itself. Either way the boundary is not
        # checkpointed until the label is observed on the target stage.
        self._journal.persist_artifact(self._issue_number, key, outcome.artifact)
        committed_label = outcome.next_label or expected_label
        if outcome.next_label is not None and live_after != outcome.next_label:
            await self._labels.commit_stage_label(
                self._issue_number, outcome.next_label
            )
        self._journal.append_checkpoint(
            self._issue_number,
            key,
            DriverCheckpoint(
                driver_id=self._driver_id,
                epoch=self._epoch,
                last_committed_phase=phase,
                committed_stage_label=committed_label,
                capsule_digest=_artifact_digest(outcome.artifact),
                outstanding_request_ids=(),
                receipts=(),
                rotation_reason=None,
            ),
        )
        # C8 step 5: the boundary is checkpointed, so the intent is spent.
        # Cleared only here, after the checkpoint — clearing it before would
        # reopen the window the record exists to close.
        self._labels.clear_intent(self._issue_number)
        self._state = self._resolve_state(outcome, expected_label)
        self._phase_attempts.pop(phase, None)
        return self._advance(
            AdvanceOutcome.COMMITTED, phase=phase, detail=outcome.detail
        )

    def _preempt(self, live_label: str | None, *, phase: DriverPhase) -> DriverAdvance:
        """Adopt the externally set label rather than clobbering it."""
        adopted = self._state_for_label(live_label or "")
        if adopted is not None:
            self.adopt_live_state(adopted)
        logger.info(
            "driver %s: #%d preempted by live label %r -> state %s",
            self._driver_id,
            self._issue_number,
            live_label,
            self._state,
        )
        return self._advance(
            AdvanceOutcome.PREEMPTED,
            phase=phase,
            reason=RejectionReason.LIVE_LABEL_CHANGED,
            detail=live_label or "",
        )
