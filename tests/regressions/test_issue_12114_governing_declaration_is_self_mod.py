"""#12114 C1: the rule about what needs a human must itself need a human.

The epic's stated risk: *"If the factory can change `policy.yaml` or
`charter.yaml` to remove a human-review class and self-approve that change,
H2 is decoration."*

Measured before fixing, rather than assumed:

    docs/standards/factory_autonomy/policy.yaml -> ['self_modification']
    charter.yaml                                -> UNCLASSED

So the risk was already half-closed and half-open. `policy.yaml` sits inside
the #10371 fail-closed class; `charter.yaml` — which declares a repo's loops
and, under H2, the change classes requiring an operator — did not.

Both are pinned here together, because the pair is the surface. Protecting one
and not the other leaves the same hole with a smaller entrance.
"""

from __future__ import annotations

import pytest

from judge_independence import BlastRadiusClass, classify_paths, is_self_modification

_GOVERNING_DECLARATIONS = (
    "charter.yaml",
    "docs/standards/factory_autonomy/policy.yaml",
)


@pytest.mark.parametrize("path", _GOVERNING_DECLARATIONS)
def test_a_governing_declaration_is_self_modification(path: str) -> None:
    """Editing it demands an independent, fail-closed verdict."""
    classes = classify_paths([path])

    assert is_self_modification(classes), (
        f"{path} classifies as {sorted(c.value for c in classes) or 'UNCLASSED'} — "
        "the factory could edit the rule about what needs a human and "
        "self-approve that edit (#12114 C1)"
    )


def test_the_charter_is_matched_wherever_a_repo_keeps_it() -> None:
    """The classifier is substring-based, so a nested charter must match too.

    A managed repo may not keep its charter at the root. If the pin only held
    for the exact root path, the protection would evaporate the moment a repo
    laid its files out differently — which is the class of miss where a guard
    stops seeing its subject after a move.
    """
    for path in ("charter.yaml", "repos/acme/charter.yaml", "./charter.yaml"):
        assert is_self_modification(classify_paths([path])), path


def test_an_ordinary_source_file_is_not_swept_in() -> None:
    """The decoy: without it, the assertions above pass against a classifier
    that calls everything self-modification."""
    classes = classify_paths(["src/planner.py"])

    assert BlastRadiusClass.SELF_MODIFICATION not in classes
