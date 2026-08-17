"""Regression pins for #11372: FakeGitHub fails loud on unmodelled shapes.

The fake's ``_run_gh`` returned ``"[]"`` for anything it didn't model. A
loop probing an unmodelled endpoint got a plausible empty answer, its
scenario passed, and the real adapter's behaviour was never exercised —
so the gaps were discovered one at a time by the fake-coverage auditor
and filed as separate issues (10 of them by 2026-08-16).

Pins:
1. An unmodelled shape RAISES with an actionable message.
2. Allowlisted quiet shapes still answer empty (with a documented reason).
3. Modelled shapes are unaffected.
"""

from __future__ import annotations

import json

import pytest

from mockworld.fakes.fake_github import FakeGitHub, FakeGitHubUnmodelledCommand


@pytest.mark.asyncio
async def test_unmodelled_shape_raises_actionably() -> None:
    fake = FakeGitHub()
    with pytest.raises(FakeGitHubUnmodelledCommand) as excinfo:
        await fake._run_gh("gh", "release", "create", "v1.0.0")
    message = str(excinfo.value)
    assert "no model for" in message
    assert "release create" in message
    # The message must tell the reader BOTH remedies.
    assert "_QUIET_UNKNOWN_GH_SHAPES" in message
    assert "#11372" in message


@pytest.mark.asyncio
async def test_allowlisted_quiet_shapes_still_answer_empty() -> None:
    fake = FakeGitHub()
    assert await fake._run_gh("gh", "api", "rate_limit") == "[]"
    assert await fake._run_gh("gh", "auth", "status") == "[]"


@pytest.mark.asyncio
async def test_modelled_shapes_unaffected() -> None:
    fake = FakeGitHub()
    fake.add_issue(7, "t", "b", labels=["hydraflow-find"])
    raw = await fake._run_gh("gh", "issue", "list", "--json", "number,title,labels")
    payload = json.loads(raw)
    assert [entry["number"] for entry in payload] == [7]
