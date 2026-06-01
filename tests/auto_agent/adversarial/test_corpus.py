"""Adversarial corpus runner — iterates corpus/ entries, asserts golden outcomes."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from preflight.agent import PreflightAgentDeps, PreflightSpawn, run_preflight
from preflight.context import PreflightContext
from preflight.decision import apply_decision

_CORPUS_ROOT = Path(__file__).parent / "corpus"


def _load(entry: Path) -> tuple[dict, dict, dict]:
    return (
        json.loads((entry / "issue.json").read_text()),
        json.loads((entry / "cassette.json").read_text()),
        json.loads((entry / "expected.json").read_text()),
    )


def _entries() -> list[Path]:
    return sorted(p for p in _CORPUS_ROOT.iterdir() if p.is_dir())


@pytest.mark.parametrize("entry", _entries(), ids=lambda p: p.name)
@pytest.mark.asyncio
async def test_corpus_entry(entry: Path) -> None:
    issue, cassette, expected = _load(entry)
    sub_label = next(
        lbl["name"] for lbl in issue["labels"] if lbl["name"] != "hitl-escalation"
    )

    spawn_fn = AsyncMock(
        return_value=PreflightSpawn(
            process=None,
            output_text=cassette["output_text"],
            cost_usd=cassette["cost_usd"],
            tokens=cassette["tokens"],
            crashed=cassette["crashed"],
        )
    )

    ctx = PreflightContext(
        issue_number=issue["number"],
        issue_body=issue["body"],
        issue_comments=[],
        sub_label=sub_label,
        escalation_context=None,
        wiki_excerpts="",
        sentry_events=[],
        recent_commits=[],
    )
    deps = PreflightAgentDeps(
        persona="test",
        cost_cap_usd=None,
        wall_clock_cap_s=None,
        spawn_fn=spawn_fn,
    )
    result = await run_preflight(
        context=ctx,
        repo_slug="x/y",
        worktree_path="/tmp",
        deps=deps,
    )
    assert result.status == expected["status"]
    if expected.get("pr_url"):
        assert result.pr_url == expected["pr_url"]

    # Verify decision applies the right labels.
    pr = AsyncMock()
    state = MagicMock()
    state.get_auto_agent_attempts = MagicMock(return_value=1)
    out = await apply_decision(
        issue_number=issue["number"],
        sub_label=sub_label,
        result=result,
        pr_port=pr,
        state=state,
        max_attempts=3,
    )
    assert out["added"] == expected["labels_added"]
    assert out["removed"] == expected["labels_removed"]
