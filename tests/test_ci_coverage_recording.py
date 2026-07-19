from pathlib import Path

CI = Path(__file__).resolve().parents[1] / ".github" / "workflows" / "ci.yml"


def test_ci_generates_coverage_json():
    text = CI.read_text()
    assert "--cov-report=json" in text, "CI must emit coverage.json for the tightener"


def test_ci_uploads_coverage_json_artifact():
    text = CI.read_text()
    assert "coverage-json" in text, "CI must upload the coverage.json artifact"
