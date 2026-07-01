"""Unit tests for AdrConformanceLoop (ADR-0094).

Mirrors tests/test_adr_touchpoint_auditor_loop.py's shape. Fixtures build a
small ADRIndex over tmp docs/adr fixtures (one enforced-FAIL ADR, one
decision-of-record ADR, one enforced-UNRESOLVED ADR), a FakeConformanceRunner
(Task 5) driving the FAIL outcome, an AsyncMock PRManager recording
create_issue calls, an in-memory-backed DedupStore on tmp, and a real
StateTracker on tmp.

The GUARDRAIL test (load-bearing, ADR-0094): the loop's ONLY repo-write
surface is filing/updating GitHub issues + appending to the gitignored
metrics jsonl. It must never mutate any file under src/, tests/, or
docs/adr/.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
from pathlib import Path

import pytest

from adr_conformance import CheckOutcome
from adr_conformance_loop import AdrConformanceLoop
from adr_index import ADRIndex
from base_background_loop import LoopDeps
from config import HydraFlowConfig
from dedup_store import DedupStore
from events import EventBus
from loop_fitness import FitnessContext, FitnessKind
from mockworld.fakes import FakeConformanceRunner
from state import StateTracker


def _deps(stop: asyncio.Event, bus: EventBus | None = None) -> LoopDeps:
    return LoopDeps(
        event_bus=bus or EventBus(),
        stop_event=stop,
        status_cb=lambda *a, **k: None,
        enabled_cb=lambda _name: True,
    )


def _write_fail_adr(adr_dir: Path) -> None:
    """ADR-0049: enforced, one make check that will FAIL (via the fake runner)."""
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
    """ADR-0051: enforced, cites a pytest node that does not exist -> UNRESOLVED."""
    body = (
        "# ADR-0051: Unresolved Fixture\n\n"
        "**Status:** Accepted\n"
        "**Date:** 2026-01-01\n"
        "**Enforcement:** enforced\n"
        "**Enforced by:** pytest:tests/test_ghost_module.py::test_ghost\n\n"
        "## Context\n\nFixture body.\n"
    )
    (adr_dir / "0051-unresolved-fixture.md").write_text(body)


def _make_repo(tmp_path: Path) -> Path:
    """Seed a minimal repo layout: docs/adr fixtures + placeholder src/tests dirs."""
    adr_dir = tmp_path / "docs" / "adr"
    adr_dir.mkdir(parents=True)
    _write_fail_adr(adr_dir)
    _write_decision_of_record_adr(adr_dir)
    _write_unresolved_adr(adr_dir)

    (tmp_path / "Makefile").write_text("conformance-fail-fixture:\n\techo hi\n")

    src_dir = tmp_path / "src"
    src_dir.mkdir()
    (src_dir / "placeholder.py").write_text("# placeholder\n")

    tests_dir = tmp_path / "tests"
    tests_dir.mkdir()
    (tests_dir / "test_placeholder.py").write_text(
        "def test_placeholder():\n    pass\n"
    )

    return tmp_path


class _FakeFactory:
    """Bundles the fakes built for a test so assertions can reach into them."""

    def __init__(
        self,
        pr,
        dedup: DedupStore,
        state: StateTracker,
        repo_root: Path,
        runner: FakeConformanceRunner,
    ) -> None:
        self.pr = pr
        self.dedup = dedup
        self.state = state
        self.repo_root = repo_root
        self.runner = runner
        # Mirrors HydraFlowConfig.repo_data_root = data_root / repo_slug.
        self.metrics_dir = repo_root / ".hydraflow" / "hydra-hydraflow" / "metrics"


class _AsyncPRManagerStub:
    """Fake PRManager: records create_issue/update_issue_body/close_issue calls."""

    def __init__(self) -> None:
        self.created_issues: list[tuple[str, str, list[str]]] = []
        self.updated_bodies: list[tuple[int, str]] = []
        self.closed_issues: list[int] = []
        self._next_issue_number = 100
        self._by_title: dict[str, int] = {}

    async def create_issue(
        self, title: str, body: str, labels: list[str] | None = None
    ) -> int:
        if title in self._by_title:
            return self._by_title[title]
        number = self._next_issue_number
        self._next_issue_number += 1
        self._by_title[title] = number
        self.created_issues.append((title, body, list(labels or [])))
        return number

    async def update_issue_body(self, issue_number: int, body: str) -> None:
        self.updated_bodies.append((issue_number, body))

    async def close_issue(self, issue_number: int) -> None:
        self.closed_issues.append(issue_number)


@pytest.fixture
def loop_fixture(tmp_path: Path):
    repo_root = _make_repo(tmp_path)
    cfg = HydraFlowConfig(
        data_root=repo_root / ".hydraflow",
        repo="hydra/hydraflow",
        repo_root=repo_root,
        adr_conformance_loop_enabled=True,
    )
    pr = _AsyncPRManagerStub()
    dedup = DedupStore("adr_conformance", repo_root / ".hydraflow" / "dedup.json")
    state = StateTracker(repo_root / ".hydraflow" / "state.json")
    adr_index = ADRIndex(repo_root / "docs" / "adr")
    runner = FakeConformanceRunner({"make:conformance-fail-fixture": CheckOutcome.FAIL})

    bus = EventBus()
    stop = asyncio.Event()
    loop = AdrConformanceLoop(
        config=cfg,
        state=state,
        pr_manager=pr,
        dedup=dedup,
        adr_index=adr_index,
        runner=runner,
        deps=_deps(stop, bus),
    )

    fakes = _FakeFactory(pr, dedup, state, repo_root, runner)
    fakes.bus = bus  # type: ignore[attr-defined]
    return loop, fakes


async def run_tick(loop: AdrConformanceLoop) -> dict:
    return await loop._do_work()


def _dummy_ctx() -> FitnessContext:
    from datetime import UTC, datetime

    return FitnessContext(
        window_start=datetime(2026, 6, 1, tzinfo=UTC),
        window_end=datetime(2026, 6, 30, tzinfo=UTC),
    )


def _hash_tree(root: Path, subdirs: tuple[str, ...]) -> dict[str, str]:
    """Content-hash every file under the given subdirs, keyed by relative path."""
    hashes: dict[str, str] = {}
    for sub in subdirs:
        base = root / sub
        if not base.exists():
            continue
        for p in sorted(base.rglob("*")):
            if p.is_file():
                rel = str(p.relative_to(root))
                hashes[rel] = hashlib.sha256(p.read_bytes()).hexdigest()
    return hashes


# ---------------------------------------------------------------------------
# Core behavior
# ---------------------------------------------------------------------------


async def test_tick_persists_jsonl_files_issue_on_fail_and_emits_event(
    loop_fixture,
) -> None:
    loop, fakes = loop_fixture
    result = await run_tick(loop)

    assert result["status"] == "ok"
    jsonl_path = fakes.metrics_dir / "adr_conformance.jsonl"
    assert jsonl_path.exists(), "tick must persist the metrics jsonl"
    lines = jsonl_path.read_text().strip().splitlines()
    assert len(lines) == 3  # FAIL + decision-of-record + UNRESOLVED
    for line in lines:
        json.loads(line)  # each line is valid JSON

    assert fakes.pr.created_issues, "a FAIL ADR should file one remediation issue"
    assert any("ADR-0049" in title for title, _body, _labels in fakes.pr.created_issues)

    history = fakes.bus.get_history()
    assert any(e.type.value == "adr_conformance_update" for e in history)
    update_events = [e for e in history if e.type.value == "adr_conformance_update"]
    payload = update_events[0].data
    assert "results" in payload
    outcomes = {r["adr_id"]: r["outcome"] for r in payload["results"]}
    assert outcomes["ADR-0049"] == "fail"
    assert outcomes["ADR-0050"] == "skipped"
    assert outcomes["ADR-0051"] == "unresolved"


async def test_decision_of_record_never_remediated(loop_fixture) -> None:
    loop, fakes = loop_fixture
    await run_tick(loop)
    assert not any(
        "ADR-0050" in title for title, _body, _labels in fakes.pr.created_issues
    )


async def test_unresolved_without_rename_match_files_issue(loop_fixture) -> None:
    """_detect_rename is a conservative stub returning None; UNRESOLVED routes
    to FILE_ISSUE (not REPOINT) until rename detection is implemented."""
    loop, fakes = loop_fixture
    await run_tick(loop)
    assert any("ADR-0051" in title for title, _body, _labels in fakes.pr.created_issues)


async def test_pass_clears_attempt_counter(loop_fixture) -> None:
    loop, fakes = loop_fixture
    fakes.state.inc_adr_conformance_attempts("ADR-0049")
    fakes.runner._outcomes["make:conformance-fail-fixture"] = CheckOutcome.PASS

    await run_tick(loop)

    assert fakes.state.get_adr_conformance_rollup("ADR-0049") is None
    # PASS clears the attempts counter -> next increment starts back at 1.
    assert fakes.state.inc_adr_conformance_attempts("ADR-0049") == 1


async def test_second_tick_dedups_and_does_not_refile(loop_fixture) -> None:
    loop, fakes = loop_fixture
    await run_tick(loop)
    first_count = len(fakes.pr.created_issues)
    assert first_count >= 1

    await run_tick(loop)
    # find_existing_issue-style dedup: same title short-circuits to the same
    # issue number via our stub's _by_title cache, so no *new* issue rows.
    assert len(fakes.pr.created_issues) == first_count


async def test_escalates_after_max_attempts(loop_fixture) -> None:
    loop, fakes = loop_fixture
    # Pre-load the attempt counter so this tick's increment lands exactly at
    # the threshold (once-at-threshold escalation, `==` not `>=`).
    fakes.state.inc_adr_conformance_attempts("ADR-0049")
    fakes.state.inc_adr_conformance_attempts("ADR-0049")

    result = await run_tick(loop)

    assert result["escalated"] >= 1
    escalation_titles = [
        title
        for title, _body, labels in fakes.pr.created_issues
        if "hitl" in "".join(labels).lower()
    ]
    assert escalation_titles or any(
        "ADR-0049" in title and "3" in title
        for title, _b, _l in fakes.pr.created_issues
    )


async def test_escalation_fires_once_across_multiple_ticks(loop_fixture) -> None:
    """A persistently-failing ADR must escalate exactly ONCE, at the attempts
    threshold — not on every subsequent tick past it (unbounded HITL spam).

    Runs the tick 5 times in a row: attempts goes 1, 2, 3 (threshold — first
    and only escalation), 4, 5 (both past-threshold, must no-op on escalate).
    The fixture has two persistently-unresolved ADRs (ADR-0049 FAIL,
    ADR-0051 UNRESOLVED); each is entitled to exactly one escalation, so we
    scope the assertion to ADR-0049 specifically.
    """
    loop, fakes = loop_fixture

    for _ in range(5):
        await run_tick(loop)

    hitl_titles = [
        title
        for title, _body, _labels in fakes.pr.created_issues
        if "HITL" in title and "ADR-0049" in title
    ]
    assert len(hitl_titles) == 1, (
        f"expected exactly one HITL escalation issue for ADR-0049, got "
        f"{len(hitl_titles)}: {hitl_titles}"
    )


async def test_kill_switch_short_circuits(loop_fixture) -> None:
    loop, fakes = loop_fixture
    loop._enabled_cb = lambda _name: False
    result = await run_tick(loop)
    assert result == {"status": "disabled"}
    assert fakes.pr.created_issues == []


async def test_config_disabled_short_circuits(loop_fixture) -> None:
    loop, fakes = loop_fixture
    loop._config = loop._config.model_copy(
        update={"adr_conformance_loop_enabled": False}
    )
    result = await run_tick(loop)
    assert result == {"status": "config_disabled"}
    assert fakes.pr.created_issues == []


def test_loop_fitness_is_housekeeping(loop_fixture) -> None:
    loop, _fakes = loop_fixture
    fitness = loop.loop_fitness(_dummy_ctx())
    assert fitness.kind is FitnessKind.HOUSEKEEPING
    assert fitness.worker_name == "adr_conformance"


def test_worker_name_and_interval(loop_fixture) -> None:
    loop, _fakes = loop_fixture
    assert loop._worker_name == "adr_conformance"
    assert loop._get_default_interval() == 86400


# ---------------------------------------------------------------------------
# GUARDRAIL (load-bearing): the loop's ONLY repo-write surface is GitHub
# issues + the gitignored jsonl. It must NEVER mutate src/, tests/, or
# docs/adr/ on disk.
# ---------------------------------------------------------------------------


async def test_loop_never_writes_repo_source_files(loop_fixture) -> None:
    loop, fakes = loop_fixture
    repo_root = fakes.repo_root

    before = _hash_tree(repo_root, ("src", "tests", "docs/adr"))
    await run_tick(loop)
    after = _hash_tree(repo_root, ("src", "tests", "docs/adr"))

    assert before == after, "loop mutated repo source — guardrail breached"
    # Same file set too (no new/deleted files under the guarded trees).
    assert set(before) == set(after)
    assert fakes.pr.created_issues, "loop should remediate via issues, not edits"
