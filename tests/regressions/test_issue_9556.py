"""Regression for #9556: the #9455 per-loop watchdog never landed on main.

#9503 was written assuming #9455 had already shipped a per-loop max-cycle
watchdog with four runtime surfaces:

1. config fields ``loop_watchdog_default_seconds`` / ``loop_watchdog_llm_seconds``
2. a forward-compatible ``timeout_cb`` on :class:`base_background_loop.LoopDeps`
3. a ``LONG_LLM_CYCLE`` ClassVar on :class:`BaseBackgroundLoop`
4. a ``LoopCycleTimeoutError`` raised when a cycle exceeds its bound, with
   enforcement wired into ``BaseBackgroundLoop._execute_cycle``

None of these exist on ``origin/main`` — ``origin/agent/issue-9455`` is an
empty-diff ancestor of main and "PR #9455" never resolved as a real PR, yet
several memory notes reference the watchdog as if shipped. This is a silent
non-delivery: the watchdog timeout override #9503 relies on has no runtime
effect.

Each test below asserts one surface of the intended contract. They are RED
until the watchdog is re-cut (or its enforcement is formally folded into
#9503). When the watchdog lands, these become standing guards that it stays
landed.
"""

from __future__ import annotations

import dataclasses
import importlib
import inspect

import pytest


def test_loopdeps_exposes_timeout_cb() -> None:
    from base_background_loop import LoopDeps

    field_names = {f.name for f in dataclasses.fields(LoopDeps)}
    assert "timeout_cb" in field_names, (
        "LoopDeps is missing the forward-compatible `timeout_cb` field that the "
        "#9455 watchdog was supposed to add (#9556 silent non-delivery). "
        f"Present fields: {sorted(field_names)}"
    )


def test_config_exposes_loop_watchdog_fields() -> None:
    from config import HydraFlowConfig

    fields = set(HydraFlowConfig.model_fields)
    missing = {
        "loop_watchdog_default_seconds",
        "loop_watchdog_llm_seconds",
    } - fields
    assert not missing, (
        "HydraFlowConfig is missing the #9455 watchdog config fields "
        f"{sorted(missing)} (#9556 silent non-delivery). Without them the "
        "watchdog timeout override has no tunable source."
    )


def test_base_loop_declares_long_llm_cycle_classvar() -> None:
    from base_background_loop import BaseBackgroundLoop

    assert hasattr(BaseBackgroundLoop, "LONG_LLM_CYCLE"), (
        "BaseBackgroundLoop is missing the `LONG_LLM_CYCLE` ClassVar that the "
        "#9455 watchdog used to grant LLM-calling loops the longer cycle bound "
        "(#9556 silent non-delivery)."
    )


def test_loop_cycle_timeout_error_exists() -> None:
    module = importlib.import_module("base_background_loop")
    exc = getattr(module, "LoopCycleTimeoutError", None)
    assert exc is not None and isinstance(exc, type) and issubclass(exc, Exception), (
        "LoopCycleTimeoutError does not exist (#9556 silent non-delivery). The "
        "#9455 watchdog was supposed to raise it when a cycle exceeds its bound; "
        "no such symbol is importable from base_background_loop."
    )


def test_execute_cycle_enforces_a_timeout() -> None:
    from base_background_loop import BaseBackgroundLoop

    source = inspect.getsource(BaseBackgroundLoop._execute_cycle)
    enforces_timeout = "wait_for" in source or "timeout" in source.lower()
    assert enforces_timeout, (
        "BaseBackgroundLoop._execute_cycle runs `await self._do_work()` with no "
        "cycle-timeout enforcement (#9556 silent non-delivery). The #9455 "
        "watchdog was supposed to bound each cycle so a hung loop cannot block "
        "indefinitely."
    )


if __name__ == "__main__":  # pragma: no cover - manual repro convenience
    raise SystemExit(pytest.main([__file__, "-v"]))
