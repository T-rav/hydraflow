"""Guard the auto-merge wiring for the volatile generated arch artifacts.

``docs/arch/.meta.json`` and ``docs/arch/generated/changelog.md`` are
regenerated on essentially every commit, so branches that both ran arch-regen
conflict on them on every staging advance. ``.gitattributes`` + a merge driver
registered by ``make ensure-hooks`` auto-resolve those two files at merge time
(``merge=union`` for the changelog, ``merge=arch-meta`` = keep-incoming for the
JSON). This guard keeps that wiring intact — if someone drops the
``.gitattributes`` entry or the ``ensure-hooks`` registration, the endless
manual re-resolution returns silently.

The test asserts only committed WIRING (files + Makefile text); it does NOT
assert the driver is registered in the current ``git config`` — CI checkouts do
not run ``make ensure-hooks``, and coupling to live git config would make this
flaky.
"""

from __future__ import annotations

from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
_GITATTRIBUTES = _REPO_ROOT / ".gitattributes"
_MAKEFILE = _REPO_ROOT / "Makefile"

# The two volatile artifacts whose merges we auto-resolve, and the strategy
# each must use. Keep in sync with .gitattributes.
_CHANGELOG = "docs/arch/generated/changelog.md"
_META = "docs/arch/.meta.json"


def _read(path: Path) -> str:
    assert path.exists(), f"expected {path.relative_to(_REPO_ROOT)} to exist"
    return path.read_text(encoding="utf-8")


def test_target_artifacts_exist() -> None:
    """The paths .gitattributes points at must be real (no stale globs).

    Only ``_META`` is checked. ``_CHANGELOG`` is no longer a .gitattributes
    target *or* a tracked file — it is gitignored and rendered at Pages-deploy
    time — so asserting it exists on disk would pass on any machine that had
    run ``arch-regen`` and fail on every fresh checkout, which is precisely
    how it failed in CI while passing locally.
    """
    assert (_REPO_ROOT / _META).exists(), (
        f"{_META} is named in .gitattributes but does not exist — the "
        "auto-merge rule is dead. Update .gitattributes if the artifact moved."
    )


def test_changelog_is_untracked_rather_than_union_merged() -> None:
    """The changelog is no longer committed, so it needs no merge rule at all.

    It used to carry `merge=union`, which auto-resolved conflicts by keeping
    both sides' lines -- i.e. by DUPLICATING entries until the next mainline
    regen cleaned them. That treated the symptom: the file renders from a
    moving `git log` window, so its bytes are a function of the branch's commit
    graph and it can never be conflict-free while tracked. It is now rendered
    at Pages-deploy time instead, which removes the conflict class outright.
    """
    import subprocess

    tracked = subprocess.run(
        ["git", "ls-files", "--", _CHANGELOG],
        cwd=_GITATTRIBUTES.parent,
        capture_output=True,
        text=True,
        check=False,
    ).stdout.strip()
    assert tracked == "", (
        f"{_CHANGELOG} is committed again — it is a view of git history, so "
        "every branch renders different bytes and it conflicts on every rebase."
    )

    attrs = _read(_GITATTRIBUTES)
    live = [
        ln
        for ln in attrs.splitlines()
        if ln.strip() and not ln.lstrip().startswith("#") and _CHANGELOG in ln
    ]
    assert not live, (
        f"stale merge rule for an untracked path: {live}. A driver for a file "
        "git no longer tracks is an instruction nothing will ever follow."
    )


def test_meta_uses_arch_meta_driver() -> None:
    """.meta.json must auto-resolve via the custom keep-incoming arch-meta driver."""
    attrs = _read(_GITATTRIBUTES)
    line = next(
        (ln for ln in attrs.splitlines() if ln.strip().startswith(_META)),
        None,
    )
    assert line is not None, (
        f".gitattributes must have a `{_META} merge=arch-meta` rule. Missing → "
        "the regen-stamp JSON conflicts on every staging advance."
    )
    assert "merge=arch-meta" in line, (
        f"{_META} must use `merge=arch-meta` (union would corrupt the JSON); "
        f"found: {line!r}"
    )


def test_ensure_hooks_registers_arch_meta_driver() -> None:
    """`make ensure-hooks` must register the arch-meta driver.

    Without the driver registration the `.gitattributes merge=arch-meta`
    reference resolves to nothing and git falls back to a normal (conflicting)
    merge for .meta.json.
    """
    makefile = _read(_MAKEFILE)
    assert "merge.arch-meta.driver" in makefile, (
        "Makefile `ensure-hooks` must register the arch-meta merge driver "
        "(`git config merge.arch-meta.driver ...`) so the .gitattributes rule "
        "has a driver to invoke. See .gitattributes for why."
    )
