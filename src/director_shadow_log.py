"""What the shadow director would have done, recorded next to what really happened.

This is the whole product of #11537's shadow phase: the deterministic controller
stays authoritative and executes every boundary, and beside each boundary this
file records the choice a Fable director would have made, so #11541 can judge
whether to let it make one for real.

Six things are recorded per boundary, because #11537 names six:

* **agreement** — did the director point at the same next step the controller
  took? :func:`classify_agreement` is the pure comparison, so the judgement is
  replayable from a log line rather than being an opinion formed at runtime;
* **invalid requests** — dispatches the broker's rule table refused, with their
  deterministic reason codes;
* **route revision** — refusals caused specifically by a routing view that moved
  under the director, counted apart from "asked for something it may not have";
* **resume failures** — see :class:`TurnFailure` and the note on it below;
* **cost** — the parent turn's USD spend, from the turn's own result frame;
* **latency** — wall-clock milliseconds for the turn.

**This is telemetry, not state.** ADR-0137's narrowing of ADR-0094 is explicit
that ``ConvergenceLedger`` remains the sole owner of convergence state, and *"a
driver may sequence the outer lap but may not own its state"*. A shadow director
that started keeping its own parallel view of where an issue is would have
broken that, so nothing here is ever read back to make a pipeline decision:
this log has exactly two readers, the operator status endpoint and a human.
Losing the whole file costs the canary its evidence and costs the pipeline
nothing.

The format is JSONL for the same reasons :mod:`driver_journal` uses it —
append-only, survives a truncated final line, readable with ``tail``.
"""

from __future__ import annotations

import json
import logging
import os
from enum import StrEnum
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel, ConfigDict, Field

from issue_driver import AdvanceOutcome

if TYPE_CHECKING:
    from pathlib import Path

    from driver_contracts import DirectorCommandKind

logger = logging.getLogger("director_shadow_log")

SHADOW_LOG_SCHEMA_VERSION = 2
"""Bumped by #11541, which added ``dispatched`` to every row.

A row is written with ``sort_keys`` over the whole model dump, so the new field
appears — as ``[]`` — on every row a shadow-mode host writes too. The model is
``extra="forbid"``, so *older* code reading a newer log drops those rows at
:meth:`ShadowObservationLog._load`; the version is what makes that diagnosable
instead of mysterious. Newer code reading an older log is unaffected: the
missing field takes its default."""

MAX_LOADED_OBSERVATIONS = 5000
"""How many trailing observations are read back into the rollup at startup."""

MAX_LOADED_BYTES = 4 * 1024 * 1024
"""How much of the log's tail is actually READ at startup.

Bounding the parse without bounding the read is not a bound: the previous
version sliced ``read_text().splitlines()``, which pulls the whole file into
memory first. This seeks instead, so a log that has grown to hundreds of
megabytes costs a few megabytes to reopen.
"""


class ShadowAgreement(StrEnum):
    """Whether the shadow director pointed where the controller actually went."""

    AGREED = "agreed"
    DIVERGED = "diverged"
    NO_COMMAND = "no_command"
    """The turn produced no usable command at all — a failure, not a disagreement."""

    UNSCORED = "unscored"
    """A command was read but this outcome has no agreement rule.

    Distinct from ``NO_COMMAND``, which means nothing usable came back. Filing
    a read command under "no command" produced a row that said *no command*
    beside the command it had just parsed, and quietly moved a wiring gap into
    the same bucket as a broken turn.
    """


class TurnFailure(StrEnum):
    """Why a director turn produced nothing usable. ``NONE`` means it did.

    Every member except ``NONE`` is a fail-closed path: the turn's output is
    discarded and no dispatch is admitted, which in shadow mode means no
    *hypothetical* dispatch is recorded either. A failure must never read as
    "the director chose to yield".
    """

    NONE = "none"
    TIMED_OUT = "timed_out"
    """Exceeded its budget and was killed with its whole process group (S6)."""

    SANDBOX_UNVERIFIED = "sandbox_unverified"
    """S4's observed-boundary assertion refused the turn."""

    MALFORMED_OUTPUT = "malformed_output"
    """Unframed stdout, or no command that satisfies ``DirectorCommand``."""

    TURN_ERROR = "turn_error"
    """The turn ran and reported failure — ``is_error``, never ``subtype``."""

    RESUME_LOSS = "resume_loss"
    """A terminal error frame with no assistant turn: the vendor dropped it.

    This runtime never passes ``--resume`` — every capsule is reconstructed from
    scratch, which is the acceptance criterion "fresh reconstruction succeeds
    without vendor session history". So a nonzero count here does not mean a
    resume was attempted; it means the vendor lost a session unprompted, in
    exactly the shape the #11533 probe proved is detectable rather than silent.
    The recovery is automatic (the next capsule is fresh anyway) and this counter
    is how often it was needed — the ADR-0137 B5 line *"successful fresh
    reconstruction on every resume failure"*.
    """

    STOPPED = "stopped"
    """The factory was stopping; the turn was never started (fail closed)."""

    #: Members below this line describe a turn that was never started. They are
    #: COUNTED, never written as a row — see :meth:`ShadowObservationLog.decline`.

    DISABLED = "disabled"
    """The live kill switch is off; the turn was never started."""

    SPEND_CEILING = "spend_ceiling"
    """The run's aggregate USD ceiling is reached; no further turn is started.

    Distinct from a capsule whose ``remaining_usd_budget`` is zero: that bounds
    what a director may *request* and still costs a turn to discover, while this
    stops the turn itself. Without it a driver that reaches a boundary every
    poll interval — a HITL driver waiting on a human, say — would spend
    indefinitely, because nothing else in the design bounds turn *count*.
    """

    NOT_A_BOUNDARY = "not_a_boundary"
    """The driver had nothing to run, so there was no decision to compare.

    Counted rather than written. Recording a row for it — the first version of
    this — put an fsync on a path the allocator reaches on every tick for every
    parked driver, which is a firehose rather than telemetry. The ratio of real
    boundaries to idle ticks is what an operator wants, and a counter carries
    that exactly as well as a row does.
    """


#: How the controller's outcome maps to the command that would agree with it.
#: Expressed as data rather than as branches so the comparison is one table an
#: operator can read, and so a new ``AdvanceOutcome`` fails loudly (see
#: :func:`classify_agreement`) rather than silently scoring as agreement.
_AGREEING_COMMAND: dict[AdvanceOutcome, str] = {
    # The controller did work at this boundary. A director that wanted workers
    # for it agrees; one that wanted to stop does not.
    AdvanceOutcome.COMMITTED: "dispatch_workers",
    AdvanceOutcome.FAILED: "dispatch_workers",
    # The issue is finished. Agreement is wanting to finish.
    AdvanceOutcome.RETIRED: "finish",
    # Nothing to do, or a fence refused the boundary. Agreement is yielding.
    AdvanceOutcome.IDLE: "yield",
    AdvanceOutcome.ALREADY_COMMITTED: "yield",
    AdvanceOutcome.PREEMPTED: "yield",
    AdvanceOutcome.REJECTED: "yield",
}


def has_agreement_rule(outcome: AdvanceOutcome) -> bool:
    """Whether :func:`classify_agreement` can judge *outcome*.

    Exposed so a caller can ask before it compares, rather than driving control
    flow through the ``KeyError``. The raise stays — it is what stops an
    unmapped outcome scoring as agreement in every other caller — but the one
    caller that must not die on it can now avoid provoking it.
    """
    return outcome in _AGREEING_COMMAND


def classify_agreement(
    outcome: AdvanceOutcome, command_kind: DirectorCommandKind | None
) -> ShadowAgreement:
    """Compare the director's command against what the controller actually did.

    Pure, total, and deliberately coarse. It answers *"would the director have
    moved this issue the same way?"* and nothing finer — a finer comparison
    (which workers, in what order) is meaningless while the director has never
    been allowed to run one, and would manufacture a precision the evidence does
    not have.

    An unmapped outcome raises rather than defaulting: scoring an outcome nobody
    wired up as agreement would inflate exactly the number ADR-0137 B5's bar
    depends on, which is the ``queue_strategy`` silent-fallback shape (#10053).
    """
    if command_kind is None:
        return ShadowAgreement.NO_COMMAND
    expected = _AGREEING_COMMAND.get(outcome)
    if expected is None:
        msg = (
            f"no agreement rule for AdvanceOutcome.{outcome.name}; add a row to "
            "director_shadow_log._AGREEING_COMMAND rather than letting an "
            "unmapped outcome score as agreement"
        )
        raise KeyError(msg)
    return (
        ShadowAgreement.AGREED
        if command_kind.value == expected
        else ShadowAgreement.DIVERGED
    )


class ShadowObservation(BaseModel):
    """One boundary, as the controller ran it and as the director would have."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: int = SHADOW_LOG_SCHEMA_VERSION
    recorded_at: str
    issue_number: int = Field(gt=0)
    driver_id: str = Field(min_length=1, max_length=128)
    epoch: int = Field(ge=0)
    phase: str = Field(default="", max_length=32)
    live_outcome: str = Field(min_length=1, max_length=32)
    live_state: str = Field(default="", max_length=32)

    agreement: ShadowAgreement
    command_kind: str | None = Field(default=None, max_length=32)
    turn_failure: TurnFailure = TurnFailure.NONE
    turn_failure_detail: str = Field(default="", max_length=500)

    would_dispatch: tuple[dict[str, Any], ...] = ()
    invalid_requests: int = Field(default=0, ge=0)
    rejection_reasons: tuple[str, ...] = ()
    route_revisions: int = Field(default=0, ge=0)

    dispatched: tuple[dict[str, Any], ...] = ()
    """Receipts for children this boundary actually ran (#11541).

    Empty under shadow mode, and empty for every boundary outside the Plan
    canary's bound — which is what makes ``workers_dispatched`` in the rollup a
    fact rather than a claim. ``would_dispatch`` beside it is the *requested*
    tree, so an operator can see a director asking for four workers and the
    canary running one — and each of its nodes carries whether that particular
    request became a child, so the two lists cannot disagree.
    """

    capsule_reconstructed_fresh: bool = True
    """Always true, and true **by construction** rather than by observation.

    ADR-0137 D2 proved ``--resume`` of a dead session fails closed, so this
    runtime never resumes: every turn gets a capsule rebuilt from live state.

    The docstring used to say "recorded rather than assumed … so the canary can
    *see* it rather than take it on faith", and that was the exact shape of the
    ``dispatched: false`` defect one field over: nothing in ``src/`` ever writes
    this, so it is a literal default dressed as a measurement, and the test that
    named it asserted the default and could not fail. Said plainly instead —
    the field is a schema marker, and the real evidence is elsewhere:
    ``tests/architecture/test_director_no_authority.py`` pins that ``--resume``
    never appears in the argv, and ``resume_failures`` in the rollup counts the
    times the vendor dropped a session unprompted.
    """

    usd_cost: float = Field(default=0.0, ge=0.0)
    latency_ms: int = Field(default=0, ge=0)
    sandbox_verdict: str = Field(default="", max_length=40)


class ShadowObservationLog:
    """Append-only JSONL log of shadow observations, with a live rollup.

    **A row on disk means a turn was attempted.** Everything that declined to
    start one — an idle tick, a stop, the kill switch, the spend ceiling — is a
    counter and nothing more (:meth:`decline`). That rule is what keeps
    ``observations == agreed + diverged + no_command + unscored`` reconcilable,
    and it is what keeps a parked driver from turning a telemetry file into a
    write loop.

    The rollup is maintained in memory as rows are appended rather than
    recomputed from the file, because the status endpoint is polled and the file
    grows without bound. Counters are per-run and start at zero; the cumulative
    **spend** is the one number that must survive a restart, so it is persisted
    separately (:attr:`spend_path`) rather than re-derived from a bounded tail
    that could evict every costed row.
    """

    def __init__(self, path: Path) -> None:
        self._path = path
        self._spend_path = path.with_suffix(".spend.json")
        self._recent: list[ShadowObservation] = []
        self._counts: dict[str, int] = {}
        self._usd_total = 0.0
        self._worker_usd_total = 0.0
        self._latency_total_ms = 0
        self._observations = 0
        self._load()
        self._usd_total = self._load_spend()

    @property
    def path(self) -> Path:
        return self._path

    @property
    def spend_path(self) -> Path:
        """Where the cumulative USD total lives, outside the tail window."""
        return self._spend_path

    # -- writes -------------------------------------------------------------

    def decline(self, kind: TurnFailure) -> None:
        """Count a boundary where no turn was started. Writes nothing.

        The allocator reaches this on every tick for every driver that has
        nothing to run, so it must stay allocation-light and must never touch
        the disk. It deliberately does **not** increment ``observations``: a
        decline is not an observation of a director's judgement, and folding it
        into the same denominator would dilute the agreement rate that
        ADR-0137 B5's bar reads — the exact contamination the boundary filter
        exists to prevent.
        """
        self._bump(kind.value)

    def record(self, observation: ShadowObservation) -> None:
        """Append one observation. Never raises into the caller's boundary.

        A telemetry write must not be able to fail an observation that has
        already happened, and the caller is a shadow component that is
        explicitly forbidden from affecting live behaviour — so an unwritable
        log degrades to a warning and an in-memory rollup.
        """
        self._fold(observation)
        if observation.usd_cost:
            self._persist_spend()
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            with self._path.open("a", encoding="utf-8") as handle:
                handle.write(
                    json.dumps(observation.model_dump(mode="json"), sort_keys=True)
                    + "\n"
                )
                handle.flush()
                os.fsync(handle.fileno())
        except OSError:
            logger.warning(
                "director shadow log: could not append to %s", self._path, exc_info=True
            )

    # -- reads --------------------------------------------------------------

    def recent(self, limit: int = 20) -> list[ShadowObservation]:
        """The most recent observations, newest last."""
        return self._recent[-limit:]

    def summary(self) -> dict[str, Any]:
        """The counters #11537 requires the operator status to show."""
        observations = self._observations
        return {
            "observations": observations,
            "agreed": self._counts.get(ShadowAgreement.AGREED.value, 0),
            "diverged": self._counts.get(ShadowAgreement.DIVERGED.value, 0),
            "no_command": self._counts.get(ShadowAgreement.NO_COMMAND.value, 0),
            "invalid_requests": self._counts.get("invalid_requests", 0),
            "route_revisions": self._counts.get("route_revisions", 0),
            "unscored": self._counts.get(ShadowAgreement.UNSCORED.value, 0),
            "resume_failures": self._counts.get(TurnFailure.RESUME_LOSS.value, 0),
            "turn_error": self._counts.get(TurnFailure.TURN_ERROR.value, 0),
            # Declines: counted, never written. An operator who has just flipped
            # the kill switch looks for ``disabled``, so omitting it made the one
            # new live control invisible in the one place it is surfaced.
            "spend_ceiling_reached": self._counts.get(
                TurnFailure.SPEND_CEILING.value, 0
            ),
            "not_a_boundary": self._counts.get(TurnFailure.NOT_A_BOUNDARY.value, 0),
            "stopped": self._counts.get(TurnFailure.STOPPED.value, 0),
            "disabled": self._counts.get(TurnFailure.DISABLED.value, 0),
            "timed_out": self._counts.get(TurnFailure.TIMED_OUT.value, 0),
            "sandbox_unverified": self._counts.get(
                TurnFailure.SANDBOX_UNVERIFIED.value, 0
            ),
            "malformed_output": self._counts.get(TurnFailure.MALFORMED_OUTPUT.value, 0),
            "usd_cost_total": round(self._usd_total, 6),
            "latency_ms_mean": (
                round(self._latency_total_ms / observations) if observations else 0
            ),
            # Counted from the receipts on disk, not asserted. Under shadow
            # mode this is zero because nothing writes a receipt — an
            # invariant, and one that stops being an invariant the moment the
            # Plan canary is armed, which is exactly when an operator needs the
            # number to be real (#11541).
            "workers_dispatched": self._counts.get("workers_dispatched", 0),
            "workers_accepted": self._counts.get("workers_accepted", 0),
            "workers_expired": self._counts.get("workers_expired", 0),
            "workers_refused": self._counts.get("workers_refused", 0),
            "worker_usd_cost_total": round(self._worker_usd_total, 6),
            "shadow_mode": self._counts.get("workers_dispatched", 0) == 0,
        }

    # -- internals ----------------------------------------------------------

    def _persist_spend(self) -> None:
        """Write the cumulative spend beside the log. Never raises."""
        try:
            self._spend_path.parent.mkdir(parents=True, exist_ok=True)
            self._spend_path.write_text(
                json.dumps({"usd_total": round(self._usd_total, 6)}), encoding="utf-8"
            )
        except OSError:
            logger.warning(
                "director shadow log: could not persist the spend total to %s",
                self._spend_path,
                exc_info=True,
            )

    def _load_spend(self) -> float:
        """The cumulative spend, from its own file rather than the log's tail.

        Deriving it from the tail was wrong twice: a bounded tail can evict
        every costed row, and the ceiling would then silently re-arm with the
        whole budget available again on each restart. The counters above are
        honestly per-run; this one number is not allowed to be.
        """
        try:
            payload = json.loads(self._spend_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return self._usd_total
        recorded = payload.get("usd_total")
        if not isinstance(recorded, int | float) or recorded < 0:
            return self._usd_total
        return float(recorded)

    def _fold(self, observation: ShadowObservation) -> None:
        self._observations += 1
        self._bump(observation.agreement.value)
        if observation.turn_failure is not TurnFailure.NONE:
            self._bump(observation.turn_failure.value)
        self._bump("invalid_requests", observation.invalid_requests)
        self._bump("route_revisions", observation.route_revisions)
        for receipt in observation.dispatched:
            # A child exists exactly when it has a spawn id. Counting every
            # receipt made ``workers_dispatched`` include refusals that never
            # started anything — so an armed run could report two workers
            # dispatched beside one node marked dispatched in its own tree, and
            # ``shadow_mode`` could flip to False on a boundary that spawned
            # nothing at all.
            ran = bool(receipt.get("child_spawn_id"))
            if ran:
                self._bump("workers_dispatched")
            if receipt.get("status") == "accepted":
                self._bump("workers_accepted")
            elif ran:
                # It ran and did not finish cleanly — reaped at its deadline, or
                # served a model that did not satisfy the requirement. Counting
                # it as *refused* put a child that consumed a worker slot in the
                # same bucket as one that was never started.
                self._bump("workers_expired")
            else:
                self._bump("workers_refused")
            cost = receipt.get("usd_cost")
            if isinstance(cost, int | float):
                self._worker_usd_total += float(cost)
        self._usd_total += observation.usd_cost
        self._latency_total_ms += observation.latency_ms
        self._recent.append(observation)
        del self._recent[:-50]

    def _bump(self, key: str, by: int = 1) -> None:
        self._counts[key] = self._counts.get(key, 0) + by

    def _load(self) -> None:
        if not self._path.exists():
            return
        try:
            # Only the tail is READ, not merely parsed: re-reading an unbounded
            # append-only file at every restart is how a telemetry log becomes a
            # startup cost, and slicing after ``read_text`` bounds neither the
            # read nor the peak memory. The file itself is never truncated — it
            # is the audit trail, and a human reads it with ``tail``.
            lines = self._read_tail()
        except OSError:
            logger.warning(
                "director shadow log: could not read %s", self._path, exc_info=True
            )
            return
        for line in lines:
            stripped = line.strip()
            if not stripped:
                continue
            try:
                self._fold(ShadowObservation.model_validate_json(stripped))
            except ValueError:
                # A process killed mid-write leaves a partial final line, and an
                # older schema version leaves a line this model cannot load.
                # Neither is corruption worth failing a rollup over.
                logger.debug("director shadow log: skipping unloadable line")

    def _read_tail(self) -> list[str]:
        """The last :data:`MAX_LOADED_BYTES` of the log, whole lines only.

        Seeks rather than reading the whole file and slicing. Bounding the parse
        without bounding the read is not a bound: ``read_text().splitlines()``
        pulls every byte into memory first, so a log that has grown to hundreds
        of megabytes costs all of them at every restart — which is the cost the
        comment on the caller claimed to be avoiding.
        """
        with self._path.open("rb") as handle:
            handle.seek(0, os.SEEK_END)
            size = handle.tell()
            handle.seek(max(size - MAX_LOADED_BYTES, 0))
            raw = handle.read()
        lines = raw.decode("utf-8", "replace").splitlines()
        if size > MAX_LOADED_BYTES and lines:
            # The seek almost certainly landed mid-record; drop that fragment.
            lines = lines[1:]
        return lines[-MAX_LOADED_OBSERVATIONS:]
