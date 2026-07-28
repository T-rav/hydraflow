"""Tests for the one-shot lesson-coverage auditor CLI (#10758).

The CLI is the runnable ``wiki_lesson_coverage`` tool that
``repo_wiki/.../gotchas/1157`` and ``.../architecture/0241`` instruct readers
to run (#10754). It is read-only: it prints a tier table, optionally writes a
``--json`` artifact, and must never dirty the tracked ``repo_wiki/`` tree.
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from types import ModuleType

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT_PATH = REPO_ROOT / "scripts" / "audit_wiki_lesson_coverage.py"


def _load_cli() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "audit_wiki_lesson_coverage", SCRIPT_PATH
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _write_entry(
    topic_dir: Path,
    *,
    entry_id: str,
    title: str,
    body: str = "",
    status: str = "active",
    superseded_by: str | None = None,
    supersedes: list[str] | None = None,
    code_refs: str | None = None,
) -> None:
    topic_dir.mkdir(parents=True, exist_ok=True)
    lines = [
        "---",
        f"id: {entry_id}",
        f"topic: {topic_dir.name}",
        "source_issue: synthesis",
        "source_phase: synthesis",
        "created_at: 2026-01-01T00:00:00+00:00",
        f"status: {status}",
        "corroborations: 1",
    ]
    if superseded_by is not None:
        lines.append(f"superseded_by: {superseded_by}")
    if supersedes:
        lines.append("supersedes: " + ",".join(supersedes))
    if code_refs is not None:
        lines.append(f"code_refs: {code_refs}")
    lines += ["---", "", f"# {title}", "", body or f"Body for {entry_id}.", ""]
    slug = title.lower().replace(" ", "-")
    (topic_dir / f"{entry_id}-issue-synthesis-{slug}.md").write_text(
        "\n".join(lines), encoding="utf-8"
    )


def _corpus_with_one_orphan(tmp_path: Path) -> tuple[Path, Path]:
    """Build a tracked wiki + source tree with exactly one orphaned lesson."""
    repo_root = tmp_path / "src_root"
    (repo_root / "src").mkdir(parents=True)
    (repo_root / "src" / "detect.py").write_text(
        '_SHA_MARKER = "x"\n', encoding="utf-8"
    )

    tracked_root = tmp_path / "repo_wiki"
    gotchas = tracked_root / "T-rav" / "hydraflow" / "gotchas"
    _write_entry(
        gotchas,
        entry_id="0841",
        title="Marker splitlines bug",
        status="superseded",
        superseded_by="0851",
        code_refs="src/detect.py:_SHA_MARKER",
    )
    _write_entry(
        gotchas,
        entry_id="0851",
        title="Unrelated successor",
        status="active",
        supersedes=["0841"],
        body="Nothing about the marker here.",
    )
    return tracked_root, repo_root


def test_cli_reports_orphan_tier_and_exits_zero(tmp_path, capsys) -> None:
    tracked_root, repo_root = _corpus_with_one_orphan(tmp_path)
    cli = _load_cli()
    rc = cli.main(
        [
            "--repo",
            "T-rav/hydraflow",
            "--tracked-root",
            str(tracked_root),
            "--repo-root",
            str(repo_root),
        ]
    )
    out = capsys.readouterr().out
    assert rc == 0
    assert "orphaned" in out
    assert "0841" in out


def test_cli_writes_json_artifact(tmp_path) -> None:
    tracked_root, repo_root = _corpus_with_one_orphan(tmp_path)
    json_path = tmp_path / "coverage.json"
    cli = _load_cli()
    rc = cli.main(
        [
            "--repo",
            "T-rav/hydraflow",
            "--tracked-root",
            str(tracked_root),
            "--repo-root",
            str(repo_root),
            "--json",
            str(json_path),
        ]
    )
    assert rc == 0
    payload = json.loads(json_path.read_text(encoding="utf-8"))
    assert payload["tier_counts"]["orphaned"] == 1
    assert payload["orphaned"][0]["predecessor_id"] == "0841"


def test_cli_never_writes_into_tracked_root(tmp_path) -> None:
    tracked_root, repo_root = _corpus_with_one_orphan(tmp_path)
    before = {p: p.read_bytes() for p in tracked_root.rglob("*.md")}
    cli = _load_cli()
    cli.main(
        [
            "--repo",
            "T-rav/hydraflow",
            "--tracked-root",
            str(tracked_root),
            "--repo-root",
            str(repo_root),
        ]
    )
    after = {p: p.read_bytes() for p in tracked_root.rglob("*.md")}
    assert before == after  # read-only: tracked wiki byte-identical
