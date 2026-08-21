"""``resolve_issue_store_stage`` — one mapping for both stage vocabularies (#11551).

Phases record lifecycle with the name the operator sees (``ImplementPhase``
says ``"implement"``); the store's queues, ``active_count`` and
``total_processed`` key on ``IssueStoreStage`` (``"ready"``). The resolver is
the single place those two vocabularies meet.
"""

from __future__ import annotations

import pytest

from issue_store import STAGE_NAME_MAP, IssueStoreStage, resolve_issue_store_stage


@pytest.mark.parametrize("stage", list(IssueStoreStage))
def test_internal_values_resolve_to_themselves(stage: IssueStoreStage) -> None:
    assert resolve_issue_store_stage(stage.value) is stage


@pytest.mark.parametrize(("stage", "display"), sorted(STAGE_NAME_MAP.items()))
def test_every_dashboard_display_name_resolves_to_its_stage(
    stage: str, display: str
) -> None:
    assert resolve_issue_store_stage(display) is IssueStoreStage(stage)


def test_implement_is_the_ready_stage() -> None:
    assert resolve_issue_store_stage("implement") is IssueStoreStage.READY


def test_triage_is_the_find_stage() -> None:
    assert resolve_issue_store_stage("triage") is IssueStoreStage.FIND


@pytest.mark.parametrize("name", ["", "bogus", "READY", "Implement", "implementing"])
def test_unknown_names_resolve_to_none(name: str) -> None:
    assert resolve_issue_store_stage(name) is None
