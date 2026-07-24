"""MockWorld scenario for SecondOrderVitalsLoop (#10373).

End-to-end over MockWorld + seeded instrument ledgers on disk: the capstone
residual monitor reads the four instruments' ledgers (IMPORTING their metric
functions), computes each family's Shewhart control limit from its persisted
history, and produces the green-while-dying verdict. The scenario seeds adverse
drift across THREE families with a primed baseline one window short of a
sustained breach; the tick's own reading completes the second sustained window,
so the verdict is ``diverging`` and exactly ONE find + HITL escalation is filed
through the github port. A two-family variant produces ``watch`` and files
nothing. The primary-health gate is injected green (the green-while-dying
precondition). Mirrors ``tests/scenarios/test_intervention_tally_scenario.py``.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from tests.scenarios.fakes.mock_world import MockWorld
from vitals.models import (
    SERIES_AUDIT_DISAGREEMENT,
    SERIES_ESCAPES,
    SERIES_INTERVENTION_CORRECTIONS,
)
from vitals.observe import PrimaryHealth

pytestmark = pytest.mark.scenario_loops


class _FakeState:
    def __init__(self, history: dict[str, list[float]], last: str = "") -> None:
        self._history = {k: list(v) for k, v in history.items()}
        self._last = last

    def get_second_order_vitals_series_history(self) -> dict[str, list[float]]:
        return {k: list(v) for k, v in self._history.items()}

    def set_second_order_vitals_series_history(
        self, history: dict[str, list[float]]
    ) -> None:
        self._history = {k: list(v) for k, v in history.items()}

    def get_second_order_vitals_last_verdict(self) -> str:
        return self._last

    def set_second_order_vitals_last_verdict(self, verdict: str) -> None:
        self._last = verdict


class _FakePR:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    async def create_issue(
        self, title: str, body: str, labels: list[str] | None = None
    ) -> int:
        self.calls.append({"title": title, "body": body, "labels": labels or []})
        return len(self.calls)


def _seed_ledgers(
    diag: Path, now_iso: str, *, escapes: int, corrections: int, disagreements: int
) -> None:
    """Seed the instrument ledgers so this tick's readings are adverse."""
    diag.mkdir(parents=True, exist_ok=True)
    if escapes:
        (diag / "escape_ledger.jsonl").write_text(
            "\n".join(
                json.dumps({"id": f"e{i}", "detected_at": now_iso})
                for i in range(escapes)
            )
            + "\n"
        )
    if corrections:
        (diag / "intervention_ledger.jsonl").write_text(
            "\n".join(
                json.dumps(
                    {"id": f"iv{i}", "ts": now_iso, "class": "instruction-violation"}
                )
                for i in range(corrections)
            )
            + "\n"
        )
    if disagreements:
        (diag / "audit_samples.jsonl").write_text(
            "\n".join(
                json.dumps(
                    {"id": f"a{i}", "audited_at": now_iso, "verdict": "disagree"}
                )
                for i in range(disagreements)
            )
            + "\n"
        )


def _build_loop(tmp_path: Path, state: _FakeState, prs: _FakePR) -> Any:
    from second_order_vitals_loop import SecondOrderVitalsLoop
    from tests.helpers import make_bg_loop_deps

    bg = make_bg_loop_deps(tmp_path)
    c = bg.config
    for field, value in {
        "repo_root": tmp_path / "repo",
        "data_root": tmp_path / "data",
        "dry_run": False,
        "second_order_vitals_min_baseline_windows": 3,
        "second_order_vitals_sustained_windows": 2,
        "second_order_vitals_watch_k": 2,
        "second_order_vitals_diverging_k": 3,
    }.items():
        object.__setattr__(c, field, value)

    def _green(_now: Any, _window_days: int) -> PrimaryHealth:
        return PrimaryHealth(ci_pass_rate=1.0, merge_throughput=100)

    return SecondOrderVitalsLoop(
        config=c,
        pr_manager=prs,
        state=state,
        deps=bg.loop_deps,
        primary_health_reader=_green,
    )


class TestSecondOrderVitalsScenario:
    async def test_three_family_drift_is_diverging_and_files_one_find(
        self, tmp_path: Path
    ) -> None:
        MockWorld(tmp_path)  # air-gapped fakes wired (parity with sibling scenarios)
        now_iso = datetime.now(UTC).isoformat()
        diag = tmp_path / "data" / "diagnostics"
        _seed_ledgers(diag, now_iso, escapes=5, corrections=5, disagreements=2)
        # Baselines primed one window short of a sustained breach; the appended
        # reading this tick completes the second sustained window.
        state = _FakeState(
            {
                SERIES_ESCAPES: [0.0, 0.0, 0.0, 5.0],
                SERIES_INTERVENTION_CORRECTIONS: [0.0, 0.0, 0.0, 5.0],
                SERIES_AUDIT_DISAGREEMENT: [0.0, 0.0, 0.0, 1.0],
            }
        )
        prs = _FakePR()
        loop = _build_loop(tmp_path, state, prs)

        result = await loop._do_work()

        assert result["verdict"] == "diverging"
        assert result["k"] == 3
        assert result["filed"] == 1
        assert len(prs.calls) == 1
        labels = prs.calls[0]["labels"]
        assert {
            "hydraflow-find",
            "second-order-vitals",
            "hydraflow-hitl-escalation",
        } <= set(labels)
        # The verdict history + report were written.
        assert (diag / "vitals.jsonl").exists()
        report = tmp_path / "repo" / "docs/arch/generated/second-order-vitals.md"
        assert report.exists()

    async def test_two_family_drift_is_watch_and_files_nothing(
        self, tmp_path: Path
    ) -> None:
        MockWorld(tmp_path)
        now_iso = datetime.now(UTC).isoformat()
        diag = tmp_path / "data" / "diagnostics"
        # Only two families seeded/primed → below the diverging bar.
        _seed_ledgers(diag, now_iso, escapes=5, corrections=5, disagreements=0)
        state = _FakeState(
            {
                SERIES_ESCAPES: [0.0, 0.0, 0.0, 5.0],
                SERIES_INTERVENTION_CORRECTIONS: [0.0, 0.0, 0.0, 5.0],
            }
        )
        prs = _FakePR()
        loop = _build_loop(tmp_path, state, prs)

        result = await loop._do_work()

        assert result["verdict"] == "watch"
        assert result["k"] == 2
        assert result["filed"] == 0
        assert prs.calls == []
