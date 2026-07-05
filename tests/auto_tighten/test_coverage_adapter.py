# tests/auto_tighten/test_coverage_adapter.py
from auto_tighten.coverage_adapter import CoverageAdapter
from auto_tighten.models import CoverageRecord


def _seed_cov(p, pct):
    p.write_text(
        CoverageRecord(
            timestamp="t", coverage_percent=pct, commit_sha="s", run_id="1"
        ).model_dump_json()
        + "\n"
    )


def _seed_pyproject(root, fail_under):
    (root / "pyproject.toml").write_text(
        f"[tool.coverage.report]\nfail_under = {fail_under}\nshow_missing = true\n"
    )


def test_current_and_baseline(tmp_path):
    cov = tmp_path / "coverage.jsonl"
    _seed_cov(cov, 78.3)
    _seed_pyproject(tmp_path, 70)
    a = CoverageAdapter(coverage_jsonl=cov, margin=1.0)
    assert a.current(tmp_path) == 78.3
    assert a.baseline(tmp_path) == 70.0


def test_direction_and_margin(tmp_path):
    a = CoverageAdapter(coverage_jsonl=tmp_path / "c.jsonl", margin=1.0)
    assert a.is_tighter(78.0, 70.0) and not a.is_tighter(70.0, 78.0)
    assert a.weakest(78.0, 74.0) == 74.0
    assert a.apply_margin(78.0) == 77.0


def test_render_tightened_rewrites_fail_under(tmp_path):
    _seed_pyproject(tmp_path, 70)
    a = CoverageAdapter(coverage_jsonl=tmp_path / "c.jsonl", margin=1.0)
    edits = a.render_tightened(tmp_path, 77.0)
    assert "fail_under = 77" in edits[0].new_text
    assert "show_missing = true" in edits[0].new_text  # only the floor line changes
