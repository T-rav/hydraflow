"""#12114 C1: the rule about what needs a human must itself need a human.

The epic's stated risk: *"If the factory can change `policy.yaml` or
`charter.yaml` to remove a human-review class and self-approve that change,
H2 is decoration."*

Measured before fixing, rather than assumed:

    docs/standards/factory_autonomy/policy.yaml -> ['self_modification']
    charter.yaml                                -> UNCLASSED

So the risk was already half-closed and half-open. `policy.yaml` sat inside
the #10371 fail-closed class; `charter.yaml` — which declares a repo's loops
and, under H2, the change classes requiring an operator — did not.

**Direction of travel (operator ruling, 2026-09-03): `charter.yaml` is the
single governing declaration and the autonomy policy's roles move under it.**
So `charter.yaml` is the one that has to be protected for the long run, and
the second assertion below followed the policy content when it moved: the
consolidation landed, `docs/standards/factory_autonomy/policy.yaml` is gone,
and what remains is `src/assets/factory_autonomy_policy.yaml` — the seed a new
repo is stamped with, not a second governing declaration.
"""

from __future__ import annotations

from judge_independence import BlastRadiusClass, classify_paths, is_self_modification


def test_the_charter_is_self_modification() -> None:
    """`charter.yaml` declares a repo's loops and, under #12114 H2, the change
    classes requiring an operator. It was UNCLASSED."""
    assert is_self_modification(classify_paths(["charter.yaml"]))


def test_the_shipped_autonomy_policy_is_self_modification() -> None:
    """The act/ask classes HydraFlow ships are still self-modification class.

    This was written TRANSITIONALLY against
    `docs/standards/factory_autonomy/policy.yaml`, to be deleted with that
    file. The file is gone (#12116) — but deleting the test with it would have
    been wrong, because the content did not stop existing. It became
    `src/assets/factory_autonomy_policy.yaml`, the seed stamped into every
    newly onboarded repo's charter.

    That move mattered: `docs/standards/` is itself in the self-modification
    set, so the old path was covered by LOCATION, and the new one classified
    UNCLASSED until it was named. Editing the shipped default changes the rules
    a repo is born with — the same authority `charter.yaml` carries, one hop
    earlier — so it is named now and this asserts it.

    Written as its own test rather than a parametrised pair on purpose. The
    two are a set of exactly two known files, and a module-level sequence fed
    to `parametrize` would owe the guard-enumeration registry a drop-detector
    that could answer "would losing a member be noticed?" — which for a
    hand-written pair it cannot, because nothing derives the pair. Two named
    tests carry the same coverage and a deletion is visible as a deleted test.
    """
    assert is_self_modification(
        classify_paths(["src/assets/factory_autonomy_policy.yaml"])
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
