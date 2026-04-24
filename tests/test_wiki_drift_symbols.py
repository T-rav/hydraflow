"""B3 — symbol-level drift detection.

P4 flagged entries citing files that no longer exist. B3 extends
the detector to also flag entries where the file still exists but
the cited symbol (class / function name after the colon) is no
longer defined in that file. Pure deterministic check — grep the
file for ``class <Symbol>`` or ``def <Symbol>`` (covering
``async def`` and leading whitespace).

LLM-driven semantic drift ("the claim about this symbol is stale
even though the symbol exists") is a follow-up; this pass is the
cheap deterministic foundation.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from wiki_drift_detector import detect_drift


def _write_entry(
    tracked_root: Path,
    repo_slug: str,
    topic: str,
    *,
    body: str,
    entry_id: str = "01JF000000000000000001",
    source_issue: int = 1,
) -> Path:
    topic_dir = tracked_root / repo_slug / topic
    topic_dir.mkdir(parents=True, exist_ok=True)
    now = datetime.now(UTC).isoformat()
    path = topic_dir / f"0001-issue-{source_issue}.md"
    path.write_text(
        "---\n"
        f"id: {entry_id}\n"
        f"topic: {topic}\n"
        f"source_issue: {source_issue}\n"
        "source_phase: implement\n"
        f"created_at: {now}\n"
        "status: active\n"
        "---\n"
        f"{body}\n",
        encoding="utf-8",
    )
    return path


def test_flags_missing_class_symbol(tmp_path: Path) -> None:
    tracked_root = tmp_path / "repo_wiki"
    repo_root = tmp_path / "repo"
    (repo_root / "src").mkdir(parents=True)
    # File exists but NO Ghost class/function defined.
    (repo_root / "src" / "foo.py").write_text("class OtherThing:\n    pass\n")

    _write_entry(
        tracked_root,
        "o/r",
        "patterns",
        body="Cited in `src/foo.py:Ghost`.",
    )

    result = detect_drift(
        tracked_root=tracked_root, repo_root=repo_root, repo_slug="o/r"
    )

    assert len(result.findings) == 1
    finding = result.findings[0]
    assert finding.missing_files == frozenset()
    assert "src/foo.py:Ghost" in finding.missing_symbols


def test_passes_when_class_symbol_exists(tmp_path: Path) -> None:
    tracked_root = tmp_path / "repo_wiki"
    repo_root = tmp_path / "repo"
    (repo_root / "src").mkdir(parents=True)
    (repo_root / "src" / "foo.py").write_text("class Ghost:\n    pass\n")

    _write_entry(tracked_root, "o/r", "patterns", body="Cited `src/foo.py:Ghost`.")

    result = detect_drift(
        tracked_root=tracked_root, repo_root=repo_root, repo_slug="o/r"
    )

    assert result.findings == []


def test_passes_when_function_symbol_exists(tmp_path: Path) -> None:
    tracked_root = tmp_path / "repo_wiki"
    repo_root = tmp_path / "repo"
    (repo_root / "src").mkdir(parents=True)
    (repo_root / "src" / "foo.py").write_text("def ghost():\n    return None\n")

    _write_entry(tracked_root, "o/r", "patterns", body="Cited `src/foo.py:ghost`.")

    result = detect_drift(
        tracked_root=tracked_root, repo_root=repo_root, repo_slug="o/r"
    )

    assert result.findings == []


def test_passes_for_async_function(tmp_path: Path) -> None:
    tracked_root = tmp_path / "repo_wiki"
    repo_root = tmp_path / "repo"
    (repo_root / "src").mkdir(parents=True)
    (repo_root / "src" / "foo.py").write_text("async def go():\n    pass\n")

    _write_entry(tracked_root, "o/r", "patterns", body="Cited `src/foo.py:go`.")

    result = detect_drift(
        tracked_root=tracked_root, repo_root=repo_root, repo_slug="o/r"
    )

    assert result.findings == []


def test_passes_for_indented_method(tmp_path: Path) -> None:
    tracked_root = tmp_path / "repo_wiki"
    repo_root = tmp_path / "repo"
    (repo_root / "src").mkdir(parents=True)
    (repo_root / "src" / "foo.py").write_text(
        "class Container:\n    def the_method(self):\n        pass\n"
    )

    _write_entry(tracked_root, "o/r", "patterns", body="Cited `src/foo.py:the_method`.")

    result = detect_drift(
        tracked_root=tracked_root, repo_root=repo_root, repo_slug="o/r"
    )

    assert result.findings == []


def test_mixed_missing_file_and_missing_symbol(tmp_path: Path) -> None:
    tracked_root = tmp_path / "repo_wiki"
    repo_root = tmp_path / "repo"
    (repo_root / "src").mkdir(parents=True)
    (repo_root / "src" / "present.py").write_text("class NotTheOne:\n    pass\n")
    # src/ghost.py deliberately missing

    _write_entry(
        tracked_root,
        "o/r",
        "patterns",
        body="Cites `src/ghost.py:Ghost` and `src/present.py:TheMissing`.",
    )

    result = detect_drift(
        tracked_root=tracked_root, repo_root=repo_root, repo_slug="o/r"
    )

    assert len(result.findings) == 1
    finding = result.findings[0]
    assert "src/ghost.py" in finding.missing_files
    assert "src/present.py:TheMissing" in finding.missing_symbols
