"""create_issue must provision a missing label before `gh issue create`.

`gh issue create --label X` aborts the WHOLE create if X doesn't exist. The
health_monitor generic loop-stall dead-man-switch files its escalation with
``["hydraflow-find", "loop-stalled"]`` — but ``loop-stalled`` is NOT in the
fixed lifecycle set ``ensure_labels_exist`` creates at boot. So the escalation
``create_issue`` returned 0 (silent failure): no issue filed, and the
``worker_stall`` SYSTEM_ALERT carried ``issue: 0`` (or never published). The
label-add path must ensure the label exists first instead of failing.

Fix: PRManager.create_issue provisions any not-yet-existing label before the
`gh issue create` call (idempotent, non-mutating).
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from tests.helpers import ConfigFactory, make_pr_manager


@pytest.fixture
def mgr(tmp_path: Path):
    from events import EventBus

    config = ConfigFactory.create(repo_root=tmp_path, repo="owner/repo")
    return make_pr_manager(config, EventBus())


@pytest.mark.asyncio
async def test_create_issue_provisions_missing_label_before_create(
    mgr, monkeypatch
) -> None:
    created_labels: list[str] = []

    async def fake_run_gh(*args, **kwargs):
        joined = " ".join(str(a) for a in args)
        if "search" in joined and "issues" in joined:
            return "[]"  # no duplicate
        if "label" in joined and "list" in joined:
            # repo already has `hydraflow-find` but NOT `loop-stalled`
            return "hydraflow-find\nbug\n"
        if "label" in joined and "create" in joined:
            created_labels.append(args[3])  # gh label create <name> ...
            return ""
        return ""

    async def fake_run_with_body(*args, **kwargs):
        joined = " ".join(str(a) for a in args)
        # Mirror gh: `issue create --label loop-stalled` fails until provisioned.
        if "loop-stalled" in joined and "loop-stalled" not in created_labels:
            raise RuntimeError("could not add label: 'loop-stalled' not found")
        return "https://github.com/owner/repo/issues/77\n"

    monkeypatch.setattr(mgr, "_run_gh", fake_run_gh)
    monkeypatch.setattr(mgr, "_run_with_body_file", fake_run_with_body)

    result = await mgr.create_issue(
        "Loop stalled", "body", labels=["hydraflow-find", "loop-stalled"]
    )

    assert result == 77, "issue must be filed, not lost to a missing-label failure"
    assert "loop-stalled" in created_labels, "missing label provisioned before use"
    assert "hydraflow-find" not in created_labels, "existing label left untouched"


@pytest.mark.asyncio
async def test_create_issue_skips_provisioning_when_all_labels_exist(
    mgr, monkeypatch
) -> None:
    """No spurious label creation when every label already exists."""
    created_labels: list[str] = []

    async def fake_run_gh(*args, **kwargs):
        joined = " ".join(str(a) for a in args)
        if "search" in joined and "issues" in joined:
            return "[]"
        if "label" in joined and "list" in joined:
            return "hydraflow-find\nloop-stalled\n"
        if "label" in joined and "create" in joined:
            created_labels.append(args[3])
            return ""
        return ""

    async def fake_run_with_body(*args, **kwargs):
        return "https://github.com/owner/repo/issues/78\n"

    monkeypatch.setattr(mgr, "_run_gh", fake_run_gh)
    monkeypatch.setattr(mgr, "_run_with_body_file", fake_run_with_body)

    result = await mgr.create_issue(
        "Loop stalled", "body", labels=["hydraflow-find", "loop-stalled"]
    )

    assert result == 78
    assert created_labels == []
