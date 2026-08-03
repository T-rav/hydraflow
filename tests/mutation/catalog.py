"""Curated mutant catalog for the mutation gauntlet (#10835).

This is **data**, not logic: a hand-authored, version-controlled set of
high-signal mutants — exactly ONE per :class:`MutantClass` in this first slice.
Each mutant is a real ``(file, find, replace)`` patch against real repository
source and names the gate that MUST kill it, so a survivor localizes exactly
one blind gate.

Every ``find`` string below was verified present-and-unique in the tree at
authoring time; ``tests/mutation/test_catalog.py`` re-checks that each anchor
still resolves, so catalog rot (a mutation point that moved under a refactor)
fails loudly rather than silently degrading into an un-appliable no-op.

The gate labels are the conceptual owners from the design's mutant-class -> gate
map (``docs/superpowers/specs/2026-08-02-mutation-gauntlet-design.md``):

* ``unit-tests``     — the fast pytest unit suite (``make test``).
* ``fake-coverage``  — the fake-coverage auditor + adapter-contract shape tests.
* ``scenario``       — the MockWorld scenario suite (``make scenario``).
* ``lint-ul``        — ubiquitous-language conformance (CI job "Gates Drift").
* ``adr-conformance``— the ADR conformance / direction family.
"""

from __future__ import annotations

from mutation_gauntlet import Mutant, MutantClass, PatchSpec, Verdict

#: The seed catalog: one mutant per class. Ordered by class for readability.
CATALOG: tuple[Mutant, ...] = (
    # -- LOGIC -> unit-tests -------------------------------------------------
    Mutant(
        id="logic-supervisor-giveup-off-by-one",
        mutant_class=MutantClass.LOGIC,
        target_gate="unit-tests",
        patch=PatchSpec(
            file="src/supervisor_observation.py",
            find="if prior >= giveup_cap:",
            replace="if prior > giveup_cap:",
        ),
        rationale=(
            "Off-by-one in the Tier-2 supervisor give-up window (ADR-0124): "
            "flipping >= to > lets an incident be nudged one extra time past "
            "the cap before escalating — the exact repeat-without-improvement "
            "over-reach the window exists to bound. Owned by the unit suite: "
            "tests/test_goal_supervisor_loop.py::test_decide_escalates_after_"
            "giveup_window pins the boundary, so a live unit gate must go red."
        ),
        expectation=Verdict.KILLED,
    ),
    # -- CONTRACT -> fake-coverage ------------------------------------------
    Mutant(
        id="contract-ghprdetail-number-optional",
        mutant_class=MutantClass.CONTRACT,
        target_gate="fake-coverage",
        patch=PatchSpec(
            file="src/contracts/shapes.py",
            find="    number: int\n    url: str | None = None",
            replace="    number: int | None = None\n    url: str | None = None",
        ),
        rationale=(
            "Adapter returns the wrong shape: making GhPRDetail.number optional "
            "lets a drifted `gh pr view` payload with no PR number parse "
            "cleanly instead of raising at the contracts boundary. This is the "
            "'a Port accepts a wrong shape' fault the adapter-contract / "
            "fake-coverage gate owns — tests/test_contracts_shapes.py asserts "
            "`number` is required, so it must go red."
        ),
        expectation=Verdict.KILLED,
    ),
    # -- SCENARIO -> scenario (MockWorld) -----------------------------------
    Mutant(
        id="scenario-transition-review-mislabel",
        mutant_class=MutantClass.SCENARIO,
        target_gate="scenario",
        patch=PatchSpec(
            file="src/pr_manager.py",
            find='"review": (self._config.review_label or ["hydraflow-review"])[0],',
            replace='"review": (self._config.hitl_label or ["hydraflow-hitl"])[0],',
        ),
        rationale=(
            "A loop advances a label it shouldn't: PRManager.transition maps the "
            "'review' pipeline stage to the hitl label, so an issue that opens a "
            "PR is mislabeled and the checkpoint is skipped. The ADR-0002 label "
            "table drift gate is blind to this (it checks the declarative table, "
            "not the runtime stage map); only a MockWorld scenario that drives an "
            "issue build -> review and asserts the review label catches it."
        ),
        expectation=Verdict.KILLED,
    ),
    # -- VOCABULARY -> lint-ul (UL / Gates Drift) ---------------------------
    Mutant(
        id="vocabulary-rename-credit-exhausted-error",
        mutant_class=MutantClass.VOCABULARY,
        target_gate="lint-ul",
        patch=PatchSpec(
            file="src/subprocess_util.py",
            find="class CreditExhaustedError(RuntimeError):",
            replace="class CreditExhaustedErrorRenamed(RuntimeError):",
        ),
        rationale=(
            "Renames a ubiquitous-language term away from its anchor: the "
            "'Credit Exhausted Error' term (docs/wiki/terms/credit-exhausted-"
            "error.md) is anchored to src/subprocess_util.py:CreditExhaustedError. "
            "Renaming the class strands the anchor, so lint_anchor_resolution "
            "fails and the UL conformance gate (CI 'Gates Drift') must go red."
        ),
        expectation=Verdict.KILLED,
    ),
    # -- ADR -> adr-conformance ---------------------------------------------
    Mutant(
        id="adr-strip-binds-direction",
        mutant_class=MutantClass.ADR,
        target_gate="adr-conformance",
        patch=PatchSpec(
            file="docs/adr/0119-credit-failover-to-glm.md",
            find="- **Binds:** both\n",
            replace="",
        ),
        rationale=(
            "Violates an Accepted ADR's enforced structural rule: ADR-0123 "
            "requires every Accepted ADR to declare a **Binds:** direction. "
            "Stripping the line from ADR-0119 (Accepted, not grandfathered) is "
            "the 'unstated direction' defect that gate forbids — "
            "tests/test_adr_direction_declared.py must go red."
        ),
        expectation=Verdict.KILLED,
    ),
    # -- SAFETY -> unit-tests (the guard's own test) ------------------------
    Mutant(
        id="safety-reraise-credit-signal-swallowed",
        mutant_class=MutantClass.SAFETY,
        target_gate="unit-tests",
        patch=PatchSpec(
            file="src/exception_classify.py",
            find="        raise exc",
            replace="        return  # MUTANT: swallow instead of re-raising",
        ),
        rationale=(
            "Flips a fail-closed guard to fail-open: reraise_on_credit_or_bug is "
            "the seam every subprocess-spawning runner calls to re-surface a "
            "CreditExhaustedError / likely-bug instead of eating it against an "
            "exhausted billing signal. Swallowing it silently burns attempt "
            "budget. tests/test_exception_classify.py asserts it re-raises, so "
            "the guard's own unit test must go red."
        ),
        expectation=Verdict.KILLED,
    ),
)


def load_catalog() -> tuple[Mutant, ...]:
    """Return the seed mutant catalog (indirection seam for the shell/tests)."""
    return CATALOG
