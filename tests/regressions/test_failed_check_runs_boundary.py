"""Regression: PRManager._get_failed_check_runs is routed through the
contracts boundary helper (Phase 13 of #8786). GhCheckRun matches the
``--json name,state,link`` shape exactly.

#10510: gh renamed the URL field ``detailsUrl`` -> ``link``. Requesting
the removed field made the whole ``gh pr checks`` call fail
(``Unknown JSON field: "detailsUrl"``), 3x-retrying every poll and
returning no failed runs. These fixtures use ``link`` (real gh output),
and ``test_requests_link_not_removed_detailsurl_field`` pins the request
field so a revert is caught."""

from __future__ import annotations

import json
import logging
from unittest.mock import patch

import pytest

from tests.conftest import SubprocessMockBuilder
from tests.helpers import ConfigFactory, make_pr_manager


@pytest.fixture
def config(tmp_path):  # noqa: ANN001
    return ConfigFactory.create(repo_root=tmp_path / "repo")


@pytest.fixture
def event_bus():  # noqa: ANN201
    from events import EventBus

    return EventBus()


@pytest.mark.asyncio
async def test_well_shaped_response_extracts_failed_runs(
    config,  # noqa: ANN001
    event_bus,  # noqa: ANN001
    caplog: pytest.LogCaptureFixture,
) -> None:
    mgr = make_pr_manager(config, event_bus)
    payload = json.dumps(
        [
            {
                "name": "Lint",
                "state": "COMPLETED",
                "conclusion": "SUCCESS",
                "link": "https://github.com/x/y/actions/runs/1",
            },
            {
                "name": "Tests",
                "state": "COMPLETED",
                "conclusion": "FAILURE",
                "link": "https://github.com/x/y/actions/runs/2",
            },
        ]
    )
    mock_create = SubprocessMockBuilder().with_stdout(payload).build()

    with (
        caplog.at_level(logging.WARNING, logger="hydraflow.contracts.boundary"),
        patch("asyncio.create_subprocess_exec", mock_create),
    ):
        result = await mgr._get_failed_check_runs(pr_number=42)

    # The PASSING_STATES filter is checked on .state (COMPLETED); only
    # checks whose state isn't in the passing/pending sets survive. The
    # exact filtering depends on PRManager._PASSING_STATES constants —
    # this assertion just verifies the parse worked + extracted run IDs.
    run_ids = [run_id for _name, run_id in result]
    assert run_ids, f"expected at least one failed run id; got {result}"
    assert not [r for r in caplog.records if "boundary validation failed" in r.message]


@pytest.mark.asyncio
async def test_drifted_state_enum_logs_warn_and_falls_back(
    config,  # noqa: ANN001
    event_bus,  # noqa: ANN001
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A new gh state value (e.g. ``WARP_DRIVE``) trips validation. The
    lenient fallback uses the raw dict so the extraction logic still
    runs — drift is observable, behaviour preserved."""
    mgr = make_pr_manager(config, event_bus)
    payload = json.dumps(
        [
            {
                "name": "FlakyCheck",
                "state": "WARP_DRIVE",  # not in the Literal
                "link": "https://github.com/x/y/actions/runs/9",
            }
        ]
    )
    mock_create = SubprocessMockBuilder().with_stdout(payload).build()

    with (
        caplog.at_level(logging.WARNING, logger="hydraflow.contracts.boundary"),
        patch("asyncio.create_subprocess_exec", mock_create),
    ):
        result = await mgr._get_failed_check_runs(pr_number=42)

    assert any("boundary validation failed" in r.message for r in caplog.records)
    # The lenient fallback still extracts the run_id from the URL.
    run_ids = [run_id for _name, run_id in result]
    assert run_ids == ["9"]


@pytest.mark.asyncio
async def test_empty_checks_list_returns_empty(
    config,  # noqa: ANN001
    event_bus,  # noqa: ANN001
) -> None:
    mgr = make_pr_manager(config, event_bus)
    mock_create = SubprocessMockBuilder().with_stdout("[]").build()
    with patch("asyncio.create_subprocess_exec", mock_create):
        result = await mgr._get_failed_check_runs(pr_number=42)
    assert result == []


@pytest.mark.asyncio
async def test_requests_link_not_removed_detailsurl_field(
    config,  # noqa: ANN001
    event_bus,  # noqa: ANN001
) -> None:
    """#10510: pin the ``gh pr checks --json`` field to ``link``.

    ``detailsUrl`` was removed from ``gh pr checks --json``; requesting it
    fails the whole call. Guard the exact field list so a revert is caught
    here instead of by a 3x-retry storm in production.
    """
    captured_args: list[str] = []

    async def _record(*args: str, **_kwargs: object):  # noqa: ANN202
        captured_args.extend(str(a) for a in args)
        proc = SubprocessMockBuilder().with_stdout("[]").build()
        return await proc(*args, **_kwargs)

    mgr = make_pr_manager(config, event_bus)
    with patch("asyncio.create_subprocess_exec", side_effect=_record):
        await mgr._get_failed_check_runs(pr_number=42)

    joined = " ".join(captured_args)
    assert "name,state,link" in joined, joined
    assert "detailsUrl" not in joined, joined
