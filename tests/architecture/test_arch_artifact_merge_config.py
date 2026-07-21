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
    """The paths .gitattributes points at must be real (no stale globs)."""
    for rel in (_CHANGELOG, _META):
        assert (_REPO_ROOT / rel).exists(), (
            f"{rel} is named in .gitattributes but does not exist — the "
            "auto-merge rule is dead. Update .gitattributes if the artifact moved."
        )


def test_changelog_uses_union_merge() -> None:
    """The append-only changelog must auto-resolve via the built-in union driver."""
    attrs = _read(_GITATTRIBUTES)
    line = next(
        (ln for ln in attrs.splitlines() if ln.strip().startswith(_CHANGELOG)),
        None,
    )
    assert line is not None, (
        f".gitattributes must have a `{_CHANGELOG} merge=union` rule so the "
        "changelog auto-resolves on merge. Missing → manual re-resolve returns."
    )
    assert "merge=union" in line, (
        f"{_CHANGELOG} must use `merge=union` (built-in, honoured by GitHub); "
        f"found: {line!r}"
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
