"""Regression tests for issue #9343.

``gh pr checks --json name,state`` returns terminal conclusion values (SUCCESS,
SKIPPED, FAILURE, etc.) in the ``state`` field for finished check runs.
``GhCheckRun.state`` only included active statuses (QUEUED, IN_PROGRESS, etc.),
so any completed check caused a ValidationError → false-positive drift signal.

Seven drift signatures survived the LiveCorpusReplayLoop retry budget and
escalated to #9343 because the same sample kept failing on every tick.

Fix: expand ``_GhCheckState`` in ``contracts.shapes`` to include all terminal
conclusion values that ``gh`` collapses into the ``state`` field.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from contracts.shadow import ShadowCorpus
from contracts.shape_dispatchers import gh_shape_validator


def _sample(
    tmp_path: Path,
    *,
    args: list[str],
    stdout: str,
    adapter: str = "github",
    command: str = "gh",
):
    corpus = ShadowCorpus(tmp_path)
    path = corpus.record(
        adapter=adapter,
        command=command,
        args=args,
        stdout=stdout,
        stderr="",
        exit_code=0,
    )
    assert path is not None
    return corpus.load(path)


_CHECKS_ARGS = [
    "pr",
    "checks",
    "9341",
    "--repo",
    "T-rav/hydraflow",
    "--json",
    "name,state",
]


@pytest.mark.asyncio
async def test_pr_checks_success_state_no_drift(tmp_path: Path) -> None:
    """Completed check runs with state='SUCCESS' must validate cleanly."""
    sample = _sample(
        tmp_path,
        args=_CHECKS_ARGS,
        stdout=json.dumps([{"name": "CI", "state": "SUCCESS"}]) + "\n",
    )
    assert await gh_shape_validator(sample) is None


@pytest.mark.asyncio
async def test_pr_checks_skipped_state_no_drift(tmp_path: Path) -> None:
    """Check runs with state='SKIPPED' must validate cleanly."""
    sample = _sample(
        tmp_path,
        args=_CHECKS_ARGS,
        stdout=json.dumps([{"name": "Dashboard Build", "state": "SKIPPED"}]) + "\n",
    )
    assert await gh_shape_validator(sample) is None


@pytest.mark.asyncio
async def test_pr_checks_failure_state_no_drift(tmp_path: Path) -> None:
    """Check runs with state='FAILURE' must validate cleanly."""
    sample = _sample(
        tmp_path,
        args=_CHECKS_ARGS,
        stdout=json.dumps([{"name": "Tests", "state": "FAILURE"}]) + "\n",
    )
    assert await gh_shape_validator(sample) is None


@pytest.mark.asyncio
async def test_pr_checks_mixed_states_no_drift(tmp_path: Path) -> None:
    """A real-world mix of active and terminal states must validate cleanly."""
    sample = _sample(
        tmp_path,
        args=_CHECKS_ARGS,
        stdout=json.dumps(
            [
                {"name": "Scenario Tests", "state": "IN_PROGRESS"},
                {"name": "Trust Gate", "state": "SUCCESS"},
                {"name": "Browser Scenarios", "state": "IN_PROGRESS"},
                {"name": "Type Check", "state": "SUCCESS"},
                {"name": "Dashboard Build", "state": "SKIPPED"},
            ]
        )
        + "\n",
    )
    assert await gh_shape_validator(sample) is None


@pytest.mark.asyncio
async def test_pr_checks_unknown_state_still_drifts(tmp_path: Path) -> None:
    """A genuinely unknown state value must still surface as drift."""
    sample = _sample(
        tmp_path,
        args=_CHECKS_ARGS,
        stdout=json.dumps([{"name": "CI", "state": "WARP_DRIVE"}]) + "\n",
    )
    result = await gh_shape_validator(sample)
    assert result is not None
    assert result["shape"] == "GhCheckRun"
