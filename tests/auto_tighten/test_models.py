# tests/auto_tighten/test_models.py
from auto_tighten.models import (
    ConfirmedTightening,
    CoverageRecord,
    FileEdit,
    Observation,  # noqa: F401 -- part of the brief's required import surface
)


def test_coverage_record_roundtrips():
    r = CoverageRecord(
        timestamp="2026-07-05T00:00:00Z",
        coverage_percent=78.4,
        commit_sha="abc123",
        run_id="99",
    )
    assert (
        CoverageRecord.model_validate_json(r.model_dump_json()).coverage_percent == 78.4
    )


def test_confirmed_tightening_holds_file_edits():
    ct = ConfirmedTightening(
        ratchet_id="coverage",
        floor=78.0,
        file_edits=[FileEdit(path="pyproject.toml", new_text="...")],
        dedup_key="coverage:78.0",
        evidence="PR #123",
    )
    assert ct.file_edits[0].path == "pyproject.toml"
