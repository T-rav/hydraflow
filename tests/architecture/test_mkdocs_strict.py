"""Strict-build test: catches broken cross-links before Pages deploy."""

import shutil
import subprocess
from pathlib import Path

import pytest


def test_mkdocs_build_strict_succeeds(real_repo_root: Path, tmp_path: Path):
    """Run `mkdocs build --strict` against the live docs tree.

    Fails on any warning. This is the gate that catches a generator
    emitting a relative link to a page that doesn't exist (e.g. an ADR
    file path that's been deleted).

    Builds into a throwaway ``--site-dir``: the default (repo-root
    ``site/``) leaves a stray top-level directory behind, which
    ``test_every_top_level_path_is_tested_or_exempt`` then flags as an
    uncovered CI path — a same-suite ordering flake.
    """
    assert shutil.which("mkdocs") is not None, "mkdocs must be installed"
    res = subprocess.run(
        ["mkdocs", "build", "--strict", "--site-dir", str(tmp_path / "site")],
        cwd=real_repo_root,
        capture_output=True,
        text=True,
        check=False,
    )
    if res.returncode != 0:
        pytest.fail(
            f"`mkdocs build --strict` failed:\n"
            f"--- stdout ---\n{res.stdout}\n"
            f"--- stderr ---\n{res.stderr}"
        )
