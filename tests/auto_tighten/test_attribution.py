import subprocess
from datetime import UTC, datetime, timedelta

from auto_tighten.attribution import AttributionResolver, baseline_since

PRS = [
    {"number": 10, "files": ["docs/readme.md"], "merged_at": "2026-07-01T00:00:00Z"},
    {"number": 11, "files": ["tests/test_foo.py"], "merged_at": "2026-07-02T00:00:00Z"},
]


def test_attributes_pr_touching_paths():
    r = AttributionResolver(list_merged_prs=lambda since: PRS)
    assert r.attribute(["tests/", "src/"], since_iso="2026-06-30T00:00:00Z") == 11


def test_returns_none_when_no_touch():
    r = AttributionResolver(list_merged_prs=lambda since: [PRS[0]])
    assert r.attribute(["tests/", "src/"], since_iso="2026-06-30T00:00:00Z") is None


def test_returns_first_match_when_multiple_prs_match():
    prs = [{"number": 5, "files": ["src/a.py"]}, {"number": 9, "files": ["tests/b.py"]}]
    r = AttributionResolver(list_merged_prs=lambda since: prs)
    assert r.attribute(["tests/", "src/"], since_iso="x") == 5


def test_forwards_since_iso_to_lister():
    received = {}

    def lister(since):
        received["since"] = since
        return []

    r = AttributionResolver(list_merged_prs=lister)
    r.attribute(["tests/"], since_iso="2026-07-01T00:00:00Z")
    assert received["since"] == "2026-07-01T00:00:00Z"


def _git(*args: str, cwd) -> None:
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True)


def _init_repo_with_baseline_commit(root, rel_path: str) -> None:
    _git("init", "-q", cwd=root)
    _git("config", "user.email", "test@example.com", cwd=root)
    _git("config", "user.name", "Test", cwd=root)
    target = root / rel_path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("fail_under = 70\n")
    _git("add", rel_path, cwd=root)
    _git("commit", "-q", "-m", "seed baseline", cwd=root)


def test_baseline_since_returns_committer_date_of_last_touching_commit(tmp_path):
    _init_repo_with_baseline_commit(tmp_path, "pyproject.toml")

    result = baseline_since(tmp_path, "pyproject.toml")

    # Must parse as an ISO timestamp and be very recent (just committed).
    parsed = datetime.fromisoformat(result)
    assert parsed.tzinfo is not None
    assert abs((datetime.now(UTC) - parsed).total_seconds()) < 300


def test_baseline_since_reflects_latest_of_multiple_commits(tmp_path):
    _init_repo_with_baseline_commit(tmp_path, "pyproject.toml")
    first = baseline_since(tmp_path, "pyproject.toml")

    (tmp_path / "pyproject.toml").write_text("fail_under = 75\n")
    _git("add", "pyproject.toml", cwd=tmp_path)
    _git("commit", "-q", "-m", "tighten baseline", cwd=tmp_path)

    second = baseline_since(tmp_path, "pyproject.toml")
    assert datetime.fromisoformat(second) >= datetime.fromisoformat(first)


def test_baseline_since_falls_back_when_git_unavailable(tmp_path):
    # No git repo here at all -> `git log` fails -> pragmatic fallback: a
    # fixed lookback window rather than raising, so attribution scanning
    # still gets a usable (if wider) window instead of blocking tightening
    # entirely on git plumbing being present.
    result = baseline_since(tmp_path, "pyproject.toml")

    parsed = datetime.fromisoformat(result)
    assert parsed.tzinfo is not None
    assert parsed < datetime.now(UTC) - timedelta(days=1)


def test_baseline_since_falls_back_when_file_never_committed(tmp_path):
    _init_repo_with_baseline_commit(tmp_path, "pyproject.toml")
    # "other.toml" was never committed -> git log has no output for it.
    result = baseline_since(tmp_path, "other.toml")

    parsed = datetime.fromisoformat(result)
    assert parsed.tzinfo is not None
    assert parsed < datetime.now(UTC) - timedelta(days=1)
