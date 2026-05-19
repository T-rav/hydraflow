"""Unit tests for FakeBotPR.

Covers:
1. Protocol conformance — FakeBotPR satisfies BotPRPort structurally.
2. Call recording — each open_bot_pr invocation is captured in .calls.
3. PR number sequencing — returns incrementing numbers starting from 1.
4. Custom seed — next_pr_number can be set at construction time.
5. reset() — clears calls and resets the PR counter.
6. Immutable call record — mutations to the caller's lists/dicts
   after the call do not affect the recorded call.
"""

from __future__ import annotations

from typing import runtime_checkable

import pytest

from mockworld.fakes.fake_bot_pr import FakeBotPR
from term_proposer_loop import BotPRPort

# ---------------------------------------------------------------------------
# Protocol conformance
# ---------------------------------------------------------------------------


def test_fake_bot_pr_satisfies_protocol() -> None:
    """FakeBotPR must be accepted as a BotPRPort at runtime.

    BotPRPort is a structural Protocol; isinstance() checks method presence
    and name, not signatures. The signature parity check lives in
    test_mockworld_fakes_conformance.py (the strict conformance suite).
    """
    # Make the Protocol runtime-checkable for this assertion only.
    runtime_protocol = runtime_checkable(BotPRPort)
    assert isinstance(FakeBotPR(), runtime_protocol), (
        "FakeBotPR does not structurally satisfy BotPRPort. "
        "Add or rename missing methods to match the Protocol."
    )


def test_fake_adapter_marker() -> None:
    assert FakeBotPR._is_fake_adapter is True


# ---------------------------------------------------------------------------
# Basic call recording
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_open_bot_pr_records_call() -> None:
    fake = FakeBotPR()
    pr_num = await fake.open_bot_pr(
        branch="ul-propose-abc",
        title="feat(ul): add Term X",
        body="Adds Term X to the glossary.",
        labels=["hydraflow-ul-proposed"],
        files={"docs/wiki/terms/term-x.md": "# Term X\n"},
    )
    assert pr_num == 1
    assert len(fake.calls) == 1
    call = fake.calls[0]
    assert call.branch == "ul-propose-abc"
    assert call.title == "feat(ul): add Term X"
    assert call.body == "Adds Term X to the glossary."
    assert call.labels == ["hydraflow-ul-proposed"]
    assert call.files == {"docs/wiki/terms/term-x.md": "# Term X\n"}


@pytest.mark.asyncio
async def test_open_bot_pr_increments_pr_number() -> None:
    fake = FakeBotPR()
    n1 = await fake.open_bot_pr(branch="b1", title="T1", body="", labels=[], files={})
    n2 = await fake.open_bot_pr(branch="b2", title="T2", body="", labels=[], files={})
    n3 = await fake.open_bot_pr(branch="b3", title="T3", body="", labels=[], files={})
    assert (n1, n2, n3) == (1, 2, 3)
    assert len(fake.calls) == 3


@pytest.mark.asyncio
async def test_custom_starting_pr_number() -> None:
    fake = FakeBotPR(next_pr_number=42)
    n = await fake.open_bot_pr(branch="b", title="T", body="", labels=[], files={})
    assert n == 42
    n2 = await fake.open_bot_pr(branch="b2", title="T2", body="", labels=[], files={})
    assert n2 == 43


# ---------------------------------------------------------------------------
# reset()
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_reset_clears_calls_and_resets_counter() -> None:
    fake = FakeBotPR()
    await fake.open_bot_pr(branch="b", title="T", body="", labels=[], files={})
    await fake.open_bot_pr(branch="b2", title="T2", body="", labels=[], files={})
    assert len(fake.calls) == 2

    fake.reset()

    assert fake.calls == []
    assert fake.next_pr_number == 1

    n = await fake.open_bot_pr(
        branch="fresh", title="Fresh", body="", labels=[], files={}
    )
    assert n == 1
    assert len(fake.calls) == 1


# ---------------------------------------------------------------------------
# Defensive copy — caller mutations don't corrupt the record
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_recorded_call_is_snapshot_of_labels_and_files() -> None:
    """Mutations to the caller's labels/files after the call do not affect
    the recorded OpenBotPRCall (FakeBotPR copies both on capture).
    """
    fake = FakeBotPR()
    labels: list[str] = ["hydraflow-ul-proposed"]
    files: dict[str, str] = {"docs/wiki/terms/foo.md": "# Foo\n"}

    await fake.open_bot_pr(branch="b", title="T", body="", labels=labels, files=files)

    # Mutate the originals after the call.
    labels.append("extra-label")
    files["docs/wiki/terms/bar.md"] = "# Bar\n"

    recorded = fake.calls[0]
    assert recorded.labels == ["hydraflow-ul-proposed"]
    assert list(recorded.files.keys()) == ["docs/wiki/terms/foo.md"]
