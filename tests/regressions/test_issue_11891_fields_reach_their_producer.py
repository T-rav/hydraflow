"""Every SubprocessTrace field is populated by the real producer (#11891).

## The class

A field is declared on a Pydantic model, documented, and consumed downstream —
but nothing ever populates it. Every test constructs the model by hand with the
field set to a literal, so it is pinned at the MODEL level and never at the
PRODUCER level. Deleting the producer's population logic keeps the suite green.

Confirmed at `TraceToolProfile.tool_errors` / `ToolCallSpan.error` (#11887).
`TraceCollector` only ever wrote the literal key `"__stream__"`, and
`ToolCallSpan.error` was never assigned at all — while `src/trace_rollup.py`
aggregated a per-tool error breakdown that was **structurally empty for the
module's whole life**. `tests/test_trace_models.py` asserted
`tool_errors["Bash"] == 1` on a profile the test itself constructed. The model
tests were not wrong; they were blind to whether anything upstream wrote it.

## Why this guard is dynamic, not a static sweep

A static sweep was tried first and REJECTED on evidence. Predicate: a field
whose name never appears as a keyword argument or attribute assignment
anywhere in `src/`. It returned 840 candidates, and after excluding settings
models (populated from env, not by a producer) still 621 — overwhelmingly
false positives, because Pydantic populates through `model_validate` and
through collection mutation that AST attribution cannot see:
`EpicState.approved_children` was flagged, and `src/state/_epic.py:83` appends
to it.

Decisively, the predicate did not catch its own KNOWN POSITIVE: none of
`ToolCallSpan`, `TraceToolProfile` or `SubprocessTrace` appeared in its output.
A sweep that misses the instance it was built from cannot be trusted on the
instances it claims to find. The original was located by *driving the real
collector and looking at what came out*, so that is what this guard does.

## The ratchet

`_PRODUCER_EXEMPT` is the justified allow-list. A field NOT in it must be
populated by one real run of the producer. Adding a field to `SubprocessTrace`
without wiring it up therefore reddens here, rather than shipping a consumer
that reads a permanently-empty value.
"""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import pytest

from models import SubprocessTrace, TraceSummary
from tests.helpers import ConfigFactory
from trace_collector import TraceCollector
from trace_rollup import _aggregate

#: Fields a single successful+failing run legitimately leaves at their default,
#: each with the reason. Anything else must be populated by the producer.
_PRODUCER_EXEMPT: dict[str, str] = {
    "crashed": "set from `not success`; a successful run is correctly False",
}

#: Same contract for the rollup producer (`trace_rollup._aggregate`).
_SUMMARY_EXEMPT: dict[str, str] = {
    "crashed": "any(t.crashed); correctly False when no trace crashed",
    "subprocess_count": "0 is a real count only when there are no traces; the "
    "probe below supplies one, so this stays guarded",
}


def _collector(tmp: Path) -> TraceCollector:
    config = ConfigFactory.create()
    config.data_root = tmp
    return TraceCollector(
        issue_number=42,
        phase="implement",
        source="implementer",
        subprocess_idx=0,
        run_id=1,
        config=config,
        event_bus=None,
    )


def _tool_use(tid: str, name: str) -> str:
    return json.dumps(
        {
            "type": "assistant",
            "message": {
                "id": "m",
                "content": [
                    {"type": "tool_use", "id": tid, "name": name, "input": {}}
                ],
            },
        }
    )


def _tool_result(tid: str, *, is_error: bool, content: str) -> str:
    return json.dumps(
        {
            "type": "user",
            "message": {
                "content": [
                    {
                        "type": "tool_result",
                        "tool_use_id": tid,
                        "is_error": is_error,
                        "content": content,
                    }
                ]
            },
        }
    )


@pytest.fixture
def produced() -> SubprocessTrace:
    """One REAL producer run: the fixture stream plus a failing tool call.

    Driven through `TraceCollector.record` rather than constructed, because
    construction is exactly the blind spot — a hand-built model proves the
    schema, never the wiring.
    """
    fixture = (
        Path(__file__).resolve().parents[1]
        / "fixtures"
        / "stream_json"
        / "claude_implement_sample.jsonl"
    )
    with tempfile.TemporaryDirectory() as td:
        c = _collector(Path(td))
        for line in fixture.read_text("utf-8").splitlines():
            if line.strip():
                c.record(line)
        # A failure too: `tool_errors` and `ToolCallSpan.error` are the fields
        # #11887 found empty, and a stream with no failing call cannot tell a
        # populated breakdown from a structurally empty one.
        c.record(_tool_use("t_fail", "Bash"))
        c.record(_tool_result("t_fail", is_error=True, content="make: *** Error 1"))
        # Exercise the remaining producer paths rather than exempting the
        # fields they fill. An exemption would record "this run did not
        # populate it", which is indistinguishable from "nothing ever does" —
        # the very confusion this guard exists to remove.
        c.record(json.dumps({"type": "error", "message": "stream blew up"}))
        c.record_skill_result(
            skill_name="tdd",
            passed=True,
            attempts=1,
            duration_seconds=1.5,
            blocking=True,
        )
        trace = c._finalize_inner(success=True)
    assert trace is not None, "the producer returned no trace at all"
    return trace


#: Derived, not spelled: the guarded set is every declared field MINUS the
#: justified exemptions. Filtering the parameter list rather than calling
#: `pytest.skip` inside the test is deliberate —
#: `tests/architecture/test_no_ignored_active_tests.py` forbids a runtime skip
#: in an active test, and it is right to: a skip reports as a test that ran.
_GUARDED_TRACE_FIELDS = sorted(set(SubprocessTrace.model_fields) - set(_PRODUCER_EXEMPT))


@pytest.mark.parametrize("field", _GUARDED_TRACE_FIELDS)
def test_every_field_is_populated_by_the_real_producer(
    produced: SubprocessTrace, field: str
) -> None:
    """Parametrised over the model's OWN field list, by reference.

    A hand-written list of fields to check would need updating by the same
    person who forgets to wire the producer, so it would never catch the case
    it exists for. Deriving from `model_fields` means a new field arrives here
    already under test.
    """
    value = getattr(produced, field)
    assert value is not None, (
        f"SubprocessTrace.{field} is None after a real producer run — declared "
        "and consumed, but nothing upstream writes it (#11891)"
    )
    if hasattr(value, "__len__"):
        assert len(value) > 0, (
            f"SubprocessTrace.{field} is empty after a real producer run — the "
            "#11887 signature: a consumer aggregates over a container the "
            "producer never fills"
        )


def test_the_guarded_set_is_not_empty() -> None:
    """Anti-vacuity for the filtering above.

    Deriving the parameter list by subtraction means an over-broad exemption
    set would silently reduce the guard to zero test cases — which reports as
    a green suite, not as a missing one.
    """
    assert len(_GUARDED_TRACE_FIELDS) >= 10, _GUARDED_TRACE_FIELDS
    assert len(_GUARDED_SUMMARY_FIELDS) >= 8, _GUARDED_SUMMARY_FIELDS


def test_the_exempt_list_names_only_fields_that_exist() -> None:
    """A stale exemption silently un-guards a field.

    If a name here stops matching the model, the entry stops exempting
    anything and starts hiding nothing — but it also stops being reviewed.
    """
    unknown = set(_PRODUCER_EXEMPT) - set(SubprocessTrace.model_fields)
    assert not unknown, f"exemptions for fields that no longer exist: {unknown}"


def test_the_per_tool_error_breakdown_is_keyed_by_tool_name(
    produced: SubprocessTrace,
) -> None:
    """The exact #11887 defect, asserted through the producer.

    `tool_errors` was populated — with the literal key `"__stream__"` — so a
    non-empty check alone would have passed while `trace_rollup`'s per-tool
    breakdown stayed empty. The key is the property that mattered.
    """
    assert produced.tools.tool_errors == {"Bash": 1}, (
        f"per-tool error breakdown is not keyed by tool name: "
        f"{produced.tools.tool_errors}"
    )
    assert "__stream__" not in produced.tools.tool_errors


def test_the_failing_span_carries_its_error_text(produced: SubprocessTrace) -> None:
    """`ToolCallSpan.error` was never assigned at all before #11887."""
    failed = [s for s in produced.tool_calls if not s.succeeded]
    assert failed, "no span was recorded as failed"
    assert failed[0].error == "make: *** Error 1"


# ---------------------------------------------------------------------------
# The rollup producer — where this sweep found its two live instances
# ---------------------------------------------------------------------------


@pytest.fixture
def rolled_up(produced: SubprocessTrace) -> TraceSummary:
    """A TraceSummary from the REAL aggregator, over a real produced trace."""
    return _aggregate(
        [produced], issue_number=42, phase="implement", run_id=1
    )


_GUARDED_SUMMARY_FIELDS = sorted(set(TraceSummary.model_fields) - set(_SUMMARY_EXEMPT))


@pytest.mark.parametrize("field", _GUARDED_SUMMARY_FIELDS)
def test_every_summary_field_is_populated_by_the_rollup(
    rolled_up: TraceSummary, field: str
) -> None:
    """The guard that found `trace_ids` and `subagent_counts`.

    Both were written by the producer as literal empties — `trace_ids=[]` and
    `subagent_counts={}` — with no consumer anywhere in `src/`, the dashboard,
    or the UI. `trace_ids` held OTel-style hex ids and outlived the
    observability stack removed by ADR-0118; `subagent_counts` was superseded
    by `tool_counts["Task"]`, which its own inline comment said.

    What made them invisible is the point of #11891: `tests/test_trace_models.py`
    passed `trace_ids=["0xabc"]` and asserted on it — against a summary the
    test itself built. Deleting the field from the model left those
    constructions **still green**, because Pydantic silently drops unknown
    keyword arguments. Only the one test that read the value back failed. The
    hand-built tests were pinning nothing.
    """
    value = getattr(rolled_up, field)
    assert value is not None, (
        f"TraceSummary.{field} is None after a real rollup — declared but "
        "never produced (#11891)"
    )
    if hasattr(value, "__len__"):
        assert len(value) > 0, (
            f"TraceSummary.{field} is empty after a real rollup: a field the "
            "producer fills with a literal empty is dead weight that makes the "
            "schema lie (#11891)"
        )


def test_the_summary_exempt_list_names_only_fields_that_exist() -> None:
    unknown = set(_SUMMARY_EXEMPT) - set(TraceSummary.model_fields)
    assert not unknown, f"exemptions for fields that no longer exist: {unknown}"


def test_a_kwarg_for_a_field_that_does_not_exist_is_silently_dropped() -> None:
    """Why the hand-constructed tests could not have caught this.

    Pinned as a property of the toolchain, not an accident of one test: this
    is the mechanism that let `trace_ids=["0xabc"]` keep passing after the
    field was gone. Any future guard for this class has to assume a
    construction kwarg proves nothing about the model.
    """
    summary = _aggregate([], issue_number=1, phase="p", run_id=1)
    rebuilt = TraceSummary(
        **summary.model_dump(), definitely_not_a_field=["0xabc"]
    )
    assert not hasattr(rebuilt, "definitely_not_a_field")
