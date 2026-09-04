"""The implement phase commits the chain before the agent runs (ADR-0149).

The security property under test is ordering: the chain must be on the
branch before the implementer is dispatched, so the agent inherits it as
history rather than authoring the files the gate later reads.
"""

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from implement_phase._build import ImplementBuildMixin
from models import Task
from subprocess_util import CreditExhaustedError


class _Phase(ImplementBuildMixin):
    """Bare host for the mixin — only the materialisation seam is under test."""

    def __init__(self, chain_writer) -> None:
        self._chain_writer = chain_writer


def _task() -> Task:
    return Task(id=7, title="Add a thing", body="Please add it.")


@pytest.mark.asyncio
async def test_the_chain_writer_is_asked_to_materialise_the_worktree():
    writer = MagicMock()
    writer.materialise = AsyncMock()
    phase = _Phase(writer)

    await phase._materialise_chain(_task(), Path("/wt"))

    writer.materialise.assert_awaited_once_with(Path("/wt"), 7)


@pytest.mark.asyncio
async def test_a_materialisation_failure_does_not_abort_the_build():
    writer = MagicMock()
    writer.materialise = AsyncMock(side_effect=OSError("disk full"))
    phase = _Phase(writer)

    await phase._materialise_chain(_task(), Path("/wt"))


@pytest.mark.asyncio
async def test_credit_exhaustion_still_propagates():
    writer = MagicMock()
    writer.materialise = AsyncMock(side_effect=CreditExhaustedError("out of credit"))
    phase = _Phase(writer)

    with pytest.raises(CreditExhaustedError):
        await phase._materialise_chain(_task(), Path("/wt"))
