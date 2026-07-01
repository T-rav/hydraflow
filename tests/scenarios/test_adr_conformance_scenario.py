"""MockWorld scenario for AdrConformanceLoop (ADR-0098).

Drives the loop end-to-end through the ``_build_adr_conformance`` catalog
builder (Task 11) against a seeded ADR fixture directory, a real
``ADRIndex``/``StateTracker``/``DedupStore`` on ``tmp_path``, and
``world.github`` (``FakeGitHub``) as the ``PRManager`` write surface.

``config.adr_conformance_loop_enabled`` defaults to ``False`` and is not a
named ``ConfigFactory.create`` param (unlike e.g.
``sandbox_failure_fixer_enabled``) — matching the direct-construction
pattern documented in ``tests/scenarios/test_sandbox_failure_fixer_scenario.py``
and used by ``tests/test_adr_conformance_loop.py``, this scenario builds
``HydraFlowConfig`` directly with the flag on rather than going through
``MockWorld.run_with_loops`` (which has no config-enable seam and would
also default ``data_root`` to ``Path(".")``, unsafe for a metrics-jsonl
write test).

Seeded ADR fixture (mirrors the unit test's three-ADR fixture):
* ADR-0049 — enforced, ``make:conformance-fail-fixture`` → FAIL (via
  ``FakeConformanceRunner``).
* ADR-0050 — decision-of-record → SKIPPED, never remediated.
* ADR-0051 — enforced, cites a pytest node that does not exist → UNRESOLVED
  (broken pointer, no rename; ``_detect_rename`` is a stub that always
  returns ``None``, so this routes to the FILE_ISSUE code-drift path).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from adr_conformance import CheckOutcome
from adr_index import ADRIndex
from base_background_loop import LoopDeps
from config import HydraFlowConfig
from dedup_store import DedupStore
from events import EventBus, EventType
from mockworld.fakes import FakeConformanceRunner
from state import StateTracker
from tests.scenarios.catalog.loop_registrations import _build_adr_conformance
from tests.scenarios.fakes.mock_world import MockWorld
from tests.scenarios.helpers.loop_port_seeding import seed_ports as _seed_ports

pytestmark = pytest.mark.scenario_loops


def _write_fail_adr(adr_dir: Path) -> None:
    """ADR-0049: enforced, one make check that will FAIL (fake runner)."""
    body = (
        "# ADR-0049: Fail Fixture\n\n"
        "**Status:** Accepted\n"
        "**Date:** 2026-01-01\n"
        "**Enforcement:** enforced\n"
        "**Enforced by:** make:conformance-fail-fixture\n\n"
        "## Context\n\nFixture body.\n"
    )
    (adr_dir / "0049-fail-fixture.md").write_text(body)


def _write_decision_of_record_adr(adr_dir: Path) -> None:
    """ADR-0050: decision-of-record — always SKIPPED, never remediated."""
    body = (
        "# ADR-0050: Decision Fixture\n\n"
        "**Status:** Accepted\n"
        "**Date:** 2026-01-01\n"
        "**Enforcement:** decision-of-record\n\n"
        "## Context\n\nFixture body.\n"
    )
    (adr_dir / "0050-decision-fixture.md").write_text(body)


def _write_unresolved_adr(adr_dir: Path) -> None:
    """ADR-0051: enforced, cites a pytest node that doesn't exist -> UNRESOLVED.

    No rename to detect (``_detect_rename`` is a conservative stub that
    always returns ``None``), so this is the "broken pointer, no rename"
    UNRESOLVED case the task brief calls for.
    """
    body = (
        "# ADR-0051: Unresolved Fixture\n\n"
        "**Status:** Accepted\n"
        "**Date:** 2026-01-01\n"
        "**Enforcement:** enforced\n"
        "**Enforced by:** pytest:tests/test_ghost_module.py::test_ghost\n\n"
        "## Context\n\nFixture body.\n"
    )
    (adr_dir / "0051-unresolved-fixture.md").write_text(body)


def _seed_repo(tmp_path: Path) -> Path:
    """Seed a minimal repo layout: docs/adr fixtures + placeholder src/tests."""
    repo_root = tmp_path / "repo"
    adr_dir = repo_root / "docs" / "adr"
    adr_dir.mkdir(parents=True)
    _write_fail_adr(adr_dir)
    _write_decision_of_record_adr(adr_dir)
    _write_unresolved_adr(adr_dir)

    (repo_root / "Makefile").write_text("conformance-fail-fixture:\n\techo hi\n")

    src_dir = repo_root / "src"
    src_dir.mkdir()
    (src_dir / "placeholder.py").write_text("# placeholder\n")

    tests_dir = repo_root / "tests"
    tests_dir.mkdir()
    (tests_dir / "test_placeholder.py").write_text(
        "def test_placeholder():\n    pass\n"
    )

    return repo_root


def _build_loop(world: MockWorld, repo_root: Path):
    """Construct AdrConformanceLoop via the Task 11 catalog builder.

    Direct construction (not ``world.run_with_loops``): the catalog has no
    config-enable seam for ``adr_conformance_loop_enabled`` (defaults
    False, and isn't a named ``ConfigFactory.create`` kwarg), and
    ``run_with_loops`` would also leave ``data_root`` at its unsafe
    ``Path(".")`` default. Mirrors ``test_sandbox_failure_fixer_scenario.py``.
    """
    config = HydraFlowConfig(
        data_root=repo_root / ".hydraflow",
        repo="hydra/hydraflow",
        repo_root=repo_root,
        adr_conformance_loop_enabled=True,
    )
    bus = EventBus()
    deps = LoopDeps(
        event_bus=bus,
        stop_event=world._harness.stop_event,
        status_cb=lambda *a, **k: None,
        enabled_cb=lambda _name: True,
    )

    state = StateTracker(repo_root / ".hydraflow" / "state.json")
    dedup = DedupStore("adr_conformance", repo_root / ".hydraflow" / "dedup.json")
    adr_index = ADRIndex(repo_root / "docs" / "adr")
    runner = FakeConformanceRunner({"make:conformance-fail-fixture": CheckOutcome.FAIL})

    _seed_ports(
        world,
        pr_manager=world.github,
        adr_conformance_state=state,
        adr_conformance_dedup=dedup,
        adr_conformance_index=adr_index,
        adr_conformance_runner=runner,
    )

    loop = _build_adr_conformance(world._loop_ports, config, deps)
    return loop, config, bus


class TestAdrConformanceScenario:
    """ADR-0098 — AdrConformanceLoop end-to-end MockWorld scenarios."""

    async def test_tick_persists_evaluates_emits_and_files(self, tmp_path) -> None:
        """One tick over FAIL/UNRESOLVED/SKIPPED ADRs.

        Asserts:
        1. All three ADRs' outcomes are persisted to adr_conformance.jsonl.
        2. Exactly one ADR_CONFORMANCE_UPDATE event is emitted, carrying all
           three per-ADR outcomes in its payload.
        3. Dedup'd remediation issues are filed for the FAIL and UNRESOLVED
           ADRs (one each, keyed adr_conformance:ADR-NNNN) — none for the
           decision-of-record ADR.
        """
        world = MockWorld(tmp_path)
        repo_root = _seed_repo(tmp_path)
        loop, config, bus = _build_loop(world, repo_root)

        result = await loop._do_work()

        assert result["status"] == "ok"
        assert result["evaluated"] == 3
        assert result["filed"] == 2  # FAIL + UNRESOLVED
        assert result["escalated"] == 0
        assert result["repointed"] == 0

        # ── 1. Per-ADR outcomes persisted to adr_conformance.jsonl ──────────
        jsonl_path = config.repo_data_root / "metrics" / "adr_conformance.jsonl"
        assert jsonl_path.exists(), f"adr_conformance.jsonl not found at {jsonl_path}"
        rows = [
            json.loads(line)
            for line in jsonl_path.read_text().splitlines()
            if line.strip()
        ]
        assert len(rows) == 3
        by_adr = {r["adr_id"]: r for r in rows}
        assert by_adr["ADR-0049"]["outcome"] == "fail"
        assert by_adr["ADR-0049"]["kind"] == "enforced"
        assert by_adr["ADR-0050"]["outcome"] == "skipped"
        assert by_adr["ADR-0050"]["kind"] == "decision-of-record"
        assert by_adr["ADR-0051"]["outcome"] == "unresolved"
        assert by_adr["ADR-0051"]["kind"] == "enforced"

        # ── 2. ADR_CONFORMANCE_UPDATE emitted with per-ADR outcomes ─────────
        history = bus.get_history()
        conformance_events = [
            e for e in history if e.type == EventType.ADR_CONFORMANCE_UPDATE
        ]
        assert len(conformance_events) == 1, (
            f"expected 1 ADR_CONFORMANCE_UPDATE event, got "
            f"{len(conformance_events)}: {[e.type for e in history]}"
        )
        payload_by_adr = {r["adr_id"]: r for r in conformance_events[0].data["results"]}
        assert payload_by_adr["ADR-0049"]["outcome"] == "fail"
        assert payload_by_adr["ADR-0050"]["outcome"] == "skipped"
        assert payload_by_adr["ADR-0051"]["outcome"] == "unresolved"

        # ── 3. Dedup'd remediation issues filed for FAIL + UNRESOLVED ───────
        issues = await world.github.list_issues_by_label("hydraflow-find")
        assert len(issues) == 2
        titles = {i["title"] for i in issues}
        assert any("ADR-0049" in t for t in titles)
        assert any("ADR-0051" in t for t in titles)
        assert not any("ADR-0050" in t for t in titles)

        dedup_keys = world._loop_ports["adr_conformance_dedup"].get()
        assert dedup_keys == {
            "adr_conformance:ADR-0049",
            "adr_conformance:ADR-0051",
        }

        # Rollup issue numbers recorded in state (keyed one issue per ADR).
        state = world._loop_ports["adr_conformance_state"]
        rollup_49 = state.get_adr_conformance_rollup("ADR-0049")
        rollup_51 = state.get_adr_conformance_rollup("ADR-0051")
        assert rollup_49 is not None
        assert rollup_51 is not None
        assert rollup_49["issue_number"] != rollup_51["issue_number"]
        assert state.get_adr_conformance_rollup("ADR-0050") is None

    async def test_second_tick_does_not_double_file(self, tmp_path) -> None:
        """A second tick over the same unresolved drift must not re-file.

        The dedup'd rollup recorded on tick 1 causes tick 2 to update the
        existing issue body (``_file_or_update_issue``'s ``if rollup:``
        branch) rather than create a new one — dedup holds across ticks.
        """
        world = MockWorld(tmp_path)
        repo_root = _seed_repo(tmp_path)
        loop, config, bus = _build_loop(world, repo_root)

        first = await loop._do_work()
        assert first["filed"] == 2

        second = await loop._do_work()
        assert second["status"] == "ok"
        assert second["evaluated"] == 3
        # classify_remediation still returns FILE_ISSUE (attempts=2 < max=3),
        # so the loop calls _file_or_update_issue again, but the rollup
        # short-circuits to update_issue_body instead of create_issue.
        assert second["filed"] == 2

        issues = await world.github.list_issues_by_label("hydraflow-find")
        assert len(issues) == 2, (
            f"expected dedup to hold (still 2 issues), got {len(issues)}: "
            f"{[i['title'] for i in issues]}"
        )

        dedup_keys = world._loop_ports["adr_conformance_dedup"].get()
        assert dedup_keys == {
            "adr_conformance:ADR-0049",
            "adr_conformance:ADR-0051",
        }

        # Two ADR_CONFORMANCE_UPDATE events total (one per tick), each
        # carrying the full three-ADR result set.
        history = bus.get_history()
        conformance_events = [
            e for e in history if e.type == EventType.ADR_CONFORMANCE_UPDATE
        ]
        assert len(conformance_events) == 2
        for event in conformance_events:
            assert len(event.data["results"]) == 3

        # jsonl accumulates 3 rows per tick (append-only ledger).
        jsonl_path = config.repo_data_root / "metrics" / "adr_conformance.jsonl"
        rows = [
            json.loads(line)
            for line in jsonl_path.read_text().splitlines()
            if line.strip()
        ]
        assert len(rows) == 6
