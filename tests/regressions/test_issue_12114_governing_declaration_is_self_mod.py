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

from judge_independence import BlastRadiusClass, classify_paths, is_self_modification


def test_the_charter_is_self_modification() -> None:
    """`charter.yaml` declares a repo's loops and, under #12114 H2, the change
    classes requiring an operator. It was UNCLASSED."""
    assert is_self_modification(classify_paths(["charter.yaml"]))


def test_the_autonomy_policy_is_self_modification() -> None:
    """`policy.yaml` carries the act/ask classes and their approval
    requirements. Already covered; asserted here so the pair is one subject.

    Written as its own test rather than a parametrised pair on purpose. The
    two are a set of exactly two known files, and a module-level sequence fed
    to `parametrize` would owe the guard-enumeration registry a drop-detector
    that could answer "would losing a member be noticed?" — which for a
    hand-written pair it cannot, because nothing derives the pair. Two named
    tests carry the same coverage and a deletion is visible as a deleted test.
    """
    assert is_self_modification(
        classify_paths(["docs/standards/factory_autonomy/policy.yaml"])
    )


def test_the_charter_is_matched_wherever_a_repo_keeps_it() -> None:
    """The classifier is substring-based, so a nested charter must match too.

    A managed repo may not keep its charter at the root. If the pin only held
    for the exact root path, the protection would evaporate the moment a repo
    laid its files out differently — the class of miss where a guard stops
    seeing its subject after a move.
    """
    for path in ("charter.yaml", "repos/acme/charter.yaml", "./charter.yaml"):
        assert is_self_modification(classify_paths([path])), path


def test_an_ordinary_source_file_is_not_swept_in() -> None:
    """The decoy: without it, the assertions above pass against a classifier
    that calls everything self-modification."""
    classes = classify_paths(["src/planner.py"])

    assert BlastRadiusClass.SELF_MODIFICATION not in classes
