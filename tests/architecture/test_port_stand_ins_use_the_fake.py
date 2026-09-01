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

The subject is DERIVED, never spelled: parameter names annotated with a
``*Port`` type anywhere in ``src/``.
"""

from __future__ import annotations

import ast
from collections import Counter
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SRC = REPO_ROOT / "src"
TESTS = REPO_ROOT / "tests"

#: Bare-mock stand-ins at Port parameters. SHRINK-ONLY: pass the Port's Fake
#: (or `MagicMock(spec=...)`) in new tests and lower this. Never raise it.
BARE_MOCK_BASELINE = 105

_BARE_MOCK_NAMES = {"MagicMock", "Mock", "NonCallableMock"}


def port_parameter_names() -> frozenset[str]:
    """Parameter names annotated with a ``*Port`` type anywhere in ``src/``."""
    names: set[str] = set()
    for path in SRC.rglob("*.py"):
        try:
            tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"))
        except SyntaxError:
            continue
        for fn in ast.walk(tree):
            if not isinstance(fn, ast.FunctionDef | ast.AsyncFunctionDef):
                continue
            for arg in [*fn.args.args, *fn.args.kwonlyargs]:
                if arg.annotation and "Port" in ast.unparse(arg.annotation):
                    names.add(arg.arg)
    return frozenset(names)


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
    params = port_parameter_names()
    found: Counter[str] = Counter()
    for path in TESTS.rglob("*.py"):
        try:
            tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"))
        except SyntaxError:
            continue
        for call in ast.walk(tree):
            if not isinstance(call, ast.Call):
                continue
            for kw in call.keywords:
                if kw.arg in params and _is_bare_mock(kw.value):
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
