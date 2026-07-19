"""HOLDOUT marker semantics for the adversarial corpus loader."""

from pathlib import Path

from tests.trust.adversarial.corpus_runner import discover_cases, is_holdout

CASES = Path(__file__).parent / "cases"


def _make_case(tmp_path: Path, name: str, *, holdout: bool) -> Path:
    d = tmp_path / name
    (d / "before").mkdir(parents=True)
    (d / "after").mkdir()
    (d / "expected_catcher.txt").write_text("diff-sanity\n")
    (d / "README.md").write_text(f"# {name}\n\nKeyword: sentinel-kw\n")
    if holdout:
        (d / "HOLDOUT").write_text("")
    return d


def test_is_holdout_detects_marker(tmp_path: Path) -> None:
    case = _make_case(tmp_path, "trap-a", holdout=True)
    plain = _make_case(tmp_path, "plain-b", holdout=False)
    assert is_holdout(case) is True
    assert is_holdout(plain) is False


def test_discover_excludes_holdout_when_asked(tmp_path: Path) -> None:
    _make_case(tmp_path, "trap-a", holdout=True)
    _make_case(tmp_path, "plain-b", holdout=False)
    names = [c.name for c in discover_cases(tmp_path, include_holdout=False)]
    assert names == ["plain-b"]
    names_all = [c.name for c in discover_cases(tmp_path)]
    assert names_all in (["plain-b", "trap-a"], ["trap-a", "plain-b"])


def test_seed_holdout_cases_exist_and_are_marked() -> None:
    holdouts = [c for c in discover_cases(CASES) if is_holdout(c)]
    assert len(holdouts) >= 6, [c.name for c in holdouts]
