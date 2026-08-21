"""Version-controlled high-water marks for the test-hygiene sensor.

Unlike the mass baseline (a grandfather *set*), test hygiene ratchets on two
scalars: the number of parametrize copies and the number of cross-file
duplicates. The committed YAML records the marks; the gate fails only when a
count rises ABOVE its mark. Falling is never a failure — collapsing a group
into one parametrized test is the point. Move the marks downward with
``scripts/regen_suite_hygiene_baseline.py --reason`` after a pruning pass.

``total_tests`` is recorded for the trend reader, not gated: suite size is a
consequence of coverage, and gating it would punish new assertions.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import yaml

from erosion.models import SuiteHygieneFinding


@dataclass(frozen=True)
class SuiteHygieneBaseline:
    """The recorded marks; ``None`` means no mark has been taken yet."""

    parametrize_copies: int | None = None
    cross_file_duplicates: int | None = None
    total_tests: int | None = None
    comment: str = ""


def load_suite_hygiene_baseline(path: Path) -> SuiteHygieneBaseline:
    """Load the marks, or an empty baseline (nothing to ratchet against) when absent."""
    if not path.exists():
        return SuiteHygieneBaseline()
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}

    def _int(key: str) -> int | None:
        value = raw.get(key)
        return int(value) if value is not None else None

    return SuiteHygieneBaseline(
        parametrize_copies=_int("parametrize_copies"),
        cross_file_duplicates=_int("cross_file_duplicates"),
        total_tests=_int("total_tests"),
        comment=str(raw.get("comment", "")),
    )


def save_suite_hygiene_baseline(
    path: Path, finding: SuiteHygieneFinding, *, comment: str
) -> None:
    """Persist *finding*'s counts as the new marks."""
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "comment": comment,
        "parametrize_copies": finding.parametrize_copies,
        "cross_file_duplicates": len(finding.cross_file_duplicates),
        "total_tests": finding.total_tests,
    }
    path.write_text(yaml.safe_dump(payload, sort_keys=True), encoding="utf-8")


def exceeded(
    finding: SuiteHygieneFinding, baseline: SuiteHygieneBaseline
) -> tuple[str, ...]:
    """Human-readable message per metric that rose above its recorded mark."""
    messages: list[str] = []
    copies = finding.parametrize_copies
    if baseline.parametrize_copies is not None and copies > baseline.parametrize_copies:
        messages.append(
            f"parametrize copies {copies} > baseline {baseline.parametrize_copies}"
        )
    dups = len(finding.cross_file_duplicates)
    if (
        baseline.cross_file_duplicates is not None
        and dups > baseline.cross_file_duplicates
    ):
        messages.append(
            f"cross-file duplicates {dups} > baseline {baseline.cross_file_duplicates}"
        )
    return tuple(messages)
