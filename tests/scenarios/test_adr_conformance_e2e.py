"""End-to-end test for AdrConformanceLoop (ADR-0098).

Exercises the full producer path with real I/O (no mocks-of-mocks):
  producer tick → adr_conformance.jsonl persisted → jsonl read back off disk
  and re-parsed via ``AdrConformance.model_validate_json`` → real EventBus
  carries the ``ADR_CONFORMANCE_UPDATE`` event.

Convention mirrored: tests/scenarios/test_fitness_scorecard_e2e.py — real
``EventBus``, real ``HydraFlowConfig``, real ``StateTracker``/``DedupStore``/
``ADRIndex`` against fixtures on ``tmp_path``. Only GitHub (``FakeGitHub``)
and the check-runner (``FakeConformanceRunner``) are faked, matching the
seed/fixture shape of tests/scenarios/test_adr_conformance_scenario.py
(Task 17) — see that module for the MockWorld-flavored dedup/re-file
scenario coverage this test does not duplicate.

Config is built directly (not via ``tests.helpers.make_bg_loop_deps`` /
``ConfigFactory.create``): ``adr_conformance_loop_enabled`` is not a named
``ConfigFactory.create`` parameter (defaults False, off by design — see
``test_adr_conformance_scenario.py``'s module docstring), so this test
constructs ``HydraFlowConfig`` directly with the flag on, mirroring the
Task 17 scenario's ``_build_loop`` helper.

The added value over Task 17's scenario test is the **round-trip**: rows
are not just asserted present in the jsonl file, they are read back off
disk and re-parsed through the real Pydantic model, catching
serialization/schema bugs that a write-only assertion would miss.

Out of scope (intentionally, per the task brief): a dashboard READ-route
e2e analogous to the fitness sibling's ``latest_fitness_by_worker``
assertion. The ADR-conformance dashboard panel/route is a separate,
deferred follow-up — there is no equivalent route to exercise yet.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from adr_conformance import AdrConformance, CheckOutcome
from adr_conformance_loop import AdrConformanceLoop
from adr_index import ADRIndex
from base_background_loop import LoopDeps
from config import HydraFlowConfig
from dedup_store import DedupStore
from events import EventBus, EventType
from mockworld.fakes import FakeConformanceRunner, FakeGitHub
from state import StateTracker

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


def _write_pass_adr(adr_dir: Path) -> None:
    """ADR-0052: enforced, one pytest check that resolves and PASSes."""
    body = (
        "# ADR-0052: Pass Fixture\n\n"
        "**Status:** Accepted\n"
        "**Date:** 2026-01-01\n"
        "**Enforcement:** enforced\n"
        "**Enforced by:** pytest:tests/test_placeholder.py::test_placeholder\n\n"
        "## Context\n\nFixture body.\n"
    )
    (adr_dir / "0052-pass-fixture.md").write_text(body)


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


def _seed_repo(tmp_path: Path) -> Path:
    """Seed a minimal repo layout: docs/adr fixtures + placeholder tests/Makefile."""
    repo_root = tmp_path / "repo"
    adr_dir = repo_root / "docs" / "adr"
    adr_dir.mkdir(parents=True)
    _write_fail_adr(adr_dir)
    _write_pass_adr(adr_dir)
    _write_decision_of_record_adr(adr_dir)

    (repo_root / "Makefile").write_text("conformance-fail-fixture:\n\techo hi\n")

    tests_dir = repo_root / "tests"
    tests_dir.mkdir()
    (tests_dir / "test_placeholder.py").write_text(
        "def test_placeholder():\n    pass\n"
    )

    return repo_root


async def test_adr_conformance_e2e(tmp_path) -> None:
    """Producer tick persists rows whose on-disk jsonl round-trips cleanly.

    Asserts:
    1. adr_conformance.jsonl exists at the loop's real ``_metrics_path()``
       with one row per evaluated ADR.
    2. Round-trip: each line is read back off disk and re-parsed via
       ``AdrConformance.model_validate_json`` — the parsed rows' adr_id/
       kind/outcome match the seeded ADRs' expected results. This proves
       the on-disk schema is loadable, not just writable.
    3. An ADR_CONFORMANCE_UPDATE event was published on the real EventBus
       with per-ADR outcomes in the payload.
    """
    repo_root = _seed_repo(tmp_path)

    config = HydraFlowConfig(
        data_root=tmp_path / ".hydraflow-data",
        repo="hydra/hydraflow",
        repo_root=repo_root,
        adr_conformance_loop_enabled=True,
    )
    bus = EventBus()
    deps = LoopDeps(
        event_bus=bus,
        stop_event=asyncio.Event(),
        status_cb=lambda *a, **k: None,
        enabled_cb=lambda _name: True,
    )

    state = StateTracker(config.repo_data_root / "state.json")
    dedup = DedupStore("adr_conformance", config.repo_data_root / "dedup.json")
    adr_index = ADRIndex(repo_root / "docs" / "adr")
    runner = FakeConformanceRunner(
        {
            "make:conformance-fail-fixture": CheckOutcome.FAIL,
            "pytest:tests/test_placeholder.py::test_placeholder": CheckOutcome.PASS,
        }
    )
    github = FakeGitHub()

    loop = AdrConformanceLoop(
        config=config,
        state=state,
        pr_manager=github,
        dedup=dedup,
        adr_index=adr_index,
        runner=runner,
        deps=deps,
    )

    result = await loop._do_work()

    assert result["status"] == "ok"
    assert result["evaluated"] == 3

    # ── 1. adr_conformance.jsonl exists at the loop's real metrics path ──────
    jsonl_path = loop._metrics_path()
    assert jsonl_path == config.repo_data_root / "metrics" / "adr_conformance.jsonl"
    assert jsonl_path.exists(), f"adr_conformance.jsonl not found at {jsonl_path}"
    lines = [line for line in jsonl_path.read_text().splitlines() if line.strip()]
    assert len(lines) == 3, f"expected 3 rows (one per ADR), got {len(lines)}"

    # ── 2. Round-trip: read back off disk, re-parse via the real model ───────
    parsed = [AdrConformance.model_validate_json(line) for line in lines]
    by_adr = {conf.adr_id: conf for conf in parsed}

    assert by_adr["ADR-0049"].kind.value == "enforced"
    assert by_adr["ADR-0049"].outcome.value == "fail"

    assert by_adr["ADR-0052"].kind.value == "enforced"
    assert by_adr["ADR-0052"].outcome.value == "pass"

    assert by_adr["ADR-0050"].kind.value == "decision-of-record"
    assert by_adr["ADR-0050"].outcome.value == "skipped"

    # ── 3. ADR_CONFORMANCE_UPDATE published on the real EventBus ─────────────
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
    assert payload_by_adr["ADR-0052"]["outcome"] == "pass"
    assert payload_by_adr["ADR-0050"]["outcome"] == "skipped"
