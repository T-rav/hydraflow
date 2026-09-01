"""Direct unit coverage for ``policy.facts.collect_adr_enforcement_facts`` (#11869).

Every composition-rule test in ``tests/test_policy_python_engine.py`` builds the
``"binds"`` fact by hand via ``_enforcement_facts(..., binds=...)``, bypassing the
collector entirely. These tests exercise the collector itself: does it read an
ADR's real ``**Binds:**`` header (through ``adr_index.ADR.binds`` /
``adr_conformance.accepted_adrs``) and emit it as the ``"binds"`` fact value.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from policy.facts import adr_subject, collect_adr_enforcement_facts

OBSERVED_AT = datetime(2026, 8, 28, 9, 30, tzinfo=UTC)


def _write_adr(adr_dir: Path, number: int, *, binds: str | None) -> None:
    lines = [
        f"# ADR-{number:04d}: Binds Fixture {number}",
        "",
        "**Status:** Accepted",
        "**Date:** 2026-01-01",
        "**Enforcement:** decision-of-record",
    ]
    if binds is not None:
        lines.append(f"**Binds:** {binds}")
    lines.extend(["", "## Context", "", "Fixture body.", ""])
    (adr_dir / f"{number:04d}-binds-fixture-{number}.md").write_text("\n".join(lines))


def _seed_repo(tmp_path: Path, *, number: int, binds: str | None) -> Path:
    """A minimal repo with exactly one Accepted ADR, for a binds-only assertion."""
    root = tmp_path / "repo"
    adr_dir = root / "docs" / "adr"
    adr_dir.mkdir(parents=True)
    _write_adr(adr_dir, number, binds=binds)

    baseline_dir = root / "tests" / "architecture"
    baseline_dir.mkdir(parents=True)
    (baseline_dir / "adr_enforcement_baseline.json").write_text(
        json.dumps({"baseline_snapshot": [], "resolved": []})
    )

    standards_dir = root / "docs" / "standards" / "adr_enforcement"
    standards_dir.mkdir(parents=True)
    (standards_dir / "exemptions.md").write_text(
        "# Exemptions\n\n## Active exemptions\n\n"
    )
    return root


def _binds_fact_value(repo_root: Path, subject: str) -> object:
    facts = collect_adr_enforcement_facts(repo_root, observed_at=OBSERVED_AT)
    [value] = [f.value for f in facts if f.subject == subject and f.key == "binds"]
    return value


@pytest.mark.parametrize("binds", ["work", "factory", "both"])
def test_collect_adr_enforcement_facts_reads_the_binds_header(
    tmp_path: Path, binds: str
) -> None:
    repo_root = _seed_repo(tmp_path, number=9001, binds=binds)

    assert _binds_fact_value(repo_root, adr_subject(9001)) == binds


def test_collect_adr_enforcement_facts_defaults_binds_to_unknown_when_unstated(
    tmp_path: Path,
) -> None:
    repo_root = _seed_repo(tmp_path, number=9002, binds=None)

    assert _binds_fact_value(repo_root, adr_subject(9002)) == "unknown"
