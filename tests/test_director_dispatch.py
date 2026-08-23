"""The director's actuator half, and the discipline that let it be split (#11542).

``CanaryDispatchMixin`` was cut out of ``FableDirector`` when the mass sensor
flagged the host class. Its *behaviour* is proven where it always was — through
the real director, in ``tests/regressions/test_issue_11542_outside_the_slice.py``
and ``tests/scenarios/test_fable_implement_canary_scenario.py`` — because a
mixin tested through a hand-rolled host proves only that the host was
hand-rolled correctly.

What lives here is what only the *split* can get wrong: the seam between the
mixin and the host, and the one pure predicate the extraction created.
"""

from __future__ import annotations

import ast
import inspect
from pathlib import Path

import pytest

from director_dispatch import UNOBSERVED_DIGEST, CanaryDispatchMixin
from driver_contracts import DriverPhase

REPO_ROOT = Path(__file__).resolve().parents[1]


class TestTheHostStillOwnsEveryBehaviour:
    def test_the_director_really_inherits_the_mixin(self) -> None:
        from fable_director import FableDirector

        assert CanaryDispatchMixin in FableDirector.__mro__

    def test_the_mixin_contributes_no_runtime_attribute_to_shadow_with(self) -> None:
        """#11629's trap, closed by construction rather than by review.

        A mixin that declares a borrowed collaborator as a runtime stub
        (``def _stopping(self): ...``) creates a real class attribute. With one
        mixin that is harmless — the host precedes it in the MRO. With two it is
        not: attribute lookup stops at the first class carrying the name, a
        ``...`` body returns ``None``, and the failure is silent. Declaring the
        seam under ``if TYPE_CHECKING:`` means no such attribute exists.
        """
        stubs = {
            name
            for name, value in vars(CanaryDispatchMixin).items()
            if inspect.isfunction(value) and _is_stub(value)
        }

        assert stubs == set()

    def test_the_borrowed_method_is_declared_for_the_type_checker(self) -> None:
        # The other half: the seam must be *declared*, not merely absent, or a
        # type checker cannot see that the mixin depends on the host at all.
        tree = ast.parse(
            (REPO_ROOT / "src/director_dispatch.py").read_text(encoding="utf-8")
        )
        guarded = {
            node.name
            for block in ast.walk(tree)
            if isinstance(block, ast.If)
            and isinstance(block.test, ast.Name)
            and block.test.id == "TYPE_CHECKING"
            for node in ast.walk(block)
            if isinstance(node, ast.FunctionDef)
        }

        assert "_stopping" in guarded

    def test_the_mixin_holds_no_state_of_its_own(self) -> None:
        # Every attribute it touches is the host's, declared as a bare
        # annotation. A real assignment here would be a second copy of state
        # the host already owns — and the ADR's whole claim is that the
        # observer owns the state and this half owns none of it.
        assigned = {
            name
            for name, value in vars(CanaryDispatchMixin).items()
            if not name.startswith("__")
            and not inspect.isfunction(value)
            and not isinstance(value, classmethod | staticmethod | property)
        }

        assert assigned == set()


class TestTheBoundPredicateTheSplitCreated:
    """``_covers`` is the one piece of logic extraction added rather than moved."""

    @pytest.mark.parametrize(
        ("predicate", "expected"),
        [
            pytest.param(None, False, id="no-predicate-covers-nothing"),
            pytest.param(lambda _phase: False, False, id="a-refusing-predicate"),
            pytest.param(lambda _phase: True, True, id="a-covering-predicate"),
        ],
    )
    def test_a_missing_predicate_covers_nothing(
        self, predicate: object, expected: bool
    ) -> None:
        # A canary with no coverage predicate is a canary that was never armed,
        # and it must read as "outside the bound" rather than raise — the
        # shadow path reaches this on every boundary.
        assert (
            CanaryDispatchMixin._covers(predicate, DriverPhase.IMPLEMENT)  # type: ignore[arg-type]  # noqa: SLF001
            is expected
        )


class TestTheUnmeasuredTokenSaysWhatItIs:
    def test_it_is_not_a_plausible_sha(self) -> None:
        # #11537's rule, and the reason the constant exists rather than an
        # empty string: a lease outside the Implement canary states that it
        # looked at nothing, instead of carrying a fabricated digest that a
        # later reader would compare against a real one.
        assert not UNOBSERVED_DIGEST.startswith("sha256:")

    def test_the_fence_treats_it_as_unmeasured(self) -> None:
        """Two words for one idea, and only one of them was recognised.

        ``implement_broker`` says ``"unmeasured"`` and ``director_dispatch``
        says ``"unobserved"``, and a ``WorktreeState`` built from the second
        read as **measured** — a fence that verifies because nothing was
        compared. Not reachable today (the unobserved tokens only ever reach a
        ``WriterLease``), which is exactly why it needed a test rather than a
        bug report.
        """
        from implement_broker import WorktreeState

        unobserved = WorktreeState(
            branch=UNOBSERVED_DIGEST,
            base_sha=UNOBSERVED_DIGEST,
            head_sha=UNOBSERVED_DIGEST,
            diff_digest=UNOBSERVED_DIGEST,
        )

        assert unobserved.measured is False


def _is_stub(func: object) -> bool:
    """True when *func*'s body is exactly ``...`` or ``pass``."""
    try:
        source = inspect.getsource(func)  # type: ignore[arg-type]
    except OSError:  # pragma: no cover - source is always available in-tree
        return False
    body = ast.parse(source.lstrip()).body[0]
    assert isinstance(body, ast.FunctionDef | ast.AsyncFunctionDef)
    statements = [n for n in body.body if not isinstance(n, ast.Expr | ast.Pass)] or [
        n
        for n in body.body
        if isinstance(n, ast.Expr) and not isinstance(n.value, ast.Constant)
    ]
    return not statements
