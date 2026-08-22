"""The two orthogonal backend dials: scheduling model and execution runtime (#11535).

Queuing decides *what* to pick next (:mod:`queue_strategy`, #10037). **Scheduling**
decides *how* a picked issue is executed, and **execution runtime** decides *who*
decides inside a phase. They are separate axes and are registered, defaulted and
flipped independently — the proposal's matrix, reproduced here as executable data
rather than prose:

===================  ====================  =======================================
``scheduling_model`` ``execution_runtime`` support
===================  ====================  =======================================
``phase_requeue``    ``stage_subprocess``  Classic. The default. Today's behaviour.
``issue_controller`` ``stage_subprocess``  The deterministic foundation (#11535).
``issue_controller`` ``fable_director``    Fable SHADOW mode (#11537). Selectable.
``phase_requeue``    ``fable_director``    Structurally invalid — two owners.
===================  ====================  =======================================

This module is pure: no I/O, no config object, no runtime wiring, the same shape
as :mod:`queue_strategy` and :mod:`driver_contracts`. Importing it changes no
pipeline behaviour.

**Fail-loud is the point.** ``queue_strategy`` shipped without a guard and had to
add one in a follow-up (#10053); a scheduler that silently falls back to a default
branch when handed an unrecognised member is the dangerous shape, because the
operator believes one discipline is running while another is. :func:`resolve_preset`
therefore raises :class:`SchedulingCombinationError` on *every* combination it does
not explicitly support, including a newly added enum member nobody wired up.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class SchedulingModel(StrEnum):
    """How a picked issue is driven across pipeline phases."""

    PHASE_REQUEUE = "phase_requeue"
    """Classic start-stop: each phase re-acquires the issue from its own queue."""

    ISSUE_CONTROLLER = "issue_controller"
    """One fenced :class:`issue_driver.IssueDriver` owns the issue across phases."""


class ExecutionRuntime(StrEnum):
    """Who decides what happens inside a phase."""

    STAGE_SUBPROCESS = "stage_subprocess"
    """Today's deterministic stage runners, one fresh subprocess per phase."""

    FABLE_DIRECTOR = "fable_director"
    """A shadow Fable director beside the deterministic runtime (#11537).

    The stage subprocesses still run and still decide; the director observes
    each boundary and records the choice it would have made. Graduating it from
    observer to decider is #11541's, behind ``director_dispatch_armed``.
    """


class SchedulingSupport(StrEnum):
    """Why a combination is or is not runnable *right now*."""

    SUPPORTED = "supported"
    UNARMED = "unarmed"
    """A designed combination whose runtime has not landed yet.

    No preset carries it today — #11537 armed the last one that did. It is kept
    because the *next* designed-but-unlanded combination needs it, and because
    ``resolve_preset``'s fail-loud contract is stated in terms of it.
    """

    INVALID = "invalid"
    """A combination that can never be made to work."""


class SchedulingCombinationError(ValueError):
    """Raised when a scheduling/runtime pair is invalid or not yet armed."""


@dataclass(frozen=True)
class SchedulingPreset:
    """One supported ``(scheduling_model, execution_runtime)`` pair.

    ``name`` is the operator-facing preset label the settings screen shows;
    the two enum fields are what the backend actually stores (the proposal's
    "present two presets, keep two orthogonal fields" rule).
    """

    name: str
    scheduling_model: SchedulingModel
    execution_runtime: ExecutionRuntime
    support: SchedulingSupport
    reason: str = ""
    director_dispatch_armed: bool = False
    """Whether a director may dispatch a **real** worker under this preset.

    False everywhere today, and the flip is #11541's, gated on ADR-0137 B5's
    evidence bar. It is a field of its own rather than a reading of
    ``execution_runtime`` because selecting the director and *trusting* the
    director are two different operator decisions, and collapsing them into one
    dial is how "we turned on the observer" becomes "we turned on the actuator".
    In shadow mode there is no code path that would read it as permission —
    :mod:`director_broker` has no dispatch method at all — so it is a declared
    seam for the next phase, not a live switch.
    """

    @property
    def uses_issue_driver(self) -> bool:
        """True when this preset runs a per-issue :class:`IssueDriver`."""
        return self.scheduling_model is SchedulingModel.ISSUE_CONTROLLER

    @property
    def uses_fable_director(self) -> bool:
        """True when a shadow Fable director observes each driver boundary."""
        return self.execution_runtime is ExecutionRuntime.FABLE_DIRECTOR


CLASSIC = SchedulingPreset(
    name="Classic",
    scheduling_model=SchedulingModel.PHASE_REQUEUE,
    execution_runtime=ExecutionRuntime.STAGE_SUBPROCESS,
    support=SchedulingSupport.SUPPORTED,
)
"""The migration default. Nothing changes for an operator who does not opt in."""

DETERMINISTIC_CONTROLLER = SchedulingPreset(
    name="Deterministic controller",
    scheduling_model=SchedulingModel.ISSUE_CONTROLLER,
    execution_runtime=ExecutionRuntime.STAGE_SUBPROCESS,
    support=SchedulingSupport.SUPPORTED,
)
"""#11535: one fenced driver per issue over the existing stage runners."""

FABLE_DIRECTOR = SchedulingPreset(
    name="Fable director (shadow)",
    scheduling_model=SchedulingModel.ISSUE_CONTROLLER,
    execution_runtime=ExecutionRuntime.FABLE_DIRECTOR,
    support=SchedulingSupport.SUPPORTED,
    reason=(
        "#11537 shadow mode: the deterministic controller executes every phase "
        "and stays authoritative; the director records what it would have "
        "dispatched. No production worker is dispatched by Fable"
    ),
)
"""#11537. Selectable, and **shadow-only** — which is not the same as armed.

The dial being selectable is what lets an operator gather ADR-0137 B5's
evidence at all; it is not permission for a director to act. Letting a director
actually dispatch is #11541's decision, gated on that evidence, and it is
:data:`SchedulingPreset.director_dispatch_armed` — deliberately a *separate*
flip from this one, so "I turned on the observer" can never be mistaken for
"I turned on the actuator".
"""

_TWO_OWNERS = SchedulingPreset(
    name="(invalid)",
    scheduling_model=SchedulingModel.PHASE_REQUEUE,
    execution_runtime=ExecutionRuntime.FABLE_DIRECTOR,
    support=SchedulingSupport.INVALID,
    reason=(
        "phase_requeue re-acquires the issue from a stage queue while a Fable "
        "director would hold it, so the issue would have two owners"
    ),
)

_PRESETS: dict[tuple[SchedulingModel, ExecutionRuntime], SchedulingPreset] = {
    (p.scheduling_model, p.execution_runtime): p
    for p in (CLASSIC, DETERMINISTIC_CONTROLLER, FABLE_DIRECTOR, _TWO_OWNERS)
}

SELECTABLE_PRESETS: tuple[SchedulingPreset, ...] = (
    CLASSIC,
    DETERMINISTIC_CONTROLLER,
    FABLE_DIRECTOR,
)
"""Presets an operator may select today, in display order (riskiest last)."""


def resolve_preset(
    scheduling_model: SchedulingModel,
    execution_runtime: ExecutionRuntime,
) -> SchedulingPreset:
    """Return the supported preset for the pair, or raise.

    Raises :class:`SchedulingCombinationError` for an invalid pair, an unarmed
    pair, and — deliberately — for any pair this table has no row for at all.
    A future enum member added without a row fails loudly at config load rather
    than silently scheduling as Classic.
    """
    preset = _PRESETS.get((scheduling_model, execution_runtime))
    if preset is None:
        msg = (
            f"unhandled scheduling combination "
            f"{scheduling_model.value}+{execution_runtime.value}: no preset is "
            f"declared for it in scheduling_model._PRESETS"
        )
        raise SchedulingCombinationError(msg)
    if preset.support is not SchedulingSupport.SUPPORTED:
        msg = (
            f"scheduling combination {scheduling_model.value}+"
            f"{execution_runtime.value} is {preset.support.value}: {preset.reason}"
        )
        raise SchedulingCombinationError(msg)
    return preset


def uses_issue_driver(
    scheduling_model: SchedulingModel,
    execution_runtime: ExecutionRuntime,
) -> bool:
    """True when the pair runs the per-issue driver rather than Classic requeue.

    The single predicate every default-off guard reads, so "is the driver
    armed?" has exactly one answer in the codebase.
    """
    return resolve_preset(scheduling_model, execution_runtime).uses_issue_driver
