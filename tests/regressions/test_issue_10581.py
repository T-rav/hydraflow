"""Regression for issue #10581.

The wiki DRIFT detector (`wiki_drift_detector.detect_drift`) only recognized
the strict single-backtick-span form ``src/path.py:Symbol``.  Plan-phase
ingested entries routinely cite code in *prose* — a symbol span near a module
span ("``DETECTOR_GENERATION`` constant in ``escape/detect.py``"), a dotted
call (``metrics.dedupe_by_detection_ref()``), or a bare ``src/models.py`` — so
an entry proposing never-implemented code sat at ``status: active`` forever
(e.g. architecture/0204, gotchas/0842).

The fix adds a **report-only** ``detect_prose_drift`` channel to
``wiki_drift_detector`` that recognizes these forms.  It never feeds
``apply_drift_markers`` — a heuristic false positive must cost a log line, not
a ``status: stale`` flip across ~395 active entries.

This module's helpers (``_write_entry``) are deliberately retargeted at the new
``detect_prose_drift`` function per the plan; they model the two live entries
from the issue.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from wiki_drift_detector import (
    ProseDriftFinding,
    detect_drift,
    detect_prose_drift,
)


def _write_entry(
    tracked_root: Path,
    repo_slug: str,
    topic: str,
    *,
    body: str,
    status: str = "active",
    source_issue: int = 10504,
    entry_id: str = "01JF000000000000000001",
) -> Path:
    topic_dir = tracked_root / repo_slug / topic
    topic_dir.mkdir(parents=True, exist_ok=True)
    now = datetime.now(UTC).isoformat()
    path = topic_dir / f"0204-issue-{source_issue}.md"
    path.write_text(
        "---\n"
        f"id: {entry_id}\n"
        f"topic: {topic}\n"
        f"source_issue: {source_issue}\n"
        "source_phase: plan\n"
        f"created_at: {now}\n"
        f"status: {status}\n"
        "---\n"
        f"{body}\n",
        encoding="utf-8",
    )
    return path


def _build_src(repo_root: Path) -> None:
    """Materialize a small ``src/`` tree modeled on the real repo.

    ``escape/detect.py`` and ``escape/metrics.py`` exist as *files* but do NOT
    define the symbols the issue's entries cite — that mismatch is exactly the
    unimplemented-proposal drift #10581 must catch.
    """
    escape = repo_root / "src" / "escape"
    escape.mkdir(parents=True)
    (escape / "__init__.py").write_text("", encoding="utf-8")
    (escape / "detect.py").write_text(
        "class Detector:\n    def run(self):\n        return None\n",
        encoding="utf-8",
    )
    (escape / "metrics.py").write_text(
        "def record_gauge(name):\n    return name\n",
        encoding="utf-8",
    )
    runner = repo_root / "src" / "runner.py"
    runner.write_text(
        "def handle_start():\n    return True\n",
        encoding="utf-8",
    )


def _suspect_symbols(findings: list[ProseDriftFinding]) -> set[str]:
    out: set[str] = set()
    for finding in findings:
        out |= set(finding.suspect_symbols)
    return out


def test_prose_two_span_cite_to_unimplemented_symbol_is_flagged(
    tmp_path: Path,
) -> None:
    # Arrange: the architecture/0204 shape — a bare identifier span paired with
    # a module-path span that resolves, but the symbol is never implemented.
    tracked_root = tmp_path / "repo_wiki"
    repo_root = tmp_path / "repo"
    _build_src(repo_root)
    _write_entry(
        tracked_root,
        "o/r",
        "architecture",
        body="We will add a `DETECTOR_GENERATION` constant in `escape/detect.py`.",
    )

    # Act
    findings = detect_prose_drift(
        tracked_root=tracked_root, repo_root=repo_root, repo_slug="o/r"
    )

    # Assert
    assert len(findings) == 1
    assert any("DETECTOR_GENERATION" in s for s in findings[0].suspect_symbols)


def test_prose_dotted_cite_to_unimplemented_symbol_is_flagged(
    tmp_path: Path,
) -> None:
    # Arrange: the dotted-call shape `metrics.dedupe_by_detection_ref()`.
    tracked_root = tmp_path / "repo_wiki"
    repo_root = tmp_path / "repo"
    _build_src(repo_root)
    _write_entry(
        tracked_root,
        "o/r",
        "gotchas",
        body="Dedup happens via `metrics.dedupe_by_detection_ref()` after ingest.",
    )

    # Act
    findings = detect_prose_drift(
        tracked_root=tracked_root, repo_root=repo_root, repo_slug="o/r"
    )

    # Assert
    assert any("dedupe_by_detection_ref" in s for s in _suspect_symbols(findings))


def test_prose_cite_to_implemented_symbol_is_not_flagged(tmp_path: Path) -> None:
    # Arrange: a genuine reference — `handle_start` IS defined under src/.
    tracked_root = tmp_path / "repo_wiki"
    repo_root = tmp_path / "repo"
    _build_src(repo_root)
    _write_entry(
        tracked_root,
        "o/r",
        "architecture",
        body="The `handle_start` entrypoint lives in `runner.py`.",
    )

    # Act
    findings = detect_prose_drift(
        tracked_root=tracked_root, repo_root=repo_root, repo_slug="o/r"
    )

    # Assert
    assert findings == []


def test_prose_cite_whose_module_does_not_resolve_is_not_flagged(
    tmp_path: Path,
) -> None:
    # Arrange: random prose in backticks near a module that names no real
    # source file must NOT be flagged — the module credibility gate.
    tracked_root = tmp_path / "repo_wiki"
    repo_root = tmp_path / "repo"
    _build_src(repo_root)
    _write_entry(
        tracked_root,
        "o/r",
        "architecture",
        body="The `execution` step reads `not_a_real_module.py` at boot.",
    )

    # Act
    findings = detect_prose_drift(
        tracked_root=tracked_root, repo_root=repo_root, repo_slug="o/r"
    )

    # Assert
    assert findings == []


def test_stale_entries_are_not_scanned(tmp_path: Path) -> None:
    # Arrange: a stale entry with an unimplemented prose cite.
    tracked_root = tmp_path / "repo_wiki"
    repo_root = tmp_path / "repo"
    _build_src(repo_root)
    _write_entry(
        tracked_root,
        "o/r",
        "architecture",
        body="We will add a `DETECTOR_GENERATION` constant in `escape/detect.py`.",
        status="stale",
    )

    # Act
    findings = detect_prose_drift(
        tracked_root=tracked_root, repo_root=repo_root, repo_slug="o/r"
    )

    # Assert
    assert findings == []


def test_bare_missing_src_file_is_flagged(tmp_path: Path) -> None:
    # Arrange: a bare `src/...py` cite whose file does not exist.
    tracked_root = tmp_path / "repo_wiki"
    repo_root = tmp_path / "repo"
    _build_src(repo_root)
    _write_entry(
        tracked_root,
        "o/r",
        "architecture",
        body="State lives in `src/models.py`.",
    )

    # Act
    findings = detect_prose_drift(
        tracked_root=tracked_root, repo_root=repo_root, repo_slug="o/r"
    )

    # Assert
    assert len(findings) == 1
    assert any("src/models.py" in s for s in findings[0].suspect_symbols)


def test_report_only_never_mutates_entry_status(tmp_path: Path) -> None:
    # Arrange
    tracked_root = tmp_path / "repo_wiki"
    repo_root = tmp_path / "repo"
    _build_src(repo_root)
    entry = _write_entry(
        tracked_root,
        "o/r",
        "architecture",
        body="We will add a `DETECTOR_GENERATION` constant in `escape/detect.py`.",
    )

    # Act
    detect_prose_drift(tracked_root=tracked_root, repo_root=repo_root, repo_slug="o/r")

    # Assert: the entry on disk is untouched — no status: stale flip.
    text = entry.read_text(encoding="utf-8")
    assert "status: active" in text
    assert "status: stale" not in text
    assert "stale_reason" not in text


def test_strict_detect_drift_behavior_unchanged(tmp_path: Path) -> None:
    # Arrange: the strict `src/path.py:Symbol` path must keep working exactly.
    tracked_root = tmp_path / "repo_wiki"
    repo_root = tmp_path / "repo"
    _build_src(repo_root)
    _write_entry(
        tracked_root,
        "o/r",
        "architecture",
        body="Cited in `src/escape/detect.py:Ghost`.",
    )

    # Act
    result = detect_drift(
        tracked_root=tracked_root, repo_root=repo_root, repo_slug="o/r"
    )

    # Assert: strict detector still flags the missing symbol.
    assert len(result.findings) == 1
    assert "src/escape/detect.py:Ghost" in result.findings[0].missing_symbols
