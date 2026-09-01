"""Producer-probe gate: a model field nothing populates must not ship (#11891).

Two defects reached production behind tests that were green the whole time:
`TraceToolProfile.tool_errors` (only ever keyed `"__stream__"`, so the per-tool
breakdown in `trace_rollup` was structurally empty for the module's life) and
`SubprocessTrace.turn_count` (never incremented). Both were pinned at the
*model* level by tests that constructed the model by hand, and never at the
*producer* level — deleting the producer's write kept the suite green.

Static analysis cannot see this class: an AST sweep for "initialised empty and
never mutated" returned one hit and it was a false positive, and `tool_errors`
was mutated anyway — just always with the wrong key. Only runtime observation
sees it.

So: drive the real producer over a recorded fixture, then require every field
to be either populated or explicitly excused. Both directions are checked, so
the excuse list cannot rot.
"""

from __future__ import annotations

import re
import sys
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest
from pydantic import BaseModel

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src"))

from tests.helpers import ConfigFactory  # noqa: E402
from trace_collector import TraceCollector  # noqa: E402
from trace_rollup import write_phase_rollup  # noqa: E402

SRC = Path(__file__).parent.parent.parent / "src"
FIXTURES = Path(__file__).parent.parent / "fixtures" / "stream_json"

# The fixture MUST exercise failure paths. Against a happy-path stream,
# `tool_errors == {}` reads as a legitimate default and the original defect
# slips through — the gate is only ever as good as what its fixture provokes.
FAILURE_PATH_STREAM = FIXTURES / "claude_implement_failure_paths.jsonl"


def persisting_producers() -> frozenset[str]:
    """Modules that serialise a Pydantic model to disk — the probe-able set.

    Derived, never spelled: a module qualifies when a ``model_dump_json()``
    call sits within two lines of a write. These are the producers whose fields
    can go structurally empty without any test noticing, because what they
    write is read back somewhere else entirely.
    """
    found: set[str] = set()
    for path in sorted(SRC.rglob("*.py")):
        text = path.read_text(encoding="utf-8", errors="replace")
        if "model_dump_json" not in text:
            continue
        lines = text.splitlines()
        for index, line in enumerate(lines):
            if "model_dump_json" not in line:
                continue
            window = "\n".join(lines[max(0, index - 2) : index + 3])
            if re.search(r"write_text|\.write\(|append_jsonl|open\(", window):
                found.add(path.relative_to(SRC).as_posix())
                break
    return frozenset(found)


#: Producers not yet probed. SHRINK-ONLY: this is the #11891 backlog made
#: countable. Lower it by adding a ProbeSpec, never by raising the number.
UNPROBED_BASELINE = 20


@dataclass(frozen=True)
class ProbeSpec:
    """One producer, driven for real, plus the defaults it may legitimately keep."""

    name: str
    #: Source module, relative to src/ — ties the probe to the derived set.
    module: str
    produce: Callable[[Path], BaseModel | None]
    excused: Mapping[str, str] = field(default_factory=dict)


def _drive_collector(tmp_path: Path) -> TraceCollector:
    config = ConfigFactory.create()
    config.data_root = tmp_path
    collector = TraceCollector(
        issue_number=1,
        phase="implement",
        source="implementer",
        subprocess_idx=0,
        run_id=1,
        config=config,
        event_bus=None,
    )
    for line in FAILURE_PATH_STREAM.read_text(encoding="utf-8").splitlines():
        if line.strip():
            collector.record(line)
    return collector


def _produce_subprocess_trace(tmp_path: Path) -> BaseModel | None:
    return _drive_collector(tmp_path).finalize(success=True)


def _produce_trace_summary(tmp_path: Path) -> BaseModel | None:
    collector = _drive_collector(tmp_path)
    collector.finalize(success=True)
    config = ConfigFactory.create()
    config.data_root = tmp_path
    return write_phase_rollup(
        config=config, issue_number=1, phase="implement", run_id=1
    )


PROBES: tuple[ProbeSpec, ...] = (
    ProbeSpec(
        name="trace_collector→SubprocessTrace",
        module="trace_collector.py",
        produce=_produce_subprocess_trace,
        excused={
            "subprocess_idx": "index of the first subprocess in a run; 0 is its real value",
            "crashed": "the probe stream completes successfully, so False is correct",
            "skill_results": "skills are recorded by agent._run_skill, not by the stream parser",
        },
    ),
    ProbeSpec(
        name="trace_rollup→TraceSummary",
        module="trace_rollup.py",
        produce=_produce_trace_summary,
        excused={
            "trace_ids": "reserved; the rollup keys traces by file path, not id",
            "crashed": "aggregates SubprocessTrace.crashed, correct for a clean run",
            "skills.skill_counts": "no skills in the stream — see skill_results above",
            "skills.subagent_counts": "subagents are counted in tool_counts as the Task tool",
            "skills.total_skills": "no skills in the stream",
            "skills.total_subagents": "no Task invocations in the stream",
        },
    ),
)

_EMPTY: tuple[Any, ...] = (None, 0, 0.0, "", "unknown", False)


def _fields_at_default(model: BaseModel, prefix: str = "") -> set[str]:
    found: set[str] = set()
    for name in type(model).model_fields:
        value = getattr(model, name)
        if isinstance(value, BaseModel):
            found |= _fields_at_default(value, f"{prefix}{name}.")
            continue
        is_empty = value in _EMPTY or (hasattr(value, "__len__") and len(value) == 0)
        if is_empty:
            found.add(f"{prefix}{name}")
    return found


class TestGuardTheGuard:
    def test_the_registry_is_not_empty(self):
        assert PROBES, "no producers registered — the gate would pass vacuously"

    def test_the_failure_path_fixture_exists(self):
        assert FAILURE_PATH_STREAM.is_file(), FAILURE_PATH_STREAM

    def test_the_fixture_actually_provokes_a_tool_error(self, tmp_path: Path):
        """A happy-path stream would excuse the very defect this gate exists for."""
        trace = _produce_subprocess_trace(tmp_path)

        assert trace is not None
        assert trace.tools.tool_errors, (
            "the probe fixture provokes no tool error, so tool_errors would read "
            "as a legitimate default and the #11887 defect would pass this gate"
        )

    @pytest.mark.parametrize("probe", PROBES, ids=lambda p: p.name)
    def test_every_excuse_carries_a_reason(self, probe: ProbeSpec):
        blank = [name for name, why in probe.excused.items() if not why.strip()]

        assert not blank, f"{probe.name}: excused without a reason: {blank}"


class TestEveryFieldIsPopulatedOrExcused:
    @pytest.mark.parametrize("probe", PROBES, ids=lambda p: p.name)
    def test_no_field_is_silently_unpopulated(self, probe: ProbeSpec, tmp_path: Path):
        produced = probe.produce(tmp_path)
        assert produced is not None, f"{probe.name} produced nothing"

        unexplained = _fields_at_default(produced) - set(probe.excused)

        assert not unexplained, (
            f"{probe.name}: {sorted(unexplained)} stayed at their default after "
            "driving the real producer over a fixture that exercises the failure "
            "paths. Either something should populate them and does not (the "
            "#11887 / #11891 defect), or add them to `excused` with the reason "
            "they are legitimately empty here."
        )

    @pytest.mark.parametrize("probe", PROBES, ids=lambda p: p.name)
    def test_no_excuse_outlives_its_reason(self, probe: ProbeSpec, tmp_path: Path):
        """The excuse list must shrink when a field starts being populated."""
        produced = probe.produce(tmp_path)
        assert produced is not None

        stale = set(probe.excused) - _fields_at_default(produced)

        assert not stale, (
            f"{probe.name}: {sorted(stale)} are now populated but still listed as "
            "excused. Remove them — an excuse list that outlives its reason is how "
            "the next unpopulated field hides."
        )


class TestCoverageOfPersistedProducersOnlyGrows:
    """#11891 as a shrink-only ratchet rather than a standing invitation."""

    def test_every_probe_names_a_real_persisting_producer(self):
        producers = persisting_producers()

        stray = [p.module for p in PROBES if p.module not in producers]

        assert not stray, (
            f"{stray} no longer serialise a model to disk — the probe is aimed "
            "at something that is not a persisted producer any more."
        )

    def test_the_derivation_finds_a_plausible_population(self):
        """Guard the guard: an empty derivation makes the ratchet vacuous."""
        producers = persisting_producers()

        assert len(producers) >= 10, (
            f"only {len(producers)} persisting producers found — the scan is "
            "broken, and a broken scan makes the baseline below meaningless."
        )

    def test_unprobed_producers_never_grow(self):
        producers = persisting_producers()
        covered = {probe.module for probe in PROBES}

        unprobed = sorted(producers - covered)

        assert len(unprobed) <= UNPROBED_BASELINE, (
            f"{len(unprobed)} persisted-model producers have no probe, over a "
            f"baseline of {UNPROBED_BASELINE}. Every one of them can ship a "
            "structurally empty field the way tool_errors and turn_count did. "
            f"Add a ProbeSpec — do not raise the baseline.\n{unprobed}"
        )

    def test_the_baseline_is_not_slack(self):
        """A baseline above the real count would silently absorb a regression."""
        unprobed = len(persisting_producers() - {p.module for p in PROBES})

        assert unprobed == UNPROBED_BASELINE, (
            f"baseline {UNPROBED_BASELINE} but {unprobed} are actually unprobed "
            "— tighten it to the real number so the next one to appear reddens."
        )
