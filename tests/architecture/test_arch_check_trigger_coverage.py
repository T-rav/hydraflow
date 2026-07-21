"""Guard: the pre-commit arch-check trigger covers every arch-generator input.

`make arch-check` regenerates ALL arch artifacts and diffs them, so at the
bake/CI/pre-push tier drift is caught comprehensively (pre-push runs it
unconditionally). The EARLY gate — `.githooks/pre-commit` — instead runs
arch-check only when a staged path matches a hand-maintained trigger
(``STAGED_ARCH`` / ``STAGED_PY``). If that trigger omits a path the generators
actually read, a change there drifts a generated artifact but slips past the
earliest gate to the bake.

That exact gap bit us: ``coverage_matrix.py`` rglobs ``docs/wiki/**`` and greps
``docs/adr/*.md`` (loop→doc references), so a wiki/ADR-only commit drifts
``docs/arch/generated/coverage_matrix.md`` — but ``docs/wiki`` / ``docs/adr``
were not in the pre-commit trigger.

This guard keeps the trigger a superset of the generators' input roots AND ties
each required root to real evidence in the generator source, so it cannot drift
from reality again: if a generator stops reading a root, drop it here; if the
trigger stops covering a root a generator still reads, this reddens.
"""

from __future__ import annotations

import re
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
_PRE_COMMIT = _REPO_ROOT / ".githooks" / "pre-commit"
_ARCH_GEN_DIR = _REPO_ROOT / "src" / "arch" / "generators"

# Arch-generator input roots that a pre-commit MUST trigger arch-check on, each
# paired with an evidence substring that must appear in the arch source — so a
# required root is only enforced while a generator actually reads it. Keep this
# in sync with the generators (that is the whole point of the guard).
_REQUIRED_INPUT_ROOTS: dict[str, str] = {
    # coverage_matrix._wiki_check rglobs the wiki tree (loop→wiki references);
    # the UL glossary also derives from docs/wiki/terms/.
    "docs/wiki": "rglob",
    # coverage_matrix._adr_check globs docs/adr/*.md (loop→ADR references).
    "docs/adr": "adr_dir",
    # ai_system_inventory + the loop registry read functional_areas.yml.
    "docs/arch/functional_areas.yml": "functional_areas.yml",
}


def _pre_commit_text() -> str:
    assert _PRE_COMMIT.exists(), f"{_PRE_COMMIT} missing — the early arch gate is gone"
    return _PRE_COMMIT.read_text(encoding="utf-8")


def _staged_arch_block(text: str) -> str:
    """Return the ``STAGED_ARCH=$(git diff ... )`` assignment body.

    Anti-vacuity: if this cannot be located the parse is broken and every
    coverage assertion below would pass on an empty string — so fail loudly.
    """
    m = re.search(r"STAGED_ARCH=\$\((.*?)\)\s*$", text, re.DOTALL | re.MULTILINE)
    assert m is not None, (
        "Could not locate the STAGED_ARCH=$(git diff ... ) assignment in "
        ".githooks/pre-commit — the arch-check trigger was restructured; update "
        "this guard to match so it does not pass vacuously."
    )
    body = m.group(1)
    assert "git diff" in body and "--" in body, (
        f"STAGED_ARCH block does not look like a pathspec filter: {body!r}"
    )
    return body


def _arch_source_blob() -> str:
    parts = [p.read_text(encoding="utf-8") for p in sorted(_ARCH_GEN_DIR.glob("*.py"))]
    return "\n".join(parts)


def test_required_roots_are_actually_read_by_generators() -> None:
    """Each required root must correspond to real generator input (no dead rules)."""
    blob = _arch_source_blob()
    for root, evidence in _REQUIRED_INPUT_ROOTS.items():
        assert evidence in blob, (
            f"Evidence {evidence!r} for input root {root!r} not found in "
            f"src/arch/generators/ — if the generators no longer read {root}, "
            "drop it from _REQUIRED_INPUT_ROOTS; otherwise fix the evidence marker."
        )


def test_precommit_trigger_covers_generator_input_roots() -> None:
    """The pre-commit arch-check trigger must reference every required input root."""
    block = _staged_arch_block(_pre_commit_text())
    missing = [root for root in _REQUIRED_INPUT_ROOTS if root not in block]
    assert not missing, (
        f"pre-commit STAGED_ARCH does not trigger arch-check for {missing}. A "
        "commit touching those (which the arch generators read) would drift a "
        "generated artifact past the earliest gate. Add each to the STAGED_ARCH "
        "git-diff pathspec in .githooks/pre-commit."
    )


def test_docs_wiki_and_adr_are_covered() -> None:
    """Anchor the specific regression that motivated this guard."""
    block = _staged_arch_block(_pre_commit_text())
    for root in ("docs/wiki", "docs/adr"):
        assert root in block, (
            f"{root} must be in the pre-commit arch-check trigger — a "
            f"{root}-only commit drifts docs/arch/generated/coverage_matrix.md "
            "(the coverage_matrix generator reads it) but would otherwise skip "
            "the pre-commit arch-check via the STAGED_* short-circuit."
        )
