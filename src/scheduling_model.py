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
``issue_controller`` ``fable_director``    Fable mode. Unarmed until #11537.
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
    """A Fable director dispatching brokered workers. Unarmed until #11537."""


class SchedulingSupport(StrEnum):
    """Why a combination is or is not runnable *right now*."""

    SUPPORTED = "supported"
    UNARMED = "unarmed"
    """A designed combination whose runtime has not landed yet."""

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

    @property
    def uses_issue_driver(self) -> bool:
        """True when this preset runs a per-issue :class:`IssueDriver`."""
        return self.scheduling_model is SchedulingModel.ISSUE_CONTROLLER


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
    name="Fable director",
    scheduling_model=SchedulingModel.ISSUE_CONTROLLER,
    execution_runtime=ExecutionRuntime.FABLE_DIRECTOR,
    support=SchedulingSupport.UNARMED,
    reason=(
        "the Fable director and dispatch broker land in #11537; "
        "no director process exists yet"
    ),
)

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

SELECTABLE_PRESETS: tuple[SchedulingPreset, ...] = (CLASSIC, DETERMINISTIC_CONTROLLER)
"""Presets an operator may select today, in display order."""


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
