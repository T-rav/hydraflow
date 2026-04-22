from __future__ import annotations

from pathlib import Path

from arch.adr_loader import load_accepted_adrs

FIXTURE = Path(__file__).parent / "fixtures" / "adr_repo"


def test_returns_only_accepted_adrs() -> None:
    adrs = load_accepted_adrs(str(FIXTURE))
    slugs = [a.slug for a in adrs]
    assert "0001-accepted" in slugs
    assert "0002-proposed" not in slugs


def test_excludes_superseded_adrs() -> None:
    adrs = load_accepted_adrs(str(FIXTURE))
    slugs = [a.slug for a in adrs]
    assert "0003-accepted-superseded" not in slugs
    assert "0004-accepted" in slugs


def test_returns_empty_list_when_no_docs_adr_dir(tmp_path) -> None:
    assert load_accepted_adrs(str(tmp_path)) == []


def test_parses_title_and_one_line_summary() -> None:
    adrs = load_accepted_adrs(str(FIXTURE))
    a = next(x for x in adrs if x.slug == "0001-accepted")
    assert a.number == "0001"
    assert "Five concurrent async loops" in a.title
    assert "async polling loops" in a.one_line.lower()
