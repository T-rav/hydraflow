"""Regression pin for #11962: a tick reports only its own receipts.

`CharterLoopRunner` accumulated receipts in the instance field `_written`
and `tick()` returned the whole list, so the second tick of a long-lived
runner returned its own receipts plus the first tick's, the third all three
ticks' worth. Any caller that counts or summarises the return value
over-reports monotonically, and the retained receipts are a slow leak in a
daemon that ticks forever. The durable history is the JSONL stream; the
return value is this tick's report.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

from charter_loop_runner import CharterLoopRunner
from charter_model import Charter
from file_util import append_jsonl

_T1 = datetime(2026, 9, 1, 9, 0, tzinfo=UTC)
_T2 = _T1 + timedelta(hours=1)


def _charter() -> Charter:
    return Charter.from_dict({"schema_version": 2, "loops": {"a": {"enabled": False}}})


async def test_a_tick_returns_only_its_own_receipts(tmp_path: Path) -> None:
    runner = CharterLoopRunner(
        repo="o/r",
        repo_root=tmp_path,
        receipts_path=tmp_path / "receipts.jsonl",
        receipt_writer=append_jsonl,
    )

    first = await runner.tick(_charter(), now=_T1)
    second = await runner.tick(_charter(), now=_T2)

    assert [r.observed_at for r in first] == [_T1.isoformat()]
    assert [r.observed_at for r in second] == [_T2.isoformat()], (
        "the second tick re-reported the first tick's receipts — the runner "
        "accumulates on the instance instead of reporting per tick (#11962)"
    )


async def test_the_durable_stream_still_holds_every_tick(tmp_path: Path) -> None:
    """The fix must not come from recording less: full history lives in the
    JSONL file, not in the return value."""
    path = tmp_path / "receipts.jsonl"
    runner = CharterLoopRunner(
        repo="o/r",
        repo_root=tmp_path,
        receipts_path=path,
        receipt_writer=append_jsonl,
    )
    await runner.tick(_charter(), now=_T1)
    await runner.tick(_charter(), now=_T2)

    rows = [json.loads(line) for line in path.read_text().strip().splitlines()]
    assert [row["observed_at"] for row in rows] == [
        _T1.isoformat(),
        _T2.isoformat(),
    ]
