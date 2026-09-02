"""A test standing in for a Port should use that Port's Fake, not a bare mock.

Every Port here has a Fake, and `tests/test_mockworld_fakes_conformance.py`
holds each Fake to its Protocol signature for signature. Nothing pushed tests
to USE them, so ~174 call sites pass a bare `MagicMock()` where a Port belongs.

That is not a style preference. A bare mock satisfies no Protocol, so adding
one `async def` to a Port breaks every one of those sites at once with
``object MagicMock can't be used in 'await' expression`` — a message naming
neither the port nor the method. #11908 hit it three separate times in a single
change: 46 tests, then 7, then 4.

Migrating 174 sites is the work; refusing the 175th is cheap. So this is a
shrink-only ratchet, and the claim it enforces is exactly that — the count only
goes down.

The subject is DERIVED, never spelled — and derived per CALL SITE, not per
parameter NAME. Matching on the name alone was too wide: ``state`` is annotated
``_StatePort`` in one preflight module, so a name-based predicate flagged every
``state=MagicMock()`` on loops where ``state`` is a ``StateTracker`` — 48 false
positives out of 105. A sweep is only as narrow as its predicate too.
"""

from __future__ import annotations

import ast
from collections import Counter
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SRC = REPO_ROOT / "src"
TESTS = REPO_ROOT / "tests"

#: Bare-mock stand-ins at Port parameters. SHRINK-ONLY, and now at ZERO: any
#: new one reddens immediately. Pass the Port's Fake or `MagicMock(spec=Port)`.
#:
#: Known limit: a call site is judged where its parameter is DECLARED, so a
#: bare mock handed to a LOCAL test helper that forwards it to a Port is not
#: seen. Closing that needs dataflow, not an index. Precision was the right
#: trade — the name-only predicate this replaced reported 105, of which ~104
#: were parameters that merely SHARE a name with a Port parameter elsewhere.
BARE_MOCK_BASELINE = 0

_BARE_MOCK_NAMES = {"MagicMock", "Mock", "NonCallableMock"}


def port_parameters_by_callee() -> dict[str, set[str]]:
    """``{callee name: {parameter names it declares as a Port}}``.

    Keyed by callee so a parameter is judged where it is DECLARED. The
    name-only version of this counted 48 sites where ``state`` is a
    ``StateTracker``, because one preflight module annotates a ``state``
    parameter ``_StatePort``.
    """
    by_callee: dict[str, set[str]] = {}

    def _record(owner: str, fn: ast.FunctionDef | ast.AsyncFunctionDef) -> None:
        for arg in [*fn.args.args, *fn.args.kwonlyargs]:
            if arg.annotation and "Port" in ast.unparse(arg.annotation):
                by_callee.setdefault(owner, set()).add(arg.arg)

    for path in SRC.rglob("*.py"):
        try:
            tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"))
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef):
                for item in node.body:
                    if isinstance(item, ast.FunctionDef | ast.AsyncFunctionDef):
                        _record(node.name, item)
            elif isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
                _record(node.name, node)
    return by_callee


def port_parameter_names() -> frozenset[str]:
    """Every parameter name any callee declares as a Port (diagnostics only)."""
    return frozenset().union(*port_parameters_by_callee().values())


def _is_bare_mock(node: ast.expr) -> bool:
    """A mock with no ``spec``/``spec_set`` promises nothing about the Protocol."""
    if not isinstance(node, ast.Call):
        return False
    func = node.func
    name = getattr(func, "id", None) or getattr(func, "attr", None)
    if name not in _BARE_MOCK_NAMES:
        return False
    return not any(kw.arg in {"spec", "spec_set"} for kw in node.keywords)


def bare_mock_stand_ins() -> Counter[str]:
    """``{test file: count}`` of bare mocks passed at a Port parameter."""
    by_callee = port_parameters_by_callee()
    found: Counter[str] = Counter()
    for path in TESTS.rglob("*.py"):
        try:
            tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"))
        except SyntaxError:
            continue
        for call in ast.walk(tree):
            if not isinstance(call, ast.Call):
                continue
            callee = ast.unparse(call.func).split(".")[-1]
            declared = by_callee.get(callee)
            if not declared:
                continue
            for kw in call.keywords:
                if kw.arg in declared and _is_bare_mock(kw.value):
                    found[str(path.relative_to(REPO_ROOT))] += 1
    return found


class TestTheScanHasASubject:
    def test_port_parameters_are_discovered(self):
        params = port_parameter_names()

        assert len(params) >= 10, (
            f"only {len(params)} Port-typed parameter names derived from src/ — "
            "the scan is broken, and a broken scan makes the baseline meaningless"
        )

    def test_a_known_port_parameter_is_in_the_derived_set(self):
        """Feed the sweep a known positive before believing its verdict."""
        assert "prs" in port_parameter_names()

    def test_a_parameter_is_judged_where_it_is_declared(self):
        """`state` is a Port in one preflight module and a StateTracker elsewhere.

        The name-only predicate counted 48 StateTracker sites as Port
        stand-ins. Judging per callee is what makes the count mean something.
        """
        by_callee = port_parameters_by_callee()

        assert "state" not in by_callee.get("DiagramLoop", set())


class TestTheDetectorIsNotDegenerate:
    def test_a_bare_mock_is_caught(self):
        node = ast.parse("MagicMock()").body[0].value

        assert _is_bare_mock(node)

    def test_a_spec_bound_mock_is_not_a_stand_in(self):
        """`spec=` binds the mock to the Protocol — that is the sanctioned escape."""
        node = ast.parse("MagicMock(spec=WorkspacePort)").body[0].value

        assert not _is_bare_mock(node)

    def test_a_fake_is_not_a_stand_in(self):
        node = ast.parse("FakeWorkspace(tmp_path)").body[0].value

        assert not _is_bare_mock(node)

    def test_a_configured_mock_without_spec_is_still_bare(self):
        """Setting attributes does not make it satisfy the Protocol."""
        node = ast.parse("MagicMock(destroy=AsyncMock())").body[0].value

        assert _is_bare_mock(node)


class TestTheCountOnlyShrinks:
    def test_bare_mock_stand_ins_never_grow(self):
        found = bare_mock_stand_ins()
        total = sum(found.values())

        assert total <= BARE_MOCK_BASELINE, (
            f"{total} bare mocks stand in for a Port, over a baseline of "
            f"{BARE_MOCK_BASELINE}. Pass the Port's Fake (every Port has one, "
            "held to the Protocol by tests/test_mockworld_fakes_conformance.py) "
            "or MagicMock(spec=<Port>). Do not raise the baseline.\n"
            f"{found.most_common(5)}"
        )

    def test_the_baseline_carries_no_slack(self):
        total = sum(bare_mock_stand_ins().values())

        assert total == BARE_MOCK_BASELINE, (
            f"baseline {BARE_MOCK_BASELINE} but {total} exist — tighten it so "
            "the next stand-in reddens."
        )
