"""Regression: UL bot-PR loops opened unbounded duplicate PRs (#9893/#9890).

2026-07-18: seven duplicate edge-proposer PRs piled up CONFLICTING+HITL while
the loop kept regenerating the same 81-edge proposal — every UL generator
loop called ``open_bot_pr`` unconditionally with a random branch suffix and
no open-PR awareness. This pins the single-flight contract: with ANY open PR
carrying a UL family label, a UL loop must skip its tick (no new PR) and
report ``skipped_open_pr``; once that PR closes, the next tick proposes.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from term_proposer_loop import UL_BOT_PR_LABELS
from tests.test_ul_single_flight import _edge_fixture


@pytest.mark.asyncio
async def test_ul_loop_never_duplicates_while_family_pr_open(
    tmp_path: Path,
) -> None:
    loop, port = _edge_fixture(tmp_path)

    first = await loop._do_work()
    assert first["status"] == "ok"
    assert len(port.calls) == 1
    blocker = next(iter(port.open_pr_labels))

    for _ in range(3):  # the 2026-07-18 pile grew one PR per tick — never again
        again = await loop._do_work()
        assert again["status"] == "skipped_open_pr"
        assert again["open_pr"] == blocker
    assert len(port.calls) == 1

    port.close_pr(blocker)
    released = await loop._do_work()
    assert released["status"] == "ok"
    assert len(port.calls) == 2


def test_family_covers_all_four_ul_labels() -> None:
    assert set(UL_BOT_PR_LABELS) == {
        "hydraflow-ul-proposed",
        "hydraflow-ul-edges",
        "hydraflow-ul-evidence",
        "hydraflow-ul-deprecated",
    }
