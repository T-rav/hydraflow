"""Unit tests for the scheduling-model / execution-runtime preset table (#11535)."""

from __future__ import annotations

import pytest

import scheduling_model
from scheduling_model import (
    CLASSIC,
    DETERMINISTIC_CONTROLLER,
    SELECTABLE_PRESETS,
    ExecutionRuntime,
    SchedulingCombinationError,
    SchedulingModel,
    SchedulingSupport,
    resolve_preset,
    uses_issue_driver,
)


def test_classic_pair_resolves_to_the_classic_preset() -> None:
    resolved = resolve_preset(
        SchedulingModel.PHASE_REQUEUE, ExecutionRuntime.STAGE_SUBPROCESS
    )

    assert resolved is CLASSIC


def test_classic_preset_is_not_the_issue_driver_path() -> None:
    resolved = resolve_preset(
        SchedulingModel.PHASE_REQUEUE, ExecutionRuntime.STAGE_SUBPROCESS
    )

    assert resolved.uses_issue_driver is False


def test_deterministic_controller_pair_resolves_to_the_deterministic_controller_preset() -> (
    None
):
    resolved = resolve_preset(
        SchedulingModel.ISSUE_CONTROLLER, ExecutionRuntime.STAGE_SUBPROCESS
    )

    assert resolved is DETERMINISTIC_CONTROLLER


def test_deterministic_controller_preset_is_the_issue_driver_path() -> None:
    resolved = resolve_preset(
        SchedulingModel.ISSUE_CONTROLLER, ExecutionRuntime.STAGE_SUBPROCESS
    )

    assert resolved.uses_issue_driver is True


def test_phase_requeue_with_fable_director_raises_as_structurally_invalid() -> None:
    # phase_requeue re-acquires the issue from a stage queue while a Fable
    # director would hold it, so the pair is invalid, not merely unarmed.
    with pytest.raises(SchedulingCombinationError, match="two owners"):
        resolve_preset(SchedulingModel.PHASE_REQUEUE, ExecutionRuntime.FABLE_DIRECTOR)


def test_issue_controller_with_fable_director_raises_as_unarmed() -> None:
    # Designed but not runnable yet: the director/broker lands in #11537.
    with pytest.raises(SchedulingCombinationError, match="unarmed"):
        resolve_preset(
            SchedulingModel.ISSUE_CONTROLLER, ExecutionRuntime.FABLE_DIRECTOR
        )


def test_uses_issue_driver_agrees_with_resolve_preset_for_the_classic_pair() -> None:
    args = (SchedulingModel.PHASE_REQUEUE, ExecutionRuntime.STAGE_SUBPROCESS)

    assert uses_issue_driver(*args) == resolve_preset(*args).uses_issue_driver


def test_uses_issue_driver_agrees_with_resolve_preset_for_the_controller_pair() -> None:
    args = (SchedulingModel.ISSUE_CONTROLLER, ExecutionRuntime.STAGE_SUBPROCESS)

    assert uses_issue_driver(*args) == resolve_preset(*args).uses_issue_driver


def test_selectable_presets_contains_only_supported_presets() -> None:
    assert all(p.support is SchedulingSupport.SUPPORTED for p in SELECTABLE_PRESETS)


def test_resolve_preset_fails_loud_for_a_pair_missing_from_the_presets_table(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # A future enum member (or a row someone forgot to wire up) must fail
    # loudly rather than silently fall back to Classic.
    monkeypatch.delitem(
        scheduling_model._PRESETS,
        (SchedulingModel.PHASE_REQUEUE, ExecutionRuntime.STAGE_SUBPROCESS),
    )

    with pytest.raises(SchedulingCombinationError, match="unhandled"):
        resolve_preset(SchedulingModel.PHASE_REQUEUE, ExecutionRuntime.STAGE_SUBPROCESS)
