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
from subprocess_util import UnstubbedSpawnError
from runner_utils import (
    StreamConfig,
    _refuse_unstubbed_stream,
    stream_claude_process,
)


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


def test_the_opt_in_stands_the_guard_down() -> None:
    """A test whose subject IS a real process tree can say so explicitly.

    This asserts the guard's decision directly rather than driving a spawn
    through the whole streaming path. The first version set the opt-in and then
    called `stream_claude_process`, which — that being the entire point of the
    opt-in — really did spawn `bash -c true`. It passed locally and died in CI's
    offline-egress regression lane with `ConnectionResetError: Connection lost`,
    turning staging red one commit after this file landed.

    A test for the guard that stops tests spawning had no business spawning.
    The property that matters is "with the opt-in set, the guard does not
    refuse" — and that needs no subprocess to establish.
    """
    runner = HostRunner()

    with mock.patch.dict("os.environ", {"HYDRAFLOW_ALLOW_REAL_LLM_SPAWN": "1"}):
        _refuse_unstubbed_stream(runner)  # must not raise

    # And without it, the same runner is refused — so the assertion above is
    # about the opt-in, not about this runner being unremarkable.
    with pytest.raises(UnstubbedSpawnError):
        _refuse_unstubbed_stream(runner)


class _Reached(Exception):
    """Raised by each stub to prove control passed the guard."""


def test_asyncio_import_is_used() -> None:
    """The identity check needs the module object, not a from-import."""
    assert asyncio.create_subprocess_exec is not None


def test_the_refusal_survives_the_catch_and_continue_idiom() -> None:
    """The guard is worthless if the codebase's standard handler eats it.

    Every spawning runner is required by CLAUDE.md to use::

        except Exception as exc:
            reraise_on_credit_or_bug(exc)
            ...  # treat as a routine crash, keep going

    and `reraise_on_credit_or_bug` re-raises only `FATAL_EXCEPTIONS`. A bare
    `RuntimeError` is in neither `INFRA_FATAL_EXCEPTIONS` nor
    `LIKELY_BUG_EXCEPTIONS`, so the refusal was swallowed at exactly the call
    sites this guard exists to protect — `report_issue_loop` turned it into
    `agent_crashed=True`, `verification_judge` into a logged warning. The spawn
    was still prevented; the SIGNAL was lost, and a loosely-asserting test reads
    a degraded crash as a legitimate negative path.
    """
    from exception_classify import is_fatal, reraise_on_credit_or_bug
    from subprocess_util import UnstubbedSpawnError

    refusal = UnstubbedSpawnError("refusing to spawn ... See #12147.")

    assert is_fatal(refusal), "the refusal must never be a swallowable error"
    with pytest.raises(UnstubbedSpawnError):
        reraise_on_credit_or_bug(refusal)

    # A plain RuntimeError still is not fatal — this test would pass for the
    # wrong reason if the fix had simply made everything fatal.
    assert not is_fatal(RuntimeError("an ordinary transient spawn failure"))


def test_the_refusal_is_still_a_runtimeerror() -> None:
    """Callers that catch RuntimeError specifically keep working."""
    from subprocess_util import UnstubbedSpawnError

    assert issubclass(UnstubbedSpawnError, RuntimeError)
