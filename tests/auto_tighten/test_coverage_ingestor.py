import json

from auto_tighten.coverage_ingestor import CoverageIngestor


def _cov_json(pct):
    return json.dumps({"totals": {"percent_covered": pct}})


def test_ingest_appends_new_run(tmp_path):
    calls = iter([("run1", "sha1", _cov_json(78.3))])
    ing = CoverageIngestor(
        tmp_path / "coverage.jsonl", fetch_latest=lambda: next(calls)
    )
    rec = ing.ingest()
    assert rec is not None and rec.coverage_percent == 78.3 and rec.run_id == "run1"


def test_ingest_skips_seen_run(tmp_path):
    seq = iter([("run1", "sha1", _cov_json(78.3)), ("run1", "sha1", _cov_json(78.3))])
    ing = CoverageIngestor(tmp_path / "coverage.jsonl", fetch_latest=lambda: next(seq))
    assert ing.ingest() is not None  # first: new
    assert ing.ingest() is None  # second: same run_id, skip


def test_ingest_handles_no_run(tmp_path):
    ing = CoverageIngestor(tmp_path / "coverage.jsonl", fetch_latest=lambda: None)
    assert ing.ingest() is None
