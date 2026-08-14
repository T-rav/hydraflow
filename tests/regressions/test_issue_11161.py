"""Regression #11161: the AGING escape surface is never machine-diagnosed.

``EscapeLedgerLoop._auto_diagnose`` pre-filtered on
``reason != SURFACE_REASON_LOW_CONFIDENCE``, so an AGING finding (a
``none-yet`` row older than ``escape_ledger_encoding_age_days``) always
skipped the diagnoser and filed a human issue — even when its regression
encoding was already on disk (the live instance: escape ``9196f7403620``,
whose encoding is reachable only through ``auto_diagnose.regression_hits``'
``git grep``, not ``added_paths``). Pins that BOTH surfacing reasons run the
same diagnose pass.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from escape.auto_diagnose import EscapeDiagnosis  # noqa: E402
from escape.models import EscapeRecord  # noqa: E402
from escape_ledger_loop import SURFACE_REASON_AGING  # noqa: E402
from escape_ledger_loop import SURFACE_REASON_LOW_CONFIDENCE  # noqa: E402
from escape_ledger_loop import EscapeLedgerLoop  # noqa: E402


class _FakeDiagnoser:
    def __init__(self, verdict: EscapeDiagnosis) -> None:
        self.verdict = verdict
        self.calls: list[EscapeRecord] = []

    async def diagnose(self, record: EscapeRecord) -> EscapeDiagnosis:
        self.calls.append(record)
        return self.verdict


def _record(rid: str) -> EscapeRecord:
    return EscapeRecord(
        id=rid,
        detected_at="2026-01-01T00:00:00+00:00",
        detection_source="bug-issue",
        detection_ref=rid.split(":", 1)[-1],
        originating_pr=None,
        originating_merge_sha="",
        merged_at="",
        time_to_detection_hours=None,
        attribution_method="fixes-chain",
        attribution_confidence="low",
        encoded_as="none-yet",
        notes="",
    )


def _loop_with_diagnoser(tmp_path: Path, diagnoser: _FakeDiagnoser) -> EscapeLedgerLoop:
    from tests.helpers import make_bg_loop_deps

    bg = make_bg_loop_deps(tmp_path)
    object.__setattr__(bg.config, "data_root", tmp_path / "data")
    from unittest.mock import MagicMock

    return EscapeLedgerLoop(
        config=bg.config,
        pr_manager=MagicMock(),
        state=MagicMock(),
        dedup=MagicMock(),
        deps=bg.loop_deps,
        auto_diagnoser=diagnoser,  # type: ignore[arg-type]
    )


async def test_aging_reason_reaches_the_diagnoser(tmp_path: Path) -> None:
    diagnoser = _FakeDiagnoser(EscapeDiagnosis.INCONCLUSIVE)
    loop = _loop_with_diagnoser(tmp_path, diagnoser)
    record = _record("bug-issue:aged")

    await loop._auto_diagnose([(record, SURFACE_REASON_AGING)])

    assert diagnoser.calls == [record], (
        "AGING findings must reach the diagnoser exactly like "
        "LOW_CONFIDENCE findings do — no reason pre-filter"
    )


async def test_low_confidence_reason_still_reaches_the_diagnoser(
    tmp_path: Path,
) -> None:
    # Unchanged pre-existing behavior — must not regress alongside the fix.
    diagnoser = _FakeDiagnoser(EscapeDiagnosis.INCONCLUSIVE)
    loop = _loop_with_diagnoser(tmp_path, diagnoser)
    record = _record("bug-issue:live")

    await loop._auto_diagnose([(record, SURFACE_REASON_LOW_CONFIDENCE)])

    assert diagnoser.calls == [record]


async def test_resolved_encoded_verdict_drops_the_aging_finding(
    tmp_path: Path,
) -> None:
    diagnoser = _FakeDiagnoser(EscapeDiagnosis.RESOLVED_ENCODED)
    loop = _loop_with_diagnoser(tmp_path, diagnoser)
    record = _record("bug-issue:aged")

    residue = await loop._auto_diagnose([(record, SURFACE_REASON_AGING)])

    assert residue == [], "a machine-resolved aging finding must not reach a human"
