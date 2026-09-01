"""#11937 — P10.8's advisory reason never reached a human.

Upheld sampled re-audit of PR #11897. The check collapsed every non-blocking
outcome into `Status.PASS` to avoid tripping the WARN-is-red rule, and left the
detail "riding in the reason". It rode nowhere: `format_terminal` skips a
finding's message when the status is PASS, and `make audit` has no other
summary or artifact surface, so the text was discarded before any human saw it.

The design's own words are the specification it failed: "This reports so the
omission is visible on the PR and deliberate rather than silent." A bare PASS
with zero output is silent.

`format_terminal` is exercised here on purpose. The audit's sharpest point was
that the original tests asserted on `Finding.status` and `d.reason` in
isolation and never rendered anything — so the gap between "the check produced
a reason" and "a human can read it" was exactly the untested seam.
"""

from __future__ import annotations

import pytest

from hydraflow_audit.checks.p10_tdd import pyramid_verdict
from hydraflow_audit.models import Finding, Severity, Status
from hydraflow_audit.report import format_terminal
from datetime import UTC, datetime

from policy.facts import collect_test_pyramid_facts
from policy.python_engine import PythonDecisionEngine

from hydraflow_audit.runner import (
    CONDITIONAL_WARN_CHECKS,
    TELEMETRY_CHECKS,
    overall_exit_code,
)

_REASON = "no sandbox test; the standard marks it conditional for a bug fix"


def _finding(status: Status, *, check_id: str = "P10.8") -> Finding:
    return Finding(
        check_id=check_id,
        status=status,
        severity=Severity.STRUCTURAL,
        principle="P10",
        source="docs/standards/testing/README.md",
        what="A change ships the test layers its shape requires",
        remediation="add the missing layer",
        message=_REASON,
    )


class TestTheReasonReachesAHuman:
    def test_a_warn_prints_its_message(self) -> None:
        rendered = format_terminal([_finding(Status.WARN)])

        assert _REASON in rendered

    def test_a_pass_still_prints_nothing(self) -> None:
        # Not a bug — PASS is silent by design, and 90-odd satisfied checks
        # printing their reasons would bury the ones that matter. The fix is
        # that an outcome with something to say is no longer a PASS.
        rendered = format_terminal([_finding(Status.PASS)])

        assert _REASON not in rendered

    def test_a_fail_prints_its_message(self) -> None:
        rendered = format_terminal([_finding(Status.FAIL)])

        assert _REASON in rendered


class TestVisibleButNotAStop:
    def test_a_p108_warn_does_not_redden_the_audit(self) -> None:
        assert overall_exit_code([_finding(Status.WARN)]) == 0

    def test_a_p108_fail_still_reddens_the_audit(self) -> None:
        # The whole point of a third concept rather than reusing telemetry or
        # advisory: this check still GATES on FAIL.
        assert overall_exit_code([_finding(Status.FAIL)]) == 1

    def test_another_checks_warn_still_reddens_the_audit(self) -> None:
        # The decoy. A blanket "WARN never fails" would satisfy the first case
        # and silently disarm every other check in the suite.
        assert overall_exit_code([_finding(Status.WARN, check_id="P1.1")]) == 1


class TestTheVocabularyStaysHonest:
    def test_p108_is_conditional_not_telemetry(self) -> None:
        """Telemetry cannot blame the PR under test; P10.8 exists to.

        Filing it under `TELEMETRY_CHECKS` would make the set's own docstring
        false, and ADR-0053 treats one name meaning two things as drift. It
        would also be load-bearing rather than cosmetic: telemetry is
        documented as never failing PR CI, and P10.8 must.
        """
        assert "P10.8" in CONDITIONAL_WARN_CHECKS
        assert "P10.8" not in TELEMETRY_CHECKS


@pytest.mark.parametrize(
    "status",
    [
        pytest.param(Status.WARN, id="warn"),
        pytest.param(Status.FAIL, id="fail"),
    ],
)
def test_the_renderer_names_the_check_alongside_its_message(status: Status) -> None:
    """A reason with no check id is an orphan line in a 100-finding report."""
    rendered = format_terminal([_finding(status)])

    assert "P10.8" in rendered


class TestTheMappingItself:
    """The layer the audit named as missing.

    The original tests reached the decision engine on one side and the rendered
    report on the other, but nothing exercised the mapping between them — which
    is exactly where the reason was being thrown away.

    Decisions here come from the REAL collector and engine rather than being
    hand-built. The mapping reads the decision's facts to find layers the
    standard marks `conditional`, and a hand-built decision carries no facts,
    so it would pass every assertion below while proving nothing about the
    matrix the check actually consults.
    """

    @staticmethod
    def _verdict(title: str, paths: list[str], waived: str | None = None):
        facts = collect_test_pyramid_facts(
            paths, observed_at=datetime.now(UTC), commit_subjects=[title]
        )
        decision = PythonDecisionEngine().decide(facts, charter=None)[0]
        return pyramid_verdict(decision, waived)

    def test_an_unmet_conditional_warns_rather_than_passing_silently(self) -> None:
        # The audit's own example: a bug fix shipping unit + scenario but no
        # sandbox test, which the standard marks `conditional` for a Bug fix.
        status, message = self._verdict(
            "fix(x): y",
            ["src/a.py", "tests/regressions/t.py", "tests/scenarios/s.py"],
        )

        assert status is Status.WARN
        assert "sandbox" in message

    def test_a_required_layer_missing_fails(self) -> None:
        status, message = self._verdict(
            "fix(x): y", ["src/a.py", "tests/regressions/t.py"]
        )

        assert status is Status.FAIL
        assert "Skip-Scenario" in message

    def test_a_waived_requirement_warns_and_names_the_waiver(self) -> None:
        # A waiver nobody can read is not a waiver — and PASS made it unreadable.
        status, message = self._verdict(
            "fix(x): y",
            ["src/a.py", "tests/regressions/t.py"],
            waived="unit-visible by construction",
        )

        assert status is Status.WARN
        assert "unit-visible by construction" in message

    @pytest.mark.parametrize(
        ("title", "paths"),
        [
            pytest.param(
                "feat(x): y",
                ["src/a.py", "tests/regressions/t.py"],
                id="ambiguous-feat",
            ),
            pytest.param(
                "refactor(x): y",
                ["src/a.py", "tests/regressions/t.py"],
                id="pure-refactor",
            ),
            pytest.param("docs(x): y", ["docs/a.md"], id="docs-only"),
        ],
    )
    def test_a_shape_the_standard_has_no_opinion_on_stays_silent(
        self, title: str, paths: list[str]
    ) -> None:
        """The scope decoy, and it caught a real over-correction.

        A first version warned on any non-blocking violation. The engine
        reports VIOLATED for every shape it cannot pin, so that warned on an
        ambiguous `feat(`, a `refactor(`, and a `docs(` touching `src/` — very
        nearly every PR. A warning on nearly every PR is a warning on none.

        Where `requires_*` is empty the standard has no opinion, so there is no
        omission to surface and PASS is the honest verdict.
        """
        status, _ = self._verdict(title, paths)

        assert status is Status.PASS

    def test_blocking_is_read_not_inferred_from_the_verdict(self) -> None:
        """`violated but not gating` is a real state, so the two are separate.

        Both of these are VIOLATED. Only one gates.
        """
        gating, _ = self._verdict("fix(x): y", ["src/a.py", "tests/regressions/t.py"])
        reporting, _ = self._verdict(
            "fix(x): y",
            ["src/a.py", "tests/regressions/t.py", "tests/scenarios/s.py"],
        )

        assert (gating, reporting) == (Status.FAIL, Status.WARN)
