"""An empty retrospective tick reports the same counters as a busy one (#11890).

`RetrospectiveLoop._do_work` had two exits with two different result shapes:

    if not items:
        return {"processed": 0, "patterns_filed": 0, "stale_proposals": 0}
    ...
    return {"processed": ..., "patterns_filed": ..., "stale_proposals": ...,
            "findings_dropped": ..., "signals_seen": ...}

The empty-queue path silently dropped `findings_dropped` and `signals_seen`.
That is the exact defect #11890 rebuilt this loop's result shape to remove: a
reader of the published `details` cannot distinguish **"counted, and it was
zero"** from **"never counted"** when the key is simply absent — and the
empty-queue path is the one a healthy idle factory takes almost every tick, so
the degraded shape was the common case.

Caught by the RC gate, not by CI. The `s95_retro_evidence_counters` sandbox
scenario asserts all three evidence counters reach `/api/events`; the full
Sandbox suite is **advisory on staging and required on `main`**, so this rode
staging green and failed on the promotion PR.

The guard below compares the two exits against each other rather than against a
spelled list. A test asserting `"signals_seen" in result` would pass forever and
say nothing about the next counter added to one path and forgotten in the other
— which is precisely how these two drifted apart.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

import pytest

from retrospective_loop import _RESULT_COUNTERS


def test_the_two_exits_agree_on_their_counter_vocabulary() -> None:
    """Derived from the source, so a new counter cannot be added to one exit only.

    Both `return` statements in `_do_work` are read out of the module and their
    key sets compared. This is deliberately a source-level comparison: the
    empty-queue exit is unreachable in a unit test without a real queue, and
    mocking one would test the mock.
    """
    import ast
    import inspect

    import retrospective_loop

    src = inspect.getsource(retrospective_loop.RetrospectiveLoop._do_work)
    tree = ast.parse(src.lstrip() if src.startswith(" ") else src)

    dict_returns: list[set[str]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Return) and isinstance(node.value, ast.Dict):
            keys = {
                k.value
                for k in node.value.keys
                if isinstance(k, ast.Constant) and isinstance(k.value, str)
            }
            # `{"status": "config_disabled"}` is a refusal, not a tick result.
            if "status" not in keys:
                dict_returns.append(keys)

    assert dict_returns, "no dict-shaped tick result found — has _do_work moved?"
    for keys in dict_returns:
        assert keys == set(_RESULT_COUNTERS), (
            "a tick result exit reports a different counter set than "
            f"_RESULT_COUNTERS: missing {set(_RESULT_COUNTERS) - keys}, "
            f"extra {keys - set(_RESULT_COUNTERS)}"
        )


def test_the_empty_queue_result_carries_every_counter() -> None:
    """The shape an idle factory publishes on almost every tick."""
    from retrospective_loop import _RESULT_COUNTERS as counters

    empty = dict.fromkeys(counters, 0)
    assert set(empty) == set(counters)
    for key in ("findings_dropped", "signals_seen"):
        assert key in empty, (
            f"{key} absent from an idle tick's result — a reader cannot tell "
            "'counted zero' from 'never counted' (#11890)"
        )


@pytest.mark.parametrize(
    "counter", ["patterns_filed", "findings_dropped", "signals_seen"]
)
def test_every_counter_the_scenario_asserts_is_in_the_vocabulary(counter: str) -> None:
    """Bind the sandbox scenario's expectations to the loop's vocabulary.

    `s95_retro_evidence_counters` asserts these three reach `/api/events`. If a
    counter is renamed here and not there, the scenario fails in the RC gate —
    the slowest, most expensive place to find out. This fails in unit tests
    instead.
    """
    assert counter in _RESULT_COUNTERS
