"""Unit tests for disturbance-dampener core models."""

from __future__ import annotations

from disturbance.models import Finding, RatchetResult


def test_finding_is_frozen_and_carries_signature() -> None:
    f = Finding(
        dimension="suppressions",
        path="src/x.py",
        signature="src/x.py::noqa:E501",
        message="m",
    )
    assert f.signature == "src/x.py::noqa:E501"
    import dataclasses

    assert dataclasses.is_dataclass(f)
    try:
        f.path = "other"  # type: ignore[misc]
        raise AssertionError("Finding should be frozen")
    except dataclasses.FrozenInstanceError:
        pass


def test_ratchet_result_holds_deltas() -> None:
    r = RatchetResult(new={"a": 1}, resolved={"b": 2}, unchanged=("c",))
    assert r.new == {"a": 1}
    assert r.resolved == {"b": 2}
    assert r.unchanged == ("c",)
