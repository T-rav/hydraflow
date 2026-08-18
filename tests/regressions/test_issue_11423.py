"""Regression pin for #11423.

``PRPort.list_closed_issues_by_label`` (src/ports.py) declares ``limit`` as
POSITIONAL_OR_KEYWORD, and the real adapter (``PRManager``) mirrors that
shape. ``FakeGitHub.list_closed_issues_by_label`` redeclared ``limit`` after
a ``*`` separator, narrowing it to KEYWORD_ONLY on the fake alone. A caller
using the positional form the Port permits
(``list_closed_issues_by_label("some-label", 50)``) raised ``TypeError``
against the fake while working fine against the real adapter — the same
failure class as #11409/#11420.

``tests/test_mockworld_fakes_conformance.py::_signatures_compatible`` never
caught this because it compares only param names and required-vs-optional
status, never ``inspect.Parameter.kind``. This file pins both the concrete
symptom (the positional call) and the structural property (kind agreement)
so a regression — or a *new* Port/Fake pair with the same drift — is caught
directly, independent of whether the shared comparator ever grows
kind-awareness.
"""

from __future__ import annotations

import inspect

from mockworld.fakes.fake_github import FakeGitHub
from pr_manager import PRManager
from tests.scenarios.ports import PRPort
from tests.test_mockworld_fakes_conformance import (
    _PORT_FAKE_PAIRS,
    _signatures_compatible,
)


async def test_fake_serves_the_positional_call_shape_the_port_permits() -> None:
    """The Port permits ``list_closed_issues_by_label(label, limit)`` as a
    fully positional call; the fake must accept the same shape AND bind
    ``limit`` to the right parameter — seeded so the truncation only comes
    out right if the positional args land where the Port says they do."""
    fake = FakeGitHub()
    for number in range(3):
        fake.add_issue(
            number,
            f"issue {number}",
            "body",
            labels=["hydraflow-find"],
            state="closed",
        )

    result = await fake.list_closed_issues_by_label("hydraflow-find", 2)

    assert len(result) == 2


def test_fake_keeps_limit_positional_or_keyword() -> None:
    sig = inspect.signature(FakeGitHub.list_closed_issues_by_label)

    assert sig.parameters["limit"].kind == inspect.Parameter.POSITIONAL_OR_KEYWORD


def test_port_fake_and_adapter_agree_on_limit_kind() -> None:
    """The fake's ``limit`` param kind must match both the Port it implements
    and the real adapter it stands in for — a caller shouldn't be able to
    tell the fake and the adapter apart by calling convention."""
    port_kind = inspect.signature(
        PRPort.list_closed_issues_by_label
    ).parameters["limit"].kind
    fake_kind = inspect.signature(
        FakeGitHub.list_closed_issues_by_label
    ).parameters["limit"].kind
    adapter_kind = inspect.signature(
        PRManager.list_closed_issues_by_label
    ).parameters["limit"].kind

    assert port_kind == fake_kind == adapter_kind


def _kind_violations(port_cls: type, fake_cls: type) -> list[str]:
    """Kind-aware structural check: for every named param present on both
    the Port and the Fake, ``Parameter.kind`` must match. This is the
    comparator the issue describes as missing from
    ``_signatures_compatible`` — reimplemented locally here as a regression
    sweep rather than folded into the shared conformance test, so this pin
    doesn't couple to that module's evolution.
    """
    violations: list[str] = []
    for name in dir(port_cls):
        if name.startswith("_"):
            continue
        port_attr = getattr(port_cls, name)
        fake_attr = getattr(fake_cls, name, None)
        if not callable(port_attr) or not callable(fake_attr):
            continue
        try:
            port_sig = inspect.signature(port_attr)
            fake_sig = inspect.signature(fake_attr)
        except (TypeError, ValueError):
            continue
        port_params = {
            p: i for p, i in port_sig.parameters.items() if p != "self"
        }
        fake_params = {
            p: i for p, i in fake_sig.parameters.items() if p != "self"
        }
        for param_name, port_param in port_params.items():
            fake_param = fake_params.get(param_name)
            if fake_param is None:
                continue
            if port_param.kind != fake_param.kind:
                violations.append(
                    f"{fake_cls.__name__}.{name}({param_name}): "
                    f"Port kind={port_param.kind} Fake kind={fake_param.kind}"
                )
    return violations


def test_kind_aware_comparator_flags_keyword_only_narrowing() -> None:
    """Sanity check on the comparator itself against a synthetic pair,
    independent of the real fix — proves the sweep below is capable of
    catching this failure class before trusting its zero-violations result.
    """

    class _Port:
        async def m(self, label: str, limit: int = 100) -> list: ...

    class _NarrowingFake:
        async def m(self, label: str, *, limit: int = 100) -> list: ...

    assert _kind_violations(_Port, _NarrowingFake) == [
        "_NarrowingFake.m(limit): "
        "Port kind=POSITIONAL_OR_KEYWORD Fake kind=KEYWORD_ONLY"
    ]


def test_registry_sweep_finds_zero_kind_violations() -> None:
    """Applied to every Port/Fake pair in the shared registry — not just
    the pair that regressed — the sweep must find nothing. This is the
    class-level assertion: #11423 was one instance of "a Fake narrows a
    Port param's kind"; any *other* pair with the same drift, present now
    or introduced later, must fail here too."""
    violations = [
        violation
        for port_cls, fake_cls in _PORT_FAKE_PAIRS
        for violation in _kind_violations(port_cls, fake_cls)
    ]
    assert violations == []


def test_signatures_compatible_still_accepts_the_kind_narrowing() -> None:
    """Context pin: the shared ``_signatures_compatible`` comparator is fed
    synthetic Port/Fake signatures reproducing this exact narrowing and
    still reports them compatible — documenting that the #11415 kind-
    blindness hole is untouched by this fix and survives it unchanged.
    Fed synthetic signatures rather than the real classes, so it stays
    green regardless of #11423's own fix.
    """

    async def port_method(self, label: str, limit: int = 100) -> list: ...
    async def narrowing_fake_method(self, label: str, *, limit: int = 100) -> list: ...

    ok, reason = _signatures_compatible(
        inspect.signature(port_method), inspect.signature(narrowing_fake_method)
    )

    assert ok, reason


def test_port_declares_limit_positional_or_keyword() -> None:
    sig = inspect.signature(PRPort.list_closed_issues_by_label)

    assert sig.parameters["limit"].kind == inspect.Parameter.POSITIONAL_OR_KEYWORD


def test_adapter_declares_limit_positional_or_keyword() -> None:
    sig = inspect.signature(PRManager.list_closed_issues_by_label)

    assert sig.parameters["limit"].kind == inspect.Parameter.POSITIONAL_OR_KEYWORD
