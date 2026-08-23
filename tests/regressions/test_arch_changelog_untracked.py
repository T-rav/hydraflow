"""The arch changelog is a view of `git log`; it must not be committed.

`docs/arch/generated/changelog.md` renders from a moving
`git log --since=90.days.ago` window, so its bytes are a function of the
branch's commit graph rather than of source. Committing it guaranteed
perpetual divergence: it conflicted on every rebase and staging advance, and
the `merge=union` driver "resolved" that by duplicating entries.

Nothing validated the committed copy -- `arch.runner` exempts it from drift
detection, `.meta.json` stopped digesting it (#11674), `mkdocs.yml` never
listed it, and `DiagramLoop` already excluded it from the regen-PR trigger.
It is now rendered at Pages-deploy time.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parents[2]
_REL = "docs/arch/generated/changelog.md"


def _git(*args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=_REPO, capture_output=True, text=True, check=False
    ).stdout.strip()


def test_the_changelog_is_not_tracked() -> None:
    assert _git("ls-files", "--", _REL) == "", (
        f"{_REL} is committed again. It is a view of git history, so every "
        "branch renders different bytes and it conflicts on every rebase."
    )


def test_the_changelog_is_ignored_so_a_regen_cannot_dirty_the_tree() -> None:
    """Untracked-but-unignored would leave a permanent '??' in git status."""
    assert _git("check-ignore", "--", _REL) == _REL, (
        f"{_REL} is untracked but NOT ignored — `arch.runner --emit` would "
        "leave it as untracked dirt in every worktree."
    )


def test_no_merge_driver_is_declared_for_it() -> None:
    """A driver for a path git no longer tracks is a stale instruction."""
    attrs = (_REPO / ".gitattributes").read_text()
    live = [
        ln
        for ln in attrs.splitlines()
        if ln.strip() and not ln.lstrip().startswith("#") and _REL in ln
    ]
    assert not live, f"stale merge rule for an untracked path: {live}"


def test_the_site_still_renders_it_at_deploy_time() -> None:
    """Untracking is only safe because Pages regenerates before it builds."""
    wf = (_REPO / ".github/workflows/pages-deploy.yml").read_text()
    assert "arch.runner --emit" in wf, (
        "pages-deploy.yml no longer regenerates artifacts — readers would get "
        "no changelog at all now that it is not committed."
    )


def test_it_is_still_emitted_by_the_runner() -> None:
    """Untracked, not undone: the artifact must still be produced."""
    from arch import runner

    assert "changelog.md" in runner._ARTIFACT_FILES
    assert "changelog.md" in runner._DRIFT_EXEMPT


@pytest.mark.parametrize(
    "other",
    ["loops.md", "ports.md", "modules.md", "events.md"],
)
def test_deterministic_artifacts_are_still_tracked(other: str) -> None:
    """Negative control -- this must not become a licence to untrack them all."""
    rel = f"docs/arch/generated/{other}"
    assert _git("ls-files", "--", rel) == rel, f"{rel} must stay committed"
