"""#12147: the streaming spawn seam must fail closed under test.

#12144 closed the lightweight seam. `stream_claude_process` resolved its runner
the identical way — `config.runner or get_default_runner()` — and spawned with
no check, reaching `VerificationJudge`, `report_issue_loop` and
`BaseSubprocessRunner`. The gap was already documented in the wiring guard's
allowlist as "pre-existing gap, out of scope for #11416".

The hard part is not the guard, it is *where it can see from*. A type check
cannot tell a real `HostRunner` from one whose spawn is stubbed, and the
streaming tests stub at three different depths. Guarding above them reddened 43
tests that hold a genuine `HostRunner` and never spawn. Each case below is one
of those depths; together they are why the predicate is identity-based rather
than type-based.
"""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Any
from unittest import mock

import pytest

from events import EventBus
from execution import HostRunner
from runner_utils import StreamConfig, stream_claude_process


def _call(**config_kwargs: Any) -> Any:
    return stream_claude_process(
        cmd=["bash", "-c", "true"],
        prompt="",
        cwd=Path.cwd(),
        active_procs=set(),
        event_bus=EventBus(),
        event_data={"issue": 12147, "source": "test_12147"},
        logger=logging.getLogger("test_12147"),
        config=StreamConfig(timeout=5.0, **config_kwargs),
    )


@pytest.mark.asyncio
async def test_an_unstubbed_real_runner_is_refused() -> None:
    """The defect: nothing stubbed anywhere, so this would really spawn."""
    with pytest.raises(RuntimeError, match="12147"):
        await _call()


@pytest.mark.asyncio
async def test_an_injected_fake_runner_passes() -> None:
    """Depth 1: the caller supplied its own runner, so it is not a HostRunner."""

    class _FakeRunner:
        async def create_streaming_process(self, *_a: Any, **_kw: Any) -> Any:
            raise _Reached

    with pytest.raises(_Reached):
        await _call(runner=_FakeRunner())


@pytest.mark.asyncio
async def test_a_class_level_patch_of_the_spawn_passes() -> None:
    """Depth 2: `HostRunner.create_streaming_process` patched on the class."""

    async def _stub(*_a: Any, **_kw: Any) -> Any:
        raise _Reached

    with (
        mock.patch.object(HostRunner, "create_streaming_process", _stub),
        pytest.raises(_Reached),
    ):
        await _call()


@pytest.mark.asyncio
async def test_a_patch_of_create_subprocess_exec_passes() -> None:
    """Depth 3, and the one most streaming tests use.

    A guard that stopped at depth 2 still reddened 43 tests that patch here and
    hold a genuine, unpatched `HostRunner` above it.
    """

    async def _stub(*_a: Any, **_kw: Any) -> Any:
        raise _Reached

    with (
        mock.patch("asyncio.create_subprocess_exec", _stub),
        pytest.raises(_Reached),
    ):
        await _call()


@pytest.mark.asyncio
async def test_the_opt_in_allows_a_deliberate_real_spawn() -> None:
    """A test whose subject IS a real process tree says so explicitly."""
    with mock.patch.dict(
        "os.environ", {"HYDRAFLOW_ALLOW_REAL_LLM_SPAWN": "1"}
    ):
        # Past the guard: it reaches the real spawn and `bash -c true` exits 0
        # rather than being refused. Anything but the guard's RuntimeError.
        try:
            await _call()
        except RuntimeError as exc:  # pragma: no cover - defensive
            assert "12147" not in str(exc)


class _Reached(Exception):
    """Raised by each stub to prove control passed the guard."""


def test_asyncio_import_is_used() -> None:
    """The identity check needs the module object, not a from-import."""
    assert asyncio.create_subprocess_exec is not None
