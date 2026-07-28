"""Tests for the round-scoped repair CLI's lesson-coverage wiring (#10757).

#10655/#10757 asked for the content-completeness check to be *wired into the
round-scoped repair*. The repair CLI grows a ``--coverage`` flag that runs the
lesson-survival tiering alongside the pointer repair and reports the orphaned
predecessors a merge left behind.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT_PATH = REPO_ROOT / "scripts" / "repair_wiki_supersession.py"


def _load_cli() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "repair_wiki_supersession", SCRIPT_PATH
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


def test_coverage_flag_reports_orphaned_predecessor(tmp_path, capsys) -> None:
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
            "--coverage",
        ]
    )
    out = capsys.readouterr().out
    assert rc == 0
    assert "orphaned" in out
    assert "0841" in out


def test_coverage_is_opt_in_default_run_unchanged(tmp_path, capsys) -> None:
    tracked_root, repo_root = _corpus_with_one_orphan(tmp_path)
    cli = _load_cli()
    rc = cli.main(["--repo", "T-rav/hydraflow", "--tracked-root", str(tracked_root)])
    out = capsys.readouterr().out
    assert rc == 0
    # Default report keeps its existing shape — no coverage section.
    assert "orphaned lessons" not in out
