"""Unit tests for DisturbanceDampenerLoop (Pattern A burn-down)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from disturbance.models import Finding
from disturbance.registry import DimensionSpec
from disturbance_dampener_loop import DisturbanceDampenerLoop


class _FakeDetector:
    def __init__(self, name: str, findings: list[Finding]) -> None:
        self.name = name
        self._findings = findings

    def detect(self, repo_root: Path) -> list[Finding]:
        return self._findings


class _FakeDedup:
    def __init__(self) -> None:
        self._keys: set[str] = set()

    def get(self) -> set[str]:
        return set(self._keys)

    def set_all(self, keys: set[str]) -> None:
        self._keys = set(keys)


class _FakeState:
    def __init__(self) -> None:
        self._a: dict[str, int] = {}

    def get_disturbance_dampener_attempts(self, k: str) -> int:
        return self._a.get(k, 0)

    def bump_disturbance_dampener_attempts(self, k: str) -> int:
        self._a[k] = self._a.get(k, 0) + 1
        return self._a[k]

    def clear_disturbance_dampener_attempts(self, k: str) -> None:
        self._a.pop(k, None)


class _Cfg:
    disturbance_dampener_enabled = True
    disturbance_dampener_max_prs_per_tick = 1
    disturbance_dampener_interval_seconds = 3600
    repo_root = Path(".")
    auto_agent_max_attempts = 3
    loop_watchdog_llm_seconds = 600
    loop_watchdog_default_seconds = 60

    def base_branch(self) -> str:
        return "staging"


def _spec(findings: list[Finding]) -> DimensionSpec:
    return DimensionSpec(
        name="suppressions",
        detector=_FakeDetector("suppressions", findings),
        baseline_path=Path("disturbance/baselines/suppressions.yaml"),
        fix_prompt="remove the suppression",
    )


def _deps(*, enabled: bool = True) -> Any:
    # Minimal LoopDeps stand-in: enabled_cb returns True, others unused in
    # _do_work paths hit here.
    import asyncio

    from base_background_loop import LoopDeps

    return LoopDeps(
        event_bus=None,
        stop_event=asyncio.Event(),
        status_cb=lambda *a, **k: None,
        enabled_cb=lambda _name: enabled,
    )


@pytest.mark.asyncio
async def test_opens_one_pr_for_backlog_file_and_dedupes() -> None:
    finding = Finding(
        dimension="suppressions",
        path="src/a.py",
        signature="src/a.py::noqa",
        message="m",
    )
    dedup = _FakeDedup()
    calls: list[dict[str, Any]] = []

    async def _fake_runner_run(
        *, prompt: str, worktree_path: str, issue_number: int
    ) -> Any:
        return type("O", (), {"crashed": False, "output_text": "ok"})()

    async def _fake_pr_opener(**kwargs: Any) -> Any:
        calls.append(kwargs)
        return type(
            "R",
            (),
            {
                "status": "opened",
                "pr_url": "u",
                "branch": kwargs["branch"],
                "error": None,
            },
        )()

    runner = type("Runner", (), {"run": staticmethod(_fake_runner_run)})()

    loop = DisturbanceDampenerLoop(
        config=_Cfg(),
        state=_FakeState(),
        prs=object(),
        dedup=dedup,
        deps=_deps(),
        runner=runner,
        dimensions=[_spec([finding])],
        baseline_loader=lambda p: {"src/a.py::noqa": 1},  # inject baseline (avoid disk)
        pr_opener=_fake_pr_opener,
    )
    result = await loop._do_work()

    assert result["opened"] == 1
    assert len(calls) == 1
    assert calls[0]["base"] == "staging"
    assert "disturbance:suppressions:src/a.py" in dedup.get()

    # Second tick: dedup now blocks it -> no PR.
    calls.clear()
    result2 = await loop._do_work()
    assert result2["opened"] == 0 and calls == []


@pytest.mark.asyncio
async def test_kill_switch_short_circuits() -> None:
    deps = _deps(enabled=False)
    loop = DisturbanceDampenerLoop(
        config=_Cfg(),
        state=_FakeState(),
        prs=object(),
        dedup=_FakeDedup(),
        deps=deps,
        runner=object(),
        dimensions=[_spec([])],
        baseline_loader=lambda p: {},
        pr_opener=None,
    )
    result = await loop._do_work()
    assert result["status"] == "disabled"
