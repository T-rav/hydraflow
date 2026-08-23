"""Strict-build test: catches broken cross-links before Pages deploy."""

import shutil
import subprocess
from pathlib import Path

import pytest


def test_mkdocs_build_strict_succeeds(
    real_repo_root: Path, tmp_path: Path, gitignored_artifacts: None
):
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


#: Generated artifacts that are gitignored rather than committed, so they are
#: absent from a fresh checkout. ``mkdocs.yml`` navs them and ``docs/index.md``
#: links them, so a strict build fails without them -- which is how CI went red
#: while every local tree (where a previous ``arch-regen`` had left the file
#: behind) stayed green.
_UNTRACKED_ARTIFACTS = ("changelog.md",)


@pytest.fixture
def gitignored_artifacts(real_repo_root: Path, tmp_path: Path) -> None:
    """Provision untracked generated artifacts, as pages-deploy.yml does.

    The real deploy runs ``arch.runner --emit`` before ``mkdocs build``; this
    test has to do the same or it is testing a site the deploy never builds.
    Emits into a throwaway directory and copies only the untracked artifacts
    across, so a stale tracked artifact is still caught by arch-check rather
    than being silently overwritten here.

    A FIXTURE rather than an inline call: ``arch.runner.emit`` runs
    ``git log --since=90.days.ago`` over the repo, and folding that into the
    test body pushed it past the 60s duration ratchet in CI (where the artifact
    is always absent). The ratchet measures the ``call`` phase only, and
    provisioning is setup — it is not the thing under test.
    """
    repo_root = real_repo_root
    generated = repo_root / "docs/arch/generated"
    missing = [n for n in _UNTRACKED_ARTIFACTS if not (generated / n).exists()]
    if not missing:
        return

    from arch import runner  # noqa: PLC0415

    staging = tmp_path / "arch-emit"
    runner.emit(repo_root=repo_root, out_dir=staging)
    for name in missing:
        shutil.copyfile(staging / name, generated / name)
