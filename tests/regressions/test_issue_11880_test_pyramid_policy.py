"""The test-pyramid standard is judged by the policy engine, not left as prose.

`docs/standards/testing/README.md` says: *"Every load-bearing feature ships
through three layers before it merges. Skipping a layer is a procedural failure
— not a judgment call."* Nothing checked it. On 2026-08-31 six load-bearing
fixes merged with unit tests only (#11880), including #11853 — whose entire
defect was a call site that 20 passing unit tests could not see.

The repo already has a policy-as-code engine (`src/policy/`, ADR-0143) whose
whole purpose is deciding standards over normalised facts. This registers the
pyramid as a third standard there rather than adding another bespoke script.

**Report-only by design.** "Load-bearing" is not statically decidable — it
depends on what a future change puts on the main path. A blocking gate would
false-positive on ordinary refactors, get disabled, and a disabled gate is
worse than the defect. Same reasoning that ruled out a pre-commit hook in
#11827. `blocking=False` on every verdict is asserted below so that stays true.
"""

from __future__ import annotations

import sys
from datetime import UTC, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

import pytest

from policy.facts import STANDARD_TEST_PYRAMID, collect_test_pyramid_facts
from policy.models import DecisionStatus
from policy.python_engine import PythonDecisionEngine


class _GovernsAll:
    """Charter stub that places every standard in force."""

    def governs(self, standard: str) -> bool:  # noqa: ARG002 - stub
        return True


def _decide(paths: list[str]):
    facts = collect_test_pyramid_facts(paths, observed_at=datetime.now(UTC))
    return PythonDecisionEngine().decide(facts, charter=_GovernsAll())[0]


def test_unit_only_is_violated_the_11853_shape() -> None:
    """The exact shape that shipped: source changed, one layer present."""
    d = _decide(["src/runner_utils.py", "tests/regressions/test_x.py"])
    assert d.status is DecisionStatus.VIOLATED
    assert "scenario" in d.reason
    assert "sandbox" in d.reason


def test_all_three_layers_is_compliant() -> None:
    d = _decide(
        [
            "src/a.py",
            "tests/regressions/t.py",
            "tests/scenarios/s.py",
            "tests/sandbox_scenarios/e.py",
        ]
    )
    assert d.status is DecisionStatus.COMPLIANT


def test_a_docs_only_change_is_exempt_not_compliant() -> None:
    """EXEMPT and COMPLIANT are different answers and must stay different.

    A docs-only PR did not *satisfy* the standard — it was never subject to it.
    Collapsing the two would make any "compliant" count a lie, and the four
    statuses exist precisely to keep that distinction (ADR-0143 Ruling 4).
    """
    d = _decide(["docs/adr/0143-x.md"])
    assert d.status is DecisionStatus.EXEMPT
    assert d.status is not DecisionStatus.COMPLIANT


@pytest.mark.parametrize(
    "paths",
    [
        ["src/a.py", "tests/regressions/t.py"],
        ["src/a.py"],
        ["docs/x.md"],
        ["src/a.py", "tests/scenarios/s.py", "tests/sandbox_scenarios/e.py"],
    ],
)
def test_no_verdict_is_ever_blocking(paths: list[str]) -> None:
    """The design constraint, asserted rather than documented.

    If this ever flips to blocking, ordinary refactors start failing CI on a
    property that is not statically decidable, and the gate gets disabled.
    """
    assert _decide(paths).blocking is False


def test_a_scenario_is_not_counted_as_a_unit_test() -> None:
    """Prefix order matters: `tests/scenarios/` also starts with `tests/`.

    Checked generic-last, or every scenario would satisfy the unit layer too
    and the standard would be trivially satisfiable by one file.
    """
    d = _decide(["src/a.py", "tests/scenarios/s.py"])
    assert d.status is DecisionStatus.VIOLATED
    assert "unit" in d.reason
    assert "sandbox" in d.reason


def test_facts_carry_no_judgement() -> None:
    """A Fact is an observation; the verdict belongs to the engine.

    Keeps the collector reusable by a different ruleset — the separation
    ADR-0143 Ruling 4 draws between declaring and deciding.
    """
    facts = collect_test_pyramid_facts(["src/a.py"], observed_at=datetime.now(UTC))
    assert {f.key for f in facts} == {
        "touches_source",
        "has_unit",
        "has_scenario",
        "has_sandbox",
    }
    assert all(f.standard == STANDARD_TEST_PYRAMID for f in facts)
    assert all(isinstance(f.value, bool) for f in facts)


def test_the_engine_refuses_an_unknown_standard_rather_than_staying_silent() -> None:
    """Pins the engine's existing contract still holds after adding a standard.

    `decide` raises on a standard it has no ruleset for, because silence would
    read as compliance. Adding the pyramid must not have widened that hole.
    """
    from policy.models import Fact
    from policy.python_engine import UnsupportedStandardError

    bogus = Fact(
        standard="not_a_real_standard",
        subject="x",
        key="k",
        value=True,
        observed_at=datetime.now(UTC),
        source="test",
    )
    with pytest.raises(UnsupportedStandardError):
        PythonDecisionEngine().decide([bogus], charter=_GovernsAll())
