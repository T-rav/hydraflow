"""Regression: a persistently failing wiki model must not spawn without bound.

Measured on the live factory, 2026-08-30. The `repo_wiki` compile call timed
out at 300s, was logged as a WARNING, swallowed, and retried the next cycle —
**71 times**. Roughly six hours of model calls that produced nothing, while
the factory reported `running=True, last_error=null` throughout, because a
swallowed warning is indistinguishable from health.

The reasoning was already in `wiki_compiler`, one branch below the bug: a
prompt-gate block "is a persistent policy misconfiguration, not a transient
failure: every tick re-blocks, so a soft warn would be a PERMANENT silent
no-op". A recurring timeout is that same class and was the one case not
treated as it.

This pins the property that matters — SPAWN COUNT, not log level. A fix that
only logged louder would still have spent the six hours.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

import pytest

from wiki_compiler import WikiCompiler
from tests.helpers import config_mock

CYCLES = 25


def _config() -> MagicMock:
    config = config_mock()
    config.wiki_compilation_tool = "claude"
    config.wiki_compilation_model = "haiku"
    config.wiki_compilation_timeout = 300
    # REAL ints. The breaker compares `failure_count >= max_failures`, and
    # `int >= MagicMock` returns a truthy mock — a mocked config would open the
    # circuit on the FIRST failure and this test would pass for the wrong
    # reason, measuring nothing.
    config.wiki_compilation_breaker_failures = 3
    config.wiki_compilation_breaker_reset_seconds = 1800
    return config


@pytest.mark.asyncio
async def test_a_persistently_failing_model_is_spawned_a_bounded_number_of_times(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    spawns: list[str] = []

    async def _always_times_out(**_kwargs: Any) -> MagicMock:
        spawns.append("spawn")
        result = MagicMock()
        result.returncode = -1
        result.stderr = "timed out after 300s"
        result.stdout = ""
        return result

    monkeypatch.setattr("runner_utils.run_lightweight_agent", _always_times_out)
    monkeypatch.setattr("wiki_compiler._model_io.is_prompt_gate_blocked", lambda _s: False)

    creds = MagicMock()
    creds.gh_token = "fake-token"
    compiler = WikiCompiler(config=_config(), runner=MagicMock(), credentials=creds)

    for _ in range(CYCLES):
        assert await compiler._call_model("prompt", "test") is None

    assert len(spawns) == 3, (
        f"{CYCLES} cycles against a permanently failing model produced "
        f"{len(spawns)} spawns; the failure is unbounded again. Each one is a "
        "full wiki_compilation_timeout of spend — 71 of them cost ~6 hours."
    )


@pytest.mark.asyncio
async def test_a_recovering_model_is_not_locked_out(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Anti-vacuity: a breaker that never re-closes is its own outage.

    Without this, `spawns == 3` above is also satisfied by a compiler that
    permanently disables itself after three unlucky calls.
    """
    ok = MagicMock()
    ok.returncode = 0
    ok.stdout = "compiled"
    ok.stderr = ""

    async def _succeeds(**_kwargs: Any) -> MagicMock:
        return ok

    monkeypatch.setattr("runner_utils.run_lightweight_agent", _succeeds)

    creds = MagicMock()
    creds.gh_token = "fake-token"
    compiler = WikiCompiler(config=_config(), runner=MagicMock(), credentials=creds)
    compiler._model_breaker.record_failure()
    compiler._model_breaker.record_failure()

    assert await compiler._call_model("prompt", "test") == "compiled"
    assert compiler._model_breaker.state == compiler._model_breaker.CLOSED
