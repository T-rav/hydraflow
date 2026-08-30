"""A ubiquitous-language name means one thing, so it has one class (ADR-0053).

CLAUDE.md: "Names are load-bearing — don't paraphrase." The glossary at
`docs/wiki/terms/` is the register of names this codebase has decided mean
something specific, and each term's `code_anchor` names the class that IS it.

Two classes with one anchored name is **two tables over one vocabulary** — the
defect `charter.yaml`'s `actors:` rule refuses by construction (ADR-0143
Ruling 6, guard 3), which shipped anyway as the dual `Charter` classes:
`charter.py`'s loader class, and a minimal placeholder in `policy/models.py`
that existed because the decision seam is held pure and could not import a
module that reads files. They had drifted in surface and in defaults, and
nothing was watching, because the anchor check only asks whether an anchor
RESOLVES — never whether a second definition answers to the same name.

The set is DERIVED from the glossary, never spelled here: a hand-written list
of names to police is the predicate that silently narrows, and this file would
then stop seeing exactly the term someone just added.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
TERMS_DIR = REPO_ROOT / "docs/wiki/terms"
SRC = REPO_ROOT / "src"

_ANCHOR = re.compile(r'^code_anchor:\s*"([^"]+)"', re.M)

#: Names already carrying two meanings when this guard landed. SHRINK-ONLY:
#: an entry may be removed once the collision is resolved, and nothing may
#: ever be added — a new collision is the thing this file exists to stop.
#:
#: EMPTY as of #11782: `JudgeVerdict` was the sole entry, and the
#: verification-judge class is now `models.VerificationJudgeVerdict`, leaving
#: `convergence_gate.JudgeVerdict` — the class `docs/wiki/terms/verdict.md`
#: actually anchors — as the only holder of the bare word.
GRANDFATHERED: frozenset[str] = frozenset()


def _anchored_class_names() -> dict[str, str]:
    """``{ClassName: term-file}`` for every term whose anchor names a class."""
    names: dict[str, str] = {}
    for term in sorted(TERMS_DIR.glob("*.md")):
        match = _ANCHOR.search(term.read_text(encoding="utf-8"))
        if not match or ":" not in match.group(1):
            continue
        _path, _, symbol = match.group(1).rpartition(":")
        if symbol and symbol[0].isupper():
            names[symbol] = term.name
    return names


def _definitions_under_src(names: set[str]) -> dict[str, list[str]]:
    found: dict[str, list[str]] = {}
    for path in sorted(SRC.rglob("*.py")):
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except (SyntaxError, UnicodeDecodeError):
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef) and node.name in names:
                found.setdefault(node.name, []).append(
                    path.relative_to(REPO_ROOT).as_posix()
                )
    return found


def test_no_ubiquitous_name_has_two_class_definitions() -> None:
    anchored = _anchored_class_names()

    # Anti-vacuity: if the glossary scan matched nothing, "no collisions" is
    # true of an empty set and this guard would pass against any codebase.
    assert len(anchored) >= 50, (
        f"only {len(anchored)} class-anchored terms parsed from {TERMS_DIR}; "
        "the glossary scan is not seeing its subject"
    )

    found = _definitions_under_src(set(anchored))
    collisions = {
        name: paths
        for name, paths in found.items()
        if len(paths) > 1 and name not in GRANDFATHERED
    }
    assert not collisions, (
        "a ubiquitous-language name is defined by more than one class — two "
        "tables over one vocabulary (ADR-0053):\n  "
        + "\n  ".join(
            f"{name} ({anchored[name]}): {paths}"
            for name, paths in sorted(collisions.items())
        )
    )


def test_the_grandfather_list_only_shrinks() -> None:
    """Every grandfathered name must still BE a collision, or leave the list.

    A baseline that keeps entries after they are fixed is a baseline nobody
    trusts, and it hides the next regression under a name already excused.
    """
    anchored = _anchored_class_names()
    found = _definitions_under_src(set(anchored))
    stale = sorted(name for name in GRANDFATHERED if len(found.get(name, [])) <= 1)
    assert not stale, (
        f"these names are no longer duplicated and must be removed from "
        f"GRANDFATHERED: {stale}"
    )
