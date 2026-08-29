"""MockWorld scenario for the decision seam (#11749).

Drives both halves of the seam over ONE seeded repo, so the decision and the
actuation are talking about the same ADRs:

* **Decisions** — ``policy.facts.collect_adr_enforcement_facts`` reads the
  seeded corpus, ``PythonDecisionEngine`` judges the recorded facts. A WEAK
  Accepted ADR with neither lane open is ``violated`` and ``blocking``; a WEAK
  Accepted ADR named in ``exemptions.md`` is ``exempt`` and not blocking.
* **Actuation** — ``AdrConformanceLoop`` ticks over the same repo against
  ``world.github``. The blocking ADR gets exactly one deduped issue (and still
  one after a second tick); the exempt ADR gets none.

Seeded corpus:

* ``ADR-0200`` — ``enforced``, cites a pytest node that does not exist. WEAK
  enforcement (nothing resolves) *and* ``UNRESOLVED`` at runtime, so it is the
  ADR that both blocks and is remediated.
* ``ADR-0400`` — ``manual`` prose pointer, allow-listed in ``exemptions.md``.
  WEAK enforcement but exempt, and ``MANUAL`` at runtime, so nothing is filed.
* ``ADR-0100`` — ``enforced`` against a real asserting node. REAL, compliant,
  and its check passes: the anti-vacuity third ADR that keeps the scenario from
  agreeing over a corpus where nothing is ever fine.

Note what is NOT claimed: the exempt ADR files no issue because its *runtime*
outcome is ``MANUAL``, not because the enforcement exemption suppresses the
conformance actuator. Letting one standard's exemption veto another standard's
remediation would be cross-standard composition, which epic #11752 explicitly
does not build here.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from adr_conformance import CheckOutcome
from adr_index import ADRIndex
from base_background_loop import LoopDeps
from config import HydraFlowConfig
from dedup_store import DedupStore
from events import EventBus
from mockworld.fakes import FakeConformanceRunner
from policy.facts import collect_adr_enforcement_facts
from policy.models import DecisionStatus
from policy.python_engine import PythonDecisionEngine
from policy.store import facts_path, read_facts
from state import StateTracker
from tests.scenarios.catalog.loop_registrations import _build_adr_conformance
from tests.scenarios.fakes.mock_world import MockWorld
from tests.scenarios.helpers.loop_port_seeding import seed_ports as _seed_ports

pytestmark = pytest.mark.scenario_loops

OBSERVED_AT = datetime(2026, 8, 28, 9, 30, tzinfo=UTC)

_REAL_ADR = "ADR-0100"
_BLOCKING_ADR = "ADR-0200"
_EXEMPT_ADR = "ADR-0400"


def _write_adr(
    adr_dir: Path, number: int, *, enforcement: str, enforced_by: str | None
) -> None:
    lines = [
        f"# ADR-{number:04d}: Seam Fixture {number}",
        "",
        "**Status:** Accepted",
        "**Date:** 2026-01-01",
        f"**Enforcement:** {enforcement}",
    ]
    if enforced_by is not None:
        lines.append(f"**Enforced by:** {enforced_by}")
    lines.extend(["", "## Context", "", "Fixture body.", ""])
    (adr_dir / f"{number:04d}-seam-fixture-{number}.md").write_text("\n".join(lines))


def _seed_repo(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    adr_dir = root / "docs" / "adr"
    adr_dir.mkdir(parents=True)

    tests_dir = root / "tests"
    tests_dir.mkdir()
    (tests_dir / "test_real.py").write_text(
        "def test_real() -> None:\n    assert True\n"
    )
    src_dir = root / "src"
    src_dir.mkdir()
    (src_dir / "placeholder.py").write_text("# placeholder\n")

    _write_adr(
        adr_dir,
        100,
        enforcement="enforced",
        enforced_by="pytest:tests/test_real.py::test_real",
    )
    _write_adr(
        adr_dir,
        200,
        enforcement="enforced",
        enforced_by="pytest:tests/test_ghost.py::test_ghost",
    )
    _write_adr(
        adr_dir, 400, enforcement="manual", enforced_by="prose:reviewer checklist"
    )

    baseline_dir = root / "tests" / "architecture"
    baseline_dir.mkdir(parents=True)
    (baseline_dir / "adr_enforcement_baseline.json").write_text(
        json.dumps({"baseline_snapshot": [], "resolved": []})
    )

    standards_dir = root / "docs" / "standards" / "adr_enforcement"
    standards_dir.mkdir(parents=True)
    (standards_dir / "exemptions.md").write_text(
        "# Exemptions\n\n## Active exemptions\n\n"
        "- ADR-0400: fixture — a reviewer-checklist decision with no on-disk "
        "invariant a test could assert.\n"
    )
    return root


def _build_loop(world: MockWorld, repo_root: Path):
    """Direct construction, mirroring ``test_adr_conformance_scenario._build_loop``.

    ``run_with_loops`` has no config-enable seam for
    ``adr_conformance_loop_enabled`` and would leave ``data_root`` at its unsafe
    ``Path(".")`` default, which this test cannot have — it asserts on a written
    fact ledger.
    """
    config = HydraFlowConfig(
        data_root=repo_root / ".hydraflow",
        repo="hydra/hydraflow",
        repo_root=repo_root,
        adr_conformance_loop_enabled=True,
    )
    deps = LoopDeps(
        event_bus=EventBus(),
        stop_event=world._harness.stop_event,
        status_cb=lambda *a, **k: None,
        enabled_cb=lambda _name: True,
    )
    _seed_ports(
        world,
        pr_manager=world.github,
        adr_conformance_state=StateTracker(repo_root / ".hydraflow" / "state.json"),
        adr_conformance_dedup=DedupStore(
            "adr_conformance", repo_root / ".hydraflow" / "dedup.json"
        ),
        adr_conformance_index=ADRIndex(repo_root / "docs" / "adr"),
        adr_conformance_runner=FakeConformanceRunner(
            {"pytest:tests/test_real.py::test_real": CheckOutcome.PASS}
        ),
    )
    return _build_adr_conformance(world._loop_ports, config, deps), config


def _enforcement_status(repo_root: Path) -> dict[str, DecisionStatus]:
    facts = collect_adr_enforcement_facts(repo_root, observed_at=OBSERVED_AT)
    return {d.subject: d.status for d in PythonDecisionEngine().decide(facts)}


def _enforcement_blocking(repo_root: Path) -> set[str]:
    facts = collect_adr_enforcement_facts(repo_root, observed_at=OBSERVED_AT)
    return {d.subject for d in PythonDecisionEngine().decide(facts) if d.blocking}


class TestStandardDecisionSeamScenario:
    """#11749 — normalized facts decide, and one actuator acts on the decision."""

    async def test_weak_adr_is_violated_and_blocking(self, tmp_path) -> None:
        repo_root = _seed_repo(tmp_path)

        statuses = _enforcement_status(repo_root)

        assert statuses[_BLOCKING_ADR] is DecisionStatus.VIOLATED
        assert _BLOCKING_ADR in _enforcement_blocking(repo_root)

    async def test_allow_listed_weak_adr_is_exempt_and_not_blocking(
        self, tmp_path
    ) -> None:
        repo_root = _seed_repo(tmp_path)

        statuses = _enforcement_status(repo_root)

        assert statuses[_EXEMPT_ADR] is DecisionStatus.EXEMPT
        assert _EXEMPT_ADR not in _enforcement_blocking(repo_root)

    async def test_real_adr_is_compliant(self, tmp_path) -> None:
        """Anti-vacuity: the corpus is not "everything is broken"."""
        repo_root = _seed_repo(tmp_path)

        assert _enforcement_status(repo_root)[_REAL_ADR] is DecisionStatus.COMPLIANT

    async def test_actuator_files_one_deduped_issue_for_the_blocking_adr(
        self, tmp_path
    ) -> None:
        world = MockWorld(tmp_path)
        repo_root = _seed_repo(tmp_path)
        loop, _config = _build_loop(world, repo_root)

        result = await loop._do_work()

        assert result["filed"] == 1
        issues = await world.github.list_issues_by_label("hydraflow-find")
        assert [i["title"] for i in issues] == [
            f"ADR conformance: {_BLOCKING_ADR} is unresolved"
        ]
        assert world._loop_ports["adr_conformance_dedup"].get() == {
            f"adr_conformance:{_BLOCKING_ADR}"
        }

    async def test_actuator_files_nothing_for_the_exempt_or_compliant_adrs(
        self, tmp_path
    ) -> None:
        world = MockWorld(tmp_path)
        repo_root = _seed_repo(tmp_path)
        loop, _config = _build_loop(world, repo_root)

        await loop._do_work()

        titles = " ".join(
            i["title"]
            for i in await world.github.list_issues_by_label("hydraflow-find")
        )
        assert _EXEMPT_ADR not in titles
        assert _REAL_ADR not in titles

    async def test_a_second_tick_does_not_file_a_second_issue(self, tmp_path) -> None:
        world = MockWorld(tmp_path)
        repo_root = _seed_repo(tmp_path)
        loop, _config = _build_loop(world, repo_root)

        await loop._do_work()
        await loop._do_work()

        issues = await world.github.list_issues_by_label("hydraflow-find")
        assert len(issues) == 1, f"dedup broke: {[i['title'] for i in issues]}"

    async def test_tick_records_the_facts_its_decision_was_made_from(
        self, tmp_path
    ) -> None:
        """The offline-reproducibility claim (#11687), as a scenario.

        The ledger written by the tick is replayed through the engine with no
        repo access at all; the action it yields must be the action the loop
        took.
        """
        world = MockWorld(tmp_path)
        repo_root = _seed_repo(tmp_path)
        loop, config = _build_loop(world, repo_root)

        await loop._do_work()

        replayed = read_facts(facts_path(config.repo_data_root))
        assert replayed, "no facts recorded"
        decisions = {d.subject: d for d in PythonDecisionEngine().decide(replayed)}
        assert decisions[_BLOCKING_ADR].remediation.value == "file_issue"
        assert decisions[_BLOCKING_ADR].blocking is True
        assert decisions[_EXEMPT_ADR].remediation.value == "none"
        assert decisions[_REAL_ADR].remediation.value == "none"
