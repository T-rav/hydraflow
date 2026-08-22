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

SHADOW_LOG_SCHEMA_VERSION = 1

MAX_LOADED_OBSERVATIONS = 5000
"""How many trailing observations are read back into the rollup at startup."""


class ShadowAgreement(StrEnum):
    """Whether the shadow director pointed where the controller actually went."""

    AGREED = "agreed"
    DIVERGED = "diverged"
    NO_COMMAND = "no_command"
    """The turn produced no usable command at all — a failure, not a disagreement."""


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

    Recorded rather than skipped silently so the ratio of real boundaries to
    idle ticks is visible; it never runs a turn and never scores as agreement.
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

    capsule_reconstructed_fresh: bool = True
    """Always true, and recorded rather than assumed.

    ADR-0137 D2 proved ``--resume`` of a dead session fails closed, so this
    runtime never resumes: every turn gets a capsule rebuilt from live state.
    The field exists so the canary can *see* that rather than take it on faith.
    """

    usd_cost: float = Field(default=0.0, ge=0.0)
    latency_ms: int = Field(default=0, ge=0)
    sandbox_verdict: str = Field(default="", max_length=40)


class ShadowObservationLog:
    """Append-only JSONL log of shadow observations, with a live rollup.

    The rollup is maintained in memory as observations are appended rather than
    recomputed by re-reading the file, because the operator status endpoint is
    polled and the file grows without bound. On construction it is seeded by
    reading whatever is already on disk once, so a restart does not reset the
    numbers an operator is watching.
    """

    def __init__(self, path: Path) -> None:
        self._path = path
        self._recent: list[ShadowObservation] = []
        self._counts: dict[str, int] = {}
        self._usd_total = 0.0
        self._latency_total_ms = 0
        self._observations = 0
        self._load()

    @property
    def path(self) -> Path:
        return self._path

    # -- writes -------------------------------------------------------------

    def record(self, observation: ShadowObservation) -> None:
        """Append one observation. Never raises into the caller's boundary.

        A telemetry write must not be able to fail an observation that has
        already happened, and the caller is a shadow component that is
        explicitly forbidden from affecting live behaviour — so an unwritable
        log degrades to a warning and an in-memory rollup.
        """
        self._fold(observation)
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
            "resume_failures": self._counts.get(TurnFailure.RESUME_LOSS.value, 0),
            "spend_ceiling_reached": self._counts.get(
                TurnFailure.SPEND_CEILING.value, 0
            ),
            "not_a_boundary": self._counts.get(TurnFailure.NOT_A_BOUNDARY.value, 0),
            "timed_out": self._counts.get(TurnFailure.TIMED_OUT.value, 0),
            "sandbox_unverified": self._counts.get(
                TurnFailure.SANDBOX_UNVERIFIED.value, 0
            ),
            "malformed_output": self._counts.get(TurnFailure.MALFORMED_OUTPUT.value, 0),
            "usd_cost_total": round(self._usd_total, 6),
            "latency_ms_mean": (
                round(self._latency_total_ms / observations) if observations else 0
            ),
            "workers_dispatched": 0,
            "shadow_mode": True,
        }

    # -- internals ----------------------------------------------------------

    def _fold(self, observation: ShadowObservation) -> None:
        self._observations += 1
        self._bump(observation.agreement.value)
        if observation.turn_failure is not TurnFailure.NONE:
            self._bump(observation.turn_failure.value)
        self._bump("invalid_requests", observation.invalid_requests)
        self._bump("route_revisions", observation.route_revisions)
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
            # Only the tail is loaded. The rollup an operator watches is a live
            # counter over a run, not a historical total, and re-reading an
            # unbounded append-only file at every restart is how a telemetry
            # log becomes a startup cost. The file itself is never truncated —
            # it is the audit trail, and a human reads it with ``tail``.
            lines = self._path.read_text(encoding="utf-8").splitlines()[
                -MAX_LOADED_OBSERVATIONS:
            ]
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
