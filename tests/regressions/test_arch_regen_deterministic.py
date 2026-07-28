"""Regression: ``arch.runner --emit`` must be DETERMINISTIC for unchanged source.

Bug (flux source): ``DiagramLoop`` (L24) opened a ``chore(arch): regenerate
architecture`` PR every interval even when the architecture was unchanged,
because ``emit()`` wrote VOLATILE fields into the committed
``docs/arch/.meta.json`` — a wall-clock ``regenerated_at`` timestamp and the
current HEAD ``commit_sha``/``source_sha``. Every regen therefore produced a
git diff even when the module graph / loop registry / ports were byte-identical,
so the loop's no-diff gate never fired → a churn PR every tick.

Fix: the committed ``.meta.json`` is now a deterministic CONTENT digest (per
artifact + overall SHA-256 of the stamped bodies), never HEAD- or wall-clock-
derived. The volatile provenance (``regenerated_at`` + HEAD sha) moved to a
gitignored ``docs/arch/.meta.local.json`` sidecar, so it never enters a commit.

This test pins the invariant: two consecutive emits of identical source produce
BYTE-IDENTICAL committed artifacts (the ``*.md`` files AND ``.meta.json``). It
trips CI the moment regen non-determinism returns.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest


@pytest.fixture
def populated_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "src").mkdir()
    (repo / "src/widget_loop.py").write_text(
        "from base_background_loop import BaseBackgroundLoop\n"
        "class WidgetLoop(BaseBackgroundLoop):\n"
        "    pass\n"
    )
    (repo / "src/mockworld/fakes").mkdir(parents=True)
    (repo / "tests/scenarios").mkdir(parents=True)
    (repo / "docs/adr").mkdir(parents=True)
    (repo / "docs/adr/0001-thing.md").write_text("# ADR-0001\n")
    subprocess.run(["git", "init"], cwd=repo, check=True, capture_output=True)
    subprocess.run(
        ["git", "-c", "user.email=t@t", "-c", "user.name=t", "add", "."],
        cwd=repo,
        check=True,
    )
    subprocess.run(
        ["git", "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-m", "init"],
        cwd=repo,
        check=True,
        capture_output=True,
    )
    return repo


def _committed_artifacts(repo: Path, out: Path) -> dict[str, bytes]:
    """Bytes of every COMMITTED artifact: the drift-checked ``*.md`` files plus
    ``.meta.json``. Excludes the gitignored ``.meta.local.json`` sidecar."""
    from arch.runner import _ARTIFACT_FILES

    files = {name: (out / name) for name in _ARTIFACT_FILES}
    files[".meta.json"] = out.parent / ".meta.json"
    return {rel: p.read_bytes() for rel, p in files.items() if p.exists()}


def test_two_emits_of_unchanged_source_are_byte_identical(populated_repo: Path) -> None:
    from arch.runner import emit

    out_a = populated_repo / "a" / "generated"
    out_b = populated_repo / "b" / "generated"
    emit(repo_root=populated_repo, out_dir=out_a)
    emit(repo_root=populated_repo, out_dir=out_b)

    art_a = _committed_artifacts(populated_repo, out_a)
    art_b = _committed_artifacts(populated_repo, out_b)

    assert art_a.keys() == art_b.keys()
    # The load-bearing assertion: no committed artifact drifts between two
    # identical-input regens (unchanged architecture → zero diff → no churn PR).
    drifted = [rel for rel in art_a if art_a[rel] != art_b[rel]]
    assert drifted == [], f"non-deterministic committed artifacts: {drifted}"
    # ``.meta.json`` in particular must be stable (it was THE flux source).
    assert art_a[".meta.json"] == art_b[".meta.json"]


def test_committed_meta_has_no_volatile_fields(populated_repo: Path) -> None:
    from arch.runner import emit

    out = populated_repo / "docs/arch/generated"
    emit(repo_root=populated_repo, out_dir=out)
    meta = json.loads((out.parent / ".meta.json").read_text())

    # No wall-clock, no HEAD sha — only content digests.
    assert "regenerated_at" not in meta
    assert "commit_sha" not in meta
    assert "content_sha" in meta and meta["content_sha"]
    for entry in meta["artifacts"].values():
        assert "source_sha" not in entry
        assert entry.get("content_sha")


def test_volatile_stamp_written_to_sidecar(populated_repo: Path) -> None:
    from arch.runner import emit

    out = populated_repo / "docs/arch/generated"
    emit(repo_root=populated_repo, out_dir=out)
    sidecar = out.parent / ".meta.local.json"

    assert sidecar.exists(), "volatile provenance sidecar must be written"
    local = json.loads(sidecar.read_text())
    # The freshness signal the committed file dropped is preserved here.
    assert local.get("regenerated_at")
    assert "commit_sha" in local


def test_sidecar_is_gitignored_in_the_real_repo() -> None:
    """The sidecar must be gitignored in the ACTUAL project so it can never
    enter a commit (which would re-arm the churn / merge conflicts)."""
    root = Path(
        subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            cwd=Path(__file__).parent,
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()
    )
    check = subprocess.run(
        ["git", "check-ignore", "docs/arch/.meta.local.json"],
        cwd=root,
        capture_output=True,
        text=True,
    )
    assert check.returncode == 0, "docs/arch/.meta.local.json must be gitignored"
    # It must also not be tracked (never committed).
    tracked = subprocess.run(
        ["git", "ls-files", "docs/arch/.meta.local.json"],
        cwd=root,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
    assert tracked == "", "docs/arch/.meta.local.json must not be git-tracked"
